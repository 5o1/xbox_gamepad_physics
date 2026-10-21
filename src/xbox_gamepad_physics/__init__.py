"""Xbox One S physical assets: three integration steps.

1. Install the Release wheel with [build,robotwin], import the input zip with
   `xbox-gamepad-physics build-resources --archive INPUT.zip --offline`, and set
   XBOX_GAMEPAD_PHYSICS_RESOURCES to the prepared directory.
2. Import load_into_scene from xbox_gamepad_physics.robotwin and load into your
   existing scene with your pose and fixed_root choice. Do not load raw URDF or
   meshes: they omit appearance materials, SDF setup and signal mapping.
3. Read gamepad_state() / set_gamepad_targets() by channel name and step your
   scene. Use a static box for SDF support, not add_ground.

Run `xbox-gamepad-physics guide` for integration and rendering options,
`example export DIRECTORY` for runnable examples.
"""

from .controller import (
    AxisSignalMapping,
    GamepadSignalController,
    PhysicalEventMapping,
    RadialSourceGroup,
    RadialSignalGroup,
    ScalarSignalMapping,
    SplitSignalMapping,
)
from .errors import (
    AssetImportError,
    MissingBackendDependencyError,
    MissingResourceError,
    ProfileError,
    ProfileManifestError,
    ResourceError,
    ResourceFormatError,
    ResourceNotFoundError,
    StateValidationError,
    UnsafeResourcePathError,
    XboxGamepadPhysicsError,
)
from .profiles import BackendProfile, load_profile
from .motion import MotionContract, MotionJoint, load_motion_contract
from .resources import load_json_resource, resource_path, resource_root, prepare_resources, query_resource_path
from .state import (
    AXIS_COUNT,
    AXIS_NAMES,
    BUTTON_COUNT,
    BUTTON_NAMES,
    CHANNEL_COUNT,
    CHANNEL_NAMES,
    GAMEPAD_LAYOUT,
    TENSOR_LAYOUT_ID,
    W3C_STANDARD_TO_CANONICAL,
    XBOX_ONE_S_CHANNELS,
    GamepadChannel,
    GamepadDeviceId,
    GamepadState,
)

__all__ = [
    "AXIS_COUNT",
    "AXIS_NAMES",
    "AxisSignalMapping",
    "AssetImportError",
    "BUTTON_COUNT",
    "BUTTON_NAMES",
    "BackendProfile",
    "CHANNEL_COUNT",
    "CHANNEL_NAMES",
    "GAMEPAD_LAYOUT",
    "TENSOR_LAYOUT_ID",
    "W3C_STANDARD_TO_CANONICAL",
    "XBOX_ONE_S_CHANNELS",
    "GamepadChannel",
    "GamepadDeviceId",
    "GamepadSignalController",
    "GamepadState",
    "MissingBackendDependencyError",
    "MissingResourceError",
    "MotionContract",
    "MotionJoint",
    "PhysicalEventMapping",
    "ProfileError",
    "ProfileManifestError",
    "ResourceError",
    "ResourceFormatError",
    "ResourceNotFoundError",
    "RadialSourceGroup",
    "RadialSignalGroup",
    "ScalarSignalMapping",
    "SplitSignalMapping",
    "StateValidationError",
    "UnsafeResourcePathError",
    "XboxGamepadPhysicsError",
    "load_json_resource",
    "load_motion_contract",
    "load_profile",
    "resource_path",
    "resource_root",
    "prepare_resources",
    "query_resource_path",
]
