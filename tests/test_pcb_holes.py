import importlib.util
from pathlib import Path
import unittest

AVAILABLE = all(importlib.util.find_spec(name) for name in ('cv2', 'numpy'))
if AVAILABLE:
    spec = importlib.util.spec_from_file_location('holes', Path(__file__).parents[1] / 'scripts/fit_pcb_holes.py')
    holes = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(holes)


@unittest.skipUnless(AVAILABLE, 'Needs GPU OpenCV environment')
class HoleFitTests(unittest.TestCase):
    def test_exact_transform_independent_holdout(self):
        data = {'fit':[{'scan':[x,y], 'photo':[2*x+7,3*y-2]}
                       for x,y in [(0,0),(10,0),(10,10),(0,10)]],
                'holdout':[{'name':'unused_point','scan':[4,6],'photo':[15,16]}]}
        result = holes.fit(data)
        self.assertLess(result['holdouts'][0]['photo_error_px'], 1e-8)
        self.assertFalse(result['physical_calibration_approved'])
        self.assertIsNone(result['metric_scale'])

    def test_collinear_points_rejected(self):
        with self.assertRaises(ValueError):
            holes.fit({'fit':[{'scan':[x,0],'photo':[x,0]} for x in range(4)], 'holdout':[]})
