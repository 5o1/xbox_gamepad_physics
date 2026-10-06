import ast
import json
import subprocess
import sys
import tempfile
from pathlib import Path
import unittest


ROOT = Path(__file__).resolve().parents[1]
INTEGRITY_SCRIPTS = (
    "scripts/check_meshes.py",
    "scripts/export_xbox_one_s_visual_parts.py",
    "scripts/check_gltf_import_versions.py",
    "scripts/audit_xbox_artist_rig.py",
    "scripts/render_licensed_ibl_sweep.py",
    "scripts/render_reference_matched_probe.py",
)


class IntegrityGateTests(unittest.TestCase):
    def test_integrity_scripts_do_not_use_optimization_sensitive_asserts(self):
        for relative in INTEGRITY_SCRIPTS:
            with self.subTest(script=relative):
                tree = ast.parse((ROOT / relative).read_text(), filename=relative)
                assertions = [node.lineno for node in ast.walk(tree) if isinstance(node, ast.Assert)]
                self.assertEqual(assertions, [], f"assert gates disappear under python -O: {assertions}")

    def test_asset_schema_gate_survives_python_optimized_mode(self):
        code = f"""
import importlib.util, json, pathlib
root = pathlib.Path({str(ROOT)!r})
module_spec = importlib.util.spec_from_file_location('asset_spec', root / 'scripts/asset_spec.py')
asset = importlib.util.module_from_spec(module_spec)
module_spec.loader.exec_module(asset)
catalog = json.loads((root / 'sources/catalog.json').read_text())
specification = asset.make_spec(catalog)
specification['schema_version'] = 999
if asset.audit(specification, catalog)['schema_valid']:
    raise SystemExit('optimized mode accepted an invalid schema version')
"""
        completed = subprocess.run(
            [sys.executable, "-O", "-c", code],
            text=True,
            capture_output=True,
            check=False,
        )
        self.assertEqual(completed.returncode, 0, completed.stdout + completed.stderr)

    def test_model_hash_gates_run_before_blender_import_under_optimized_mode(self):
        with tempfile.TemporaryDirectory() as temporary:
            temporary = Path(temporary)
            bad_glb = temporary / "wrong.glb"
            bad_glb.write_bytes(b"not the reviewed model")
            commands = [
                [
                    sys.executable,
                    "-O",
                    str(ROOT / "scripts/export_xbox_one_s_visual_parts.py"),
                    "--",
                    str(bad_glb),
                    str(temporary / "export"),
                ]
            ]
            gltf_root = temporary / "gltf-root"
            source = gltf_root / "xbox/xbox_one_s_controllergamepad_animated.glb"
            source.parent.mkdir(parents=True)
            source.write_bytes(b"not the reviewed model")
            commands.append(
                [
                    sys.executable,
                    "-O",
                    str(ROOT / "scripts/check_gltf_import_versions.py"),
                    "--",
                    str(gltf_root),
                ]
            )
            for command in commands:
                with self.subTest(script=Path(command[2]).name):
                    completed = subprocess.run(command, text=True, capture_output=True, check=False)
                    self.assertNotEqual(completed.returncode, 0)
                    self.assertIn("does not match", completed.stdout + completed.stderr)
                    self.assertNotIn("No module named 'bpy'", completed.stdout + completed.stderr)

    def test_hdri_hash_gates_run_before_blender_import_under_optimized_mode(self):
        with tempfile.TemporaryDirectory() as temporary:
            temporary = Path(temporary)
            candidate = temporary / "candidate"
            candidate.mkdir()
            bad_hdri = temporary / "boiler_room_4k.exr"
            bad_hdri.write_bytes(b"not the reviewed HDRI")
            for script in ("render_licensed_ibl_sweep.py", "render_reference_matched_probe.py"):
                with self.subTest(script=script):
                    completed = subprocess.run(
                        [
                            sys.executable,
                            "-O",
                            str(ROOT / "scripts" / script),
                            "--",
                            str(ROOT),
                            str(candidate),
                            str(bad_hdri),
                        ],
                        text=True,
                        capture_output=True,
                        check=False,
                    )
                    self.assertNotEqual(completed.returncode, 0)
                    self.assertIn("does not match", completed.stdout + completed.stderr)
                    self.assertNotIn("No module named 'bpy'", completed.stdout + completed.stderr)

    def test_render_scripts_use_the_declared_camera_and_stable_result_paths(self):
        licensed = (ROOT / "scripts/render_licensed_ibl_sweep.py").read_text()
        self.assertIn('camera.data.sensor_fit = "VERTICAL"', licensed)
        self.assertIn('"historical_near_pole"', licensed)
        self.assertIn('"historical_near_pole_width_scaled"', licensed)
        self.assertNotIn("accepted official-viewer near-pole", licensed)
        reference = (ROOT / "scripts/render_reference_matched_probe.py").read_text()
        self.assertIn('"output_directory": "reference_matched_cycles_probe"', reference)
        self.assertNotIn('f"reference_matched_cycles_{hdri_record', reference)

    def test_reference_probe_reads_and_hash_gates_the_captured_camera(self):
        reference = (ROOT / "scripts/render_reference_matched_probe.py").read_text()
        self.assertIn('verified_reference_artifact("runtime")', reference)
        self.assertIn('verified_reference_artifact("front")', reference)
        self.assertIn('captured_camera.get("position")', reference)
        self.assertIn('captured_camera.get("target")', reference)
        self.assertIn('captured_fov = runtime.get("fov")', reference)
        self.assertIn('vertical_fov{fov_token}', reference)
        self.assertIn('"official_runtime_sha256": runtime_hash', reference)
        self.assertIn('"official_reference_sha256": reference_front_hash', reference)
        self.assertNotIn("target = Vector((-0.037516", reference)
        self.assertNotIn("position = Vector((-0.037516", reference)
        self.assertNotIn("vertical_fov35_strength", reference)

    def test_licensed_sweep_rejects_arbitrary_camera_modes_before_blender_import(self):
        completed = subprocess.run(
            [
                sys.executable,
                str(ROOT / "scripts/render_licensed_ibl_sweep.py"),
                "--",
                str(ROOT),
                str(ROOT),
                str(ROOT / "missing.exr"),
                "6.0",
            ],
            text=True,
            capture_output=True,
            check=False,
        )
        self.assertNotEqual(completed.returncode, 0)
        self.assertIn("unknown camera mode", completed.stdout + completed.stderr)
        self.assertNotIn("No module named 'bpy'", completed.stdout + completed.stderr)

    def test_render_scripts_reject_a_caller_supplied_evidence_root(self):
        with tempfile.TemporaryDirectory() as temporary:
            fake_root = Path(temporary)
            candidate = fake_root / "candidate"
            candidate.mkdir()
            hdri = fake_root / "boiler_room_4k.exr"
            hdri.write_bytes(b"attacker-controlled")
            for name in ("render_licensed_ibl_sweep.py", "render_reference_matched_probe.py"):
                with self.subTest(script=name):
                    completed = subprocess.run(
                        [sys.executable, str(ROOT / "scripts" / name), "--", str(fake_root), str(candidate), str(hdri)],
                        text=True,
                        capture_output=True,
                        check=False,
                    )
                    self.assertNotEqual(completed.returncode, 0)
                    self.assertIn("Project evidence root must be", completed.stdout + completed.stderr)
                    self.assertNotIn("No module named 'bpy'", completed.stdout + completed.stderr)

    def test_render_manifests_distinguish_historical_and_hash_gated_evidence(self):
        root = ROOT / "results/xbox_official_import_comparison/official_import_4.5.9_LTS"
        manifests = list(root.glob("*/manifest.json"))
        self.assertTrue(manifests)
        for path in manifests:
            with self.subTest(path=path):
                manifest = json.loads(path.read_text())
                self.assertIn("artifact_distribution", manifest)
                if manifest.get("artifact_status") == "historical_pre_scene_hash_gate":
                    self.assertIn("provenance_limit", manifest)
                else:
                    digest = manifest.get("source_scene_sha256")
                    self.assertIsInstance(digest, str)
                    self.assertRegex(digest, r"^[0-9a-f]{64}$")
                    self.assertIn("source_scene_audit", manifest)


if __name__ == "__main__":
    unittest.main()
