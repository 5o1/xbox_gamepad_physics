"""Compatibility wrapper for the packaged maintainer_coacd builder."""
from pathlib import Path
import sys
sys.path.insert(0,str(Path(__file__).resolve().parents[1]/"src"))
from xbox_gamepad_physics.builders.maintainer_coacd import *
from xbox_gamepad_physics.builders.maintainer_coacd import main
if __name__=="__main__":main()
