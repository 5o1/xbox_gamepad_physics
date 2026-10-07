#!/usr/bin/env python3
"""Run project regressions and emit a reproducible, non-destructive report.

``fast`` permits dependency-gated skips and labels the result partial. ``full``
requires every discovered Python and JavaScript test to execute. ``browser``
adds the CDP integration harness. Reports go to stdout unless ``--output`` is
given; replacing the tracked report additionally requires ``--publish``.
"""

from __future__ import annotations

import argparse
import hashlib
import importlib.metadata
import io
import json
import os
from pathlib import Path
import re
import subprocess
import sys
import time
import unittest


ROOT = Path(__file__).resolve().parents[1]
PUBLISHED_REPORTS = {
    "full": ROOT / "results" / "full_regression.json",
    "browser": ROOT / "results" / "integrated_regression.json",
}
FINGERPRINT_EXCLUDES = {
    "results/full_regression.json",
    "results/integrated_regression.json",
}
THREE_BROWSER_BINDINGS = {
    "/vendor/build/three.module.js": "build/three.module.js",
    "/vendor/build/three.core.js": "build/three.core.js",
    "/vendor/examples/jsm/loaders/OBJLoader.js": "examples/jsm/loaders/OBJLoader.js",
    "/vendor/examples/jsm/controls/OrbitControls.js": "examples/jsm/controls/OrbitControls.js",
}
SUPPORTING_BROWSER_BINDINGS = {
    "/registry/asset_index.json": "assets/asset_index.json",
    "/reference/identity_front.png": (
        "results/legacy_casper_1914_visual_parts/identity_front.png"
    ),
}
LOCAL_MODULE_IMPORT = re.compile(
    r"(?:\bfrom\s*|\bimport\s*(?:\(\s*)?)[\"'](\./[^\"']+)[\"']"
)
SHA256_HEX = re.compile(r"^[0-9a-f]{64}$")
CACHE_BUSTER_PARAMETER = "__xbox_regression_nonce"
PYTHON_TEST_TIMEOUT_SECONDS = 180


def git(*args: str) -> str:
    return subprocess.check_output(
        ["git", *args], cwd=ROOT, text=True, stderr=subprocess.STDOUT
    ).strip()


def tracked_snapshot() -> dict:
    """Hash every tracked project byte except the self-referential report."""
    raw = subprocess.check_output(["git", "ls-files", "-z"], cwd=ROOT)
    paths = sorted(
        path.decode("utf-8")
        for path in raw.split(b"\0")
        if path and path.decode("utf-8") not in FINGERPRINT_EXCLUDES
    )
    entries = []
    for relative in paths:
        target = ROOT / relative
        if not target.is_file():
            raise RuntimeError(f"tracked input is missing: {relative}")
        entries.append([relative, hashlib.sha256(target.read_bytes()).hexdigest()])
    payload = json.dumps(entries, ensure_ascii=False, separators=(",", ":")).encode()
    return {
        "method": "SHA256 of compact JSON [tracked relative path, SHA256(file bytes)] pairs sorted by Unicode code point; generated regression reports excluded to avoid self-reference",
        "file_count": len(entries),
        "sha256": hashlib.sha256(payload).hexdigest(),
        "entries": entries,
    }


def repository_state() -> dict:
    """Capture the commit, dirtiness and exact tracked bytes as one checkpoint."""
    status = git("status", "--porcelain=v1", "--untracked-files=all")
    return {
        "tested_commit": git("rev-parse", "HEAD"),
        "working_tree_clean": not bool(status),
        "status_porcelain": status.splitlines() if status else [],
        "source_snapshot": tracked_snapshot(),
    }


def repository_change_reasons(before: dict, after: dict) -> list[str]:
    reasons = []
    if before.get("tested_commit") != after.get("tested_commit"):
        reasons.append("tested_commit")
    before_snapshot = before.get("source_snapshot", {})
    after_snapshot = after.get("source_snapshot", {})
    if (
        before_snapshot.get("sha256") != after_snapshot.get("sha256")
        or before_snapshot.get("file_count") != after_snapshot.get("file_count")
    ):
        reasons.append("source_snapshot")
    if before.get("status_porcelain") != after.get("status_porcelain"):
        reasons.append("working_tree_status")
    if before.get("working_tree_clean") != after.get("working_tree_clean"):
        reasons.append("working_tree_clean")
    return reasons


