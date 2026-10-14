"""Use the same optional gateway interpreter as the six shutdown process tests."""
import importlib.util
import os
from pathlib import Path
import shutil
import subprocess
import sys
import unittest


@unittest.skipUnless((os.environ.get('XBOX_TELEOP_TEST_PYTHON') or importlib.util.find_spec('aiohttp'))
                     and shutil.which('ffmpeg'), 'gateway video process tests need aiohttp and FFmpeg')
class GatewaySlowClientsTest(unittest.TestCase):
    def test_real_gateway_slow_client_and_cancellation_contract(self):
        python=os.environ.get('XBOX_TELEOP_TEST_PYTHON',sys.executable)
        result=subprocess.run([python,str(Path(__file__).with_name('_teleop_gateway_slow.py'))],
                              capture_output=True,text=True,timeout=45)
        self.assertEqual(result.returncode,0,result.stdout+result.stderr)
