"""CUDA mask selection preserves caller ordinals and opaque GPU/MIG identifiers."""
import unittest
from xbox_gamepad_physics.gpu import gpu_environment


class GPUSelectionTest(unittest.TestCase):
    def test_no_mask(self):
        self.assertEqual(gpu_environment(2, {'OTHER': 'value'}),
                         {'OTHER': 'value', 'CUDA_VISIBLE_DEVICES': '2'})

    def test_integer_mask(self):
        parent = {'CUDA_VISIBLE_DEVICES': '3,1'}
        self.assertEqual(gpu_environment(0, parent)['CUDA_VISIBLE_DEVICES'], '3')
        self.assertEqual(gpu_environment(1, parent)['CUDA_VISIBLE_DEVICES'], '1')
        self.assertEqual(parent['CUDA_VISIBLE_DEVICES'], '3,1')

    def test_uuid_and_mig_mask(self):
        mask = {'CUDA_VISIBLE_DEVICES': 'GPU-example,MIG-GPU-example/1/0'}
        self.assertEqual(gpu_environment(0, mask)['CUDA_VISIBLE_DEVICES'], 'GPU-example')
        self.assertEqual(gpu_environment(1, mask)['CUDA_VISIBLE_DEVICES'], 'MIG-GPU-example/1/0')

    def test_out_of_range_and_hidden_devices(self):
        for index, mask in ((1, '3'), (0, ''), (0, '-1'), (1, '3,-1,2')):
            with self.subTest(index=index, mask=mask), self.assertRaisesRegex(ValueError, 'outside'):
                gpu_environment(index, {'CUDA_VISIBLE_DEVICES': mask})
        for index in (-1, True, '0'):
            with self.subTest(index=index), self.assertRaises(ValueError):
                gpu_environment(index, {})
