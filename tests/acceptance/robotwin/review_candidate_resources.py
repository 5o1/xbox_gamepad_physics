"""Audit new backend-only resource changes against its pre-combination copy."""
import argparse
import copy
import json
from pathlib import Path
import xml.etree.ElementTree as ET


def canonical(element):
    return (element.tag, dict(element.attrib), [canonical(c) for c in element])


def review(root):
    directories = [root / name / 'robotwin/full_controls' for name in ('resources_a1', 'resources_a2')]
    trees = [ET.parse(d / 'mobility.urdf').getroot() for d in directories]
    links = [{e.attrib['name']: e for e in t.findall('link')} for t in trees]
    joints = [{e.attrib['name']: e for e in t.findall('joint')} for t in trees]
    assert links[0].keys() == links[1].keys()
    assert joints[0].keys() == joints[1].keys()
    changed = [n for n in joints[0] if canonical(joints[0][n]) != canonical(joints[1][n])]
    rows = []
    for name in links[0]:
        origins_same = all(canonical(e.find('origin')) == canonical(joints[1][e.attrib['name']].find('origin'))
                           for e in joints[0].values() if e.find('child').attrib['link'] == name)
        rows.append({'link': name, 'link_inertial_visual_collision_unchanged': canonical(links[0][name]) == canonical(links[1][name]),
                     'parent_joint_origin_unchanged': origins_same})
    for name in changed:
        a, b = [copy.deepcopy(j[name]) for j in joints]
        for e in (a, b):
            e.find('dynamics').set('friction', '0')
        assert canonical(a) == canonical(b), name
    manifests = [json.loads((d / 'manifest.json').read_text()) for d in directories]
    contracts = [json.loads((root / name / manifest['motion_contract']).read_text())
                 for name, manifest in zip(('resources_a1', 'resources_a2'), manifests)]
    result = {'comparison': 'Private new-chain pre-combination resources_a1 versus frozen resources_a2; not a fresh pre-branch main geometry verification',
              'links': rows, 'changed_urdf_joints': changed,
              'only_joint_xml_changes_are_legacy_friction_clear': True,
              'state_mapping_unchanged': contracts[0]['bindings'] == contracts[1]['bindings'],
              'mass_kg_before_after': [sum(float(l.find('inertial/mass').attrib['value']) for l in group.values()) for group in links]}
    assert all(row['link_inertial_visual_collision_unchanged'] and row['parent_joint_origin_unchanged'] for row in rows)
    assert result['state_mapping_unchanged']
    (root / 'GEOMETRY_MAPPING_AUDIT.json').write_text(json.dumps(result, indent=2) + '\n')
    print(json.dumps({k: v for k, v in result.items() if k != 'links'}))


if __name__ == '__main__':
    parser = argparse.ArgumentParser()
    parser.add_argument('root', type=Path)
    review(parser.parse_args().root)
