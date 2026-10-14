"""Serial transport to a single Cycles worker. HTTP never selects commands/files."""
import base64
from collections import deque
import json
import math
import subprocess
import threading


class CyclesBridge:
    def __init__(self, command, *, env=None):
        self.process = subprocess.Popen(command, stdin=subprocess.PIPE, stdout=subprocess.PIPE,
                                        stderr=subprocess.STDOUT, text=True, bufsize=1, env=env)
        self.lock = threading.Lock()
        self.tail = deque(maxlen=12)

    def render(self, request):
        width, height = request['size']
        if not (isinstance(width, int) and isinstance(height, int) and 1 <= width <= 1600 and 1 <= height <= 1200):
            raise ValueError('render size must be within 1600 x 1200')
        camera, parts = request['camera'], request['parts']
        values = [*camera['position'], *camera['quaternion'], camera['fov']]
        if len(camera['position']) != 3 or len(camera['quaternion']) != 4 or not 1 < camera['fov'] < 179:
            raise ValueError('invalid camera')
        if len(parts) != 16 or any(len(matrix) != 16 for matrix in parts.values()):
            raise ValueError('expected 16 part matrices')
        values.extend(v for matrix in parts.values() for v in matrix)
        if not all(isinstance(v, (int, float)) and math.isfinite(v) for v in values):
            raise ValueError('non-finite pose')
        with self.lock:
            if self.process.poll() is not None:
                raise RuntimeError('Cycles worker stopped: ' + '\n'.join(self.tail))
            self.process.stdin.write(json.dumps(request) + '\n')
            self.process.stdin.flush()
            for line in self.process.stdout:
                if line.startswith('XGP_FRAME '):
                    return base64.b64decode(line[len('XGP_FRAME '):], validate=False)
                if line.startswith('XGP_ERROR '):
                    raise RuntimeError(line.strip())
                self.tail.append(line.strip())
            raise RuntimeError('Cycles worker closed: ' + '\n'.join(self.tail))

    def close(self):
        self.process.stdin.close()
        try:
            self.process.wait(timeout=10)
        except subprocess.TimeoutExpired:
            self.process.terminate()
