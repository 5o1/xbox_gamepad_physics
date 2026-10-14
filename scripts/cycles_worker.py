from pathlib import Path
import sys
sys.path.insert(0,str(Path(__file__).resolve().parents[1]/"src"))
import runpy
runpy.run_module("xbox_gamepad_physics.web.cycles_worker", run_name="__main__")
