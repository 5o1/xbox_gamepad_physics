"""Replace obsolete absolute provenance locations with repository-relative records.

This only changes source_directory metadata, never scored inputs or thresholds.
Runtime resource and output directories continue to come from private site config.
"""
import argparse
from pathlib import Path
import re


def normalize(root):
    path = root / 'src/xbox_gamepad_physics/build_data/acceptance/ruling20_sdf303_v1.json'
    before = path.read_text()
    after, count = re.subn(r'("source_directory": ")[^"\n]*/(build/experiments/[^"\n]+)(")',
                          r'\1\2\3', before)
    if count:
        path.write_text(after)
    return count


if __name__ == '__main__':
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--repository', type=Path, required=True)
    args = parser.parse_args()
    print(f'Normalized {normalize(args.repository)} provenance records')
