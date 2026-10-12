"""One-way timing bounds and quaternion drift calculations without SAPIEN."""
from pathlib import Path
import math
import sys
import unittest
sys.path.insert(0,str(Path(__file__).resolve().parents[1]))
from teleop.safety_analysis import clock_interval, mapped_time, affine_time, pose_motion, rotation_degrees


class SafetyMeasurementTest(unittest.TestCase):
    def test_clock_bounds_cover_asymmetric_transit(self):
        # Real offset 100 ms, forward 2 ms, return 6 ms, processing 1 ms.
        p=[{'t0_ms':10,'server_received_ns':112000000,'server_sent_ns':113000000,'t3_ms':19}]
        self.assertEqual(clock_interval(p),(94,102))
        mapped=mapped_time(20,p,p)
        self.assertLessEqual(mapped['lower_ns'],120000000)
        self.assertGreaterEqual(mapped['upper_ns'],120000000)
        self.assertEqual(mapped['uncertainty_ms'],4)

    def test_inconsistent_clock_samples_fail(self):
        with self.assertRaises(ValueError):clock_interval([
            {'t0_ms':0,'server_received_ns':1000000,'server_sent_ns':10000000,'t3_ms':0}])

    def test_affine_clock_covers_real_rate_difference_and_asymmetric_transit(self):
        probes=[]
        for c in (0,20,40,1000,1020,1040):
            # Server clock a=.9, b=100; forward 2, return 6 server ms.
            probes.append({'t0_ms':c,'server_received_ns':int((.9*c+102)*1e6),
                'server_sent_ns':int((.9*c+103)*1e6),'t3_ms':c+9/.9})
        m=affine_time(500,probes[:3],probes[3:])
        self.assertLessEqual(m['lower_ns'],550000000)
        self.assertGreaterEqual(m['upper_ns'],550000000)
        self.assertLessEqual(m['rate_bounds'][0],.9)
        self.assertGreaterEqual(m['rate_bounds'][1],.9)

    def test_pose_units_and_quaternion_sign(self):
        self.assertEqual(rotation_degrees([1,0,0,0],[-1,0,0,0]),0)
        a=[0,0,0,1,0,0,0];b=[.003,.004,0,math.cos(math.pi/4),0,0,math.sin(math.pi/4)]
        distance,angle=pose_motion(a,b)
        self.assertAlmostEqual(distance,5)
        self.assertAlmostEqual(angle,90)


if __name__=='__main__':unittest.main()
