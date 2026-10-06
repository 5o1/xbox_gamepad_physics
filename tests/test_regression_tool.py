import importlib.util
import json
import subprocess
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch


ROOT = Path(__file__).resolve().parents[1]
SPEC = importlib.util.spec_from_file_location("run_regression", ROOT / "scripts" / "run_regression.py")
regression = importlib.util.module_from_spec(SPEC)
SPEC.loader.exec_module(regression)


class RegressionToolTest(unittest.TestCase):
    def test_snapshot_covers_previously_omitted_test_inputs(self):
        paths = {path for path, _ in regression.tracked_snapshot()["entries"]}
        self.assertIn("assets/asset_index.json", paths)
        self.assertIn("results/coordinate_reference.json", paths)
        self.assertIn(
            "results/legacy_casper_1914_width_scaled_1708_proxy/inventory.json",
            paths,
        )
        self.assertNotIn("results/integrated_regression.json", paths)
        self.assertNotIn("results/full_regression.json", paths)

    def test_report_write_is_non_destructive_by_default(self):
        with self.assertRaisesRegex(RuntimeError, "--publish"):
            regression.write_report({}, regression.PUBLISHED_REPORTS["browser"], publish=False)
        with tempfile.TemporaryDirectory() as directory:
            output = Path(directory) / "report.json"
            regression.write_report({"status": "pass"}, output, publish=False)
            self.assertEqual(json.loads(output.read_text()), {"status": "pass"})
        with self.assertRaisesRegex(RuntimeError, "canonical --output"):
            regression.write_report({"profile": "full"}, None, publish=True)
        with tempfile.TemporaryDirectory() as directory:
            wrong = Path(directory) / "wrong.json"
            with self.assertRaisesRegex(RuntimeError, "must publish"):
                regression.write_report({"profile": "full"}, wrong, publish=True)

    def test_acceptance_limits_come_from_canonical_registry(self):
        registry = json.loads((ROOT / "assets/asset_index.json").read_text())
        limits = regression.acceptance_limits()
        self.assertEqual(limits["primary_candidate_id"], registry["primary_appearance_candidate_id"])
        self.assertEqual(limits["viewer_variant_id"], registry["interactive_viewer"]["active_variant_id"])
        self.assertEqual(
            limits["target_geometry_approved"],
            registry["approved_target_geometry_candidate_id"] is not None,
        )

    def test_node_summary_counts_todo_cancelled_and_rejects_inconsistency(self):
        output = "\n".join(
            (
                "# tests 3",
                "# pass 1",
                "# fail 0",
                "# cancelled 1",
                "# skipped 0",
                "# todo 1",
            )
        )
        summary = regression.parse_node_test_summary(output, "synthetic.mjs")
        self.assertEqual(summary["todo"], 1)
        self.assertEqual(summary["cancelled"], 1)
        with self.assertRaisesRegex(RuntimeError, "internally inconsistent"):
            regression.parse_node_test_summary(output.replace("# tests 3", "# tests 4"), "bad.mjs")

    def test_node_test_file_with_zero_registered_tests_is_rejected(self):
        output = "\n".join(
            (
                "# tests 0",
                "# pass 0",
                "# fail 0",
                "# cancelled 0",
                "# skipped 0",
                "# todo 0",
            )
        )
        summary = regression.parse_node_test_summary(output, "empty.mjs")
        with self.assertRaisesRegex(RuntimeError, "zero tests"):
            regression.require_nonempty_node_test_file(summary, "empty.mjs")

    def test_python_expected_failure_cannot_be_reported_as_passed(self):
        summary = {
            "command": "synthetic",
            "run": 1,
            "passed": 0,
            "failed": 0,
            "errors": 0,
            "skipped": 0,
            "expected_failures": 1,
            "unexpected_successes": 0,
            "skip_reasons": [],
        }
        with self.assertRaisesRegex(RuntimeError, "forbids expected failures"):
            regression.validate_python_summary(summary, "synthetic output", allow_skips=True)

    def test_python_zero_test_worker_result_is_rejected(self):
        summary = {
            "command": "synthetic",
            "run": 0,
            "passed": 0,
            "failed": 0,
            "errors": 0,
            "skipped": 0,
            "expected_failures": 0,
            "unexpected_successes": 0,
            "skip_reasons": [],
        }
        with self.assertRaisesRegex(RuntimeError, "zero tests"):
            regression.validate_python_summary(summary, "", allow_skips=True)

    def test_python_test_worker_timeout_is_bounded(self):
        timeout = subprocess.TimeoutExpired(
            ["python", "worker"], regression.PYTHON_TEST_TIMEOUT_SECONDS
        )
        with patch.object(regression.subprocess, "run", side_effect=timeout):
            with self.assertRaisesRegex(RuntimeError, "timed out"):
                regression.run_python_tests(allow_skips=True)


if __name__ == "__main__":
    unittest.main()
