import sys
import unittest
from pathlib import Path
import numpy as np

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / 'HeadNeckAtlas'))
from AtlasLib.geometry import sample_slice, interior_anchor, layout_labels, volume_ml


class GeometryTests(unittest.TestCase):
    def test_slice_oblique_physical_projection(self):
        mask = np.zeros((4, 4, 4), dtype=np.uint8)
        mask[1, 2, 1] = 1
        # screen x follows I+K; y follows J; origin K=0
        xy = np.eye(4)
        xy[2, 0] = 1
        result = sample_slice(mask, np.eye(4), xy, 4, 4)
        self.assertTrue(result[2, 1])
        self.assertEqual(int(result.sum()), 1)

    def test_ras_flip_and_origin(self):
        mask = np.zeros((1, 3, 3), dtype=np.uint8)
        mask[0, 1, 0] = 1
        affine = np.eye(4)
        affine[0, 0], affine[0, 3] = -2, 4
        xy = np.eye(4)
        result = sample_slice(mask, affine, xy, 5, 3)
        self.assertTrue(result[1, 4])
        self.assertFalse(result[1, 0])

    def test_outside_volume_is_empty(self):
        xy = np.eye(4)
        xy[2, 3] = 50
        self.assertIsNone(interior_anchor(sample_slice(np.ones((2, 2, 2)), np.eye(4), xy, 4, 4)))

    def test_largest_nonconvex_component_anchor_is_inside(self):
        mask = np.zeros((10, 10), dtype=bool)
        mask[1:8, 1:3] = True
        mask[6:8, 1:8] = True
        mask[0, 9] = True
        x, y = interior_anchor(mask)
        self.assertTrue(mask[y, x])
        self.assertNotEqual((x, y), (9, 0))

    def test_label_crowding_and_drag_stay_in_bounds(self):
        items = [{'id': str(i), 'anchor': (20, 5)} for i in range(6)]
        result = layout_labels(items, 400, 100, {'0': (5000, -1000)})
        visible = [item for item in result if not item['hidden']]
        self.assertLess(len(visible), 6)
        ys = sorted(item['position'][1] for item in visible)
        self.assertTrue(all(b - a >= 24 for a, b in zip(ys, ys[1:])))
        self.assertTrue(all(0 <= item['position'][0] <= 260 and 0 <= item['position'][1] <= 76 for item in visible))

    def test_volume_uses_affine_determinant(self):
        affine = np.diag([2, 3, 4, 1])
        self.assertAlmostEqual(volume_ml(np.ones((2, 2, 2)), affine), .192)

    def test_rejects_singular_and_nonfinite_geometry(self):
        for affine in [np.zeros((4, 4)), np.full((4, 4), np.nan)]:
            with self.assertRaises(ValueError):
                sample_slice(np.ones((1, 1, 1)), affine, np.eye(4), 2, 2)


if __name__ == '__main__':
    unittest.main()
