"""Resource acquisition boundaries: DAG invalidation, locking and release IO."""
from __future__ import annotations

from contextlib import contextmanager
from functools import partial
import hashlib
import http.server
import json
import os
from pathlib import Path
import shutil
import subprocess
import sys
import tempfile
import threading
import unittest
from unittest import mock
import zipfile

ROOT = Path(__file__).resolve().parents[2]
for path in (ROOT / "src", ROOT / "scripts"):
    if str(path) not in sys.path:
        sys.path.insert(0, str(path))

import build_resources as builder
from xbox_gamepad_physics import resources
from xbox_gamepad_physics._resource_cache import cache_lock
from xbox_gamepad_physics.errors import ResourceError, ResourceFormatError, ResourceNotFoundError


@contextmanager
def working_directory(path):
    previous = Path.cwd()
    os.chdir(path)
    try:
        yield
    finally:
        os.chdir(previous)


class ResourceResolutionTest(unittest.TestCase):
    def setUp(self):
        resources.resource_root.cache_clear()
        self.environment = mock.patch.dict(os.environ)
        self.environment.start()
        os.environ.pop(resources.RESOURCE_ENV, None)
        self.addCleanup(self.environment.stop)
        self.addCleanup(resources.resource_root.cache_clear)

    def test_environment_precedes_repository_and_is_cached(self):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            os.environ[resources.RESOURCE_ENV] = str(root)
            self.assertEqual(resources.resource_root(), root)
            os.environ[resources.RESOURCE_ENV] = str(root / "other")
            self.assertEqual(resources.resource_root(), root)
            self.assertEqual(resources._resolve_root()[1], "environment")

    def test_repository_precedes_project_root(self):
        with tempfile.TemporaryDirectory() as directory:
            with working_directory(Path(directory)):
                self.assertEqual(resources._resolve_root(), (ROOT / "build/resources", "repository", ROOT))

    def test_installed_package_uses_nearest_project_ancestor(self):
        with tempfile.TemporaryDirectory() as directory:
            base = Path(directory)
            package = base / "installed/site-packages/xbox_gamepad_physics"
            package.mkdir(parents=True)
            project = base / "project"
            (project / "nested/child").mkdir(parents=True)
            (project / "pyproject.toml").write_text("")
            with mock.patch.object(resources, "PACKAGE_ROOT", package), working_directory(project / "nested/child"):
                self.assertEqual(resources._resolve_root(), (project / ".xbox_gamepad_physics/resources", "project", None))
                (project / "pyproject.toml").unlink()
                (project / ".git").write_text("gitdir: elsewhere")
                self.assertEqual(resources._resolve_root()[0], project / ".xbox_gamepad_physics/resources")
                (project / ".git").unlink()
                # The test host may itself have /tmp/pyproject.toml. Restrict
                # the ancestor search to this isolated fixture for this case.
                with mock.patch.object(resources, "_ancestors", side_effect=lambda path: (path,)):
                    with self.assertRaisesRegex(ResourceNotFoundError, resources.RESOURCE_ENV):
                        resources._resolve_root()

    def _graph(self, repo, calls):
        (repo / "scripts").mkdir()
        (repo / "scripts/build_resources.py").write_text("# builder input\n")
        (repo / "src/xbox_gamepad_physics").mkdir(parents=True)
        (repo / "src/xbox_gamepad_physics/resources.py").write_text("# output metadata\n")
        (repo / "first.txt").write_text("one")
        (repo / "independent.txt").write_text("separate")

        def generate(name):
            def run(out, root):
                calls.append(name)
                out.mkdir(parents=True)
                (out / "value.txt").write_text("valid " + name)
            return run
        return (
            builder.Node("first", ("first.txt",), (), "first", generate("first")),
            builder.Node("downstream", (), ("first",), "downstream", generate("downstream")),
            builder.Node("independent", ("independent.txt",), (), "independent", generate("independent")),
        )

    def test_stamp_hit_skips_and_content_change_rebuilds_only_downstream(self):
        with tempfile.TemporaryDirectory() as directory:
            repo = Path(directory)
            calls = []
            graph = self._graph(repo, calls)
            cache = repo / "cache"
            builder.build(cache, repo=repo, graph=graph)
            calls.clear()
            builder.build(cache, repo=repo, graph=graph)
            self.assertEqual(calls, [])
            source = repo / "first.txt"
            old = source.stat()
            source.write_text("two")
            os.utime(source, ns=(old.st_atime_ns, old.st_mtime_ns))
            status = builder.node_status(cache, repo=repo, graph=graph)
            self.assertEqual({s["name"] for s in status if s["stale"]}, {"first", "downstream"})
            builder.build(cache, repo=repo, graph=graph)
            self.assertEqual(calls, ["first", "downstream"])
            calls.clear()
            (cache / "first/value.txt").unlink()
            builder.build(cache, repo=repo, graph=graph)
            self.assertEqual(calls, ["first", "downstream"])

    def test_failed_build_keeps_complete_previous_cache(self):
        with tempfile.TemporaryDirectory() as directory:
            repo = Path(directory)
            graph = self._graph(repo, [])
            cache = repo / "cache"
            builder.build(cache, repo=repo, graph=graph)
            def fail(out, root):
                out.mkdir(parents=True)
                (out / "partial.txt").write_text("partial")
                raise ValueError("injected generator failure")
            broken = (builder.Node("first", ("first.txt",), (), "first", fail), *graph[1:])
            with self.assertRaisesRegex(ResourceError, "injected generator failure"):
                builder.build(cache, force=True, repo=repo, graph=broken)
            self.assertTrue((cache / "first/value.txt").is_file())
            self.assertFalse((cache / "first/partial.txt").exists())
            self.assertFalse(cache.with_name("cache.lock").exists())

    def test_two_processes_first_use_build_once_with_complete_cache(self):
        with tempfile.TemporaryDirectory() as directory:
            repo = Path(directory)
            (repo / "scripts").mkdir()
            (repo / "scripts/build_resources.py").write_text("# source\n")
            (repo / "src/xbox_gamepad_physics").mkdir(parents=True)
            (repo / "src/xbox_gamepad_physics/resources.py").write_text("# output metadata\n")
            (repo / "input.txt").write_text("input")
            worker = repo / "worker.py"
            worker.write_text('''import json, sys, time
from pathlib import Path
from types import SimpleNamespace
import build_resources as builder
from xbox_gamepad_physics import resources
repo = Path(sys.argv[1])
cache = repo / "build/resources"
def generate(out, root):
    with (repo / "calls.txt").open("a") as stream:
        stream.write("build\\n")
    time.sleep(0.3)
    out.mkdir(parents=True)
    (out / "manifest.json").write_text(json.dumps({"complete": True}))
    (out / "second.txt").write_text("ready")
graph = (builder.Node("test", ("input.txt",), (), "test/profile", generate),)
resources._repository = lambda: repo
resources._builder = lambda _: SimpleNamespace(build=lambda output, repo: builder.build(output, repo=repo, graph=graph))
assert resources.load_json_resource("test", "profile")["complete"]
assert (resources.resource_root() / "test/profile/second.txt").is_file()
''')
            env = dict(os.environ, PYTHONPATH=os.pathsep.join((str(ROOT / "src"), str(ROOT / "scripts"))))
            processes = [subprocess.Popen([sys.executable, str(worker), str(repo)], env=env, stdout=subprocess.PIPE, stderr=subprocess.PIPE, text=True) for _ in range(2)]
            for process in processes:
                stdout, stderr = process.communicate(timeout=30)
                self.assertEqual(process.returncode, 0, stdout + stderr)
            self.assertEqual((repo / "calls.txt").read_text().splitlines(), ["build"])
            self.assertTrue((repo / "build/resources/.stamps/test.json").is_file())
            self.assertFalse((repo / "build/resources.lock").exists())

    def test_dead_stale_lock_is_reclaimed_and_live_lock_times_out(self):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory) / "resources"
            lock = root.with_name("resources.lock")
            process = subprocess.Popen([sys.executable, "-c", "pass"])
            process.wait(timeout=10)
            lock.write_text(json.dumps({"pid": process.pid, "timestamp": 1}))
            with cache_lock(root, timeout=0.1):
                self.assertEqual(json.loads(lock.read_text())["pid"], os.getpid())
            with cache_lock(root):
                with self.assertRaisesRegex(ResourceError, "timed out"):
                    with cache_lock(root, timeout=0.05):
                        self.fail("live lock was stolen")


