"""Clock-bounded delivery distributions and actual root drift after silent loss."""
import argparse
from bisect import bisect_right
import json
import math
from pathlib import Path
from .record import iter_records,find_record


def distribution(values):
    values=sorted(values)
    return {'count':len(values),'min':values[0],'p50':values[math.ceil(.5*len(values))-1],
            'p95':values[math.ceil(.95*len(values))-1],'max':values[-1],'mean':sum(values)/len(values)} if values else None


def clock_interval(probes):
    # Server = browser + offset. Nonnegative forward/return times bound offset.
    low=max(p['server_sent_ns']/1e6-p['t3_ms'] for p in probes)
    high=min(p['server_received_ns']/1e6-p['t0_ms'] for p in probes)
    if low>high:raise ValueError('clock offset bounds do not intersect; inspect drift/probes')
    return low,high


def mapped_time(browser_ms, before, after):
    # Bracket calibration and conservatively include drift between the two estimates.
    pre=clock_interval(before);post=clock_interval(after)
    low=min(pre[0],post[0]);high=max(pre[1],post[1])
    return {'lower_ns':(browser_ms+low)*1e6,'upper_ns':(browser_ms+high)*1e6,
            'estimate_ns':(browser_ms+(low+high)/2)*1e6,'uncertainty_ms':(high-low)/2,
            'pre_offset_bounds_ms':pre,'post_offset_bounds_ms':post}


def affine_time(browser_ms, before, after):
    """Map independently paced clocks, with causal bounds (no symmetry assumption)."""
    probes=before+after
    origin=probes[0]['t0_ms']
    server_origin=probes[0]['server_received_ns']/1e6
    # b >= S2 - a*C3; b <= S1 - a*C0, after centering for precision.
    lower=[(-(p['t3_ms']-origin),p['server_sent_ns']/1e6-server_origin) for p in probes]
    upper=[(-(p['t0_ms']-origin),p['server_received_ns']/1e6-server_origin) for p in probes]
    amin,amax=0.,float('inf')
    for l in lower:
        for u in upper:
            coeff=l[0]-u[0];right=u[1]-l[1]
            if coeff>0:amax=min(amax,right/coeff)
            elif coeff<0:amin=max(amin,right/coeff)
            elif right<0:raise ValueError('inconsistent probe timestamps')
    if amin>amax or not math.isfinite(amax):raise ValueError('no bounded affine clock model')
    lines=lower+upper
    candidates=[amin,amax]
    for i,(m,c) in enumerate(lines):
        for n,d in lines[i+1:]:
            if m!=n:
                a=(d-c)/(m-n)
                if amin<=a<=amax:candidates.append(a)
    target=browser_ms-origin;lo=float('inf');hi=-float('inf')
    for a in candidates:
        bmin=max(m*a+c for m,c in lower);bmax=min(m*a+c for m,c in upper)
        if bmin>bmax+1e-7:continue
        lo=min(lo,a*target+bmin);hi=max(hi,a*target+bmax)
    a=(amin+amax)/2;bmin=max(m*a+c for m,c in lower);bmax=min(m*a+c for m,c in upper)
    estimate=a*target+(bmin+bmax)/2
    return {'model':'affine','rate_estimate_server_per_browser':a,'rate_bounds':[amin,amax],
            'estimate_ns':(server_origin+estimate)*1e6,
            'lower_ns':(server_origin+lo)*1e6,'upper_ns':(server_origin+hi)*1e6,
            'uncertainty_ms':(hi-lo)/2}


def rotation_degrees(a,b):
    dot=abs(sum(x*y for x,y in zip(a,b)))/math.sqrt(sum(x*x for x in a)*sum(x*x for x in b))
    return math.degrees(2*math.acos(min(1.,max(0.,dot))))


def pose_motion(a,b):
    return math.sqrt(sum((x-y)**2 for x,y in zip(a[:3],b[:3])))*1000,rotation_degrees(a[3:],b[3:])


