"""Owner-approved single-point force schedule and frozen T3-v2 scoring."""
from __future__ import annotations


def force_schedule(protocol):
    dt=protocol['dt_s'];timing=protocol['timing_s'];tick=0
    for phase in ['settle','load','hold','unload','observe']:
        count=round(timing[phase]/dt)
        for index in range(count):
            tick+=1
            gain=((index+1)/count if phase=='load' else 1-(index+1)/count if phase=='unload' else 1. if phase=='hold' else 0.)
            yield {'time_s':tick*dt,'phase':phase,'gain':gain}


def score_point(rows,protocol,vertical_force):
    c=protocol['criteria'];hold=[r for r in rows if r['phase']=='hold']
    observe=[r for r in rows if r['phase']=='observe']
    tail=hold[-round(c['positive_tail_s']/protocol['dt_s']):]
    tilt_min=min(r['shaft_angle_deg'] for r in hold)
    signal_max=max(max(r['signal'],r['raw_fraction']) for r in hold)
    tail_min=min(min(r['signal'],r['raw_fraction']) for r in tail)
    unloaded=max(max(r['signal'],r['raw_fraction']) for r in observe)
    fixture=tilt_min>=c['minimum_hold_tilt_deg']
    positive=vertical_force==protocol['positive_control_n']
    force_pass=(tail_min>=c['positive_tail_signal_min'] if positive else signal_max<=c['low_hold_signal_max'])
    return {'fixture_valid':fixture,'hold_tilt_min_deg':tilt_min,'hold_tilt_max_deg':max(r['shaft_angle_deg'] for r in hold),
        'hold_signal_max':signal_max,'positive_tail_signal_min':tail_min,'unloaded_signal_max':unloaded,
        'final_signal':rows[-1]['signal'],'final_raw_fraction':rows[-1]['raw_fraction'],
        'positive_control':positive,'force_signal_passed':force_pass,'unloaded_passed':unloaded<=c['unloaded_signal_max'],
        'physical_passed':force_pass and unloaded<=c['unloaded_signal_max'] if fixture else None,
        'passed':fixture and force_pass and unloaded<=c['unloaded_signal_max'],
        'hold_samples':len(hold),'positive_tail_samples':len(tail),'observe_samples':len(observe)}
