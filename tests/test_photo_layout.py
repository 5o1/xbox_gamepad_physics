import importlib.util
from pathlib import Path
import unittest

spec = importlib.util.spec_from_file_location('photo', Path(__file__).parents[1] / 'scripts/check_photo_layout.py')
photo = importlib.util.module_from_spec(spec)
spec.loader.exec_module(photo)


class PhotoLayoutTests(unittest.TestCase):
    def test_exact_ruler_and_held_out_error(self):
        data = {'ruler_fit_mm_y_px': [[0, 7], [10, 27]],
                'ruler_holdout_mm_y_px': [[5, 18]],
                'shaft_opening_centers_px': [[0, 20], [0, 40]],
                'manual_readout_sensitivity_px': 1}
        result = photo.analyze(data)
        self.assertEqual(result['ruler_plane_equivalent_separation_mm'], 10)
        self.assertEqual(result['held_out_residual_px'], [1])
        self.assertEqual(result['center_readout_only_sensitivity_mm'], [9, 11])
        self.assertIsNone(result['physical_distance_m'])

    def test_degenerate_and_reversed_ruler_rejected(self):
        for marks in [[], [[1, 2], [1, 3]], [[0, 2], [1, 1]]]:
            with self.assertRaises(ValueError):
                photo.ruler_fit(marks)
