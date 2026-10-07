"""Slicer desktop research workflow; uses existing imaging and segmentation tools."""
import importlib.metadata
import json
import os
from pathlib import Path
import shutil
import tempfile
import time
import traceback

import numpy as np
import qt
import slicer
import vtk
from slicer.ScriptedLoadableModule import ScriptedLoadableModule, ScriptedLoadableModuleWidget
from AtlasLib.bundle import dump_json
from AtlasLib.catalog import STRUCTURES, TASKS, display_name
from AtlasLib.inference import MODEL_VERSION, build_request
from AtlasLib.overlay import SliceOverlay
from AtlasLib.slicer_bridge import AtlasSession, validate_volume, volume_affine


class HeadNeckAtlas(ScriptedLoadableModule):
    def __init__(self, parent):
        super().__init__(parent)
        parent.title = '头颈 CT 科研图谱'
        parent.categories = ['Research']
        parent.dependencies = []
        parent.contributors = ['HeadNeckAtlas contributors']
        parent.helpText = '本地科研工具：CT、自动分割、解剖标签、人工修正和研究包。模型结果需要人工核查。'
        parent.acknowledgementText = 'Built on 3D Slicer and TotalSegmentator. Please cite both projects when used in research.'


class HeadNeckAtlasWidget(ScriptedLoadableModuleWidget):
    def setup(self):
        super().setup()
        self.session = AtlasSession()
        self.session.restore()
        self.process = None
        self.job_dir = None
        self.cancelled = False
        self.overlay = SliceOverlay(lambda: self.session)
        self.scene_observers = []
        self.scene_observers.append(slicer.mrmlScene.AddObserver(slicer.mrmlScene.StartCloseEvent, self.scene_closing))
        self.scene_observers.append(slicer.mrmlScene.AddObserver(slicer.mrmlScene.EndImportEvent, self.scene_imported))
        panel = qt.QWidget()
        form = qt.QFormLayout(panel)
        title = qt.QLabel('头颈 CT 科研图谱 · MVP')
        title.setStyleSheet('font-size:18px;font-weight:bold;padding:6px;')
        form.addRow(title)
        hint = qt.QLabel('本地单病例 · 自动结果与人工修正分别保存\n首次运行需准备模型；患者数据不会由本模块上传。')
        hint.setWordWrap(True)
        form.addRow(hint)
        self.volumeSelector = slicer.qMRMLNodeComboBox()
        self.volumeSelector.nodeTypes = ['vtkMRMLScalarVolumeNode']
        self.volumeSelector.addEnabled = False
        self.volumeSelector.removeEnabled = False
        self.volumeSelector.noneEnabled = True
        self.volumeSelector.setMRMLScene(slicer.mrmlScene)
        form.addRow('CT 输入', self.volumeSelector)
        self.button(form, '导入 DICOM…', lambda: slicer.util.selectModule('DICOM'))
        self.button(form, '确认所选非 DICOM 体积来自 CT', self.confirm_ct)
        self.taskCombo = qt.QComboBox()
        for task, name in TASKS.items():
            self.taskCombo.addItem(name, task)
        form.addRow('分割任务', self.taskCombo)
        self.deviceCombo = qt.QComboBox()
        self.deviceCombo.addItem('CPU（较慢）', 'cpu')
        self.deviceCombo.addItem('NVIDIA CUDA GPU', 'gpu')
        form.addRow('推理设备', self.deviceCombo)
        self.downloadCheck = qt.QCheckBox('允许本次运行下载缺失权重（可能数 GB）')
        form.addRow(self.downloadCheck)
        self.runButton = self.button(form, '运行自动分割', self.start_inference)
        self.cancelButton = self.button(form, '取消推理', self.cancel_inference)
        self.cancelButton.enabled = False
        self.progress = qt.QProgressBar()
        self.progress.setRange(0, 1)
        self.progress.setValue(0)
        form.addRow(self.progress)
        self.status = qt.QLabel('请选择 CT 输入。')
        self.status.setWordWrap(True)
        form.addRow(self.status)
        self.structureList = qt.QListWidget()
        self.structureList.setMinimumHeight(170)
        form.addRow('解剖结构（双击定位）', self.structureList)
        self.button(form, '开始 / 继续人工修正', self.edit_corrected)
        self.button(form, '三平面布局', lambda: self.change_layout(slicer.vtkMRMLLayoutNode.SlicerLayoutFourUpView))
        self.button(form, '轴位布局', lambda: self.change_layout(slicer.vtkMRMLLayoutNode.SlicerLayoutOneUpRedSliceView))
        self.button(form, '恢复标签位置', self.reset_labels)
        self.caseName = qt.QLineEdit()
        self.caseName.setPlaceholderText('例如 study-001；用于新的研究目录')
        form.addRow('研究编号', self.caseName)
        self.saveButton = self.button(form, '保存研究包…', self.save_bundle)
        self.loadButton = self.button(form, '打开研究包…', self.load_bundle)
        self.log = qt.QPlainTextEdit()
        self.log.setReadOnly(True)
        self.log.setMaximumHeight(150)
        form.addRow('运行日志', self.log)
        self.layout.addWidget(panel)
        self.layout.addStretch(1)
        self.volumeSelector.connect('currentNodeChanged(vtkMRMLNode*)', self.volume_changed)
        self.structureList.connect('itemChanged(QListWidgetItem*)', self.visibility_changed)
        self.structureList.connect('itemDoubleClicked(QListWidgetItem*)', self.jump_to_structure)
        self.volumeSelector.setCurrentNode(self.session.volume)
        self.refresh()

    def button(self, form, label, callback):
        button = qt.QPushButton(label)
        button.connect('clicked(bool)', lambda checked=False: self.guarded(callback))
        form.addRow(button)
        return button

    def guarded(self, callback):
        try:
            callback()
        except Exception as exc:
            self.status.text = str(exc)
            self.log.appendPlainText(traceback.format_exc())
            slicer.util.errorDisplay(str(exc))

    def enter(self):
        if hasattr(self, 'overlay'):
            self.refresh()

    def exit(self):
        self.overlay.close()

    def cleanup(self):
        self.cancel_inference()
        self.overlay.close()
        for tag in self.scene_observers:
            slicer.mrmlScene.RemoveObserver(tag)
        self.scene_observers = []

    def scene_closing(self, *args):
        self.cancel_inference()
        self.overlay.close()
        self.session = AtlasSession()

    def scene_imported(self, *args):
        self.session.restore()
        self.volumeSelector.blockSignals(True)
        self.volumeSelector.setCurrentNode(self.session.volume)
        self.volumeSelector.blockSignals(False)
        self.refresh()

    def volume_changed(self, volume):
        if self.process:
            self.volumeSelector.blockSignals(True)
            self.volumeSelector.setCurrentNode(self.session.volume)
            self.volumeSelector.blockSignals(False)
            return
        self.overlay.close()
        try:
            self.session.select_volume(volume)
            if volume:
                slicer.util.setSliceViewerLayers(background=volume)
                slicer.util.resetSliceViews()
                self.status.text = '可运行分割；模型结果需人工核查。'
        except ValueError as exc:
            self.session.select_volume(None)
            self.status.text = str(exc)
        self.refresh()

    def confirm_ct(self):
        volume = self.volumeSelector.currentNode()
        if not volume:
            raise ValueError('请先选择体积。')
        if slicer.util.confirmYesNoDisplay('确认此体积来自 CT，并保留原始 HU 与空间几何？'):
            volume.SetAttribute('HeadNeckAtlas.Modality', 'CT')
            self.volume_changed(volume)

    def change_layout(self, layout):
        self.overlay.close()
        slicer.app.layoutManager().setLayout(layout)
        self.refresh()

    def refresh(self):
        self.structureList.blockSignals(True)
        self.structureList.clear()
        for name in STRUCTURES:
            exists = bool(self.session.active and self.session.active.GetSegmentation().GetSegment(name))
            item = qt.QListWidgetItem(display_name(name) + (' · 已生成' if exists else ' · 未生成'))
            item.setData(qt.Qt.UserRole, name)
            item.setFlags(item.flags() | qt.Qt.ItemIsUserCheckable)
            item.setCheckState(qt.Qt.Unchecked if name in self.session.hidden else qt.Qt.Checked)
            self.structureList.addItem(item)
        self.structureList.blockSignals(False)
        busy = self.process is not None
        self.runButton.enabled = bool(self.session.volume) and not busy
        self.saveButton.enabled = bool(self.session.automatic) and not busy
        self.loadButton.enabled = not busy
        self.cancelButton.enabled = busy
        self.session.configure_visibility()
        self.overlay.bind()

    def visibility_changed(self, item):
        name = item.data(qt.Qt.UserRole)
        hidden = set(self.session.hidden)
        if item.checkState() == qt.Qt.Checked:
            hidden.discard(name)
        else:
            hidden.add(name)
        self.session.hidden = sorted(hidden)
        self.session.configure_visibility()
        self.session.persist()
        self.overlay.schedule()

    def jump_to_structure(self, item):
        name = item.data(qt.Qt.UserRole)
        mask = self.session.masks(names=[name]).get(name)
        if mask is None or not mask.any():
            self.status.text = '该结构尚未生成或当前病例中为空。'
            return
        k, j, i = np.argwhere(mask)[len(np.argwhere(mask)) // 2]
        ras = volume_affine(self.session.volume) @ np.array([i, j, k, 1])
        slicer.modules.markups.logic().JumpSlicesToLocation(float(ras[0]), float(ras[1]), float(ras[2]), True)

    def reset_labels(self):
        self.session.offsets = {}
        self.session.persist()
        self.overlay.schedule()

    def edit_corrected(self):
        if self.process:
            raise ValueError('推理运行中，请等待或取消。')
        node = self.session.create_corrected()
        self.refresh()
        slicer.util.selectModule('SegmentEditor')
        editor = slicer.modules.segmenteditor.widgetRepresentation().self().editor
        editor.setSegmentationNode(node)
        editor.setSourceVolumeNode(self.session.volume)

    def start_inference(self):
        if self.process:
            raise ValueError('已有运行中的推理。')
        validate_volume(self.session.volume)
        if self.session.corrected:
            raise ValueError('已开始修正；要重新推理，请开启新病例会话。')
        task = self.taskCombo.currentData
        if any(run.get('task') == task for run in self.session.runs):
            raise ValueError('当前任务已完成，请运行另一任务。')
        try:
            from TotalSegmentator import TotalSegmentatorLogic
        except ImportError:
            raise RuntimeError('缺少 SlicerTotalSegmentator 扩展；请先安装或配置其模块路径。')
        logic = TotalSegmentatorLogic()
        if task not in logic.tasks or not hasattr(logic, 'readSegmentation'):
            raise RuntimeError('扩展接口不兼容。')
        try:
            version = importlib.metadata.version('TotalSegmentator')
        except importlib.metadata.PackageNotFoundError:
            raise RuntimeError(f'缺少模型依赖；需要在 Slicer Python 中安装 TotalSegmentator {MODEL_VERSION}。')
        if version != MODEL_VERSION:
            raise RuntimeError(f'需要 TotalSegmentator {MODEL_VERSION}，当前 {version}。')
        self.job_dir = Path(tempfile.mkdtemp(prefix='atlas-inference-'))
        input_file = self.job_dir / 'input.nii.gz'
        if not slicer.util.saveNode(self.session.volume, str(input_file)):
            raise IOError('推理输入保存失败。')
        self.request = build_request(input_file, self.job_dir / 'output.nii.gz', task,
                                     self.deviceCombo.currentData, bool(self.downloadCheck.checked))
        dump_json(self.job_dir / 'request.json', self.request)
        self.cancelled = False
        self.job_volume = self.session.volume
        self.started = time.monotonic()
        executable = shutil.which('PythonSlicer') or str(Path(slicer.app.slicerHome) / 'bin' / 'PythonSlicer.exe')
        self.process = qt.QProcess()
        self.process.setProcessChannelMode(qt.QProcess.MergedChannels)
        self.process.connect('readyReadStandardOutput()', self.process_log)
        self.process.connect('finished(int,QProcess::ExitStatus)', self.inference_finished)
        self.process.connect('errorOccurred(QProcess::ProcessError)', self.process_error)
        self.progress.setRange(0, 0)
        self.status.text = '正在分割；切片仍可浏览。CPU 全分辨率推理可能需要较长时间。'
        self.refresh()
        self.process.start(executable, [str(Path(__file__).parent / 'AtlasLib' / 'worker.py'), str(self.job_dir / 'request.json')])

    def process_log(self):
        if self.process:
            data = self.process.readAllStandardOutput().data()
            text = data.decode('utf-8', errors='replace') if isinstance(data, bytes) else str(data)
            self.log.appendPlainText(text[-12000:])

    def process_error(self, error):
        if self.process and error == qt.QProcess.FailedToStart:
            self.inference_finished(-1, None)

    def cancel_inference(self):
        if self.process:
            self.cancelled = True
            self.process.kill()

    def inference_finished(self, code, status):
        process, self.process = self.process, None
        try:
            if process:
                data = process.readAllStandardOutput().data()
                self.log.appendPlainText(data.decode('utf-8', errors='replace') if isinstance(data, bytes) else str(data))
            if self.cancelled or self.session.volume is not self.job_volume:
                self.status.text = '推理已取消，未导入结果。'
                return
            response_file = self.job_dir / 'response.json'
            if not response_file.exists():
                raise RuntimeError('推理进程未生成运行记录，请查看日志。')
            response = json.loads(response_file.read_text(encoding='utf-8'))
            if code != 0 or response['status'] != 'success':
                raise RuntimeError(response.get('error', '推理失败。'))
            import nibabel as nib
            image = nib.load(self.request['output'])
            shape = slicer.util.arrayFromVolume(self.session.volume).shape[::-1]
            if image.shape != shape or not np.allclose(image.affine, volume_affine(self.session.volume), atol=1e-3):
                raise ValueError('模型输出与原图几何不一致，结果未导入。')
            from TotalSegmentator import TotalSegmentatorLogic
            logic = TotalSegmentatorLogic()
            logic.useStandardSegmentNames = False
            result = slicer.mrmlScene.AddNewNodeByClass('vtkMRMLSegmentationNode', 'Atlas pending')
            result.CreateDefaultDisplayNodes()
            try:
                logic.readSegmentation(result, self.request['output'], self.request['task'])
                response['extension_version'] = 'unavailable'
                module_path = Path(slicer.modules.totalsegmentator.path)
                from AtlasLib.bundle import sha256
                response['extension_source_sha256'] = sha256(module_path)
                # Temporary absolute paths are not useful after the job is cleaned up.
                response['request'] = {key: value for key, value in self.request.items() if key not in ('input', 'output')}
                self.session.ingest(result, self.request['task'], response)
            finally:
                slicer.mrmlScene.RemoveNode(result)
            self.status.text = f"分割完成，耗时 {response['elapsed_seconds']:.1f} 秒；请核查并修正。"
        except Exception as exc:
            self.status.text = str(exc)
            self.log.appendPlainText(traceback.format_exc())
        finally:
            self.progress.setRange(0, 1)
            self.progress.setValue(1)
            if process:
                process.deleteLater()
            if self.job_dir and self.job_dir.exists():
                shutil.rmtree(self.job_dir)
            self.job_dir = None
            self.refresh()

    def save_bundle(self):
        name = self.caseName.text.strip()
        if not name or name in ('.', '..') or any(ch in name for ch in '\\/:*?"<>|') or name.endswith(('.', ' ')):
            raise ValueError('请输入有效研究编号。')
        directory = qt.QFileDialog.getExistingDirectory(slicer.util.mainWindow(), '选择研究包父目录')
        if directory:
            path = self.session.save(Path(directory) / name)
            self.status.text = '已保存：' + str(path)
            self.refresh()

    def load_bundle(self):
        directory = qt.QFileDialog.getExistingDirectory(slicer.util.mainWindow(), '选择包含 manifest.json 的研究包目录')
        if not directory:
            return
        from AtlasLib.bundle import validate_bundle
        validate_bundle(directory)
        if not slicer.util.confirmYesNoDisplay('打开研究包会替换当前 Slicer 场景。未保存的修正将丢失，继续？'):
            return
        self.overlay.close()
        self.session = AtlasSession()
        self.session.load(directory)
        self.volumeSelector.setCurrentNode(self.session.volume)
        slicer.util.setSliceViewerLayers(background=self.session.volume)
        self.refresh()
        self.status.text = '研究包已加载。'
