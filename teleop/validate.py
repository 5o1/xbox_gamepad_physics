"""Compatibility entry for tests.acceptance.robotwin.validation."""
import importlib
import runpy
import sys
if __name__ == "__main__":
    runpy.run_module("tests.acceptance.robotwin.validation", run_name="__main__")
else:
    sys.modules[__name__] = importlib.import_module("tests.acceptance.robotwin.validation")
