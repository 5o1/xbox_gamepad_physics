"""Verify pinned reference CAD text; never execute third-party CAD code."""
import argparse
import ast
import hashlib
import json
from pathlib import Path


def audit(manifest, directory):
    checks = []
    directory = Path(directory).resolve()
    for item in manifest['files']:
        path = (directory / item['file']).resolve()
        if path.parent != directory:
            raise ValueError('Reference path outside directory')
        raw = path.read_bytes()
        if hashlib.sha256(raw).hexdigest() != item['sha256']:
            raise ValueError(f'Hash mismatch: {item["file"]}')
        constants = {}
        if item['constants']:
            for node in ast.parse(raw.decode()).body:
                if isinstance(node, ast.Assign) and isinstance(node.value, ast.Constant):
                    for target in node.targets:
                        if isinstance(target, ast.Name):
                            constants[target.id] = node.value.value
            for key, expected in item['constants'].items():
                actual = constants.get(key)
                if type(actual) not in (int, float) or actual != expected:
                    raise ValueError(f'Literal mismatch: {item["file"]}:{key}')
        checks.append({'file':item['file'], 'sha256_verified':True,
                       'constants_verified':list(item['constants'])})
    return {'reference_only':True, 'target_parameters_adopted':False, 'files':checks}


if __name__ == '__main__':
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('manifest', type=Path)
    parser.add_argument('directory', type=Path)
    args = parser.parse_args()
    print(json.dumps(audit(json.loads(args.manifest.read_text()), args.directory), indent=2))
