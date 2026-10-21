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
    license="MIT",
    package_dir={"": "src"},
    packages=find_packages("src"),
    include_package_data=False,
    package_data={"xbox_gamepad_physics": ["_resource_lock.json", "build_data/*", "build_data/**/*", "build_data/**/**/*"],
                  "xbox_gamepad_physics.examples": ["templates/*"],
                  "xbox_gamepad_physics.web": ['static/ui/index.html', 'static/ui/*.mjs', 'static/ui/gamepad_overlay/*', 'static/ui/gamepad_overlay/demo/*', 'static/vendor/three/*', 'static/vendor/three/build/*', 'static/vendor/three/examples/jsm/controls/*', 'static/vendor/three/examples/jsm/loaders/*', 'static/vendor/three/examples/jsm/utils/*', 'static/*.json'],
                  "xbox_gamepad_physics.teleop": ["web/*", "templates/*", "windows_relay.ps1"]},
    extras_require={
        "build": ["numpy>=1.24", "trimesh>=4.4", "Pillow>=9", "manifold3d==3.5.4"],
        "teleop": ["aiohttp>=3.9", "PyYAML>=6", "numpy>=1.24", "Pillow>=9", "transforms3d>=0.4", "opencv-python>=4.8", "trimesh>=4.4", "manifold3d==3.5.4"],
        "maintainer": ["coacd==1.0.14"],
        "robotwin": ["sapien==3.0.3"],
        "mujoco": ["mujoco==3.16.0+concon.sdf3689.2"],
        "isaac": [],
        "example": ["PyYAML>=6", "numpy>=1.24", "Pillow>=9", "transforms3d>=0.4"],
    },
    entry_points={
        "console_scripts": [
            "xbox-gamepad-physics=xbox_gamepad_physics.cli:main",
        ]
    },
)
