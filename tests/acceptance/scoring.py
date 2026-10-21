"""Ruling20 physical scoring, separated from presentation/browser evidence."""
from __future__ import annotations


def target_value(spec,signals,events):
    if spec["channel"] is None:return events.get("pair_bind_connect",0)
    return (spec["sign"] if spec["kind"]=="stick" else 1)*signals[spec["channel"]]


def threshold(channel,criteria):
    if channel and channel.startswith("dpad_"):return criteria["dpad_threshold"]
    return criteria["analog_threshold"] if channel and channel.endswith(("_x","_y","trigger")) else criteria["digital_threshold"]


def misfires(spec,signals,criteria):
    allowed={spec["channel"]}
    if spec["kind"]=="stick":
        side=spec["channel"].rsplit("_",1)[0]
        allowed|={side+"_x",side+"_y"}
    return {n:v for n,v in signals.items() if n not in allowed and abs(v)>=threshold(n,criteria)}


def score_case(suite,case,rows):
    spec=case.plan;criteria=suite.criteria
    hold=[r for r in rows if r["probe"]["phase"]=="hold" and r["probe"].get("phase_age_s",0)>=0]
    stable=hold[-125:]
    if len(stable)!=125:
        raise ValueError("ruling20 requires 125 complete hold steps")
    values=[target_value(spec,r["signals"],r["probe"]["events"]) for r in stable]
    bad={n:max(abs(r["signals"][n]) for r in stable) for n in stable[0]["signals"]
         if any(n in misfires(spec,r["signals"],criteria) for r in stable)}
    observe=[r for r in rows if r["probe"]["phase"]=="observe"]
    neutral=next((r for i,r in enumerate(observe) if all(abs(target_value(spec,x["signals"],x["probe"]["events"]))<=criteria["neutral_epsilon"] for x in observe[i:])),None)
    return_time=(neutral["step"]-observe[0]["step"])*.004 if neutral is not None else None
    internal=max(r["gamepad_internal_pairs"] for r in rows)
    reached=min(values)>=threshold(spec["channel"],criteria)
    centered=return_time is not None and return_time<=.5
    result={"case":case.case_id,"target_min":min(values),"target_max":max(values),
            "target_threshold":threshold(spec["channel"],criteria),"signal_passed":reached,
            "misfires":bad,"no_misfires":not bad,"return_time_after_withdraw_s":return_time,
            "return_passed":centered,"internal_pairs":internal,"hold_sim_seconds":len(hold)*.004,
            "termination":next((r["probe"]["termination"] for r in rows if r["probe"].get("termination")),None),
            "dpad_bottomed_noncritical":max(values)>=.9 if spec["kind"]=="dpad" else None}
    # Preserve historical scoring. Contact observability is an additional claim,
    # not a fabricated zero or a hidden change to the ruling20 pass expression.
    result["physics_passed"]=reached and not bad and centered and internal==0
    result["presentation_passed"]=None
    result["e2e_passed"]=None
    result["contact_observed"]=any(r.get("contacts") for r in rows) if all("contacts" in r for r in rows) else None
    result["joint_limit_excess"]={name:max(r.get("joint_limit_excess",{}).get(name,0) for r in rows)
                                  for name in {n for r in rows for n in r.get("joint_limit_excess",{})}}
    return result
