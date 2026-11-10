"""Archive small actual inputs and numerical model differences, read-only."""
import hashlib
import os
import json
from pathlib import Path
import shutil
import xml.etree.ElementTree as ET

RAW = Path(os.environ['NODE_WORK'], 'station-rtf-20261110/code/build/experiments/station_rtf/view_attribution')
ASSETS = Path(os.environ['NODE_WORK'], 'task-am-0.4.2/workspace/assets')
result = {}
for version in ['0.4.1','0.4.2']:
    root = ASSETS / ('xbox_gamepad_physics_v'+version) / 'resources'
    folder = root/'robotwin/full_controls'
    manifest = json.loads((folder/'manifest.json').read_text())
    urdf = folder/manifest['entrypoint']
    motion = root/manifest['motion_contract']
    out = RAW/'input'/version
    out.mkdir(parents=True,exist_ok=True)
    for path in [folder/'manifest.json',urdf,motion]:
        shutil.copy2(path,out/path.name)
    tree = ET.parse(urdf)
    result[version] = dict(resources=str(root), sha256={str(p):hashlib.sha256(p.read_bytes()).hexdigest() for p in [folder/'manifest.json',urdf,motion]},
        links={l.get('name'):ET.tostring(l.find('inertial'),encoding='unicode') for l in tree.findall('link')},
        joints={j.get('name'):{k:ET.tostring(j.find(k),encoding='unicode') for k in ['parent','child','origin','axis','limit','dynamics'] if j.find(k) is not None} for j in tree.findall('joint')},
        joint_dynamics=manifest['joint_dynamics'],contact_material=manifest['contact_material'])
(RAW/'input/model-inputs.json').write_text(json.dumps(result,indent=2)+'\n')
for group in ['C0','C1-a3','C1-stock']:
    s=json.loads((RAW/group/'summary.json').read_text())
    print(group,[(r['case'],r['target_min'],r['target_max'],r['physics_passed']) for r in s['T4']])
code = RAW.parents[3]
relative = ['robotwin/loader.py','robotwin/mappings.py','robotwin/physical.py','motion.py','controller.py','backends/common/physical.py']
packages = {}
for label, package in {
    'C0_installed':Path(os.environ['NODE_ENVS'], 'sapien-3.0.3concon-xgp0.4.2-py310/lib/python3.10/site-packages/xbox_gamepad_physics'),
    'C1_tag_source':RAW/'input/baseline041/src/xbox_gamepad_physics',
}.items():
    packages[label] = {p:hashlib.sha256((package/p).read_bytes()).hexdigest() for p in relative if (package/p).is_file()}
paths=['tests/acceptance/robotwin/run_suite.py','tests/acceptance/robotwin/executor.py','tests/acceptance/runner.py','tests/acceptance/scoring.py','tests/acceptance/data/ruling20_sdf303_v1.json']
(RAW/'input/source-sha256.json').write_text(json.dumps(dict(packages=packages,frozen={p:hashlib.sha256((code/p).read_bytes()).hexdigest() for p in paths}),indent=2)+'\n')
