"""Versioned ruling20 data; no backend cooking or contact-point reselection."""
from __future__ import annotations
from dataclasses import dataclass
import json
from pathlib import Path
from typing import Mapping
from ..backends.common.model import Pose
from ..backends.common.transforms import point, inverse, rotate


@dataclass(frozen=True)
class PressCase:
    case_id: str
    plan: Mapping[str, object]
    root_pose: Pose
    source_paths: Mapping[str, str]
    timeline: tuple[Mapping[str, object], ...]
    baseline: Mapping[str, object]
    joint_limits: Mapping[str, object]

    def in_root_frame(self):
        transform = inverse(self.root_pose)
        return {**self.plan, **{name:point(transform,self.plan[name]) for name in ("point_m","start_m","pivot_m")},
                "direction":rotate(transform.orientation_wxyz,self.plan["direction"])}

    def at_pose(self, root_pose: Pose):
        if root_pose == self.root_pose:
            return dict(self.plan)
        local = self.in_root_frame()
        return {**local, **{name:point(root_pose,local[name]) for name in ("point_m","start_m","pivot_m")},
                "direction":rotate(root_pose.orientation_wxyz,local["direction"])}

    def replay_steps(self):
        """Replay exact recorded step/phase clocks, including the transition row."""
        for segment in self.timeline:
            for step in range(segment["first_step"],segment["last_step"]+1):
                yield {"step":step,"phase":segment["phase"],
                       "phase_age_s":(step-segment["phase_origin_step"])*.004}


@dataclass(frozen=True)
class PressSuite:
    suite_id: str
    cases: tuple[PressCase, ...]
    settings: Mapping[str, float]
    press_stop: Mapping[str, float]
    fixture: Mapping[str, object]
    criteria: Mapping[str, object]
    evidence: Mapping[str, object]

    def case(self, case_id):
        for case in self.cases:
            if case.case_id == case_id:
                return case
        raise KeyError(case_id)


def load_suite(path: Path | None = None) -> PressSuite:
    path=Path(path) if path is not None else Path(__file__).resolve().parents[1]/"build_data/acceptance/ruling20_sdf303_v1.json"
    value=json.loads(path.read_text())
    if value["suite_id"] != "ruling20_sdf303_v1":
        raise ValueError("unsupported press suite revision")
    cases=tuple(PressCase(v["case_id"],v["plan"],Pose(tuple(v["root_pose"][:3]),tuple(v["root_pose"][3:])),
                          v["source_paths"],tuple(v["timeline"]),v["baseline"],v["joint_limits"]) for v in value["cases"])
    if len(cases)!=26 or len({c.case_id for c in cases})!=26:
        raise ValueError("ruling20 must contain exactly 26 distinct cases")
    return PressSuite(value["suite_id"],cases,value["settings"],value["press_stop"],value["fixture"],value["criteria"],value["evidence"])