class ReleaseDownloadTest(unittest.TestCase):
    setUp = ResourceResolutionTest.setUp
    def _release(self, base):
        # Pin the version: a checkout run via PYTHONPATH has no installed metadata.
        patcher = mock.patch.object(resources, "package_version", return_value="0.0.0+fixture")
        patcher.start()
        self.addCleanup(patcher.stop)
        served = base / "http"
        served.mkdir()
        archive = served / "release.zip"
        manifest = {
            "schema_version": 1, "asset_id": "xbox_one_s", "backend": "robotwin",
            "profile": "full_controls", "available": True, "dynamics_ready": True,
            "entrypoint": "mobility.urdf", "required_files": ["mobility.urdf"], "reason": None,
        }
        with zipfile.ZipFile(archive, "w") as zipped:
            for name in ("kinematics/xbox_one_s.json", "kinematics/xbox_one_s_evidence.json",
                         "kinematics/kinematics_build_audit.json", "common/xbox_one_s/motion/full_controls.json",
                         "common/xbox_one_s/visual/manifest.json",
                         "common/xbox_one_s/collision/manifest.json",
                         "mujoco/visual_v0/visual_manifest.json",
                         "robotwin/left_stick/manifest.json", "mujoco/full_controls/manifest.json"):
                zipped.writestr(name, "{}")
            zipped.writestr("common/xbox_one_s/visual/meshes.bin", b"fixture")
            zipped.writestr("robotwin/full_controls/manifest.json", json.dumps(manifest))
            zipped.writestr("robotwin/full_controls/mobility.urdf", "<robot/>")
            zipped.writestr("assets/xbox_one_s/README.md", "attribution fixture")
        requests = []
        class Handler(http.server.SimpleHTTPRequestHandler):
            def do_GET(self):
                requests.append(self.path)
                super().do_GET()
            def log_message(self, *args):
                pass
        server = http.server.ThreadingHTTPServer(("127.0.0.1", 0), partial(Handler, directory=str(served)))
        thread = threading.Thread(target=server.serve_forever, daemon=True)
        thread.start()
        def close():
            server.shutdown()
            server.server_close()
            thread.join(timeout=5)
        self.addCleanup(close)
        package = base / "package"
        package.mkdir()
        lock = {"version": resources.package_version(), "url": f"http://127.0.0.1:{server.server_port}/release.zip",
                "sha256": hashlib.sha256(archive.read_bytes()).hexdigest()}
        (package / "_resource_lock.json").write_text(json.dumps(lock))
        project = base / "project"
        project.mkdir()
        (project / "pyproject.toml").write_text("")
        return package, project, lock, requests

    def test_download_verify_extract_load_and_reuse(self):
        from xbox_gamepad_physics.profiles import require_physics_ready
        with tempfile.TemporaryDirectory() as directory:
            package, project, lock, requests = self._release(Path(directory))
            with mock.patch.object(resources, "PACKAGE_ROOT", package), working_directory(project):
                profile = require_physics_ready("robotwin", "full_controls")
                self.assertTrue(profile.physics_ready)
                self.assertEqual(profile.manifest_path.parent.parent.parent, project / ".xbox_gamepad_physics/resources")
                self.assertEqual(resources.missing_resources(resources.resource_root()), [])
                status = resources.resource_status()
                self.assertEqual([node["name"] for node in status["nodes"]], ["release"])
                self.assertFalse(any(node["stale"] for node in status["nodes"]))
                resources.resource_root.cache_clear()
                resources.resource_root()
                self.assertEqual(requests, ["/release.zip"])
                (resources.resource_root() / "robotwin/full_controls/mobility.urdf").unlink()
                require_physics_ready("robotwin", "full_controls")
                self.assertEqual(requests, ["/release.zip", "/release.zip"])

    def test_hash_mismatch_rejects_download_without_publishing(self):
        with tempfile.TemporaryDirectory() as directory:
            package, project, lock, requests = self._release(Path(directory))
            lock["sha256"] = "invalid-integrity-fixture"
            (package / "_resource_lock.json").write_text(json.dumps(lock))
            with mock.patch.object(resources, "PACKAGE_ROOT", package), working_directory(project):
                with self.assertRaisesRegex(ResourceFormatError, "SHA-256 mismatch") as error:
                    resources.load_json_resource("robotwin", "full_controls")
                self.assertIn(lock["url"], str(error.exception))
                self.assertIn(str(project / ".xbox_gamepad_physics/resources"), str(error.exception))
                self.assertFalse((project / ".xbox_gamepad_physics/resources").exists())

    def test_missing_lock_explains_manual_recovery(self):
        with tempfile.TemporaryDirectory() as directory:
            package, project, _, _ = self._release(Path(directory))
            (package / "_resource_lock.json").unlink()
            with mock.patch.object(resources, "PACKAGE_ROOT", package), working_directory(project):
                with self.assertRaisesRegex(ResourceNotFoundError, "no _resource_lock.json") as error:
                    resources.resource_root()
                self.assertIn(resources.release_url(), str(error.exception))
                self.assertIn(str(project / ".xbox_gamepad_physics/resources"), str(error.exception))

    @unittest.skipIf(os.name == "nt", "POSIX permission bits are needed to make a truly read-only package directory")
    def test_installed_readonly_package_never_writes_home_or_site_packages(self):
        with tempfile.TemporaryDirectory() as directory:
            base = Path(directory)
            package, project, _, requests = self._release(base)
            home = base / "home"
            home.mkdir()
            installed = base / "installed/site-packages"
            target = installed / "xbox_gamepad_physics"
            shutil.copytree(ROOT / "src/xbox_gamepad_physics", target,
                            ignore=shutil.ignore_patterns("resource_data", "__pycache__", "_resource_lock.json"))
            shutil.copy2(package / "_resource_lock.json", target)
            # A real install carries distribution metadata; the code reads its version from it.
            metadata = installed / "xbox_gamepad_physics-0.0.0+fixture.dist-info"
            metadata.mkdir()
            (metadata / "METADATA").write_text(
                "Metadata-Version: 2.1\nName: xbox-gamepad-physics\nVersion: 0.0.0+fixture\n"
            )
            before = sorted(p.relative_to(installed).as_posix() for p in installed.rglob("*"))
            for p in installed.rglob("*"):
                p.chmod(0o555 if p.is_dir() else 0o444)
            installed.chmod(0o555)
            try:
                env = dict(os.environ, HOME=str(home), USERPROFILE=str(home), PYTHONPATH=str(installed))
                command = [sys.executable, "-B", "-c", '''from pathlib import Path
from xbox_gamepad_physics import resources, require_physics_ready
assert require_physics_ready("robotwin", "full_controls").physics_ready
assert resources.resource_root() == Path.cwd() / ".xbox_gamepad_physics/resources"
''']
                processes = [subprocess.Popen(command, cwd=project, env=env, stdout=subprocess.PIPE, stderr=subprocess.PIPE, text=True) for _ in range(2)]
                for process in processes:
                    stdout, stderr = process.communicate(timeout=30)
                    self.assertEqual(process.returncode, 0, stdout + stderr)
                self.assertEqual(requests, ["/release.zip"])
                self.assertEqual(list(home.iterdir()), [])
                self.assertEqual(sorted(p.relative_to(installed).as_posix() for p in installed.rglob("*")), before)
            finally:
                installed.chmod(0o755)
                for p in installed.rglob("*"):
                    p.chmod(0o755 if p.is_dir() else 0o644)


if __name__ == "__main__":
    unittest.main()
