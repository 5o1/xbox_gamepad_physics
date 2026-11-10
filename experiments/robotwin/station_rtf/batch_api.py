"""Call an existing public PhysX scene API through a version-pinned adapter."""
import ctypes


def scene_batch(articulation, library, value=0):
    adapter = ctypes.CDLL(str(library))
    call = adapter.station_rtf_batch
    call.argtypes = [ctypes.c_size_t, ctypes.c_uint32]
    call.restype = ctypes.c_uint32
    return int(call(articulation.get_links()[0]._physx_pointer, value))
