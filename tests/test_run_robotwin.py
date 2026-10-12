"""Configuration/runner contract and optional real SAPIEN smoke coverage."""

from __future__ import annotations

import importlib.util
import json
from pathlib import Path
import sys
import tempfile
import unittest
from unittest import mock

import yaml


ROOT = Path(__file__).resolve().parents[1]
sys.path[:0] = [str(ROOT), str(ROOT / "src")]

from experiments import EXPERIMENTS
from experiments import runner


class ConfigurationTest(unittest.TestCase):
    def test_load_config(self):
        smoke = runner.load_config(ROOT / "configs/smoke_full_controls.yaml")
        self.assertEqual(smoke["experiment"], "smoke")
        self.assertEqual(smoke["profile"], "full_controls")
        self.assertFalse(smoke["scene"]["render"])
        self.assertEqual(smoke["params"]["steps"], 500)
        render = runner.load_config(ROOT / "configs/render_review.yaml")
        self.assertEqual(render["experiment"], "render_review")
        self.assertTrue(render["scene"]["render"])
        with tempfile.TemporaryDirectory() as directory:
            invalid = Path(directory) / "invalid.yaml"
            invalid.write_text("- not a mapping\n", encoding="utf-8")
            with self.assertRaisesRegex(ValueError, "mapping"):
                runner.load_config(invalid)

    def test_nested_overrides_and_yaml_types(self):
        cfg = runner.load_config(ROOT / "configs/smoke_full_controls.yaml")
        runner.apply_overrides(cfg, [
            "params.steps=20", "scene.timestep=0.01", "gamepad.fixed_root=false",
            "gamepad.pose=[0, 0, 0.2, 1, 0, 0, 0]", "experiment=smoke",
        ])
        self.assertEqual(cfg["params"]["steps"], 20)
        self.assertIs(type(cfg["params"]["steps"]), int)
        self.assertEqual(cfg["scene"]["timestep"], 0.01)
        self.assertIs(cfg["gamepad"]["fixed_root"], False)
        self.assertEqual(cfg["gamepad"]["pose"], [0, 0, 0.2, 1, 0, 0, 0])
        self.assertEqual(cfg["experiment"], "smoke")

    def test_unknown_keys_fail(self):
        for override in ("typo=1", "params.step=20", "missing.steps=20", "params.steps.typo=1"):
            with self.subTest(override=override):
                cfg = runner.load_config(ROOT / "configs/smoke_full_controls.yaml")
                with self.assertRaisesRegex(KeyError, "unknown configuration key"):
                    runner.apply_overrides(cfg, [override])
        with self.assertRaisesRegex(ValueError, "key=value"):
            runner.apply_overrides({}, ["params.steps"])

    def test_registry(self):
        self.assertEqual(set(EXPERIMENTS), {"smoke", "render_review", "drive_reach", "drop", "collision_check", "collision_overlay", "teleop_replay"})
        self.assertTrue(all(callable(run) for run in EXPERIMENTS.values()))


class RunnerTest(unittest.TestCase):
    def test_fake_experiment_outputs_and_context(self):
        cfg = runner.load_config(ROOT / "configs/smoke_full_controls.yaml")
        cfg["experiment"] = "fake"
        scene, gamepad = object(), object()

        def fake_run(final_cfg, ctx):
            self.assertEqual(final_cfg["params"]["steps"], 20)
            self.assertIs(ctx.scene, scene)
            self.assertIs(ctx.gamepad, gamepad)
            (ctx.output_dir / "artifact.txt").write_text("fake experiment\n", encoding="utf-8")
            return {"passed": True, "steps": final_cfg["params"]["steps"]}

        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            config = root / "fake.yaml"
            config.write_text(yaml.safe_dump(cfg), encoding="utf-8")
            with (
                mock.patch.dict(EXPERIMENTS, {"fake": fake_run}),
                mock.patch.object(runner, "ROOT", root),
                mock.patch.object(runner, "create_scene", return_value=scene) as create,
                mock.patch("xbox_gamepad_physics.robotwin.load_into_scene", return_value=gamepad) as load,
            ):
                self.assertEqual(runner.main([str(config), "--set", "params.steps=20"]), 0)
                outputs = list((root / "build/runs/fake").iterdir())
                self.assertEqual(len(outputs), 1)
                output = outputs[0]
                self.assertRegex(output.name, r"^\d{8}-\d{6}$")
                self.assertEqual(
                    {path.name for path in output.iterdir()},
                    {"config.yaml", "meta.json", "metrics.json", "artifact.txt"},
                )
                final_cfg = runner.load_config(output / "config.yaml")
                self.assertEqual(final_cfg["params"]["steps"], 20)
                create.assert_called_once_with(final_cfg["scene"])
                load.assert_called_once_with(scene, profile="full_controls", **final_cfg["gamepad"])
                metrics = json.loads((output / "metrics.json").read_text())
                self.assertEqual(metrics, {"passed": True, "steps": 20})
                meta = json.loads((output / "meta.json").read_text())
                self.assertEqual(set(meta), {"git_commit", "git_dirty", "python", "sapien", "resource_root", "command"})
                self.assertEqual(meta["command"][0], sys.executable)
                self.assertIn("params.steps=20", meta["command"])
                self.assertTrue(Path(meta["resource_root"]).is_absolute())
                explicit = root / "explicit"
                self.assertEqual(runner.main([
                    str(config), "--set", "params.steps=20", "--output", str(explicit),
                ]), 0)
                self.assertTrue((explicit / "metrics.json").is_file())


@unittest.skipIf(importlib.util.find_spec("sapien") is None, "SAPIEN is an optional backend dependency")
class SapienSmokeTest(unittest.TestCase):
    def test_smoke_twenty_steps_passes(self):
        config = ROOT / "configs/smoke_full_controls.yaml"
        cfg = runner.apply_overrides(runner.load_config(config), ["params.steps=20"])
        with tempfile.TemporaryDirectory() as directory:
            metrics = runner.run_experiment(cfg, config, directory)
        self.assertIs(metrics["passed"], True)
        self.assertTrue(all(metrics["checks"].values()))


if __name__ == "__main__":
    unittest.main()
