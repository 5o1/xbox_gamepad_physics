"""Frozen single-point protocol: timing and positive/negative scoring boundaries."""
import json
from pathlib import Path
from tests.acceptance.isaac.t3_point import force_schedule,score_point

P=json.loads((Path(__file__).parents[2]/'acceptance/isaac/stick_click_t3_point_v2.json').read_text())

def rows(fraction):
    return [{**r,'signal':fraction if r['phase']=='hold' else 0.,
        'raw_fraction':fraction if r['phase']=='hold' else 0.,'shaft_angle_deg':2.} for r in force_schedule(P)]

def test_exact_registered_schedule():
    r=list(force_schedule(P));assert len(r)==875
    assert [sum(x['phase']==p for x in r) for p in ['settle','load','hold','unload','observe']]==[250,125,250,125,125]
    assert r[374]['gain']==1. and r[749]['gain']==0. and r[-1]['time_s']==3.5

def test_low_signal_failure_is_not_hidden_by_valid_fixture():
    result=score_point(rows(.051),P,1.)
    assert result['fixture_valid'] and not result['passed'] and not result['force_signal_passed']

def test_positive_control_uses_last_half_second_and_requires_raw_ratio():
    r=rows(.96)
    for x in r:
        if x['phase']=='hold' and x['time_s']<=2.:x['signal']=x['raw_fraction']=.5
    result=score_point(r,P,8.14);assert result['passed'] and result['positive_tail_samples']==125
    r[624]['raw_fraction']=.94
    assert not score_point(r,P,8.14)['passed']

def test_invalid_tilt_does_not_make_a_physical_conclusion():
    r=rows(0.);r[500]['shaft_angle_deg']=.999
    result=score_point(r,P,1.)
    assert not result['fixture_valid'] and result['physical_passed'] is None

def test_unloaded_transient_is_reported_even_if_endpoint_is_zero():
    r=rows(0.);r[750]['signal']=.06
    assert not score_point(r,P,1.)['unloaded_passed']