def analyze(args):
    browser=json.loads(args.browser.read_text())
    samples=[];events={}
    for row in iter_records(find_record(args.run)):
        if row['type']!='step':continue
        meta=row['input'];s={'step':row['step'],'time_ns':meta['physics_done_ns'],'pose':row['main']['pose'],
            'target':row['target_pose'],'finger_target':row['finger_target_m'],'command':row['command'],
            'finger_drive_targets':row['main']['drive_targets'],
            'boundary_ns':meta['boundary_ns'],'prepared_ns':meta['command_ready_ns'],
            'targets_set_ns':meta['targets_set_ns'],'last_activity_ns':meta['last_activity_ns'],
            'focus':any(e['kind']=='focus' for e in meta['events']),
            'hold':meta['hold'],'seq':meta['last_input_seq'],'contacts':row['contacts']}
        samples.append(s)
        for event in meta['events']:
            if event['kind'] in ('stop','disconnect','lease-expired'):
                events.setdefault((event['kind'],event['seq']),[]).append((event,s))
    times=[s['time_ns'] for s in samples]
    boundaries=[s['boundary_ns'] for s in samples]
    focus_steps=[s['step'] for s in samples if s['focus']]
    target_times=[s['targets_set_ns'] for s in samples]
    deliveries=[]
    for trial in browser['events']:
        kind='disconnect' if trial['kind']=='disconnect' else 'stop'
        matches=events[(kind,trial['seq'])]
        event,s=matches[0]
        mapped=affine_time(trial['action_ms'],trial['clock_before'],trial['clock_after'])
        receipt=event['received_ns']
        before=samples[s['step']-1]
        next_focus=bisect_right(focus_steps,s['step'])
        hold_end=focus_steps[next_focus] if next_focus<len(focus_steps) else len(samples)
        held=samples[s['step']:hold_end]
        at_receipt=max(0,bisect_right(target_times,receipt)-1)
        current=samples[at_receipt]
        since_receipt=samples[at_receipt+1:hold_end]
        current_goal_held=all(p['target']==current['target'] and p['finger_target']==current['finger_target'] for p in since_receipt)
        deliveries.append({**trial,'clock_mapping':mapped,'server_received_ns':receipt,
            'delivery_estimate_ms':(receipt-mapped['estimate_ns'])/1e6,
            'delivery_bounds_ms':[(receipt-mapped['upper_ns'])/1e6,(receipt-mapped['lower_ns'])/1e6],
            'receipt_to_target_hold_ms':(s['targets_set_ns']-receipt)/1e6,
            'completed_physics_steps_before_hold':bisect_right(times,s['targets_set_ns'])-bisect_right(times,receipt),
            'first_eligible_boundary_step':bisect_right(boundaries,receipt),
            'target_at_receipt_step':at_receipt,'target_at_receipt':current['target'],
            'current_target_and_preload_held_since_receipt':current_goal_held,
            'hold_step':s['step'],'boundary_delay_steps':s['step']-bisect_right(boundaries,receipt),
            'held_steps_until_next_focus':len(held),
            'held_target_and_preload_constant':all(p['target']==before['target'] and p['finger_target']==before['finger_target'] for p in held),
            'target_change_at_hold_mm':pose_motion(before['target'],s['target'])[0],
            'finger_target_change_at_hold_m':abs(before['finger_target']-s['finger_target']),
            'finger_target_at_hold_m':s['finger_target']})
    losses=[]
    for trial in browser['losses']:
        event,s=events[('lease-expired',trial['seq'])][0]
        mapped=affine_time(trial['cut_ms'],trial['clock_before'],trial['clock_after'])
        base= max(0,bisect_right(times,mapped['estimate_ns'])-1)
        last_tick=next(p for p in reversed(samples[:base+1]) if any(p['command']['translation']))
        # A 4 ms discretization guard covers pose sampling at step boundaries.
        baselo=max(0,bisect_right(times,mapped['lower_ns']-4e6)-1)
        basehi=min(len(samples)-1,bisect_right(times,mapped['upper_ns']+4e6))
        hold=s['step'];end=min(len(samples),bisect_right(times,s['targets_set_ns']+500e6))
        def maxima(first,last,initial):
            differences=[pose_motion(initial['pose'],p['pose']) for p in samples[first:last]]
            return {'translation_mm':max(x[0] for x in differences),'rotation_degrees':max(x[1] for x in differences)}
        held=samples[hold:end]
        prior=samples[hold-1]
        hold_constant=all(pose_motion(prior['target'],p['target'])[0]<1e-9 and
            rotation_degrees(prior['target'][3:],p['target'][3:])<1e-5 and p['finger_target']==prior['finger_target'] for p in held)
        peak_before=maxima(base,hold,samples[base]);peak_settled=maxima(base,end,samples[base])
        upper_before=max(maxima(b,hold,samples[b])['translation_mm'] for b in range(baselo,basehi+1))
        upper_settled=max(maxima(b,end,samples[b])['translation_mm'] for b in range(baselo,basehi+1))
        upper_rotation_before=max(maxima(b,hold,samples[b])['rotation_degrees'] for b in range(baselo,basehi+1))
        upper_rotation_settled=max(maxima(b,end,samples[b])['rotation_degrees'] for b in range(baselo,basehi+1))
        # Stationary target settling is reported rather than called an instantaneous stop.
        at_end=held[-1]
        end_speed=pose_motion(samples[at_end['step']-1]['pose'],at_end['pose'])[0]/.004
        losses.append({**trial,'clock_mapping':mapped,'cut_step_estimate':base,'cut_step_bounds':[baselo,basehi],
            'last_tick_to_cut_ms':(mapped['estimate_ns']-last_tick['time_ns'])/1e6,
            'finger_target_during_hold_m':s['finger_target'], 'hold_step':hold,'last_activity_ns':s['last_activity_ns'],
            'lease_expiry_ns':event['received_ns'],'detected_ns':s['prepared_ns'],'targets_set_ns':s['targets_set_ns'],
            'expiry_to_detection_ms':(s['prepared_ns']-event['received_ns'])/1e6,
            'detector_loop_period_at_hold_ms':(s['prepared_ns']-prior['prepared_ns'])/1e6,
            'last_receipt_to_detection_ms':(s['prepared_ns']-s['last_activity_ns'])/1e6,
            'cut_to_detection_estimate_ms':(s['prepared_ns']-mapped['estimate_ns'])/1e6,
            'detection_to_target_hold_ms':(s['targets_set_ns']-s['prepared_ns'])/1e6,
            'before_detection_peak':peak_before,'through_settling_peak':peak_settled,
            'conservative_translation_before_hold_mm':upper_before,
            'conservative_translation_through_settling_mm':upper_settled,
            'conservative_rotation_before_hold_degrees':upper_rotation_before,
            'conservative_rotation_through_settling_degrees':upper_rotation_settled,
            'continued_target_increments':sum(any(p['command']['translation']) for p in samples[base+1:hold]),
            'held_target_and_preload_constant':hold_constant,'terminal_speed_mm_s':end_speed,
            'main_external_contact_pairs_during_loss':sum(sum(any(b.startswith('main/') for b in c['bodies']) for c in p['contacts']) for p in samples[base:hold+1])})
    summary={'chrome_version':browser['chrome_version'],'event_delivery':{},'silent_loss':{},
             'relative_clock_rate':distribution([r['clock_mapping']['rate_estimate_server_per_browser'] for r in deliveries+losses]),
             'clock_uncertainty_ms':distribution([r['clock_mapping']['uncertainty_ms'] for r in deliveries+losses])}
    for kind in ('escape','blur','disconnect'):
        trials=[t for t in deliveries if t['kind']==kind]
        summary['event_delivery'][kind]={
            'delivery_estimate_ms':distribution([t['delivery_estimate_ms'] for t in trials]),
            'delivery_lower_bound_ms':distribution([t['delivery_bounds_ms'][0] for t in trials]),
            'delivery_upper_bound_ms':distribution([t['delivery_bounds_ms'][1] for t in trials]),
            'receipt_to_target_hold_ms':distribution([t['receipt_to_target_hold_ms'] for t in trials])}
    for fine in (False,True):
        for diagonal in (False,True):
            trials=[t for t in losses if t['fine']==fine and t['diagonal']==diagonal]
            key=('fine' if fine else 'coarse')+('_diagonal' if diagonal else '_single')
            summary['silent_loss'][key]={
                k:distribution([t[k] for t in trials]) for k in ('detector_loop_period_at_hold_ms','expiry_to_detection_ms','last_receipt_to_detection_ms',
                'cut_to_detection_estimate_ms','detection_to_target_hold_ms','terminal_speed_mm_s',
                'conservative_translation_before_hold_mm','conservative_translation_through_settling_mm','conservative_rotation_before_hold_degrees','conservative_rotation_through_settling_degrees','last_tick_to_cut_ms')}
            for phase in ('before_detection_peak','through_settling_peak'):
                summary['silent_loss'][key][phase]={unit:distribution([t[phase][unit] for t in trials])
                                                   for unit in ('translation_mm','rotation_degrees')}
    summary['K10']=all(t['completed_physics_steps_before_hold']<=1 and t['held_target_and_preload_constant'] and t['target_change_at_hold_mm']<=1e-9 and
                          t['finger_target_change_at_hold_m']==0 for t in deliveries) and all(
        t['detection_to_target_hold_ms']<=4 and t['held_target_and_preload_constant'] for t in losses)
    summary['K10_definition']='at most one physics step completes between server receipt and target hold; targets/preload at hold preserved until refocus; elapsed wall-clock values reported separately'
    summary['N9_coarse_over_5mm_risk']=any(not t['fine'] and t['before_detection_peak']['translation_mm']>5 for t in losses)
    args.output.write_text(json.dumps({'summary':summary,'event_trials':deliveries,'loss_trials':losses},indent=2))
    print(json.dumps(summary,indent=2))


if __name__=='__main__':
    p=argparse.ArgumentParser(description=__doc__);p.add_argument('--run',type=Path,required=True)
    p.add_argument('--browser',type=Path,required=True);p.add_argument('--output',type=Path,required=True)
    analyze(p.parse_args())
