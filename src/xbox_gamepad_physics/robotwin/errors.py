"""Errors raised by the RoboTwin/SAPIEN integration."""

from xbox_gamepad_physics.errors import XboxGamepadPhysicsError
from xbox_gamepad_physics.errors import ProfileManifestError


class RoboTwinIntegrationError(XboxGamepadPhysicsError):
    """Base class for errors at the RoboTwin integration boundary."""


class RoboTwinManifestError(ProfileManifestError, RoboTwinIntegrationError):
    """The ready profile is missing backend-specific required data."""


class SceneCompatibilityError(RoboTwinIntegrationError):
    """The supplied object does not expose a compatible SAPIEN scene."""


class ArticulationLoadError(RoboTwinIntegrationError):
    """SAPIEN could not produce exactly one gamepad articulation."""


class JointConfigurationError(RoboTwinIntegrationError):
    """The loaded articulation and declared joint configuration disagree."""


class NativeInstallError(RoboTwinIntegrationError):
    """A requested native RoboTwin asset copy is unsafe or incomplete."""
