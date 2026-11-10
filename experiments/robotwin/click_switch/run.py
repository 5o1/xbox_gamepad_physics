"""Reuse frozen acceptance and station benchmark entrypoints with the prototype."""
import argparse
from contextlib import nullcontext
import os
from unittest.mock import patch
import hashlib
import json
from pathlib import Path
import sys
import time

from experiments.robotwin.click_switch.override import policy


def distribution(repetitions):
    import numpy as np
    trials = [dict(median_us=float(np.median(v)/1000),p95_us=float(np.percentile(v,95)/1000),
        mean_us=float(np.mean(v)/1000)) for v in repetitions]
    return dict(trials=trials,median_us=float(np.median([r['median_us'] for r in trials])),
        p95_us=float(np.median([r['p95_us'] for r in trials])),
        median_range_us=[min(r['median_us'] for r in trials),max(r['median_us'] for r in trials)],
        p95_range_us=[min(r['p95_us'] for r in trials),max(r['p95_us'] for r in trials)])


def main():
    p=argparse.ArgumentParser(description=__doc__)
    p.add_argument('--mode',choices=['pure','hybrid','preload'],required=True)
    p.add_argument('--entry',choices=['acceptance','benchmark'],required=True)
    p.add_argument('--epsilon-m',type=float,default=1e-6)
    p.add_argument('--deployment-1ms',action='store_true')
    p.add_argument('--always-awake',action='store_true')
    a,remaining=p.parse_known_args()
    output=Path(remaining[remaining.index('--output')+1])
    sys.argv=[sys.argv[0]]+remaining
    if a.entry=='acceptance':
        from tests.acceptance.robotwin.station_rtf import main as upstream
    else:
        from experiments.robotwin.station_rtf.benchmark import main as upstream
    started=time.monotonic()
    context = nullcontext([]) if a.mode=='preload' else policy(mode=a.mode,epsilon_m=a.epsilon_m,measure=a.entry=='benchmark')
    # Same prepared-resource snapshot path as the acceptance executor. Prevent
    # resource auto-builds against shared maintained inputs in this diagnostic.
    resource_root=Path(os.environ['XBOX_GAMEPAD_PHYSICS_RESOURCES'])
    from experiments.robotwin.click_switch import awake, deployment
    awake_context=awake.policy() if a.always_awake else nullcontext([])
    deployment_context=deployment.policy() if a.deployment_1ms else nullcontext(None)
    with patch('xbox_gamepad_physics.resources.resource_root',return_value=resource_root), \
         context as switches, awake_context as awake_records, deployment_context as deployment_receipt:
        upstream()
        snapshots=[s.snapshot() for s in switches]
        if a.entry=='benchmark' and a.mode!='preload':
            import numpy as np
            steps=int(remaining[remaining.index('--steps')+1]) if '--steps' in remaining else 3000
            # Existing timer surrounds scene.step including the inserted callback.
            # Preserve it as native_with_callback; inner timers measure actual
            # native scene.step separately. Full backend step remains untouched.
            path=output/'step_times.npz'
            with np.load(path) as source:arrays={key:source[key] for key in source.files}
            native=[np.asarray(s.native_ns[-steps:],dtype=np.int64) for s in switches]
            callback=[np.asarray(s.callback_ns[-steps:],dtype=np.int64) for s in switches]
            for i,(n,c) in enumerate(zip(native,callback)):
                arrays[f'native_with_callback_{i}_ns']=arrays[f'native_{i}_ns']
                arrays[f'native_{i}_ns']=n
                arrays[f'callback_{i}_ns']=c
            np.savez_compressed(path,**arrays)
            receipt=json.loads((output/'summary.json').read_text())
            receipt['distribution']['native_with_callback']=receipt['distribution']['native']
            receipt['distribution']['native']=distribution(native)
            receipt['distribution']['callback']=distribution(callback)
            receipt['provenance']['step_times_sha256']=hashlib.sha256(path.read_bytes()).hexdigest()
            receipt['prototype']=dict(mode=a.mode,epsilon_m=a.epsilon_m,switch_states=snapshots)
            (output/'summary.json').write_text(json.dumps(receipt,indent=2)+'\n')
        receipt=json.loads((output/'summary.json').read_text())
        if a.always_awake:receipt['always_awake']=awake_records
        if deployment_receipt is not None:
            (output/'deployment.json').write_text(json.dumps(deployment_receipt,indent=2)+'\n')
            receipt['deployment_dt_s']=.001
        (output/'summary.json').write_text(json.dumps(receipt,indent=2)+'\n')
        (output/'click_switch.json').write_text(json.dumps(dict(mode=a.mode,epsilon_m=a.epsilon_m,
            elapsed_s=time.monotonic()-started,states=snapshots,always_awake=awake_records,
            deployment_1ms=a.deployment_1ms),indent=2)+'\n')

if __name__=='__main__':main()
