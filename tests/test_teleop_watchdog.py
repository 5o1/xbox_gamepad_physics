"""Timeout validation, exact SSH budget and reconnect rules under a fake clock."""
import os
from pathlib import Path
import tempfile
import unittest
from unittest.mock import patch
from teleop.site import IdleWatchdog,settings,tunnel_keepalive,validate_tunnel_timeout,tunnel_timeout_argument


class WatchdogTest(unittest.TestCase):
    def test_defaults_boundaries_and_invalid_values(self):
        with patch.dict(os.environ,{},clear=True):
            self.assertEqual(settings('/tmp/nonexistent-teleop-watchdog')['TELEOP_TUNNEL_TIMEOUT_S'],'60')
        for value in (10,60,300):self.assertEqual(validate_tunnel_timeout(str(value)),value)
        for value in (9,301,0,'invalid',60.5):
            with self.assertRaisesRegex(ValueError,'10–300'):validate_tunnel_timeout(value)
        import argparse
        for value in ('9','301'):
            with self.assertRaisesRegex(argparse.ArgumentTypeError,'10–300'):tunnel_timeout_argument(value)
        with tempfile.TemporaryDirectory() as d:
            path=Path(d)/'site.env';path.write_text('TELEOP_TUNNEL_TIMEOUT_S=301\n')
            with patch.dict(os.environ,{},clear=True),self.assertRaisesRegex(ValueError,'10–300'):settings(path)

    def test_keepalive_product_for_entire_supported_range(self):
        for timeout in range(10,301):
            interval,count=tunnel_keepalive(timeout)
            self.assertEqual(interval*count,timeout)
            self.assertIn(count,(1,2,3))

    def test_no_connection_expires_from_session_start(self):
        now=[100.];watch=IdleWatchdog(10,lambda:now[0])
        now[0]=109.999;self.assertFalse(watch.expired())
        now[0]=110.;self.assertTrue(watch.expired())

    def test_messages_keep_alive_and_disconnect_reconnect_reset_same_window(self):
        now=[0.];watch=IdleWatchdog(10,lambda:now[0])
        for stamp in (8.,16.,24.):
            now[0]=stamp;watch.activity();self.assertFalse(watch.expired())
        now[0]=25.;watch.activity('control-disconnect')
        now[0]=34.999;self.assertFalse(watch.expired())
        # A reconnect itself is deliberately not an activity; its first message is.
        watch.activity();now[0]=44.;self.assertFalse(watch.expired())
        now[0]=44.999;self.assertTrue(watch.expired())
