"""Load records and findings data shared without scene traversal or engine imports."""
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
class LoadedAssetRecord:
    asset_id: str
    backend: str
    profile: str
    configuration_id: str
    collision_requested: str
    collision_actual: str | None
    appearance_attached: bool

    def legacy_record(self):
        return {"profile": self.profile, "collision": self.collision_requested,
                "attach_visual": self.appearance_attached}


def legacy_load_record(*, profile, collision, attach_visual):
    return LoadedAssetRecord("xbox_one_s", "robotwin", profile, "legacy-default",
                             collision, collision, attach_visual).legacy_record()
