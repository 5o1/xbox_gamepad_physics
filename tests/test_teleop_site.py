"""Private site configuration and missing-setting diagnostics."""
import os
from pathlib import Path
import subprocess
import tempfile
import unittest
from unittest.mock import patch
from teleop.site import settings, require, ROOT


class SiteTest(unittest.TestCase):
    def test_shell_python_agree_and_environment_override(self):
        with tempfile.TemporaryDirectory() as directory:
            path=Path(directory)/'site.env'
            path.write_text("TELEOP_GPU_HOST='example-host' # comment\nTELEOP_SSH_PORT='1234'\n")
            with patch.dict(os.environ, {'TELEOP_SITE_CONFIG':str(path),'TELEOP_GPU_HOST':'override-host'}):
                self.assertEqual(settings()['TELEOP_GPU_HOST'],'override-host')
                output=subprocess.check_output(['bash','-c','eval "$(python3 -m teleop.site --shell)"; printf "%s %s" "$TELEOP_GPU_HOST" "$TELEOP_SSH_PORT"'],cwd=ROOT,text=True)
                self.assertEqual(output,'override-host 1234')

    def test_missing_config_names_template(self):
        with patch.dict(os.environ, {'TELEOP_SITE_CONFIG':'/tmp/missing-teleop-site'},clear=True):
            with self.assertRaisesRegex(ValueError,'teleop_site.example.env'):
                require('TELEOP_GPU_HOST')

    def test_local_file_is_ignored(self):
        if not (ROOT / '.git').exists():
            self.skipTest('运行镜像不含Git元数据；ignore规则在本地checkout验证')
        self.assertEqual(subprocess.call(['git','check-ignore','-q','configs/local/teleop_site.env'],cwd=ROOT),0)
