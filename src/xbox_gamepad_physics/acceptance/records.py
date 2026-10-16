"""Incremental evidence records that retain actual denominators and nulls."""
from __future__ import annotations
from dataclasses import dataclass
import json
from pathlib import Path


@dataclass(frozen=True)
class ContactObservation:
    env_id: int
    body_id: str
    other_id: str
    time_s: float
    frame: str
    link: str | None = None
    point_m: tuple | None = None
    impulse_ns: tuple | None = None
    force_n: tuple | None = None
    separation_m: float | None = None
    aggregation_window_s: float | None = None
    missing_reason: str | None = None


class ResultSink:
    def __init__(self,path):
        self.path=Path(path)
        self.path.parent.mkdir(parents=True,exist_ok=True)
        self.file=self.path.open("w",encoding="utf-8")

    def write(self,row):
        self.file.write(json.dumps(row)+"\n")
        self.file.flush()

    def close(self):
        self.file.close()


def summarize(results,*,planned=26):
    allowed={"passed","failed","not_run","execution_error","unsupported"}
    counts={key:0 for key in allowed}
    for row in results:
        if row["status"] not in allowed:raise ValueError("unknown case status")
        counts[row["status"]]+=1
    return {"planned":planned,"attempted":sum(counts[k] for k in ("passed","failed","execution_error")),
            "completed":counts["passed"]+counts["failed"],"counts":counts}


def combine_presentation(physical,presentation):
    return {**physical,"presentation_passed":presentation.get("passed"),
            "e2e_passed":(bool(physical["physics_passed"] and physical.get("contact_observed") and presentation["passed"])
                          if presentation.get("passed") is not None else None)}
