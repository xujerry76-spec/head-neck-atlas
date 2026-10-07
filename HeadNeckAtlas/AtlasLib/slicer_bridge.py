"""MRML integration. All methods run on Slicer's main thread."""
import csv
import json
from pathlib import Path
import tempfile
import hashlib
import zipfile
import numpy as np
import slicer
import vtk
from .bundle import dump_json, validate_bundle, write_bundle
from .catalog import STRUCTURES, display_name
from .geometry import valid_affine, volume_ml


def matrix_array(matrix):
    return np.array([[matrix.GetElement(row, col) for col in range(4)] for row in range(4)])


def volume_affine(volume):
    matrix = vtk.vtkMatrix4x4()
    volume.GetIJKToRASMatrix(matrix)
    return valid_affine(matrix_array(matrix))


def save_labelmap(labels, reference, path):
    node = slicer.mrmlScene.AddNewNodeByClass('vtkMRMLLabelMapVolumeNode', 'Atlas export temporary')
    try:
        slicer.util.updateVolumeFromArray(node, labels)
        matrix = vtk.vtkMatrix4x4()
        reference.GetIJKToRASMatrix(matrix)
        node.SetIJKToRASMatrix(matrix)
        if not slicer.util.saveNode(node, str(path)):
            raise IOError('多标签分割保存失败。')
        check = slicer.util.loadVolume(str(path), {'show': False})
        try:
            if not np.allclose(volume_affine(check), volume_affine(reference), atol=1e-4):
                raise IOError('导出分割几何校验失败。')
            np.testing.assert_array_equal(slicer.util.arrayFromVolume(check), labels)
        finally:
            slicer.mrmlScene.RemoveNode(check)
    finally:
        slicer.mrmlScene.RemoveNode(node)


def validate_volume(volume):
    if not volume or not volume.GetImageData() or any(d <= 0 for d in volume.GetImageData().GetDimensions()):
        raise ValueError('请选择有有效像素数据的 CT。')
    if volume.GetParentTransformNode():
        raise ValueError('影像有外部变换，请先在 Transforms 中硬化变换。')
    volume_affine(volume)
    modality = volume.GetAttribute('HeadNeckAtlas.Modality')
    uids = (volume.GetAttribute('DICOM.instanceUIDs') or '').split()
    if not modality and uids:
        modality = slicer.dicomDatabase.instanceValue(uids[0], '0008,0060')
    if modality != 'CT':
        raise ValueError('仅支持 CT；非 DICOM 体积需明确确认 CT 来源。')


def validate_segmentation_geometry(segmentation, volume):
    if segmentation.GetParentTransformNode():
        raise ValueError('分割存在未硬化的外部变换。')
    segmentation.CreateBinaryLabelmapRepresentation()
    reference = volume_affine(volume)
    for index in range(segmentation.GetSegmentation().GetNumberOfSegments()):
        segment_id = segmentation.GetSegmentation().GetNthSegmentID(index)
        image = slicer.vtkOrientedImageData()
        if not segmentation.GetBinaryLabelmapRepresentation(segment_id, image):
            raise ValueError('分割缺少二值掩膜。')
        matrix = vtk.vtkMatrix4x4()
        image.GetImageToWorldMatrix(matrix)
        relative = np.linalg.inv(reference) @ matrix_array(matrix)
        if (not np.allclose(relative[:3, :3], np.eye(3), atol=1e-4)
                or not np.allclose(relative[:3, 3], np.round(relative[:3, 3]), atol=1e-4)):
            raise ValueError('分割几何与原图不在同一体素网格，请先明确重采样后再使用。')


