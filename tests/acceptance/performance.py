"""Comparable performance scene fields without unmeasured throughput targets."""
from dataclasses import dataclass


@dataclass(frozen=True)
class PerformanceScene:
    num_envs: int
    dt_s: float
    solver: str
    seed: int
    warmup_steps: int | None = None
    measurement_steps: int | None = None
    rendering: bool = False

    def __post_init__(self):
        if self.num_envs not in (1,64,1024):
            raise ValueError("declared comparison sizes are 1, 64 and 1024")


@dataclass(frozen=True)
class PerformanceResult:
    status: str
    completed_steps: int
    reset_seconds: float | None = None
    step_seconds: float | None = None
    cook_seconds: float | None = None
    gpu_total_used_bytes: int | None = None
    torch_allocated_bytes: int | None = None
    external_load: object = None
    missing_reason: str | None = None
