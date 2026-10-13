"""Checkout-only input readers. All collision coordinates are global metres."""
from pathlib import Path
import numpy as np
import trimesh


def load_hulls(path):
    """Read OBJ o hull_N records without reordering faces or vertices."""
    vertices, objects, faces, name = [], [], [], None
    for line in Path(path).read_text().splitlines():
        fields = line.split()
        if not fields:
            continue
        if fields[0] == 'v':
            vertices.append([float(v) for v in fields[1:4]])
        elif fields[0] == 'o':
            if faces:
                objects.append((name, faces))
            name, faces = fields[1], []
        elif fields[0] == 'f':
            ids = [int(x.split('/')[0]) for x in fields[1:]]
            ids = [x - 1 if x > 0 else len(vertices) + x for x in ids]
            for k in range(1, len(ids) - 1):
                faces.append([ids[0], ids[k], ids[k + 1]])
    if faces:
        objects.append((name, faces))
    result = []
    vertices = np.asarray(vertices)
    for name, faces in objects:
        faces = np.asarray(faces)
        ids = np.unique(faces)
        result.append((name, trimesh.Trimesh(vertices[ids], np.searchsorted(ids, faces), process=False)))
    if not result:
        raise ValueError(f'No hulls in {path}')
    return result
