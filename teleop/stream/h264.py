"""Annex-B NVENC access-unit framing (AUD enabled, no reordered frames)."""
import re

START = re.compile(b"\x00\x00(?:\x00)?\x01")
AUD = re.compile(b"\x00\x00(?:\x00)?\x01\x09")


class AccessUnits:
    def __init__(self):
        self.pending = b""

    def feed(self, data):
        self.pending += data
        units = []
        markers = list(AUD.finditer(self.pending))
        while len(markers) >= 2:
            end = markers[1].start()
            units.append(self.pending[:end])
            self.pending = self.pending[end:]
            markers = list(AUD.finditer(self.pending))
        return units


def info(data):
    key = False
    codec = None
    for marker in START.finditer(data):
        i = marker.end()
        kind = data[i] & 31
        if kind == 5:
            key = True
        if kind == 7:
            codec = "avc1."+data[i+1:i+4].hex().upper()
    return key, codec
