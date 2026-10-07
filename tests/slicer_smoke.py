"""Run with Slicer --python-script; uses synthetic data, no patient/model download."""
import json
import sys
import tempfile
import traceback
from pathlib import Path
import numpy as np
import slicer
import vtk

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / 'HeadNeckAtlas'))
OUTPUT = ROOT / 'test-results'
OUTPUT.mkdir(exist_ok=True)


def run():
    from AtlasLib.slicer_bridge import AtlasSession, matrix_array
    slicer.mrmlScene.Clear(0)
    volume = slicer.mrmlScene.AddNewNodeByClass('vtkMRMLScalarVolumeNode', 'Synthetic CT')
    data = np.full((16, 32, 32), -1000, dtype=np.int16)
    data[2:14, 6:26, 6:26] = 50
    slicer.util.updateVolumeFromArray(volume, data)
    volume.SetSpacing(1, 1, 2)
    volume.SetOrigin(-16, -16, -16)
    volume.SetAttribute('HeadNeckAtlas.Modality', 'CT')
    volume.CreateDefaultDisplayNodes()
    session = AtlasSession()
    session.select_volume(volume)
    result = slicer.mrmlScene.AddNewNodeByClass('vtkMRMLSegmentationNode', 'Test result')
    result.CreateDefaultDisplayNodes()
    result.SetReferenceImageGeometryParameterFromVolumeNode(volume)
    seg_id = result.GetSegmentation().AddEmptySegment('eye_left', 'eye_left')
    mask = np.zeros_like(data, dtype=np.uint8)
    mask[6:10, 8:12, 8:12] = 1
    slicer.util.updateSegmentBinaryLabelmapFromArray(mask, result, seg_id, volume)
    session.ingest(result, 'head_glands_cavities', {'model_version': 'synthetic-test', 'status': 'success',
                                                 'class_map': {'1': 'eye_left', '2': 'eye_right'}})
    assert session.automatic.GetHideFromEditors(), 'Automatic result must not appear in editable node selectors'
    with tempfile.TemporaryDirectory(dir=OUTPUT) as temp:
        session.save(Path(temp) / 'before-correction')
        assert session.corrected is None, 'Saving must not lock further task inference'
        try:
            session.save(Path(temp) / 'before-correction')
        except FileExistsError:
            pass
        else:
            raise AssertionError('Existing bundle overwritten')
        assert session.corrected is None, 'Failed save changed edit state'
    assert session.measurements()['eye_right']['automatic_ml'] == 0
    assert session.measurements()['eye_right']['status'] == 'absent'
    slicer.util.updateSegmentBinaryLabelmapFromArray(np.zeros_like(mask), session.automatic, 'eye_left', volume)
    try:
        session.measurements()
    except ValueError:
        pass
    else:
        raise AssertionError('Automatic baseline tampering was not detected')
    slicer.util.updateSegmentBinaryLabelmapFromArray(mask, session.automatic, 'eye_left', volume)
    corrected = session.create_corrected()
    edited = mask.copy()
    edited[6, 8, 8] = 0
    slicer.util.updateSegmentBinaryLabelmapFromArray(edited, corrected, 'eye_left', volume)
    np.testing.assert_array_equal(slicer.util.arrayFromSegmentBinaryLabelmap(session.automatic, 'eye_left', volume), mask)
    assert session.measurements()['eye_left']['corrected_ml'] == .126
    with tempfile.TemporaryDirectory(dir=OUTPUT) as temp:
        bundle = Path(temp) / 'case'
        unrelated = slicer.mrmlScene.AddNewNodeByClass('vtkMRMLScalarVolumeNode', 'Unrelated patient sentinel')
        slicer.util.updateVolumeFromArray(unrelated, np.zeros((2, 2, 2), dtype=np.int16))
        session.save(bundle)
        assert (bundle / 'automatic.nii.gz').is_file()
        assert (bundle / 'corrected.nii.gz').is_file()
        slicer.mrmlScene.Clear(0)
        session = AtlasSession()
        session.load(bundle)
        assert not any(node.GetName() == 'Unrelated patient sentinel' for node in slicer.util.getNodesByClass('vtkMRMLScalarVolumeNode')), 'Bundle leaked unrelated case'
        np.testing.assert_array_equal(slicer.util.arrayFromSegmentBinaryLabelmap(session.corrected, 'eye_left', session.volume), edited)
        assert session.runs[0]['model_version'] == 'synthetic-test'
        # Checksum-valid but semantically invalid scenes must roll back current work.
        import zipfile
        from AtlasLib.bundle import write_bundle
        invalid = Path(temp) / 'invalid-case'
        def bad_scene(path):
            (path / 'run.json').write_text('{}')
            with zipfile.ZipFile(path / 'scene.mrb', 'w') as archive:
                archive.writestr('Bad/scene.mrml', '<MRML version="Slicer5.12.4"></MRML>')
        write_bundle(invalid, bad_scene)
        try:
            session.load(invalid)
        except (ValueError, IOError):
            pass
        else:
            raise AssertionError('Invalid case scene was accepted')
        assert session.volume is not None, 'Failed load did not restore the original scene'
        np.testing.assert_array_equal(slicer.util.arrayFromSegmentBinaryLabelmap(session.corrected, 'eye_left', session.volume), edited)
    slicer.util.selectModule('HeadNeckAtlas')
    widget = slicer.modules.headneckatlas.widgetRepresentation().self()
    widget.volumeSelector.setCurrentNode(session.volume)
    widget.session = session
    widget.refresh()
    slicer.util.setSliceViewerLayers(background=session.volume)
    slicer.util.resetSliceViews()
    slicer.app.processEvents()
    widget.overlay.update()
    assert widget.structureList.count == 6
    assert widget.overlay.mask_cache is not None
    new_mask = edited.copy()
    new_mask[7, 9, 9] = 0
    slicer.util.updateSegmentBinaryLabelmapFromArray(new_mask, session.corrected, 'eye_left', session.volume)
    assert widget.overlay.mask_cache is None, 'Segment edits must invalidate slice anchor cache'
    widget.overlay.update()
    # Show a real slice capture as a visual inspection artifact.
    view = slicer.app.layoutManager().sliceWidget('Red').sliceView()
    view.grab().save(str(OUTPUT / 'slicer-synthetic.png'))
    slicer.util.mainWindow().resize(1280, 800)
    slicer.app.processEvents()
    slicer.util.mainWindow().grab().save(str(OUTPUT / 'slicer-module.png'))
    # Actual QProcess boundary: deny downloads and observe failure without stale import.
    session.select_volume(None)
    session.select_volume(widget.volumeSelector.currentNode())
    widget.refresh()
    widget.start_inference()
    import time
    deadline = time.monotonic() + 90
    while widget.process is not None and time.monotonic() < deadline:
        slicer.app.processEvents()
        time.sleep(.02)
    assert widget.process is None, 'Worker timed out'
    assert widget.session.automatic is None, 'Failure imported an automatic result'
    assert ('权重' in widget.status.text or '下载' in widget.status.text), widget.status.text
    widget.start_inference()
    slicer.mrmlScene.Clear(0)
    deadline = time.monotonic() + 15
    while widget.process is not None and time.monotonic() < deadline:
        slicer.app.processEvents()
        time.sleep(.02)
    assert widget.process is None, 'Scene close left a worker running'
    slicer.app.processEvents()
    assert widget.session.volume is None
    print('SLICER_SMOKE_PASS', flush=True)


try:
    run()
except Exception:
    error = traceback.format_exc()
    (OUTPUT / 'slicer-smoke-result.json').write_text(json.dumps({'status': 'failed', 'error': error}, indent=2), encoding='utf-8')
    print(error, flush=True)
    slicer.app.exit(1)
else:
    (OUTPUT / 'slicer-smoke-result.json').write_text(json.dumps({'status': 'passed', 'slicer': slicer.app.applicationVersion}), encoding='utf-8')
    slicer.app.exit(0)
