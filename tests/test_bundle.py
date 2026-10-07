import json
import sys
import tempfile
import unittest
from pathlib import Path
sys.path.insert(0, str(Path(__file__).resolve().parents[1] / 'HeadNeckAtlas'))
from AtlasLib.bundle import write_bundle, validate_bundle


class BundleTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.addCleanup(self.temp.cleanup)
        self.path = Path(self.temp.name) / 'case'

    def produce(self, path):
        (path / 'run.json').write_text('{"case": "研究甲"}', encoding='utf-8')
        (path / 'scene.mrb').write_bytes(b'scene')

    def test_roundtrip_and_existing_directory_not_overwritten(self):
        write_bundle(self.path, self.produce)
        self.assertEqual(validate_bundle(self.path)['schema'], 1)
        with self.assertRaises(FileExistsError):
            write_bundle(self.path, self.produce)

    def test_partial_producer_does_not_publish(self):
        def fail(path):
            self.produce(path)
            raise RuntimeError('disk failure')
        with self.assertRaises(RuntimeError):
            write_bundle(self.path, fail)
        self.assertFalse(self.path.exists())
        self.assertEqual(list(self.path.parent.iterdir()), [])

    def test_tampering_rejected(self):
        write_bundle(self.path, self.produce)
        (self.path / 'scene.mrb').write_bytes(b'tampered')
        with self.assertRaises(ValueError):
            validate_bundle(self.path)

    def test_manifest_traversal_rejected(self):
        write_bundle(self.path, self.produce)
        manifest = json.loads((self.path / 'manifest.json').read_text())
        manifest['files']['../secret'] = 'x'
        (self.path / 'manifest.json').write_text(json.dumps(manifest))
        with self.assertRaises(ValueError):
            validate_bundle(self.path)

    def test_unlisted_files_and_missing_scene_rejected(self):
        write_bundle(self.path, self.produce)
        (self.path / 'unexpected').write_text('x')
        with self.assertRaises(ValueError):
            validate_bundle(self.path)
        with self.assertRaises(ValueError):
            write_bundle(self.path.parent / 'empty', lambda path: None)
