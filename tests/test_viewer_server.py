import io
import json
import hashlib
import sys
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / 'scripts'))
from serve_viewer import Handler, validate_asset_variant, validate_vendor


class ViewerLoggingTest(unittest.TestCase):
    def test_response_survives_lost_logging_pipe(self):
        for error in (BrokenPipeError(), ValueError('closed stream')):
            with self.subTest(error=type(error).__name__):
                handler = object.__new__(Handler)
                handler.client_address = ('127.0.0.1', 1)
                handler.requestline = 'GET / HTTP/1.1'
                handler.request_version = 'HTTP/1.1'
                handler.command = 'GET'
                handler.wfile = io.BytesIO()
                with patch('sys.stderr') as stderr:
                    stderr.write.side_effect = error
                    handler.send_response(200)
                    handler.end_headers()
                self.assertTrue(handler.wfile.getvalue().startswith(b'HTTP/1.0 200'))

    def test_reference_route_resolves_inside_explicit_root(self):
        handler = object.__new__(Handler)
        base = Path('/tmp/xbox-viewer-server-test')
        handler.roots = {
            '/': base / 'viewer',
            '/assets/': base / 'assets',
            '/vendor/': base / 'vendor',
            '/reference/': base / 'reference',
            '/candidate-reference/': base / 'candidate-reference',
            '/registry/': base / 'registry',
            '/evidence/': base / 'evidence',
        }
        self.assertEqual(
            Path(handler.translate_path('/reference/identity_front.png')),
            (base / 'reference' / 'identity_front.png').resolve(),
        )
        self.assertEqual(
            Path(handler.translate_path('/reference/../secret.png')),
            (base / 'reference' / '__denied__').resolve(),
        )
        self.assertEqual(
            Path(handler.translate_path('/registry/asset_index.json')),
            (base / 'registry' / 'asset_index.json').resolve(),
        )

    def test_identity_reference_in_document_exists(self):
        project = Path(__file__).resolve().parents[1]
        document = (project / 'viewer' / 'index.html').read_text(encoding='utf-8')
        self.assertIn('/reference/identity_front.png', document)
        self.assertTrue((project / 'results' / 'legacy_casper_1914_visual_parts' / 'identity_front.png').is_file())

    def test_server_rejects_assets_that_do_not_match_variant_registry(self):
        project = Path(__file__).resolve().parents[1]
        registry = json.loads((project / 'assets' / 'asset_index.json').read_text())
        variant_id = registry['interactive_viewer']['active_variant_id']
        canonical = project / 'results' / 'legacy_casper_1914_width_scaled_1708_proxy' / 'inventory.json'
        with tempfile.TemporaryDirectory() as directory:
            assets = Path(directory)
            (assets / 'inventory.json').write_bytes(canonical.read_bytes())
            _, variant = validate_asset_variant(project, assets, variant_id)
            self.assertEqual(variant['inventory_sha256'], hashlib.sha256(canonical.read_bytes()).hexdigest())
            (assets / 'inventory.json').write_text('{}')
            with self.assertRaisesRegex(ValueError, 'does not match'):
                validate_asset_variant(project, assets, variant_id)
            with self.assertRaisesRegex(ValueError, 'not the registry'):
                validate_asset_variant(project, assets, 'wrong-variant')

    def test_explicit_nondefault_variant_is_hash_bound_to_profile_and_container(self):
        with tempfile.TemporaryDirectory() as directory:
            project = Path(directory) / 'project'
            assets = Path(directory) / 'external'
            (project / 'assets' / 'profile').mkdir(parents=True)
            assets.mkdir()
            inventory = b'{"objects":[]}'
            container = b'glTF-test-container'
            profile = {
                'schema_version': 2,
                'variant_id': 'estimated_v0',
                'visual': {
                    'file': 'model.glb',
                    'sha256': hashlib.sha256(container).hexdigest(),
                },
                'parameter_source': 'sources/parameters.json',
                'parameter_source_sha256': hashlib.sha256(b'{}').hexdigest(),
            }
            profile_bytes = (json.dumps(profile) + '\n').encode()
            registry = {
                'interactive_viewer': {
                    'entry': '../viewer/index.html',
                    'active_variant_id': 'legacy',
                    'allowed_variant_ids': ['estimated_v0'],
                },
                'derived_variants': {
                    'estimated_v0': {
                        'inventory_sha256': hashlib.sha256(inventory).hexdigest(),
                        'viewer_entry': '../viewer/v0.html',
                        'viewer_profile': {
                            'path': 'profile/viewer_profile.json',
                            'sha256': hashlib.sha256(profile_bytes).hexdigest(),
                        },
                    },
                },
            }
            (project / 'assets' / 'asset_index.json').write_text(json.dumps(registry))
            (project / 'viewer').mkdir()
            (project / 'viewer' / 'v0.html').write_text('test')
            (project / 'assets' / 'profile' / 'viewer_profile.json').write_bytes(profile_bytes)
            (project / 'sources').mkdir()
            (project / 'sources' / 'parameters.json').write_bytes(b'{}')
            (assets / 'inventory.json').write_bytes(inventory)
            (assets / 'model.glb').write_bytes(container)
            _, variant = validate_asset_variant(project, assets, 'estimated_v0')
            self.assertEqual(variant['viewer_profile']['sha256'], hashlib.sha256(profile_bytes).hexdigest())
            self.assertEqual(variant['_validated_viewer_url'], '/v0.html')
            (assets / 'model.glb').write_bytes(b'tampered')
            with self.assertRaisesRegex(ValueError, 'visual container SHA-256'):
                validate_asset_variant(project, assets, 'estimated_v0')

    def test_vendor_version_and_key_file_hashes_are_enforced(self):
        with tempfile.TemporaryDirectory() as directory:
            project = Path(directory) / 'project'
            vendor = Path(directory) / 'vendor'
            (project / 'sources').mkdir(parents=True)
            (vendor / 'build').mkdir(parents=True)
            package_bytes = b'{"name":"three","version":"0.180.0"}'
            module_bytes = b'export const REVISION = "180";'
            record = {
                'dependencies': {
                    'three': '0.180.0',
                    'extracted_files': {
                        'package.json': hashlib.sha256(package_bytes).hexdigest(),
                        'build/three.module.js': hashlib.sha256(module_bytes).hexdigest(),
                    },
                }
            }
            (project / 'sources' / 'viewer_design.json').write_text(json.dumps(record))
            (vendor / 'package.json').write_bytes(package_bytes)
            (vendor / 'build' / 'three.module.js').write_bytes(module_bytes)
            self.assertEqual(validate_vendor(project, vendor), '0.180.0')
            (vendor / 'build' / 'three.module.js').write_bytes(b'tampered')
            with self.assertRaisesRegex(ValueError, 'does not match'):
                validate_vendor(project, vendor)
            (vendor / 'package.json').write_text('{"name":"three","version":"0.179.0"}')
            with self.assertRaisesRegex(ValueError, 'expected'):
                validate_vendor(project, vendor)


if __name__ == '__main__':
    unittest.main()
