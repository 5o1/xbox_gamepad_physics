"""K12 scripted gamepad handoffs and gamepad grasp, preserving asset drives."""
import argparse
import json
from pathlib import Path

from .session import Command, pose_data
from .validate import pose_error


def make(cfg, output):
    from .runtime import make_session
    output.mkdir(parents=True,exist_ok=True)
    record=(output/'record.jsonl').open('w')
    return make_session(cfg,output,record),record


def handoffs(cfg, output, pressed=False):
    import numpy as np
    import sapien
    session,record=make(cfg,output)
    probe=None
    # Settle onto the tabletop before placing the holding indenter. Otherwise
    # the initial 0.5 mm air gap moves the pad within a step before the scripted
    # root-following probe can update at the next boundary.
    if pressed:
        session.phase='settle_on_table'
        session.step(Command(toggle_gamepad=True))
        for _ in range(125):session.step(Command())
        session.step(Command(toggle_gamepad=True))
        for _ in range(125):session.step(Command())
        session.phase='a_hold_handoffs'
    if pressed:
        builder=session.scene.create_actor_builder()
        builder.add_box_collision(half_size=[.003,.003,.002], material=session.scene.create_physical_material(.8,.6,0))
        probe=builder.build_kinematic(name='a_hold_probe')
        # A physical indenter, following root translation so the press is held.
        body=probe.find_component_by_type(sapien.physx.PhysxRigidDynamicComponent)
        session.body_ids[body]='a_hold_probe'
    rows=[];transitions=[]
    def step(command=Command()):
        if probe:
            root=session.gamepad.articulation.get_root_pose()
            approach=.004*max(0.,1-len(rows)/125)
            body.set_kinematic_target(root*sapien.Pose([.040,.013,.0214+approach]))
        row=session.step(command)['state'];rows.append(row);return row
    for _ in range(250):step()
    for _ in range(4):
        reference=rows[-1]['gamepad']['pose'];signals=rows[-1]['signals']
        ref_joint=rows[-1]['gamepad']['joints']
        window=[step(Command(toggle_gamepad=True))]+[step() for _ in range(124)]
        events=window[0]['gamepad_transition']
        position=max(pose_error(r['gamepad']['pose'],reference)[0] for r in window)
        angle=max(pose_error(r['gamepad']['pose'],reference)[1] for r in window)
        signal_jump=max(abs(v) for v in events['signal_delta'].values())
        transitions.append({'to':events['to'],'root_displacement_m':position,'root_rotation_rad':angle,
                            'handoff_signal_jump':signal_jump,
                            'a_signal_before':signals['south'],'a_signal_min':min(r['signals']['south'] for r in window),
                            'a_position_change_m':max(abs(r['gamepad']['joints']['a_press']-ref_joint['a_press']) for r in window),
                            'passed':position<=.001 and angle<=np.deg2rad(1) and signal_jump<=1e-6})
    if pressed:
        for event in transitions:
            event['passed'] &= event['a_signal_before']>=.95 and event['a_signal_min']>=.95 and event['a_position_change_m']<=1e-5
    result={'passed':all(t['passed'] for t in transitions),'pressed':pressed,'transitions':transitions,
            'maximum_internal_contact_pairs':max(r['gamepad_internal_pairs'] for r in rows),
            'maximum_between_copy_contacts':max(r['gamepad_between_copy_contacts'] for r in rows),
            'original_groups':session.gamepad_switch.groups,
            'articulation_count':1,
            'drive_properties':{j.name:[float(j.stiffness),float(j.damping),float(j.force_limit),float(j.friction)]
                                for j in session.gamepad.articulation.get_active_joints()}}
    result['passed'] &= result['maximum_internal_contact_pairs']==0 and result['maximum_between_copy_contacts']==0
    record.close();(output/'metrics.json').write_text(json.dumps(result,indent=2));return result