def validate_publish_provenance(provenance: dict) -> None:
    before = provenance.get("before", {})
    after = provenance.get("after", {})
    observed_reasons = repository_change_reasons(before, after)
    reported_reasons = provenance.get("change_reasons")
    if reported_reasons != observed_reasons:
        raise RuntimeError(
            "refusing to publish: repository provenance is internally inconsistent"
        )
    if provenance.get("changed_during_run") is not bool(observed_reasons):
        raise RuntimeError(
            "refusing to publish: repository change flag is internally inconsistent"
        )
    if before.get("working_tree_clean") is not True:
        raise RuntimeError("refusing to publish: working tree was dirty before tests")
    if after.get("working_tree_clean") is not True:
        raise RuntimeError("refusing to publish: working tree became dirty during tests")
    if observed_reasons:
        raise RuntimeError("refusing to publish: repository changed during tests")


def sha256_file(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


def viewer_browser_bindings() -> dict[str, str]:
    """Return every local module reachable from app.mjs plus the HTML entry."""
    viewer_root = (ROOT / "viewer").resolve()
    index = viewer_root / "index.html"
    if 'src="/app.mjs"' not in index.read_text(encoding="utf-8"):
        raise RuntimeError("viewer/index.html no longer loads the audited /app.mjs entry")
    pending = [viewer_root / "app.mjs"]
    visited: set[Path] = set()
    bindings = {"/": "viewer/index.html"}
    while pending:
        path = pending.pop()
        path = path.resolve()
        if path in visited:
            continue
        if not path.is_relative_to(viewer_root) or not path.is_file():
            raise RuntimeError(f"unsafe or missing local viewer module: {path}")
        visited.add(path)
        relative = path.relative_to(viewer_root)
        bindings["/" + relative.as_posix()] = "viewer/" + relative.as_posix()
        source = path.read_text(encoding="utf-8")
        for specifier in LOCAL_MODULE_IMPORT.findall(source):
            imported = (path.parent / specifier).resolve()
            if not imported.is_relative_to(viewer_root):
                raise RuntimeError(
                    f"viewer module import escapes viewer root: {path} -> {specifier}"
                )
            pending.append(imported)
    return bindings


def expected_browser_source_bindings() -> dict[str, dict]:
    expected = {}
    for request_path, relative in {
        **viewer_browser_bindings(),
        **SUPPORTING_BROWSER_BINDINGS,
    }.items():
        target = ROOT / relative
        if not target.is_file():
            raise RuntimeError(f"browser binding input is missing: {relative}")
        expected[request_path] = {
            "binding_kind": "workspace",
            "binding_path": relative,
            "sha256": sha256_file(target),
            "byte_length": target.stat().st_size,
        }

    record_path = ROOT / "sources" / "viewer_design.json"
    record = json.loads(record_path.read_text(encoding="utf-8"))
    extracted = record.get("dependencies", {}).get("extracted_files")
    if not isinstance(extracted, dict):
        raise RuntimeError("sources/viewer_design.json lacks Three.js extracted_files")
    for request_path, record_key in THREE_BROWSER_BINDINGS.items():
        digest = extracted.get(record_key)
        if not isinstance(digest, str) or not SHA256_HEX.fullmatch(digest):
            raise RuntimeError(
                f"sources/viewer_design.json lacks a valid SHA-256 for {record_key}"
            )
        expected[request_path] = {
            "binding_kind": "three_source_record",
            "binding_path": record_key,
            "sha256": digest,
            "byte_length": None,
        }
    return expected


def validate_browser_source_binding(payload: dict, base_url: str) -> dict:
    """Bind the exercised HTTP bytes to this worktree and its Three record."""
    binding = payload.get("source_binding")
    if not isinstance(binding, dict):
        raise RuntimeError("browser harness lacks source_binding")
    if binding.get("hash_algorithm") != "SHA-256":
        raise RuntimeError("browser harness source binding uses an unsupported hash")

    cache = binding.get("cache")
    if not isinstance(cache, dict):
        raise RuntimeError("browser harness lacks cache-control evidence")
    if cache.get("network_cache_disabled") is not True:
        raise RuntimeError("browser harness did not disable the browser network cache")
    if cache.get("browser_cache_cleared_before_navigation") is not True:
        raise RuntimeError("browser harness did not clear the browser cache")
    if cache.get("nonce_parameter") != CACHE_BUSTER_PARAMETER:
        raise RuntimeError("browser harness used an unexpected cache-buster parameter")
    nonce = cache.get("nonce")
    if not isinstance(nonce, str) or len(nonce) < 8:
        raise RuntimeError("browser harness cache-buster nonce is missing")

    requested_raw = binding.get("requested_navigation_url")
    navigation_raw = binding.get("navigation_url")
    if not isinstance(requested_raw, str) or not isinstance(navigation_raw, str):
        raise RuntimeError("browser harness lacks requested/actual navigation URLs")
    from urllib.parse import parse_qs, urlsplit

    configured = urlsplit(base_url)
    requested = urlsplit(requested_raw)
    navigation = urlsplit(navigation_raw)
    configured_identity = (configured.scheme, configured.netloc, configured.path or "/")
    if (requested.scheme, requested.netloc, requested.path or "/") != configured_identity:
        raise RuntimeError("browser requested navigation URL does not match --base-url")
    if (navigation.scheme, navigation.netloc, navigation.path or "/") != configured_identity:
        raise RuntimeError("browser actual navigation URL does not match --base-url")
    if parse_qs(requested.query).get(CACHE_BUSTER_PARAMETER) != [nonce]:
        raise RuntimeError("requested navigation URL lacks the reported cache-buster")
    if parse_qs(navigation.query).get(CACHE_BUSTER_PARAMETER) != [nonce]:
        raise RuntimeError("actual navigation URL lacks the reported cache-buster")
    runtime = payload.get("runtime", {})
    if runtime.get("requested_navigation_url") != requested_raw:
        raise RuntimeError("runtime and source binding disagree on requested navigation URL")
    if runtime.get("navigation_url") != navigation_raw:
        raise RuntimeError("runtime and source binding disagree on actual navigation URL")

    resources = binding.get("resources")
    if not isinstance(resources, list):
        raise RuntimeError("browser harness source_binding.resources is not a list")
    by_request = {}
    for resource in resources:
        if not isinstance(resource, dict):
            raise RuntimeError("browser harness emitted a malformed source resource")
        request_path = resource.get("request_path")
        if not isinstance(request_path, str) or request_path in by_request:
            raise RuntimeError(f"duplicate or invalid browser source resource: {request_path!r}")
        by_request[request_path] = resource

    expected = expected_browser_source_bindings()
    if set(by_request) != set(expected):
        missing = sorted(set(expected) - set(by_request))
        extra = sorted(set(by_request) - set(expected))
        raise RuntimeError(
            f"browser source resource set mismatch; missing={missing}, extra={extra}"
        )
    for request_path, expectation in expected.items():
        resource = by_request[request_path]
        for field in ("binding_kind", "binding_path"):
            if resource.get(field) != expectation[field]:
                raise RuntimeError(
                    f"browser source binding {request_path} has unexpected {field}"
                )
        digest = resource.get("sha256")
        if not isinstance(digest, str) or not SHA256_HEX.fullmatch(digest):
            raise RuntimeError(f"browser source binding {request_path} has invalid SHA-256")
        if digest != expectation["sha256"]:
            raise RuntimeError(
                f"served SHA-256 for {request_path} does not match "
                f"{expectation['binding_kind']} {expectation['binding_path']}"
            )
        byte_length = resource.get("byte_length")
        if not isinstance(byte_length, int) or isinstance(byte_length, bool) or byte_length <= 0:
            raise RuntimeError(f"browser source binding {request_path} has invalid byte length")
        if expectation["byte_length"] is not None and byte_length != expectation["byte_length"]:
            raise RuntimeError(
                f"served byte length for {request_path} does not match {expectation['binding_path']}"
            )
        response_raw = resource.get("response_url")
        if not isinstance(response_raw, str):
            raise RuntimeError(f"browser source binding {request_path} lacks response URL")
        response = urlsplit(response_raw)
        if (response.scheme, response.netloc) != (navigation.scheme, navigation.netloc):
            raise RuntimeError(f"browser source binding {request_path} changed origin")
        if response.path != request_path:
            raise RuntimeError(f"browser source binding {request_path} has mismatched response path")
        if resource.get("status") != 200:
            raise RuntimeError(f"browser source binding {request_path} was not HTTP 200")
        if resource.get("from_disk_cache") is not False:
            raise RuntimeError(f"browser source binding {request_path} came from disk cache")
        if resource.get("from_service_worker") is not False:
            raise RuntimeError(f"browser source binding {request_path} came from a service worker")
        if resource.get("response_occurrence_count") != 1:
            raise RuntimeError(
                f"browser source binding {request_path} was observed more than once"
            )
        if resource.get("duplicate_response_urls") != []:
            raise RuntimeError(
                f"browser source binding {request_path} has duplicate response evidence"
            )

    workspace_count = sum(
        item["binding_kind"] == "workspace" for item in expected.values()
    )
    return {
        "verified": True,
        "navigation_url": navigation_raw,
        "resource_count": len(expected),
        "workspace_resource_count": workspace_count,
        "three_source_record_resource_count": len(expected) - workspace_count,
        "external_obj_bytes_bound_to_git": False,
    }


def python_test_worker_payload() -> dict:
    """Run unittest discovery once for the bounded child-process worker."""
    suite = unittest.defaultTestLoader.discover(str(ROOT / "tests"), pattern="test_*.py")
    stream = io.StringIO()
    result = unittest.TextTestRunner(stream=stream, verbosity=2).run(suite)
    summary = {
        "command": f"{sys.executable} -m unittest discover -s tests -p test_*.py -v",
        "run": result.testsRun,
        "passed": result.testsRun
        - len(result.failures)
        - len(result.errors)
        - len(result.skipped)
        - len(result.expectedFailures)
        - len(result.unexpectedSuccesses),
        "failed": len(result.failures),
        "errors": len(result.errors),
        "skipped": len(result.skipped),
        "expected_failures": len(result.expectedFailures),
        "unexpected_successes": len(result.unexpectedSuccesses),
        "skip_reasons": [f"{test}: {reason}" for test, reason in result.skipped],
    }
    return {"summary": summary, "test_output": stream.getvalue()}


def validate_python_summary(summary: dict, test_output: str, allow_skips: bool) -> dict:
    count_fields = (
        "run",
        "passed",
        "failed",
        "errors",
        "skipped",
        "expected_failures",
        "unexpected_successes",
    )
    if any(not isinstance(summary.get(field), int) for field in count_fields):
        raise RuntimeError(f"Python worker emitted invalid counters: {summary}")
    if summary["run"] <= 0:
        raise RuntimeError("Python test discovery executed zero tests")
    classified = sum(summary[field] for field in count_fields if field != "run")
    if classified != summary["run"] or any(summary[field] < 0 for field in count_fields):
        raise RuntimeError(f"Python test summary is internally inconsistent: {summary}")
    if summary["failed"] or summary["errors"] or summary["unexpected_successes"]:
        raise RuntimeError("Python tests failed\n" + test_output)
    if summary["skipped"] and not allow_skips:
        raise RuntimeError(
            f"full regression forbids skipped tests ({summary['skipped']})\n"
            + test_output
        )
    if summary["expected_failures"] or summary["unexpected_successes"]:
        raise RuntimeError(
            "regression forbids expected failures and unexpected successes "
            f"({summary['expected_failures']} expected, "
            f"{summary['unexpected_successes']} unexpected)\n"
            + test_output
        )
    return summary


def run_python_tests(allow_skips: bool) -> dict:
    command = [sys.executable, str(Path(__file__).resolve()), "--python-test-worker"]
    try:
        process = subprocess.run(
            command,
            cwd=ROOT,
            text=True,
            capture_output=True,
            timeout=PYTHON_TEST_TIMEOUT_SECONDS,
        )
    except subprocess.TimeoutExpired as error:
        raise RuntimeError(
            f"Python tests timed out after {PYTHON_TEST_TIMEOUT_SECONDS} seconds"
        ) from error
    if process.returncode:
        raise RuntimeError(
            "Python test worker failed\n" + process.stdout + process.stderr
        )
    try:
        payload = json.loads(process.stdout)
    except json.JSONDecodeError as error:
        raise RuntimeError(
            "Python test worker emitted invalid JSON\n" + process.stdout + process.stderr
        ) from error
    if not isinstance(payload, dict) or not isinstance(payload.get("summary"), dict):
        raise RuntimeError(f"Python test worker emitted an invalid payload: {payload!r}")
    return validate_python_summary(
        payload["summary"], str(payload.get("test_output", "")), allow_skips
    )


def parse_node_test_summary(output: str, relative: str) -> dict:
    def count(label: str) -> int:
        matches = re.findall(rf"^# {label} (\d+)\s*$", output, flags=re.MULTILINE)
        if not matches:
            raise RuntimeError(
                f"Node test summary lacks '# {label} N' in {relative}\n{output}"
            )
        return int(matches[-1])

    summary = {
        "run": count("tests"),
        "passed": count("pass"),
        "failed": count("fail"),
        "cancelled": count("cancelled"),
        "skipped": count("skipped"),
        "todo": count("todo"),
    }
    classified = sum(summary[key] for key in ("passed", "failed", "cancelled", "skipped", "todo"))
    if summary["run"] != classified:
        raise RuntimeError(
            f"Node test summary is internally inconsistent in {relative}: {summary}"
        )
    return summary


def require_nonempty_node_test_file(summary: dict, relative: str) -> None:
    if summary["run"] <= 0:
        raise RuntimeError(f"JavaScript test file executed zero tests: {relative}")


def run_javascript_tests() -> dict:
    files = sorted((ROOT / "tests").glob("test_*.mjs"))
    if not files:
        raise RuntimeError("no JavaScript tests discovered")
    totals = {
        "run": 0,
        "passed": 0,
        "failed": 0,
        "cancelled": 0,
        "skipped": 0,
        "todo": 0,
    }
    commands = []
    for path in files:
        relative = str(path.relative_to(ROOT))
        command = ["node", relative]
        commands.append(" ".join(command))
        try:
            process = subprocess.run(
                command, cwd=ROOT, text=True, capture_output=True, timeout=120
            )
        except subprocess.TimeoutExpired as error:
            raise RuntimeError(
                f"JavaScript tests timed out after 120 seconds in {relative}"
            ) from error
        output = process.stdout + process.stderr
        if process.returncode:
            raise RuntimeError(f"JavaScript tests failed in {relative}\n" + output)

        parsed = parse_node_test_summary(output, relative)
        require_nonempty_node_test_file(parsed, relative)
        for key in totals:
            totals[key] += parsed[key]
    summary = {
        "commands": commands,
        "files": len(files),
        **totals,
    }
    if summary["failed"] or summary["cancelled"] or summary["skipped"] or summary["todo"]:
        raise RuntimeError(f"JavaScript regression is not complete: {summary}")
    return summary


def run_browser_harness(base_url: str, cdp_port: int) -> dict:
    command = ["node", "tests/browser_harness.mjs"]
    environment = os.environ.copy()
    environment.update(
        XBOX_VIEWER_URL=base_url,
        XBOX_VIEWER_CDP_URL=f"http://127.0.0.1:{cdp_port}",
    )
    try:
        process = subprocess.run(
            command,
            cwd=ROOT,
            text=True,
            capture_output=True,
            env=environment,
            timeout=240,
        )
    except subprocess.TimeoutExpired as error:
        raise RuntimeError("browser harness timed out after 240 seconds") from error
    if process.returncode:
        raise RuntimeError("browser harness failed\n" + process.stdout + process.stderr)
    payload = None
    for line in reversed(process.stdout.splitlines()):
        try:
            candidate = json.loads(line)
        except json.JSONDecodeError:
            continue
        if isinstance(candidate, dict) and candidate.get("schema_version") == 2:
            payload = candidate
            break
    if payload is None:
        raise RuntimeError("browser harness emitted no machine-readable schema v2 result\n" + process.stdout)
    required = (
        payload.get("passed") is True,
        payload.get("critical_resource_validation") is True,
        payload.get("primary_appearance_candidate_tested") is False,
        isinstance(payload.get("fixture_inventory", {}).get("inventory_sha256"), str),
        isinstance(payload.get("runtime", {}).get("browser", {}).get("product"), str),
        payload.get("runtime", {}).get("three_revision") == "180",
    )
    if not all(required):
        raise RuntimeError("browser harness result is incomplete: " + json.dumps(payload))
    payload["source_binding_validation"] = validate_browser_source_binding(
        payload, base_url
    )
    payload["command"] = (
        f"XBOX_VIEWER_URL={base_url} XBOX_VIEWER_CDP_URL=http://127.0.0.1:{cdp_port} "
        + " ".join(command)
    )
    payload["synthetic_fixture_only"] = True
    return payload


def dependency_versions() -> dict:
    names = ["numpy", "scipy", "trimesh", "opencv-python", "torch"]
    versions = {}
    for name in names:
        try:
            versions[name] = importlib.metadata.version(name)
        except importlib.metadata.PackageNotFoundError:
            versions[name] = None
    return versions


def acceptance_limits() -> dict:
    registry = json.loads((ROOT / "assets" / "asset_index.json").read_text(encoding="utf-8"))
    viewer = registry.get("interactive_viewer", {})
    return {
        "status_authority": "assets/asset_index.json",
        "primary_candidate_id": registry.get("primary_appearance_candidate_id"),
        "viewer_variant_id": viewer.get("active_variant_id"),
        "target_geometry_approved": registry.get("approved_target_geometry_candidate_id") is not None,
        "real_controller_tested": viewer.get("real_controller_verified") is True,
        "contact_dynamics_validated": registry.get("physical_asset", {}).get("contact_dynamics_validated") is True,
    }


def build_report(
    profile: str,
    base_url: str | None,
    cdp_port: int | None,
    *,
    before_state: dict | None = None,
) -> dict:
    allow_skips = profile == "fast"
    started = time.time()
    before = before_state if before_state is not None else repository_state()
    python = run_python_tests(allow_skips=allow_skips)
    javascript = run_javascript_tests()
    browser = None
    if profile == "browser":
        if not base_url or cdp_port is None:
            raise RuntimeError("browser profile requires --base-url and --cdp-port")
        browser = run_browser_harness(base_url, cdp_port)
    after = repository_state()
    change_reasons = repository_change_reasons(before, after)
    changed_during_run = bool(change_reasons)
    status = "partial_pass" if python["skipped"] else "pass"
    if changed_during_run:
        status = "invalid_changed_during_run"
    return {
        "schema_version": 1,
        "scope": "software regression only; not physical asset acceptance",
        "profile": profile,
        "status": status,
        "tested_commit": before["tested_commit"],
        "working_tree_clean": (
            before["working_tree_clean"] and after["working_tree_clean"]
        ),
        "source_snapshot": before["source_snapshot"],
        "repository_provenance": {
            "before": before,
            "after": after,
            "changed_during_run": changed_during_run,
            "change_reasons": change_reasons,
        },
        "environment": {
            "python": sys.version,
            "platform": sys.platform,
            "node": subprocess.check_output(["node", "--version"], text=True).strip(),
            "git": subprocess.check_output(["git", "--version"], text=True).strip(),
            "direct_dependency_versions": dependency_versions(),
        },
        "python": python,
        "javascript": javascript,
        "browser": browser,
        "duration_seconds": round(time.time() - started, 3),
        "acceptance_limits": acceptance_limits(),
    }


def write_report(report: dict, output: Path | None, publish: bool) -> None:
    rendered = json.dumps(report, ensure_ascii=False, indent=2) + "\n"
    if output is None:
        if publish:
            raise RuntimeError("--publish requires the profile's canonical --output path")
        print(rendered, end="")
        return
    output = output.resolve()
    published_paths = {path.resolve() for path in PUBLISHED_REPORTS.values()}
    if output in published_paths and not publish:
        raise RuntimeError("refusing to overwrite a tracked report without --publish")
    if publish:
        expected = PUBLISHED_REPORTS.get(report.get("profile"))
        if expected is None or output != expected.resolve():
            raise RuntimeError(
                f"profile {report.get('profile')!r} must publish to "
                f"{expected.relative_to(ROOT) if expected else 'no canonical report'}"
            )
    output.parent.mkdir(parents=True, exist_ok=True)
    temporary = output.with_name(output.name + ".tmp")
    temporary.write_text(rendered, encoding="utf-8")
    os.replace(temporary, output)


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--python-test-worker", action="store_true", help=argparse.SUPPRESS)
    parser.add_argument("--profile", choices=("fast", "full", "browser"), default="fast")
    parser.add_argument("--base-url")
    parser.add_argument("--cdp-port", type=int)
    parser.add_argument("--output", type=Path)
    parser.add_argument("--publish", action="store_true")
    args = parser.parse_args()
    if args.python_test_worker:
        print(json.dumps(python_test_worker_payload()))
        return 0
    if args.publish and args.profile == "fast":
        parser.error("a partial fast run cannot be published")
    try:
        before = None
        if args.publish:
            before = repository_state()
            if before["working_tree_clean"] is not True:
                raise RuntimeError(
                    "refusing to publish: working tree is dirty before tests"
                )
        report = build_report(
            args.profile,
            args.base_url,
            args.cdp_port,
            before_state=before,
        )
        if args.publish:
            validate_publish_provenance(report["repository_provenance"])
        write_report(report, args.output, args.publish)
    except (OSError, RuntimeError, subprocess.CalledProcessError) as error:
        print(f"regression failed: {error}", file=sys.stderr)
        return 1
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
