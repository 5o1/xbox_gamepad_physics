import copy
import importlib.util
import unittest
from pathlib import Path
from urllib.parse import urljoin


ROOT = Path(__file__).resolve().parents[1]
SPEC = importlib.util.spec_from_file_location(
    "run_regression_browser_binding", ROOT / "scripts" / "run_regression.py"
)
regression = importlib.util.module_from_spec(SPEC)
SPEC.loader.exec_module(regression)


class BrowserSourceBindingTest(unittest.TestCase):
    base_url = "http://127.0.0.1:9876/"
    nonce = "12345678-test-nonce"

    def payload(self):
        navigation_url = self.base_url + "?__xbox_regression_nonce=" + self.nonce
        resources = []
        for request_path, expected in regression.expected_browser_source_bindings().items():
            resources.append(
                {
                    "request_path": request_path,
                    "binding_kind": expected["binding_kind"],
                    "binding_path": expected["binding_path"],
                    "response_url": (
                        navigation_url
                        if request_path == "/"
                        else urljoin(self.base_url, request_path)
                    ),
                    "status": 200,
                    "from_disk_cache": False,
                    "from_service_worker": False,
                    "response_occurrence_count": 1,
                    "duplicate_response_urls": [],
                    "byte_length": expected["byte_length"] or 1,
                    "sha256": expected["sha256"],
                }
            )
        return {
            "runtime": {
                "requested_navigation_url": navigation_url,
                "navigation_url": navigation_url,
            },
            "source_binding": {
                "hash_algorithm": "SHA-256",
                "cache": {
                    "network_cache_disabled": True,
                    "browser_cache_cleared_before_navigation": True,
                    "nonce_parameter": "__xbox_regression_nonce",
                    "nonce": self.nonce,
                },
                "requested_navigation_url": navigation_url,
                "navigation_url": navigation_url,
                "resources": resources,
            },
        }

    def test_current_viewer_module_graph_is_fully_bound(self):
        bindings = regression.viewer_browser_bindings()
        self.assertEqual(
            set(bindings),
            {
                "/",
                "/app.mjs",
                "/assembly_constraints.mjs",
                "/diagnostics.mjs",
                "/drag2d.mjs",
                "/gamepad_state.mjs",
                "/rig.mjs",
            },
        )
        result = regression.validate_browser_source_binding(self.payload(), self.base_url)
        self.assertTrue(result["verified"])
        self.assertEqual(result["resource_count"], 13)
        self.assertFalse(result["external_obj_bytes_bound_to_git"])

    def test_viewer_and_three_hash_mismatches_fail_closed(self):
        for request_path in ("/app.mjs", "/vendor/build/three.module.js"):
            with self.subTest(request_path=request_path):
                payload = self.payload()
                resource = next(
                    item
                    for item in payload["source_binding"]["resources"]
                    if item["request_path"] == request_path
                )
                resource["sha256"] = "0" * 64
                with self.assertRaisesRegex(RuntimeError, "does not match"):
                    regression.validate_browser_source_binding(payload, self.base_url)

    def test_missing_extra_and_duplicate_resources_fail_closed(self):
        missing = self.payload()
        missing["source_binding"]["resources"].pop()
        with self.assertRaisesRegex(RuntimeError, "resource set mismatch"):
            regression.validate_browser_source_binding(missing, self.base_url)

        extra = self.payload()
        extra["source_binding"]["resources"].append(
            {
                "request_path": "/unreviewed.mjs",
                "binding_kind": "workspace",
                "binding_path": "viewer/unreviewed.mjs",
                "response_url": self.base_url + "unreviewed.mjs",
                "status": 200,
                "from_disk_cache": False,
                "from_service_worker": False,
                "response_occurrence_count": 1,
                "duplicate_response_urls": [],
                "byte_length": 1,
                "sha256": "0" * 64,
            }
        )
        with self.assertRaisesRegex(RuntimeError, "resource set mismatch"):
            regression.validate_browser_source_binding(extra, self.base_url)

        duplicate = self.payload()
        duplicate["source_binding"]["resources"].append(
            copy.deepcopy(duplicate["source_binding"]["resources"][0])
        )
        with self.assertRaisesRegex(RuntimeError, "duplicate"):
            regression.validate_browser_source_binding(duplicate, self.base_url)

        repeated_response = self.payload()
        repeated_response["source_binding"]["resources"][0][
            "response_occurrence_count"
        ] = 2
        repeated_response["source_binding"]["resources"][0][
            "duplicate_response_urls"
        ] = [repeated_response["source_binding"]["resources"][0]["response_url"]]
        with self.assertRaisesRegex(RuntimeError, "observed more than once"):
            regression.validate_browser_source_binding(
                repeated_response, self.base_url
            )

    def test_cache_navigation_and_origin_evidence_is_mandatory(self):
        cases = []
        cache_enabled = self.payload()
        cache_enabled["source_binding"]["cache"]["network_cache_disabled"] = False
        cases.append((cache_enabled, "did not disable"))

        cache_not_cleared = self.payload()
        cache_not_cleared["source_binding"]["cache"][
            "browser_cache_cleared_before_navigation"
        ] = False
        cases.append((cache_not_cleared, "did not clear"))

        missing_nonce = self.payload()
        missing_nonce["source_binding"]["navigation_url"] = self.base_url
        missing_nonce["runtime"]["navigation_url"] = self.base_url
        cases.append((missing_nonce, "actual navigation URL lacks"))

        wrong_origin = self.payload()
        wrong_origin["source_binding"]["resources"][0]["response_url"] = (
            "http://127.0.0.1:9999/?__xbox_regression_nonce=" + self.nonce
        )
        cases.append((wrong_origin, "changed origin"))

        disk_cache = self.payload()
        disk_cache["source_binding"]["resources"][0]["from_disk_cache"] = True
        cases.append((disk_cache, "came from disk cache"))

        for payload, message in cases:
            with self.subTest(message=message):
                with self.assertRaisesRegex(RuntimeError, message):
                    regression.validate_browser_source_binding(payload, self.base_url)


if __name__ == "__main__":
    unittest.main()
