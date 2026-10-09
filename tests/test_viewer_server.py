import hashlib
import json
from pathlib import Path
import sys
import tempfile
import unittest


ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "scripts"))
from serve_viewer import Handler, validate_asset_variant, validate_vendor


class ViewerServerTest(unittest.TestCase):
    def test_routes_cannot_escape_their_configured_roots(self):
        handler = object.__new__(Handler)
        base = Path("/tmp/xbox-viewer-server-test")
        handler.roots = {
            "/": base / "viewer",
            "/assets/": base / "assets",
            "/vendor/": base / "vendor",
            "/reference/": base / "reference",
            "/candidate-reference/": base / "candidate-reference",
            "/registry/": base / "registry",
            "/evidence/": base / "evidence",
        }
        self.assertEqual(
            Path(handler.translate_path("/reference/identity_front.png")),
            (base / "reference" / "identity_front.png").resolve(),
        )
        self.assertEqual(
            Path(handler.translate_path("/reference/../secret.png")),
            (base / "reference" / "__denied__").resolve(),
        )

    def test_variant_profile_paths_and_visual_container_are_validated(self):
        with tempfile.TemporaryDirectory() as directory:
            project = Path(directory) / "project"
            external = Path(directory) / "external"
            (project / "assets/profile").mkdir(parents=True)
            (project / "viewer").mkdir()
            (project / "references").mkdir()
            external.mkdir()

            inventory = b'{"objects":[]}'
            container = b"glTF-test-container"
            parameters = b"{}"
            profile = {
                "schema_version": 2,
                "variant_id": "estimated_v0",
                "visual": {
                    "file": "model.glb",
                    "sha256": hashlib.sha256(container).hexdigest(),
                },
                "parameter_source": "references/parameters.json",
            }
            profile_bytes = (json.dumps(profile) + "\n").encode()
            registry = {
                "interactive_viewer": {
                    "entry": "../viewer/index.html",
                    "active_variant_id": "legacy",
                    "allowed_variant_ids": ["estimated_v0"],
                },
                "derived_variants": {
                    "estimated_v0": {
                        "viewer_entry": "../viewer/v0.html",
                        "viewer_profile": {
                            "path": "profile/viewer_profile.json",
                        },
                    }
                },
            }
            (project / "assets/asset_index.json").write_text(json.dumps(registry))
            (project / "assets/profile/viewer_profile.json").write_bytes(profile_bytes)
            (project / "viewer/v0.html").write_text("test")
            (project / "references/parameters.json").write_bytes(parameters)
            (external / "inventory.json").write_bytes(inventory)
            (external / "model.glb").write_bytes(container)

            _, variant = validate_asset_variant(project, external, "estimated_v0")
            self.assertEqual(variant["_validated_viewer_url"], "/v0.html")
            (external / "model.glb").write_bytes(b"tampered")
            with self.assertRaisesRegex(ValueError, "visual container SHA-256"):
                validate_asset_variant(project, external, "estimated_v0")

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
