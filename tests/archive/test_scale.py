import importlib.util
from pathlib import Path
import math
import unittest

path = Path(__file__).resolve().parents[2] / "scripts/archive/scale_visual_candidate.py"
spec = importlib.util.spec_from_file_location("scaling", path)
scaling = importlib.util.module_from_spec(spec)
spec.loader.exec_module(scaling)


class ScaleTests(unittest.TestCase):
    def test_uniform_scale_and_preserve_faces(self):
        lines = ["v -2 1 3", "v 2 5 7", "f 1 2 1"]
        scale = scaling.width_scale(scaling.parse_vertices(lines), 0.153)
        actual = scaling.scale_lines(lines, scale)
        self.assertEqual(actual[-1], lines[-1])
        points = scaling.parse_vertices(actual)
        self.assertAlmostEqual(points[1][0] - points[0][0], 0.153)
        self.assertAlmostEqual(points[1][1] - points[0][1], 0.153)
        self.assertAlmostEqual(points[1][2] - points[0][2], 0.153)

    def test_invalid_width_and_coordinates(self):
        for vertices, width in (
            ([], 1),
            ([(0, 0, 0)], 1),
            ([(0, 0, 0), (1, 0, 0)], -1),
            ([(math.nan, 0, 0)], 1),
        ):
            with self.assertRaises(ValueError):
                scaling.width_scale(vertices, width)


if __name__ == "__main__":
    unittest.main()
