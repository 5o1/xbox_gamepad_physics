"""Linux abstract Unix datagram endpoint, independent of run path length."""
from pathlib import Path


def command_address(run):
    # Both processes share this unique existing run directory. An abstract
    # endpoint creates no socket file, and disappears when its owner closes.
    stat=Path(run).stat()
    return f'\0xbox-teleop-{stat.st_dev:x}-{stat.st_ino:x}'
