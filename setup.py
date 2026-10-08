"""Compatibility shim for RoboTwin environments with pre-PEP-621 setuptools.

The canonical metadata remains in ``pyproject.toml``.  Some existing RoboTwin
Python 3.10 environments ship setuptools 59, which ignores ``[project]`` and
otherwise installs an ``UNKNOWN`` editable package.  Keep this small mirror
until the supported RoboTwin environment provides a modern build backend.
"""

from setuptools import find_packages, setup


setup(
    name="xbox-gamepad-physics",
    version="0.1.0",
    description="Evidence-bound Xbox One S physical asset and simulator adapters",
    python_requires=">=3.10",
    package_dir={"": "src"},
    packages=find_packages("src"),
    include_package_data=True,
    package_data={
        "xbox_gamepad_physics": [
            "resource_data/*",
            "resource_data/*/*",
            "resource_data/*/*/*",
            "resource_data/*/*/visual/*",
            "resource_data/*/*/visual/**/*",
            "resource_data/*/*/collision/*",
            "resource_data/*/*/collision/**/*",
        ]
    },
    extras_require={
        "mujoco": ["mujoco==3.15.0"],
        "robotwin": ["sapien==3.0.0b1"],
    },
    entry_points={
        "console_scripts": [
            "xbox-gamepad-physics=xbox_gamepad_physics.cli:main",
        ]
    },
)
