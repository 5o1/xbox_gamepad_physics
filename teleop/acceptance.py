"""GPU K8 scripts and registered phase-1 replay, after FPS windows finish."""
import argparse
import json
from pathlib import Path
import subprocess
import sys
from .site import require
from .record import find_record,read_header


def write_replay_config(path, header, record):
    # run_robotwin reads YAML. JSON's 1e-05 is a string in YAML 1.1;
    # safe_dump keeps small test values numeric at this format boundary.
    import yaml
    cfg = dict(header['config'], experiment='teleop_replay', params={'record':str(record)})
    path.write_text(yaml.safe_dump(cfg, sort_keys=False))


def main():
    p=argparse.ArgumentParser(description=__doc__)
    p.add_argument('--root',type=Path,required=True)
    p.add_argument('--gpu',type=int,default=int(require('TELEOP_GPU')))
    p.add_argument('--phase1-record',type=Path,required=True)
    p.add_argument('--cursor-config',type=Path,help='live_config.json: compile cursor events into world Commands')
    args=p.parse_args()
    args.root.mkdir(parents=True,exist_ok=True)
    commands=[{} for _ in range(4000)]
    for step in range(100,500,25):commands[step]={'translation':[-1,0,0],'fine':True}
    for step in range(550,800,25):commands[step]={'rotation':[0,0,.1],'fine':True}
    commands[850]={'opening':-1,'fine':True}
    commands[1000]={'toggle':True}
    for step in range(1001,1150,10):commands[step]={'translation':[0,-1,0],'fine':True}
    commands[1600]={'toggle':True}
    commands[2000]={'stop':True}
    commands[2400]={'opening':1,'fine':True}
    commands[2600]={'toggle_gamepad':True}
    commands[3000]={'toggle_gamepad':True}
    if args.cursor_config:
        from dataclasses import asdict
        from .inputs import Inputs
        from .session import command_target
        cfg=json.loads(args.cursor_config.read_text())
        control=Inputs(cfg['stream']['input_repeat_seconds'],cfg['stream']['control_lease_seconds'],
                       camera_relative=True,input_config=cfg['teleop']['input'],cursor_config=cfg['stream']['cursor'])
        pose=cfg['teleop']['initial_pose'];finger=cfg['teleop']['initial_opening_m']
        events={0:[{'kind':'focus'}],550:[{'kind':'keys','keys':['KeyW','ShiftLeft']}],
                650:[{'kind':'keys','keys':[]}],700:[{'kind':'view','view':'left'}],
                750:[{'kind':'keys','keys':['KeyA','ShiftLeft']}],800:[{'kind':'keys','keys':[]}],
                850:[{'kind':'delta','grip':'close'}],1000:[{'kind':'delta','toggle':True}],
                1600:[{'kind':'delta','toggle':True}],2000:[{'kind':'stop','reason':'scripted-escape'}],
                2200:[{'kind':'focus'}],2400:[{'kind':'delta','grip':'open'}],
                2600:[{'kind':'delta','toggle_gamepad':True}],3000:[{'kind':'delta','toggle_gamepad':True}]}
        for step in range(100,500,25):events[step]=[{'kind':'delta','screen_pixels':[5 if step%50==0 else -5,3],'fine':True}]
        for step in range(1100,1400,25):events[step]=[{'kind':'delta','screen_pixels':[2,-2],'fine':True}]
        seq=0;commands=[]
        for step in range(4000):
            for event in events.get(step,[]):
                seq+=1;control.accept({'seq':seq,**event},step)
            cmd=control.command(step*.004,pose=pose,finger_target=finger)
            control.commit();commands.append(asdict(cmd))
            if not cmd.toggle:pose,finger=command_target(pose,finger,cmd,cfg['teleop']['input'])
        (args.root/'k8_cursor_events.json').write_text(json.dumps(events,indent=2))
    path=args.root/'k8_commands.json'
    path.write_text(json.dumps(commands))
    for mode in ('on','off'):
        cmd=[require('TELEOP_STREAM_PYTHON'),'-u','-m','teleop.stream.gateway','--run',str(args.root/f'k8_stream_{mode}'),
             '--gpu',str(args.gpu),'--port',require('TELEOP_REMOTE_PORT'),'--commands',str(path),'--steps',str(len(commands))]
        if mode=='off':cmd.append('--stream-off')
        subprocess.run(cmd,check=True)
    from .verify import compare
    result=compare([find_record(args.root/'k8_stream_on'),find_record(args.root/'k8_stream_off')],args.root/'k8_metrics.json')
    print(json.dumps(result))
    if not result['passed']:raise RuntimeError('streaming changed the physics trajectory')
    # Exercise the repository's registered experiment entry, not only direct imports.
    record=args.phase1_record
    header=read_header(record)
    cfg_path=args.root/'k9_config.yaml';write_replay_config(cfg_path,header,record)
    base=require('TELEOP_BASE_PYTHON')
    subprocess.run([base,'run_robotwin.py',str(cfg_path),'--output',str(args.root/'k9_replay')],check=True)
    record=find_record(args.root/'k8_stream_off')
    header=read_header(record)
    cfg_path=args.root/'k9_switch_config.yaml';write_replay_config(cfg_path,header,record)
    subprocess.run([base,'run_robotwin.py',str(cfg_path),'--output',str(args.root/'k9_switch_replay')],check=True)
    result=compare([record,args.root/'k9_switch_replay/replay.jsonl'],args.root/'k9_switch_metrics.json')
    if not result['passed']:raise RuntimeError('switch replay diverged')


if __name__=='__main__':main()