def grasp(cfg, output):
    import copy
    import numpy as np
    import sapien
    from transforms3d.quaternions import mat2quat
    cfg=copy.deepcopy(cfg)
    # +X finger length points down; jaws span the middle shell front/back in world Y.
    rotation=np.array([[0,0,1],[0,1,0],[-1,0,0]])
    cfg['teleop']['initial_pose']=[0,.010,.163,*mat2quat(rotation).tolist()]
    cfg['teleop']['initial_opening_m']=cfg['teleop']['input']['open_target_m']
    session,record=make(cfg,output);rows=[];clearance_rows=[]
    def step(command=Command(),phase=''):
        session.phase=phase;row=session.step(command)['state']
        if phase in ('p0_hold','freeze_gripper'):
            low=min(float(l.compute_global_aabb_tight()[0][2]) for l in session.gamepad.articulation.get_links() if l.get_collision_shapes())
            row['gamepad_bottom_z_m']=low
            clearance_rows.append({'step':row['step'],'phase':phase,'bottom_z_m':low})
        rows.append(row);return row
    step(Command(toggle_gamepad=True),'unfreeze_gamepad')
    for _ in range(125):step(phase='settle')
    step(Command(opening=-100),'close')
    for _ in range(250):step(phase='close')
    trajectory=cfg['teleop']['grasp_test'];count=round(trajectory['lift_seconds']/.004)
    tick=trajectory['lift_m']/count/cfg['teleop']['input']['fine']['translation_m']
    for _ in range(count):step(Command(translation=(0,0,tick),fine=True),'lift')
    for _ in range(250):step(phase='settle_hold')
    def relative(row):
        root=row['frozen' if row['state']!='main' else 'main']['pose'];pad=row['gamepad']['pose']
        return pose_data(sapien.Pose(root[:3],root[3:]).inv()*sapien.Pose(pad[:3],pad[3:]))
    reference=relative(rows[-1])
    hold=[step(phase='p0_hold') for _ in range(500)]
    displacement=max(pose_error(relative(r),reference)[0] for r in hold)
    angle=max(pose_error(relative(r),reference)[1] for r in hold)
    table_contacts=sum(any('table' in c['bodies'] and any(b.startswith('gamepad/') for b in c['bodies']) for c in r['contacts']) for r in hold)
    # Lowest cooked collision point measured at the end; each link's actual shape geometry.
    clearance=min(r['gamepad_bottom_z_m'] for r in hold)
    p0={'relative_displacement_m':displacement,'relative_rotation_rad':angle,'bottom_clearance_m':clearance,
        'table_contact_steps':table_contacts,'hold_seconds':2.,
        'passed':bool(clearance>=.03 and table_contacts==0 and displacement<=.002 and angle<=np.deg2rad(2))}
    freeze=None
    if p0['passed']:
        reference=relative(rows[-1]);hold=[step(Command(toggle=i==0),'freeze_gripper') for i in range(500)]
        displacement=max(pose_error(relative(r),reference)[0] for r in hold)
        angle=max(pose_error(relative(r),reference)[1] for r in hold)
        freeze={'relative_displacement_m':displacement,'relative_rotation_rad':angle,'hold_seconds':2.,
                'passed':bool(displacement<=.002 and angle<=np.deg2rad(2))}
    result={'passed':bool(p0['passed'] and freeze and freeze['passed']), 'P0':p0,'freeze_gripper':freeze,
            'maximum_internal_contact_pairs':max(r['gamepad_internal_pairs'] for r in rows),
            'maximum_between_copy_contacts':max(r['gamepad_between_copy_contacts'] for r in rows),
            'trajectory':cfg['teleop']['grasp_test'],'initial_gripper_pose':cfg['teleop']['initial_pose']}
    result['passed'] &= result['maximum_internal_contact_pairs']==0 and result['maximum_between_copy_contacts']==0
    (output/'clearance.json').write_text(json.dumps(clearance_rows,indent=2))
    record.close();(output/'metrics.json').write_text(json.dumps(result,indent=2));return result


if __name__=='__main__':
    from .server import live_config
    p=argparse.ArgumentParser(description=__doc__);p.add_argument('--output',type=Path,required=True)
    p.add_argument('--config',type=Path,default=Path('configs/teleop_gripper.yaml'))
    p.add_argument('--gate',choices=['static','pressed','grasp'],required=True)
    a=p.parse_args();cfg=live_config(a.config)
    result=grasp(cfg,a.output) if a.gate=='grasp' else handoffs(cfg,a.output,a.gate=='pressed')
    print(json.dumps(result));raise SystemExit(0 if result['passed'] else 1)
