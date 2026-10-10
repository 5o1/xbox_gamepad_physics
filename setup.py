"""Compatibility shim for RoboTwin environments with pre-PEP-621 setuptools.

The canonical metadata remains in ``pyproject.toml``.  Some existing RoboTwin
Python 3.10 environments ship setuptools 59, which ignores ``[project]`` and
otherwise installs an ``UNKNOWN`` editable package.  Keep this small mirror
until the supported RoboTwin environment provides a modern build backend.
"""

import re
from pathlib import Path

from setuptools import find_packages, setup


# pyproject.toml is the single source of the version; setuptools 59 cannot read it itself.
_PYPROJECT = (Path(__file__).resolve().parent / "pyproject.toml").read_text(encoding="utf-8")
_VERSION = re.search(r'^version\s*=\s*"([^"]+)"', _PYPROJECT, re.M).group(1)


setup(
    name="xbox-gamepad-physics",
    version=_VERSION,
    description="Evidence-bound Xbox One S physical asset and simulator adapters",
    python_requires=">=3.10",
    package_dir={"": "src"},
    packages=find_packages("src"),
    include_package_data=False,
    package_data={"xbox_gamepad_physics": ["_resource_lock.json"]},
    extras_require={
        "build": ["numpy>=1.24", "trimesh>=4.4", "Pillow>=9"],
        "mujoco": ["mujoco==3.15.0", "typing_extensions>=4.16"],
        "robotwin": ["sapien==3.0.0b1"],
    },
    entry_points={
        "console_scripts": [
            "xbox-gamepad-physics=xbox_gamepad_physics.cli:main",
        ]
    },
)
