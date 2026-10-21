"""Explicit engine-free backend declarations; no plugin or platform discovery."""
from __future__ import annotations

from dataclasses import dataclass
from typing import Literal

from ..errors import ResourceError


@dataclass(frozen=True)
class UsageSpec:
    loader_entrypoint: str
    example: str
    guide_command: str = "xbox-gamepad-physics guide"
    example_export_command: str = "xbox-gamepad-physics example export ./gamepad_example"
    warning: str = "Use the public loader to retain appearance, collision and signals."
    backend_notes: tuple[str, ...] = ()

    def manifest(self) -> dict:
        return {"warning": self.warning, "entrypoint": self.loader_entrypoint,
                "example": self.example, "guide": self.guide_command,
                "example_export": self.example_export_command}


@dataclass(frozen=True)
class BackendSpec:
    name: str
    profiles: tuple[str, ...]
    node_names: tuple[str, ...]
    loader_entrypoint: str
    builder_entrypoint: str
    usage: UsageSpec
    capabilities: frozenset[str] = frozenset()
    builder_runtime: Literal["python", "isaac_app"] = "python"

    def require_builder_runtime(self, runtime: str = "python") -> None:
        if runtime not in {"python", "isaac_app"}:
            raise ResourceError(f"unknown builder runtime {runtime!r}")
        if self.builder_runtime == "isaac_app" and runtime != "isaac_app":
            raise ResourceError(
                f"{self.name} builder requires runtime={self.builder_runtime!r}; "
                "start Isaac Sim through the caller's AppLauncher first and invoke "
                "the builder inside that platform process. Automatic startup is disabled."
            )


_WARNING = ("These are internal build artifacts. Direct mesh or URDF loading loses "
            "appearance materials, SDF configuration and signal mapping.")
_EXAMPLE = """import sapien
from xbox_gamepad_physics.robotwin import load_into_scene
pad = load_into_scene(scene, sapien.Pose([0, 0, 0.4]), fixed_root=True)
state = pad.gamepad_state()  # Adapt signals by channel name.
"""
ROBOTWIN = BackendSpec(
    "robotwin", ("left_stick", "full_controls"),
    ("robotwin_left_stick", "robotwin_full_controls"),
    "xbox_gamepad_physics.robotwin.load_into_scene",
    "xbox_gamepad_physics.builders.build_resources.build",
    UsageSpec("xbox_gamepad_physics.robotwin.load_into_scene", _EXAMPLE, warning=_WARNING),
    frozenset({"named_joints", "signals", "birth_fixed_free", "runtime_root_switch_cpu"}),
)
MUJOCO_RELEASE_GUIDANCE = 'The [mujoco] extra downloads Python 3.10/3.11 Linux x86_64 wheels from the owner-maintained https://github.com/5o1/mujoco/releases/tag/v3.16.0-concon.sdf3689.2 fork Release. It uses upstream PR #3689 to correct MuJoCo 3.16.0 mesh SDF sign errors before that patch is merged upstream. The selected distribution is 3.16.0+concon.sdf3689.2; official 3.16.0 is not the adopted build.'

MUJOCO = BackendSpec("mujoco", ("full_controls",), ("mujoco_full_controls",),
                     "xbox_gamepad_physics.mujoco.bind", "xbox_gamepad_physics.mujoco.builder.build",
                     UsageSpec("xbox_gamepad_physics.mujoco.bind",
                               "from xbox_gamepad_physics.mujoco import load_standalone\n"
                               "scene = load_standalone(fixed_root=True)\n"
                               "pad = scene.gamepad\n",
                               guide_command="xbox-gamepad-physics guide --backend mujoco",
                               example_export_command="See examples/mujoco/README.md in the source checkout.",
                               backend_notes=("Caller compiles make_spec/attach_to_spec, then binds by name.",
                                              "Fixed/free root choice is structural before compilation.",
                                              MUJOCO_RELEASE_GUIDANCE)),
                     capabilities=frozenset({"named_joints", "signals", "birth_fixed_free", "target_drive"}))
ISAAC = BackendSpec("isaac", ("full_controls",), ("isaac_full_controls",),
                    "xbox_gamepad_physics.isaac.bind_articulation", "xbox_gamepad_physics.isaac.builder.build_usd",
                    UsageSpec("xbox_gamepad_physics.isaac.bind_articulation", ""),
                    builder_runtime="isaac_app")
BACKENDS = {item.name: item for item in (ROBOTWIN, MUJOCO, ISAAC)}


def backend_spec(name: str) -> BackendSpec:
    try:
        return BACKENDS[name]
    except KeyError as error:
        raise ResourceError(f"unknown backend {name!r}; known={tuple(BACKENDS)}") from error


def selected_nodes(graph, targets: tuple[str, ...]):
    """Select target nodes and their complete upstream closure, in graph order."""
    table = {node.name: node for node in graph}
    selected = set()
    def include(name):
        if name not in table:
            raise ResourceError(f"unknown resource target {name!r}")
        if name in selected:
            return
        selected.add(name)
        for upstream in table[name].upstream:
            include(upstream)
    for name in targets:
        include(name)
    return tuple(node for node in graph if node.name in selected)
