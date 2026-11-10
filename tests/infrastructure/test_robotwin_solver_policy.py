"""Numerical timestep policy parsing and selection, without native SAPIEN."""
import copy
from dataclasses import dataclass
import json
from pathlib import Path
import sys
import unittest
import warnings
from unittest.mock import patch

ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT/'src'))
from xbox_gamepad_physics.robotwin.physical import solver_iteration_points, select_solver_iterations


class SolverPolicyTest(unittest.TestCase):
    def setUp(self):
        options = json.loads((ROOT/'references/full_controls.json').read_text())['backend_options']['robotwin']
        self.options = {'solver_iterations': options['solver_iterations']}

    def test_parse_parameters_and_order(self):
        points = solver_iteration_points(self.options)
        self.assertEqual([(p.timestep_s, p.iterations) for p in points], [(.001, (10, 1)), (.004, (64, 16))])
        self.options['solver_iterations']['validated_points'].reverse()
        self.assertEqual(solver_iteration_points(self.options), points)

    def test_ceiling_selection_and_native_float_precision(self):
        for dt, expected in ((.0005, (10, 1)), (.001, (10, 1)), (.0010000000474974513, (10, 1)),
                             (.0011, (64, 16)), (.002, (64, 16)), (.004, (64, 16)), (.004000000189989805, (64, 16))):
            with self.subTest(dt=dt), warnings.catch_warnings():
                warnings.simplefilter('error')
                selected = select_solver_iterations(self.options, dt)
                self.assertEqual(selected.iterations, expected)
                self.assertEqual(selected.timestep_s, dt)

    def test_above_range_warns_and_keeps_usable_maximum(self):
        with self.assertWarnsRegex(RuntimeWarning, '0.008 s.*0.004 s.*64/16.*unvalidated'):
            selected = select_solver_iterations(self.options, .008)
        self.assertEqual((selected.iterations, selected.validated_timestep_s), ((64, 16), .004))

    def test_override_is_explicit_and_does_not_claim_validation(self):
        with warnings.catch_warnings():
            warnings.simplefilter('error')
            selected = select_solver_iterations(self.options, .008, (24, 2))
        self.assertEqual(selected.iterations, (24, 2))
        self.assertEqual(selected.source, 'override')
        self.assertIsNone(selected.validated_timestep_s)
        for invalid in ((0, 1), (10, -1), (True, 1), (10.0, 1), (10,), '10/1'):
            with self.subTest(override=invalid), self.assertRaises(ValueError):
                select_solver_iterations(self.options, .001, invalid)

    def test_historical_fixed_and_absent_policy(self):
        legacy = {k: self.options['solver_iterations']['validated_points'][1][k] for k in ('position', 'velocity')}
        selected = select_solver_iterations({'solver_iterations': legacy}, None)
        self.assertEqual((selected.iterations, selected.source), ((64, 16), 'legacy_fixed'))
        self.assertEqual(select_solver_iterations({}, None).source, 'scene_default')

    def test_existing_diagnostic_overrides_support_both_resource_formats(self):
        from experiments.robotwin.station_rtf.overrides import policy
        from experiments.robotwin.view_attribution.run import fixed_iterations
        from xbox_gamepad_physics.robotwin import loader

        @dataclass
        class Description:
            backend_options: dict

        legacy = {key: self.options['solver_iterations']['validated_points'][1][key]
                  for key in ('position', 'velocity')}
        for options in (self.options, {'solver_iterations': legacy}):
            original = copy.deepcopy(options)
            for context, expected in ((lambda: policy((24, 2)), (24, 2)),
                                      (fixed_iterations, (10, 1)), (policy, (64, 16))):
                with self.subTest(expected=expected), patch.object(
                    loader, '_validated_description', return_value=Description(options)
                ), context():
                    description = loader._validated_description('full_controls')
                    self.assertEqual(select_solver_iterations(description.backend_options, .004).iterations, expected)
                self.assertEqual(options, original)

    def test_invalid_policy_and_timestep_report_input_error(self):
        for dt in (None, 0, -1, True, float('nan'), float('inf')):
            with self.subTest(dt=dt), self.assertRaises(ValueError):
                select_solver_iterations(self.options, dt)
        for field, value in (('timestep_s', {'value': .001, 'unit': 'ms', 'evidence': []}),
                             ('position', {'value': 10, 'unit': '1', 'evidence': []})):
            raw = copy.deepcopy(self.options)
            raw['solver_iterations']['validated_points'][0][field] = value
            with self.subTest(field=field), self.assertRaises(ValueError):
                solver_iteration_points(raw)
        for points in ([], [self.options['solver_iterations']['validated_points'][0]]*2):
            with self.subTest(points=points), self.assertRaises(ValueError):
                solver_iteration_points({'solver_iterations': {'validated_points': points}})


if __name__ == '__main__':
    unittest.main()
