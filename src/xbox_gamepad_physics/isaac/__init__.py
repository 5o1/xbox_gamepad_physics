"""Native Isaac adapter. AppLauncher and simulation lifetime belong to the caller."""
from .builder import UsdArtifact, build_usd

__all__ = ['UsdArtifact', 'build_usd', 'make_articulation_cfg', 'bind_articulation', 'bind_batched_articulation', 'IsaacBatchedGamepadHandle', 'step']


def __getattr__(name):
    if name == 'step':
        from .stepping import step
        return step
    if name in {'make_articulation_cfg', 'bind_articulation'}:
        from . import articulation
        return getattr(articulation, name)
    if name in {'bind_batched_articulation', 'IsaacBatchedGamepadHandle'}:
        from . import batch
        return getattr(batch, name)
    raise AttributeError(name)
