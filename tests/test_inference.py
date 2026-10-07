import sys
import tempfile
import unittest
from pathlib import Path
sys.path.insert(0, str(Path(__file__).resolve().parents[1] / 'HeadNeckAtlas'))
from AtlasLib.inference import build_request, run_worker


class InferenceTests(unittest.TestCase):
    def test_rejects_invalid_task_device_and_missing_input(self):
        with tempfile.TemporaryDirectory() as temp:
            image = Path(temp) / 'ct.nii.gz'
            image.write_bytes(b'fixture')
            for task, device in [('anything', 'cpu'), ('head_muscles', 'auto')]:
                with self.assertRaises(ValueError):
                    build_request(image, Path(temp)/'out.nii.gz', task, device, False)
            with self.assertRaises(FileNotFoundError):
                build_request(Path(temp)/'missing', Path(temp)/'out', 'head_muscles', 'cpu', False)

    def test_download_consent_is_explicit_boolean(self):
        with tempfile.TemporaryDirectory() as temp:
            image = Path(temp) / 'ct.nii.gz'
            image.touch()
            with self.assertRaises(ValueError):
                build_request(image, Path(temp)/'out', 'head_muscles', 'cpu', 'false')
            request = build_request(image, Path(temp)/'out', 'head_muscles', 'cpu', False)
            self.assertFalse(request['allow_download'])
            self.assertFalse(request['fast'])

    def test_worker_records_failure_without_success(self):
        with tempfile.TemporaryDirectory() as temp:
            request = Path(temp) / 'request.json'
            request.write_text('{"task":"unknown"}')
            import contextlib
            import io
            with contextlib.redirect_stdout(io.StringIO()):
                self.assertEqual(run_worker(request), 1)
            import json
            response = json.loads(request.with_name('response.json').read_text())
            self.assertEqual(response['status'], 'failed')
            self.assertIn('error', response)


if __name__ == '__main__':
    unittest.main()
