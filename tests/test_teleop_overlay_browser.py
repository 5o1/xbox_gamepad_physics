"""K11 exercises real SVG output through both canonical input boundaries."""
from pathlib import Path
import tempfile
import unittest
import importlib.util
from teleop.overlay_validate import validate
from teleop.site import settings


class OverlayBrowserTest(unittest.IsolatedAsyncioTestCase):
    @unittest.skipUnless(importlib.util.find_spec('playwright'), '浏览器验收需要Playwright；系统Chrome端到端测试在本机运行')
    @unittest.skipUnless(settings().get('TELEOP_BROWSER'), '浏览器验收需要本地配置 TELEOP_BROWSER（configs/local/teleop_site.env）')
    async def test_all_core_channels_in_dashboard_and_teleop(self):
        with tempfile.TemporaryDirectory() as directory:
            result = await validate(Path(directory))
        self.assertEqual(len(result["cases"]), 50)
        self.assertTrue(result["passed"], [c for c in result["cases"] if not c["passed"]])
        self.assertEqual({b["mode"] for b in result["boundaries"]}, {"dashboard", "teleop"})
        self.assertTrue(all(b["all_inputs_canonical_32"] for b in result["boundaries"]))


if __name__ == "__main__":
    unittest.main()
