import copy
import importlib.util
import io
import sys
import unittest
from pathlib import Path
from unittest.mock import patch


ROOT = Path(__file__).resolve().parents[1]
SPEC = importlib.util.spec_from_file_location(
    "run_regression_provenance", ROOT / "scripts" / "run_regression.py"
)
regression = importlib.util.module_from_spec(SPEC)
SPEC.loader.exec_module(regression)


def repository_state(*, clean=True, commit="abc123", digest="1" * 64, status=None):
    if status is None:
        status = [] if clean else [" M viewer/app.mjs"]
    return {
        "tested_commit": commit,
        "working_tree_clean": clean,
        "status_porcelain": status,
        "source_snapshot": {
            "method": "synthetic",
            "file_count": 1,
            "sha256": digest,
            "entries": [["viewer/app.mjs", digest]],
        },
    }


def provenance(before, after):
    reasons = regression.repository_change_reasons(before, after)
    return {
        "before": before,
        "after": after,
        "changed_during_run": bool(reasons),
        "change_reasons": reasons,
    }


class RegressionProvenanceTest(unittest.TestCase):
    def test_change_reasons_cover_commit_tracked_bytes_and_worktree_status(self):
        before = repository_state()

        after = repository_state(commit="def456")
        self.assertEqual(
            regression.repository_change_reasons(before, after), ["tested_commit"]
        )

        after = repository_state(digest="2" * 64)
        self.assertEqual(
            regression.repository_change_reasons(before, after), ["source_snapshot"]
        )

        after = repository_state(clean=False)
        self.assertEqual(
            regression.repository_change_reasons(before, after),
            ["working_tree_status", "working_tree_clean"],
        )

    def test_build_report_cannot_call_a_mutated_run_passed(self):
        before = repository_state()
        after = repository_state(digest="2" * 64)
        python_summary = {"skipped": 0}
        javascript_summary = {"run": 1}
        with (
            patch.object(regression, "run_python_tests", return_value=python_summary),
            patch.object(
                regression, "run_javascript_tests", return_value=javascript_summary
            ),
            patch.object(regression, "repository_state", return_value=after),
            patch.object(regression, "dependency_versions", return_value={}),
            patch.object(regression, "acceptance_limits", return_value={}),
            patch.object(
                regression.subprocess,
                "check_output",
                side_effect=[b"v22.0.0\n", b"git version 2.0\n"],
            ),
        ):
            report = regression.build_report(
                "fast", None, None, before_state=before
            )

        self.assertEqual(report["status"], "invalid_changed_during_run")
        self.assertTrue(report["repository_provenance"]["changed_during_run"])
        self.assertEqual(
            report["repository_provenance"]["change_reasons"], ["source_snapshot"]
        )
        self.assertEqual(report["repository_provenance"]["before"], before)
        self.assertEqual(report["repository_provenance"]["after"], after)

    def test_publish_validation_requires_clean_identical_checkpoints(self):
        before = repository_state()
        after = copy.deepcopy(before)
        regression.validate_publish_provenance(provenance(before, after))

        dirty_before = repository_state(clean=False)
        with self.assertRaisesRegex(RuntimeError, "dirty before"):
            regression.validate_publish_provenance(
                provenance(dirty_before, copy.deepcopy(dirty_before))
            )

        dirty_after = repository_state(clean=False)
        with self.assertRaisesRegex(RuntimeError, "became dirty"):
            regression.validate_publish_provenance(provenance(before, dirty_after))

        changed_after = repository_state(digest="2" * 64)
        with self.assertRaisesRegex(RuntimeError, "changed during tests"):
            regression.validate_publish_provenance(provenance(before, changed_after))

    def test_publish_validation_rejects_forged_change_flag_or_reason_list(self):
        before = repository_state()
        after = repository_state(digest="2" * 64)
        forged = provenance(before, after)
        forged["changed_during_run"] = False
        with self.assertRaisesRegex(RuntimeError, "flag is internally inconsistent"):
            regression.validate_publish_provenance(forged)

        forged = provenance(before, after)
        forged["change_reasons"] = []
        with self.assertRaisesRegex(RuntimeError, "internally inconsistent"):
            regression.validate_publish_provenance(forged)

    def test_publish_dirty_preflight_rejects_before_tests_start(self):
        dirty = repository_state(clean=False)
        stderr = io.StringIO()
        argv = [
            "run_regression.py",
            "--profile",
            "full",
            "--publish",
            "--output",
            str(regression.PUBLISHED_REPORTS["full"]),
        ]
        with (
            patch.object(sys, "argv", argv),
            patch.object(regression, "repository_state", return_value=dirty),
            patch.object(regression, "build_report") as build_report,
            patch("sys.stderr", stderr),
        ):
            result = regression.main()

        self.assertEqual(result, 1)
        build_report.assert_not_called()
        self.assertIn("dirty before tests", stderr.getvalue())


if __name__ == "__main__":
    unittest.main()
