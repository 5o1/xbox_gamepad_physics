"""Select a GPU by its ordinal in the caller's CUDA-visible device list."""
import os


def gpu_environment(index, environ=None):
    """Return a child environment exposing only the selected device.

    With no CUDA_VISIBLE_DEVICES, index is the physical ordinal. Otherwise it
    selects an entry in the caller's mask, preserving GPU UUID/MIG identifiers.
    Children see that device as ordinal 0. An empty/exhausted mask is an error.
    This resolves identifiers without initializing CUDA in the parent process.
    """
    if type(index) is not int or index < 0:
        raise ValueError('--gpu must be a nonnegative integer index into the caller-visible devices')
    env = dict(os.environ if environ is None else environ)
    mask = env.get('CUDA_VISIBLE_DEVICES')
    if mask is None:
        device = str(index)
    else:
        devices = []
        for item in mask.split(','):
            item = item.strip()
            if not item or item == '-1':
                break
            devices.append(item)
        if index >= len(devices):
            raise ValueError(f'--gpu {index} is outside the CUDA_VISIBLE_DEVICES range ({len(devices)} devices)')
        device = devices[index]
    env['CUDA_VISIBLE_DEVICES'] = device
    return env
