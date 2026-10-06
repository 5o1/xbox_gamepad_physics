import io
import sys
import unittest
from pathlib import Path
from unittest.mock import patch

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / 'scripts'))
from serve_viewer import Handler


class ViewerLoggingTest(unittest.TestCase):
    def test_response_survives_lost_logging_pipe(self):
        for error in (BrokenPipeError(), ValueError('closed stream')):
            with self.subTest(error=type(error).__name__):
                handler = object.__new__(Handler)
                handler.client_address = ('127.0.0.1', 1)
                handler.requestline = 'GET / HTTP/1.1'
                handler.request_version = 'HTTP/1.1'
                handler.command = 'GET'
                handler.wfile = io.BytesIO()
                with patch('sys.stderr') as stderr:
                    stderr.write.side_effect = error
                    handler.send_response(200)
                    handler.end_headers()
                self.assertTrue(handler.wfile.getvalue().startswith(b'HTTP/1.0 200'))


if __name__ == '__main__':
    unittest.main()
