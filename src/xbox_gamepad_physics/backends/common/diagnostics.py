"""Readiness and findings data shared without scene traversal or engine imports."""
from __future__ import annotations
from dataclasses import asdict, dataclass, field
from typing import Mapping


@dataclass(frozen=True)
class Finding:
    code: str
    severity: str
    message: str
    context: Mapping[str, object] = field(default_factory=dict)

    def as_dict(self):
        return asdict(self)


@dataclass(frozen=True)
class Readiness:
    authoring: str = "not_run"
    load: str = "not_run"
    signal: str = "not_run"
    collision_cook: str = "not_run"
    contact: str = "not_run"
    appearance: str = "not_run"
    parallel: str = "not_run"
    evidence: Mapping[str, str] = field(default_factory=dict)

    def __post_init__(self):
        statuses = {"not_run", "passed", "failed", "partial", "unsupported"}
        for name in ("authoring", "load", "signal", "collision_cook", "contact", "appearance", "parallel"):
            if getattr(self, name) not in statuses:
                raise ValueError(f"invalid readiness status for {name}")


@dataclass(frozen=True)
class LoadedAssetRecord:
    asset_id: str
    backend: str
    profile: str
    configuration_id: str
    collision_requested: str
    collision_actual: str | None
    appearance_attached: bool
    readiness: Readiness = field(default_factory=Readiness)

    def legacy_record(self):
        return {"profile": self.profile, "collision": self.collision_requested,
                "attach_visual": self.appearance_attached}


def legacy_load_record(*, profile, collision, attach_visual):
    return LoadedAssetRecord("xbox_one_s", "robotwin", profile, "legacy-default",
                             collision, collision, attach_visual).legacy_record()
