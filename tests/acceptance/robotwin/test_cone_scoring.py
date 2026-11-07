"""Behavioral regression for the original diagonal and single-axis criteria."""
import json,unittest
from .stick_cone_production import P,score_trace

class ConeScoringTest(unittest.TestCase):
 def test_diagonal_has_only_upper_angle_bound(self):
  protocol=json.loads(P.read_text())
  for direction,angle,expected in [('diagonal45',22.89,True),('positive_x',22.89,False),('diagonal45',23.11,False)]:
   rows=[{'time_s':t,'angle_deg':angle if t<=1 else 0,'tilt_qvel_rad_s':[0,0]} for t in [.8,1.,1.8,2.]]
   with self.subTest(direction=direction,angle=angle):
    score=score_trace(direction,rows,protocol)
    self.assertEqual(score['passed'],expected)
    self.assertEqual(score['boundary_reached'],angle>=22.9)

if __name__=='__main__':unittest.main()
