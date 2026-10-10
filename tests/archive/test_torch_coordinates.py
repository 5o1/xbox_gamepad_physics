import json
import sys
import unittest
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[2] / 'scripts' / 'archive'))
try:
    import torch
    from torch_coordinates import CoordinateMap
except ImportError:
    torch = None


@unittest.skipIf(torch is None, 'Run in GPU-node existing Torch environment')
class CoordinateTests(unittest.TestCase):
    def setUp(self):
        self.joints = [dict(channel=c, q0=-.2 if c < 4 else 0,
                            q1=.3 if c < 4 else .004, evidence='Synthetic fixture')
                       for c in (0, 1, 10, 11, 4)]
        self.model = CoordinateMap(self.joints)
        self.x = torch.full((2, 3, 21), .25, dtype=torch.float64)
        self.x[..., 0] = -.4
        self.x.requires_grad_()

    def test_forward_inverse_gradcheck_and_upstream_gradient(self):
        self.assertTrue(torch.autograd.gradcheck(self.model, (self.x,)))
        q = self.model(self.x).detach().requires_grad_()
        self.assertTrue(torch.autograd.gradcheck(self.model.inverse, (q,)))
        restored = self.model.inverse(self.model(self.x))
        torch.testing.assert_close(restored, self.x[..., self.model.channels])
        restored.sum().backward()
        expected = torch.zeros_like(self.x)
        expected[..., self.model.channels] = 1
        torch.testing.assert_close(self.x.grad, expected)

    def test_viewer_reference(self):
        path = Path(__file__).resolve().parent / 'fixtures/coordinate_reference.json'
        data = json.loads(path.read_text())
        model = CoordinateMap(data['joints'])
        x = torch.tensor(data['states'], dtype=torch.float64)
        q = model(x)
        torch.testing.assert_close(q, torch.tensor(data['coordinates'], dtype=q.dtype), atol=1e-12, rtol=1e-12)
        torch.testing.assert_close(model.inverse(q), torch.tensor(data['signals'], dtype=q.dtype), atol=1e-12, rtol=1e-12)

    def test_outside_inverse_has_zero_gradient_and_unknown_stays_absent(self):
        q = torch.full((5,), 2., dtype=torch.float64, requires_grad=True)
        out = self.model.inverse(q)
        self.assertEqual(out.shape, (5,))
        out.sum().backward()
        torch.testing.assert_close(q.grad, torch.zeros_like(q))

    def test_null_parameters_invalid_input_and_duplicates_rejected(self):
        for change in ({'q0': None}, {'q1': 0}, {'evidence': ''}, {'channel': True}):
            with self.assertRaises(ValueError):
                CoordinateMap([{**self.joints[0], **change}])
        with self.assertRaises(ValueError):
            CoordinateMap([self.joints[0], self.joints[0]])
        for x in (torch.zeros(20), torch.zeros(21, dtype=torch.int64), torch.full((21,), float('nan')), torch.ones(21)*2):
            with self.assertRaises(ValueError):
                self.model(x)

    def test_float32_preserves_dtype(self):
        x = self.x.detach().float().requires_grad_()
        y = self.model.inverse(self.model(x))
        self.assertEqual(y.dtype, torch.float32)
        y.sum().backward()
        self.assertTrue(torch.isfinite(x.grad).all())


if __name__ == '__main__':
    unittest.main()
