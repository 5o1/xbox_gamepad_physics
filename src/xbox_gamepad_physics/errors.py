"""Public exception hierarchy for the Xbox gamepad physics package."""


class XboxGamepadPhysicsError(Exception):
    """Base class for package errors that callers may handle explicitly."""


class StateValidationError(XboxGamepadPhysicsError, ValueError):
    """A gamepad state has the wrong shape, type, or numeric range."""


class ResourceError(XboxGamepadPhysicsError):
    """Base class for packaged-resource failures."""


class UnsafeResourcePathError(ResourceError, ValueError):
    """A resource request attempts to leave its backend/profile directory."""


class MissingResourceError(ResourceError, FileNotFoundError):
    """A simulator artifact or other required package resource is absent."""


class ResourceNotFoundError(MissingResourceError):
    """A requested packaged resource is absent."""


class ResourceFormatError(ResourceError, ValueError):
    """A packaged resource cannot be decoded as the requested format."""


class ProfileError(XboxGamepadPhysicsError):
    """Base class for backend profile failures."""


class ProfileManifestError(ProfileError, ValueError):
    """A backend profile manifest violates the public manifest contract."""


class PhysicsNotReadyError(ProfileError, RuntimeError):
    """A profile is intentionally blocked from use by a physics loader."""


class MissingBackendDependencyError(XboxGamepadPhysicsError, ImportError):
    """An optional simulator dependency required by a backend is unavailable."""


class AssetImportError(XboxGamepadPhysicsError, RuntimeError):
    """A ready backend artifact failed while entering a simulator scene."""
