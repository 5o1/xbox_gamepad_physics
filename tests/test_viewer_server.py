import hashlib
import json
from pathlib import Path
import sys
import tempfile
import unittest
import threading
import urllib.error
import urllib.request


ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "scripts"))
from serve_viewer import Handler, validate_asset_variant, validate_vendor


class ViewerServerTest(unittest.TestCase):
    def test_overlay_review_video_supports_partial_reads_for_seeking(self):
        from xbox_gamepad_physics.web.server import create_overlay_server
        with tempfile.TemporaryDirectory() as directory:
            payload = b'0123456789'
            (Path(directory)/'clip.mp4').write_bytes(payload)
            server = create_overlay_server(trace_dir=directory, port=0)
            thread = threading.Thread(target=server.serve_forever, daemon=True)
            thread.start()
            url = f'http://127.0.0.1:{server.server_port}/traces/clip.mp4'
            try:
                with urllib.request.urlopen(url) as response:
                    self.assertEqual(response.headers['Accept-Ranges'], 'bytes')
                    self.assertEqual(response.read(), payload)
                for header, expected in (('bytes=2-5', b'2345'), ('bytes=7-', b'789'),
                                         ('bytes=-3', b'789'), ('bytes=0-99', payload)):
                    with self.subTest(header=header):
                        request = urllib.request.Request(url, headers={'Range':header})
                        with urllib.request.urlopen(request) as response:
                            self.assertEqual(response.status, 206)
                            self.assertEqual(int(response.headers['Content-Length']), len(expected))
                            self.assertEqual(response.read(), expected)
                request = urllib.request.Request(url, headers={'Range':'bytes=20-'})
                with self.assertRaises(urllib.error.HTTPError) as raised:
                    urllib.request.urlopen(request)
                self.assertEqual(raised.exception.code, 416)
                self.assertEqual(raised.exception.headers['Content-Range'], 'bytes */10')
                raised.exception.close()
                request = urllib.request.Request(url, method='HEAD', headers={'Range':'bytes=2-5'})
                with urllib.request.urlopen(request) as response:
                    self.assertEqual(response.status, 200)
                    self.assertEqual(response.headers['Content-Length'], '10')
                    self.assertEqual(response.read(), b'')
            finally:
                server.shutdown()
                server.server_close()
                thread.join()

    def test_routes_cannot_escape_their_configured_roots(self):
        handler = object.__new__(Handler)
        base = Path("/tmp/xbox-viewer-server-test")
        handler.roots = {
            "/": base / "viewer",
            "/assets/": base / "assets",
            "/generated/": base / "generated",
            "/vendor/": base / "vendor",
            "/registry/": base / "registry",
            "/evidence/": base / "evidence",
        }
        self.assertEqual(
            Path(handler.translate_path("/generated/kinematics/profile.json")),
            (base / "generated" / "kinematics" / "profile.json").resolve(),
        )
        self.assertEqual(
            Path(handler.translate_path("/generated/../secret.json")),
            (base / "generated" / "__denied__").resolve(),
        )

    def test_variant_profile_paths_and_visual_container_are_validated(self):
        with tempfile.TemporaryDirectory() as directory:
            project = Path(directory) / "project"
            external = Path(directory) / "external"
            (project / "assets").mkdir(parents=True)
            (project / "build/generated/kinematics").mkdir(parents=True)
            (project / "viewer").mkdir()
            external.mkdir()

            inventory = b'{"objects":[]}'
            container = b"glTF-test-container"
            parameters = b"{}"
            profile = {
                "schema_version": 2,
                "variant_id": "test_variant",
                "visual": {
                    "file": "model.glb",
                    "sha256": hashlib.sha256(container).hexdigest(),
                },
                "parameter_source": "/generated/kinematics/parameters.json",
            }
            profile_bytes = (json.dumps(profile) + "\n").encode()
            registry = {
                "interactive_viewer": {
                    "entry": "../viewer/index.html",
                    "active_variant_id": "legacy",
                    "allowed_variant_ids": ["test_variant"],
                },
                "derived_variants": {
                    "test_variant": {
                        "viewer_entry": "../viewer/index.html",
                        "viewer_profile": {
                            "route": "/generated/kinematics/viewer_profile.json",
                        },
                    }
                },
            }
            (project / "assets/asset_index.json").write_text(json.dumps(registry))
            (project / "build/generated/kinematics/viewer_profile.json").write_bytes(profile_bytes)
            (project / "build/generated/kinematics/parameters.json").write_bytes(parameters)
            (project / "viewer/index.html").write_text("test")
            (external / "inventory.json").write_bytes(inventory)
            (external / "model.glb").write_bytes(container)

            _, variant = validate_asset_variant(project, external, "test_variant")
            self.assertEqual(variant["_validated_viewer_url"], "/index.html")
            self.assertEqual(
                variant["_validated_profile_url"],
                "/generated/kinematics/viewer_profile.json",
            )
            (external / "model.glb").write_bytes(b"tampered")
            with self.assertRaisesRegex(ValueError, "visual container SHA-256"):
                validate_asset_variant(project, external, "test_variant")

    def test_vendor_version_and_module_hash_are_enforced(self):
        with tempfile.TemporaryDirectory() as directory:
            project = Path(directory) / "project"
            vendor = Path(directory) / "vendor"
            (project / "references").mkdir(parents=True)
            (vendor / "build").mkdir(parents=True)
            package = b'{"name":"three","version":"0.180.0"}'
            module = b'export const REVISION = "180";'
            record = {
                "dependencies": {
                    "three": "0.180.0",
                    "extracted_files": {
                        "package.json": hashlib.sha256(package).hexdigest(),
                        "build/three.module.js": hashlib.sha256(module).hexdigest(),
                    },
                }
            }
            (project / "references/viewer_design.json").write_text(json.dumps(record))
            (vendor / "package.json").write_bytes(package)
            (vendor / "build/three.module.js").write_bytes(module)
            self.assertEqual(validate_vendor(project, vendor), "0.180.0")
            (vendor / "build/three.module.js").write_bytes(b"tampered")
            with self.assertRaisesRegex(ValueError, "does not match"):
                validate_vendor(project, vendor)


if __name__ == "__main__":
    unittest.main()
