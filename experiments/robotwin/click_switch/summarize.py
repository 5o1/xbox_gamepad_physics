"""Collect measured runs, unchanged baseline case identities, and raw handles."""
import argparse
import hashlib
import json
from pathlib import Path
import numpy as np


def sha(path):
    digest=hashlib.sha256()
    with path.open('rb') as source:
        for block in iter(lambda:source.read(1024*1024),b''):digest.update(block)
    return digest.hexdigest()


def main():
    p=argparse.ArgumentParser();p.add_argument('--root',type=Path,required=True);a=p.parse_args()
    root=a.root;load=lambda path:json.loads((root/path).read_text())
    prior=load('input/prior-default-acceptance.json')
    baseline_cases=set(prior['T4']['passed_cases'])
    result=dict(acceptance={},release={},benches={},baseline_t4_passed=sorted(baseline_cases))
    for mode in ('pure','hybrid'):
        for solver in ('64-16','10-1'):
            name=f'{mode}-{solver}-t1'
            result['acceptance'][name]=load(name+'/summary.json')
    for solver in ('64-16','10-1'):
        name=f'hybrid-{solver}-full';receipt=load(name+'/summary.json')
        receipt['t4_regressed_cases']=sorted(baseline_cases-set(receipt['results']['T4']['passed_cases']))
        receipt['t4_newly_passed_cases']=sorted(set(receipt['results']['T4']['passed_cases'])-baseline_cases)
        result['acceptance'][name]=receipt
    for name in ('pure-64-16-release-r1','pure-10-1-release','hybrid-64-16-release','hybrid-10-1-release',
                 'hybrid-64-16-release-30s','hybrid-10-1-release-30s'):
        if not (root/name/'summary.json').exists():continue
        receipt=load(name+'/summary.json')
        receipt['position_pass_count']=sum(r['final_within'] for r in receipt['results'])
        receipt['sleep_count']=sum(r['sleeping_at_end'] for r in receipt['results'])
        result['release'][name]=receipt
    names=['baseline-new-static-r1']+[f'hybrid-{solver}-{condition}-r1'
        for solver in ('64-16','10-1') for condition in ('static','active','contact')]
    for name in names:
        receipt=load(name+'/summary.json')
        with np.load(root/name/'step_times.npz') as arrays:
            receipt['array_lengths']={key:len(arrays[key]) for key in arrays.files}
        receipt['wall_s']=load(name+'/click_switch.json')['elapsed_s']
        result['benches'][name]=receipt
    result['deployment_acceptance']={}
    result['awake_benches']={}
    for config in ('A-64-16','A-10-1','B-10-1'):
        name=f'deployment-{config}-full'
        receipt=load(name+'/summary.json')
        receipt['t4_regressed_cases']=sorted(baseline_cases-set(receipt['results']['T4']['passed_cases']))
        receipt['t4_newly_passed_cases']=sorted(set(receipt['results']['T4']['passed_cases'])-baseline_cases)
        receipt['conversion']=load(name+'/deployment.json')
        result['deployment_acceptance'][name]=receipt
    for label in ('A','B'):
        for condition in ('static','active','contact'):
            name=f'awake-{label}-10-1-{condition}'
            receipt=load(name+'/summary.json')
            with np.load(root/name/'step_times.npz') as arrays:
                receipt['array_lengths']={key:len(arrays[key]) for key in arrays.files}
                complete=np.concatenate([arrays[key] for key in arrays.files if key.startswith('total_')])
                receipt['complete_step_deadline']=dict(samples=len(complete),over_800_us=int(np.sum(complete>800000)),maximum_us=float(np.max(complete)/1000))
            receipt['wall_s']=load(name+'/click_switch.json')['elapsed_s']
            result['awake_benches'][name]=receipt
    result['stopped_sleep_observation']=load('stop-receipt.json')
    result['gravity']=load('gravity/summary.json')
    result['sleep_probe']=load('sleep-probe-r1/summary.json')
    (root/'summary.json').write_text(json.dumps(result,indent=2)+'\n')
    raw={str(path.relative_to(root)):sha(path) for path in sorted(root.rglob('*'))
        if path.is_file() and path.name not in ('raw-sha256.json','source-sha256.json')}
    (root/'raw-sha256.json').write_text(json.dumps(raw,indent=2)+'\n')
    code=Path(__file__).resolve().parents[3]
    paths=list((code/'experiments/robotwin/click_switch').glob('*'))
    paths+=list((code/'tests/acceptance/robotwin').glob('*.py'))
    paths+=list((code/'tests/acceptance/robotwin').glob('*.json'))
    paths+=list((code/'experiments/robotwin/station_rtf').glob('*.py'))
    paths+=[code/'tests/acceptance'/name for name in ('runner.py','scoring.py','cases.py','__init__.py','data/ruling20_sdf303_v1.json')]
    paths+=[code/'references/full_controls.json',code/'src/xbox_gamepad_physics/robotwin/loader.py',
            code/'src/xbox_gamepad_physics/robotwin/mappings.py']
    source={str(path.relative_to(code)):sha(path) for path in sorted(paths) if path.is_file()}
    (root/'source-sha256.json').write_text(json.dumps(source,indent=2)+'\n')
    print(json.dumps(dict(raw_files=len(raw),summary_sha256=sha(root/'summary.json'),
        raw_manifest_sha256=sha(root/'raw-sha256.json'),source_manifest_sha256=sha(root/'source-sha256.json'))),flush=True)

if __name__=='__main__':main()
