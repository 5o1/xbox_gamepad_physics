"""Read-only K8 and server-boundary K10 checks on raw records."""
import argparse
import json
from pathlib import Path
from .record import iter_records,find_record


def compare(paths,output):
    from experiments.teleop_replay import read_record, step_difference, numeric_difference
    _, a=read_record(paths[0]);_, b=read_record(paths[1])
    first=None;max_pose=0.;max_joint=0.;signals=True
    for x,y in zip(a,b):
        diff=step_difference(x,y)
        if 'gamepad_frozen' in x or 'gamepad_frozen' in y:
            extra=max(numeric_difference(x.get(k),y.get(k)) for k in
                      ('gripper_freeze','gamepad_frozen','gamepad_transition','gamepad_collision_groups','gamepad_between_copy_contacts','gamepad_articulation_count'))
            diff['freeze_max_abs']=extra
            diff['passed'] &= extra<=1e-9
            diff['pose_max_abs']=max(diff['pose_max_abs'],extra)
        max_pose=max(max_pose,diff['pose_max_abs']);max_joint=max(max_joint,diff['joint_max_abs'])
        signals &= diff['signals_equal']
        if not diff['passed'] and first is None:first=diff
    result={'passed':first is None and len(a)==len(b),'steps':[len(a),len(b)],'first_divergence':first,
            'max_pose_abs':max_pose,'max_joint_abs':max_joint,'signals_equal':signals}
    output.write_text(json.dumps(result,indent=2))
    return result


def safety(run,output):
    from experiments.teleop_replay import numeric_difference
    timing=list(iter_records(find_record(run,'physics_timing')))
    cases=[];previous=None;active_case=None;lag_rows=0;lag_examples=[];trailing_rows=0
    for row in iter_records(find_record(run)):
        if row['type']!='step':continue
        step=row['step']
        if step>=len(timing):
            trailing_rows+=1
            continue
        t=timing[step];meta=row.get('input',{})
        if meta.get('received_seq',0)>meta.get('last_input_seq',0):
            lag_rows+=1
            if len(lag_examples)<5:
                lag_examples.append({'step':step,'received_seq':meta['received_seq'],
                    'applied_seq':meta['last_input_seq'],'command':row['command']})
        events=[e for e in t['input_events'] if e['kind'] in ('stop','disconnect','lease-expired')]
        if t.get('hold') and events:
            event=events[-1];receipt=event['received_ns']
            eligible=next((x['step'] for x in timing[max(0,step-5):step+2] if x['boundary_ns']>=receipt),step)
            active_case={'kind':event['kind'],'reason':t['hold_reason'],'seq':event['seq'],
                'applied_step':step,'first_eligible_boundary':eligible,'boundary_delay_steps':step-eligible,
                'sampling_delay_ms':max(0,(t['boundary_ns']-receipt)/1e6),
                'completed_step_after_event_ms':(t['end_ns']-receipt)/1e6,
                'target_at_hold':row['target_pose'],'finger_target_at_hold_m':row['finger_target_m'],
                'initial_target_change':numeric_difference(previous['target_pose'],row['target_pose']) if previous else None,
                'initial_finger_target_change_m':abs(previous['finger_target_m']-row['finger_target_m']) if previous else None,
                'held_steps':0,'max_target_change':0.,'max_finger_target_change_m':0.}
            cases.append(active_case)
        if active_case:
            if any(e['kind']=='focus' for e in t['input_events']):active_case=None
            else:
                active_case['held_steps']+=1
                active_case['max_target_change']=max(active_case['max_target_change'],numeric_difference(active_case['target_at_hold'],row['target_pose']))
                active_case['max_finger_target_change_m']=max(active_case['max_finger_target_change_m'],abs(active_case['finger_target_at_hold_m']-row['finger_target_m']))
        previous=row
    result={'server_boundary_passed':bool(cases) and all(c['boundary_delay_steps']<=0 and
        c['initial_target_change']<=1e-12 and c['initial_finger_target_change_m']<=1e-12 and
        c['max_target_change']<=1e-12 and c['max_finger_target_change_m']<=1e-12 for c in cases),
        'trailing_steps_without_timing':trailing_rows,'cases':cases,'queued_sequence_rows':lag_rows,'queued_sequence_examples':lag_examples,
        'definition':'first physics boundary after server receipt or lease expiry; silent-loss detection is separately 200 ms, not 4 ms'}
    output.write_text(json.dumps(result,indent=2))
    return result


if __name__=='__main__':
    p=argparse.ArgumentParser(description=__doc__)
    p.add_argument('--compare',nargs=2,type=Path);p.add_argument('--safety',type=Path);p.add_argument('--output',type=Path,required=True)
    a=p.parse_args()
    print(json.dumps(compare(a.compare,a.output) if a.compare else safety(a.safety,a.output)))
