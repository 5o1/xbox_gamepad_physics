"""Single-writer latest-value mmap with a generation guard; never queues physics."""
import json
import mmap
from pathlib import Path
import struct


class Latest:
    def __init__(self, path, capacity, create=False):
        self.capacity = capacity
        path = Path(path)
        if create:
            with path.open("wb") as stream:
                stream.truncate(capacity+16)
        self.file = path.open("r+b")
        self.memory = mmap.mmap(self.file.fileno(), 0)

    def write(self, payload):
        if len(payload) > self.capacity:
            raise ValueError("latest-value capacity exceeded")
        generation = struct.unpack_from("<Q", self.memory, 0)[0]
        struct.pack_into("<Q", self.memory, 0, generation+1)
        self.memory[16:16+len(payload)] = payload
        struct.pack_into("<Q", self.memory, 8, len(payload))
        struct.pack_into("<Q", self.memory, 0, generation+2)

    def read(self):
        for _ in range(3):
            first, length = struct.unpack_from("<QQ", self.memory, 0)
            if not first or first % 2 or length > self.capacity:
                continue
            payload = self.memory[16:16+length]
            if first == struct.unpack_from("<Q", self.memory, 0)[0]:
                return first, payload
        return None

    def close(self):
        self.memory.close()
        self.file.close()


def packet(metadata, data=b""):
    header = json.dumps(metadata, separators=(",", ":")).encode()
    return struct.pack("!I", len(header))+header+data


def unpack(data):
    length = struct.unpack_from("!I", data)[0]
    return json.loads(data[4:4+length]), data[4+length:]


SNAPSHOT_CAPACITY = 1024*1024
FRAME_CAPACITY = 1280*720*3+65536