class AtlasSession:
    def __init__(self):
        self.volume = self.automatic = self.corrected = None
        self.runs, self.offsets, self.hidden = [], {}, []
        self.automatic_fingerprint = None

    @property
    def active(self):
        return self.corrected or self.automatic

    def select_volume(self, volume):
        if volume is self.volume:
            return
        if volume:
            validate_volume(volume)
        for segmentation in (self.automatic, self.corrected):
            if segmentation and segmentation.GetDisplayNode():
                segmentation.GetDisplayNode().SetVisibility(False)
        self.volume, self.automatic, self.corrected = volume, None, None
        self.runs, self.offsets, self.hidden = [], {}, []
        self.automatic_fingerprint = None
        self.persist()

    def persist(self):
        node = slicer.mrmlScene.GetSingletonNode('HeadNeckAtlas', 'vtkMRMLScriptedModuleNode')
        if not node:
            node = slicer.vtkMRMLScriptedModuleNode()
            node.SetSingletonTag('HeadNeckAtlas')
            node.SetModuleName('HeadNeckAtlas')
            node = slicer.mrmlScene.AddNode(node)
        for role, value in [('Input', self.volume), ('Automatic', self.automatic), ('Corrected', self.corrected)]:
            node.SetNodeReferenceID(role, value.GetID() if value else None)
        node.SetParameter('Runs', json.dumps(self.runs, ensure_ascii=False))
        node.SetParameter('Offsets', json.dumps(self.offsets))
        node.SetParameter('Hidden', json.dumps(self.hidden))
        node.SetParameter('AutomaticFingerprint', self.automatic_fingerprint or '')

    def restore(self):
        node = slicer.mrmlScene.GetSingletonNode('HeadNeckAtlas', 'vtkMRMLScriptedModuleNode')
        if not node:
            self.volume = self.automatic = self.corrected = None
            self.runs, self.offsets, self.hidden = [], {}, []
            self.automatic_fingerprint = None
            return
        self.volume = node.GetNodeReference('Input')
        self.automatic = node.GetNodeReference('Automatic')
        self.corrected = node.GetNodeReference('Corrected')
        self.runs = json.loads(node.GetParameter('Runs') or '[]')
        self.offsets = json.loads(node.GetParameter('Offsets') or '{}')
        self.hidden = json.loads(node.GetParameter('Hidden') or '[]')
        self.automatic_fingerprint = node.GetParameter('AutomaticFingerprint') or None

    def ingest(self, result, task, record):
        validate_volume(self.volume)
        if self.corrected:
            raise ValueError('已经开始人工修正，请创建新病例会话后重新推理。')
        if any(run.get('task') == task for run in self.runs):
            raise ValueError('此任务已完成，请先切换新病例会话。')
        validate_segmentation_geometry(result, self.volume)
        if not self.automatic:
            self.automatic = slicer.mrmlScene.AddNewNodeByClass('vtkMRMLSegmentationNode', 'Atlas 自动结果')
            self.automatic.CreateDefaultDisplayNodes()
            self.automatic.SetReferenceImageGeometryParameterFromVolumeNode(self.volume)
        segmentation = result.GetSegmentation()
        for index in range(segmentation.GetNumberOfSegments()):
            source = segmentation.GetSegment(segmentation.GetNthSegmentID(index))
            name = source.GetName()
            if self.automatic.GetSegmentation().GetSegment(name):
                raise ValueError(f'重复结构：{name}')
            copy = slicer.vtkSegment()
            copy.DeepCopy(source)
            copy.SetName(name)
            copy.SetTag('HeadNeckAtlas.Task', task)
            self.automatic.GetSegmentation().AddSegment(copy, name)
        self.runs.append(dict(record, task=task))
        self.automatic.SetAttribute('HeadNeckAtlas.Role', 'automatic')
        self.automatic.SetHideFromEditors(True)
        self.automatic_fingerprint = self.fingerprint(self.automatic)
        self.automatic.GetDisplayNode().SetVisibility(True)
        self.configure_visibility()
        self.persist()

    def create_corrected(self):
        if not self.automatic:
            raise ValueError('请先完成自动分割。')
        self.verify_automatic()
        if not self.corrected:
            self.corrected = slicer.mrmlScene.AddNewNodeByClass('vtkMRMLSegmentationNode', 'Atlas 人工修正')
            self.corrected.CreateDefaultDisplayNodes()
            self.corrected.GetSegmentation().DeepCopy(self.automatic.GetSegmentation())
            self.corrected.SetReferenceImageGeometryParameterFromVolumeNode(self.volume)
            self.corrected.SetAttribute('HeadNeckAtlas.Role', 'corrected')
        self.automatic.GetDisplayNode().SetVisibility(False)
        self.configure_visibility()
        self.persist()
        return self.corrected

    def configure_visibility(self):
        if not self.active:
            return
        display = self.active.GetDisplayNode()
        display.SetVisibility(True)
        display.SetOpacity2DFill(.12)
        display.SetOpacity2DOutline(.85)
        for index in range(self.active.GetSegmentation().GetNumberOfSegments()):
            segment_id = self.active.GetSegmentation().GetNthSegmentID(index)
            display.SetSegmentVisibility(segment_id, segment_id in STRUCTURES and segment_id not in self.hidden)

    def iter_masks(self, segmentation):
        validate_segmentation_geometry(segmentation, self.volume)
        if segmentation is self.automatic:
            self.verify_automatic()
        for i in range(segmentation.GetSegmentation().GetNumberOfSegments()):
            name = segmentation.GetSegmentation().GetNthSegmentID(i)
            yield name, slicer.util.arrayFromSegmentBinaryLabelmap(segmentation, name, self.volume).astype(bool)

    def masks(self, segmentation=None, names=None):
        segmentation = segmentation or self.active
        if not segmentation or not self.volume:
            return {}
        if segmentation is self.automatic:
            self.verify_automatic()
        validate_segmentation_geometry(segmentation, self.volume)
        ids = [segmentation.GetSegmentation().GetNthSegmentID(i) for i in range(segmentation.GetSegmentation().GetNumberOfSegments())]
        return {name: slicer.util.arrayFromSegmentBinaryLabelmap(segmentation, name, self.volume).astype(bool)
                for name in ids if names is None or name in names}

    def slice_masks(self):
        """Compact cropped masks for display; avoid allocating six full CT volumes."""
        if not self.active:
            return {}
        validate_segmentation_geometry(self.active, self.volume)
        self.verify_automatic()
        result = {}
        for name in STRUCTURES:
            if not self.active.GetSegmentation().GetSegment(name):
                continue
            image = slicer.vtkOrientedImageData()
            self.active.GetBinaryLabelmapRepresentation(name, image)
            matrix = vtk.vtkMatrix4x4()
            image.GetImageToWorldMatrix(matrix)
            extent = image.GetExtent()
            shift = np.eye(4)
            shift[:3, 3] = [extent[0], extent[2], extent[4]]
            result[name] = (slicer.util.arrayFromSegmentBinaryLabelmap(self.active, name).astype(bool),
                            matrix_array(matrix) @ shift)
        return result

    def fingerprint(self, segmentation):
        digest = hashlib.sha256()
        for index in range(segmentation.GetSegmentation().GetNumberOfSegments()):
            name = segmentation.GetSegmentation().GetNthSegmentID(index)
            digest.update(name.encode('utf-8'))
            digest.update(slicer.util.arrayFromSegmentBinaryLabelmap(segmentation, name, self.volume).astype(bool).tobytes())
        return digest.hexdigest()

    def verify_automatic(self):
        if self.automatic and self.automatic_fingerprint and self.fingerprint(self.automatic) != self.automatic_fingerprint:
            raise ValueError('自动基准结果已被修改，不能作为模型原始结果导出。请重新推理或打开未修改的研究包。')

    def expected_names(self):
        return {name for run in self.runs for name in run.get('class_map', {}).values()}

    def measurements(self):
        automatic = {name: volume_ml(mask, volume_affine(self.volume)) for name, mask in self.iter_masks(self.automatic)}
        corrected = ({name: volume_ml(mask, volume_affine(self.volume)) for name, mask in self.iter_masks(self.corrected)}
                     if self.corrected else automatic)
        affine = volume_affine(self.volume)
        return {name: {'automatic_ml': automatic.get(name, 0.),
                       'corrected_ml': corrected.get(name, 0.),
                       'status': 'present' if corrected.get(name, 0.) > 0 else 'absent'}
                for name in sorted(set(automatic) | set(corrected) | self.expected_names())}

    def save(self, destination):
        validate_volume(self.volume)
        if not self.automatic:
            raise ValueError('请先生成自动结果。')
        self.persist()
        names = sorted(set(self.measurements()) | self.expected_names())
        mapping = {name: index + 1 for index, name in enumerate(names)}
        arrays = {}
        for role, node in [('automatic', self.automatic), ('corrected', self.corrected or self.automatic)]:
            labels = np.zeros(slicer.util.arrayFromVolume(self.volume).shape, dtype=np.uint16)
            for name, mask in self.iter_masks(node):
                if np.any((labels != 0) & mask):
                    raise ValueError(f'{role} 中结构重叠，不能无损导出单层多标签 NIfTI。请先处理重叠或使用 Slicer 场景保存。')
                labels[mask] = mapping[name]
            arrays[role] = labels
        measurement = self.measurements()
        def produce(path):
            if not slicer.util.saveNode(self.volume, str(path / 'input.nii.gz')):
                raise IOError('影像保存失败。')
            affine = volume_affine(self.volume)
            for role, labels in arrays.items():
                save_labelmap(labels, self.volume, path / f'{role}.nii.gz')
            check = slicer.util.loadVolume(str(path / 'input.nii.gz'), {'show': False})
            try:
                if not np.allclose(volume_affine(check), affine, atol=1e-4):
                    raise IOError('导出影像几何校验失败。')
            finally:
                slicer.mrmlScene.RemoveNode(check)
            dump_json(path / 'class_map.json', {str(value): {'id': name, 'name_zh': display_name(name)} for name, value in mapping.items()})
            dump_json(path / 'labels.json', {'offsets': self.offsets, 'hidden': self.hidden})
            dump_json(path / 'run.json', {'schema': 1, 'slicer': slicer.app.applicationVersion,
                                        'atlas_version': '0.1.0', 'runs': self.runs,
                                        'geometry_ras': affine.tolist(), 'shape_kji': list(arrays['automatic'].shape),
                                        'series_uid': self.volume.GetAttribute('DICOM.SeriesInstanceUID') or 'unavailable'})
            with open(path / 'volumes.csv', 'w', newline='', encoding='utf-8-sig') as stream:
                writer = csv.writer(stream)
                writer.writerow(['structure', 'name_zh', 'automatic_ml', 'corrected_ml', 'status'])
                for name, values in measurement.items():
                    writer.writerow([name, display_name(name), values['automatic_ml'], values['corrected_ml'], values['status']])
            self.save_case_scene(path / 'scene.mrb')
            if not zipfile.is_zipfile(path / 'scene.mrb'):
                raise IOError('场景包格式无效。')
        return write_bundle(destination, produce)

    def save_case_scene(self, destination):
        """Serialize only this case; unrelated images and scene nodes are excluded."""
        scene = slicer.vtkMRMLScene()
        with tempfile.TemporaryDirectory(prefix='atlas-case-scene-') as temp:
            root = Path(temp)
            (root / 'Data').mkdir()
            scene.SetRootDirectory(str(root))
            volume = scene.AddNewNodeByClass('vtkMRMLScalarVolumeNode', 'Atlas CT')
            volume.CopyContent(self.volume)
            volume.SetAndObserveDisplayNodeID(None)
            volume.SetAndObserveStorageNodeID(None)
            volume.SetAndObserveTransformNodeID(None)
            volume.SetAttribute('HeadNeckAtlas.Modality', 'CT')
            volume.CreateDefaultDisplayNodes()
            volume.GetDisplayNode().CopyContent(self.volume.GetDisplayNode())
            volume.AddDefaultStorageNode()
            volume.GetStorageNode().SetFileName(str(root / 'Data' / 'input.nii.gz'))
            if not volume.GetStorageNode().WriteData(volume):
                raise IOError('病例场景影像保存失败。')
            volume.GetStorageNode().SetFileName('Data/input.nii.gz')
            nodes = {}
            for role, source in [('Automatic', self.automatic), ('Corrected', self.corrected or self.automatic)]:
                node = scene.AddNewNodeByClass('vtkMRMLSegmentationNode', 'Atlas ' + role)
                node.GetSegmentation().DeepCopy(source.GetSegmentation())
                node.SetReferenceImageGeometryParameterFromVolumeNode(volume)
                node.CreateDefaultDisplayNodes()
                node.GetDisplayNode().CopyContent(source.GetDisplayNode())
                node.SetHideFromEditors(role == 'Automatic')
                node.AddDefaultStorageNode()
                filename = role.lower() + '.seg.nrrd'
                node.GetStorageNode().SetFileName(str(root / 'Data' / filename))
                if not node.GetStorageNode().WriteData(node):
                    raise IOError('病例场景分割保存失败。')
                node.GetStorageNode().SetFileName('Data/' + filename)
                nodes[role] = node
            parameters = slicer.vtkMRMLScriptedModuleNode()
            parameters.SetSingletonTag('HeadNeckAtlas')
            parameters.SetModuleName('HeadNeckAtlas')
            parameters = scene.AddNode(parameters)
            parameters.SetNodeReferenceID('Input', volume.GetID())
            for role, node in nodes.items():
                parameters.SetNodeReferenceID(role, node.GetID())
            parameters.SetParameter('Runs', json.dumps(self.runs))
            parameters.SetParameter('Offsets', json.dumps(self.offsets))
            parameters.SetParameter('Hidden', json.dumps(self.hidden))
            parameters.SetParameter('AutomaticFingerprint', self.automatic_fingerprint or '')
            scene.SetURL(str(root / 'scene.mrml'))
            if not scene.Commit():
                raise IOError('病例场景序列化失败。')
            with zipfile.ZipFile(destination, 'w', zipfile.ZIP_DEFLATED) as archive:
                for file in root.rglob('*'):
                    if file.is_file():
                        archive.write(file, 'AtlasCase/' + file.relative_to(root).as_posix())

    def load(self, path):
        root = Path(path)
        validate_bundle(root)
        # Reject malicious archive paths before Slicer extracts the scene.
        with zipfile.ZipFile(root / 'scene.mrb') as archive:
            if archive.testzip():
                raise ValueError('场景压缩包损坏。')
            for info in archive.infolist():
                name = info.filename.replace('\\', '/')
                if Path(name).is_absolute() or '..' in Path(name).parts or ':' in name:
                    raise ValueError('场景压缩包包含不安全路径。')
        # Recover the current scene if importing or semantic validation fails.
        with tempfile.TemporaryDirectory(prefix='atlas-load-rollback-') as temp:
            backup = str(Path(temp) / 'backup.mrb')
            if not slicer.util.saveScene(backup):
                raise IOError('无法备份当前场景，取消打开研究包。')
            try:
                slicer.mrmlScene.Clear(0)
                if not slicer.util.loadScene(str(root / 'scene.mrb')):
                    raise IOError('场景加载失败。')
                self.restore()
                validate_volume(self.volume)
                if not self.automatic or not self.corrected:
                    raise ValueError('场景缺少自动或修正结果。')
                validate_segmentation_geometry(self.automatic, self.volume)
                validate_segmentation_geometry(self.corrected, self.volume)
                self.verify_automatic()
                self.configure_visibility()
            except Exception:
                slicer.mrmlScene.Clear(0)
                if not slicer.util.loadScene(backup):
                    raise IOError('场景导入及回滚失败，原始研究包仍保留。')
                self.restore()
                raise
