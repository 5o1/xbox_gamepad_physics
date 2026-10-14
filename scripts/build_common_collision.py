"""Compatibility wrapper for the packaged common_collision builder."""
from pathlib import Path
import sys
sys.path.insert(0,str(Path(__file__).resolve().parents[1]/"src"))
from xbox_gamepad_physics.builders.common_collision import *
from xbox_gamepad_physics.builders.common_collision import main
if __name__=="__main__":main()
