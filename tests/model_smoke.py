"""Real model pipeline smoke on a synthetic head; accuracy is not evaluated."""
import json
import os
from pathlib import Path
import sys
import numpy as np
import nibabel as nib

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / 'HeadNeckAtlas'))
os.environ['TOTALSEG_HOME_DIR'] = str(ROOT / 'tools' / 'model-cache')
from AtlasLib.bundle import dump_json
from AtlasLib.inference import build_request, run_worker

directory = ROOT / 'test-results' / 'model-smoke'
directory.mkdir(parents=True, exist_ok=True)
grid = np.indices((64, 64, 64)).astype(float)
radius = np.sqrt(((grid - np.array([32, 32, 32])[:, None, None, None]) ** 2).sum(axis=0))
image = np.full((64, 64, 64), -1000, dtype=np.int16)
image[radius < 27] = 40
image[(radius > 24) & (radius < 27)] = 900
affine = np.diag([2., 2., 2., 1.])
affine[:3, 3] = [-64, -64, -64]
nib.save(nib.Nifti1Image(image, affine), str(directory / 'input.nii.gz'))
task = sys.argv[1] if len(sys.argv) > 1 else 'head_glands_cavities'
output = directory / (task + '.nii.gz')
if output.exists():
    raise RuntimeError('Use a fresh output directory for model smoke.')
request = build_request(directory / 'input.nii.gz', output, task, 'cpu', True)
dump_json(directory / 'request.json', request)
code = run_worker(directory / 'request.json')
response = json.loads((directory / 'response.json').read_text(encoding='utf-8'))
if code == 0:
    labels = nib.load(str(output))
    assert labels.shape == image.shape
    np.testing.assert_allclose(labels.affine, affine)
    assert set(np.unique(labels.get_fdata()).astype(int)) <= {0} | {int(value) for value in response['class_map']}
    print('REAL_MODEL_SMOKE_PASS (synthetic data; no accuracy claim)', flush=True)
sys.exit(code)
