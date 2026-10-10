"""Build the closed per-component collision mesh base for the Xbox One S.

Every component (main shell, front plate and each control) is written as one
or more closed, manifold, outward-facing shells in simulation metres. The mesh
base is the input to collision generation; it does not reproduce visual-only
detail.

The output is a frozen, reviewed snapshot: the face selections below belong to
one specific source mesh, and the script refuses other sources instead of
guessing. Later source changes do not require regenerating it.
"""

from __future__ import annotations

import argparse
import json
from pathlib import Path

import numpy as np
import trimesh


ROOT = Path(__file__).resolve().parents[1]
VISUAL_REL = "src/xbox_gamepad_physics/resource_data/common/xbox_one_s/visual"
GENERATOR_REL = "scripts/build_collision_meshbase.py"
DEFAULT_OUTPUT = ROOT / "assets/xbox_one_s/collision_meshbase"

PART_BY_CONTROL = {
    "a": "00_A_Button_VISUAL_UNCALIBRATED",
    "b": "01_B_Button_VISUAL_UNCALIBRATED",
    "left_shoulder": "02_Bumper_L_VISUAL_UNCALIBRATED",
    "right_shoulder": "03_Bumper_R_VISUAL_UNCALIBRATED",
    "pair": "04_Connect_Button_VISUAL_UNCALIBRATED",
    "shell": "05_Controller_Body_VISUAL_UNCALIBRATED",
    "dpad": "06_D-Pad_VISUAL_UNCALIBRATED",
    "view": "07_Menu_L_VISUAL_UNCALIBRATED",
    "menu": "08_Menu_R_VISUAL_UNCALIBRATED",
    "left_stick": "09_Stick_L_VISUAL_UNCALIBRATED",
    "right_stick": "10_Stick_R_VISUAL_UNCALIBRATED",
    "left_trigger": "11_Trigger_L_VISUAL_UNCALIBRATED",
    "right_trigger": "12_Trigger_R_VISUAL_UNCALIBRATED",
    "x": "13_X_Button_VISUAL_UNCALIBRATED",
    "guide": "14_XboxButton_VISUAL_UNCALIBRATED",
    "y": "15_Y_Button_VISUAL_UNCALIBRATED",
}

# Reviewed source-face sets (indices into the vertex-merged body mesh).
FOLD_FACES = [4056, 4054, 4055, 4057, 4058, 4059, 4060, 4061, 4062, 4063, 4064, 4065, 4067,
              4106, 4107, 4108, 4100, 4101, 3808, 3809, 745, 744, 581, 354, 375, 374, 396,
              1519, 1518]
LOWER_INTERFACE_FACES = [2226, 2227, 2232, 2233, 2242, 2243, 2244, 2245, 2248, 2249, 2206,
                         2207, 2210, 2211, 2214, 2215, 2216, 2217, 2218, 2219, 2177, 2166,
                         2167, 2168, 2169, 2176, 4146, 4147]
USB_FACES = [2352, 2364, 2363, 2362, 2355, 2354, 2353, 2377, 2366, 2376, 2371, 2370, 2369,
             2368, 2367, 2365]
PROCESS_DATE = "2026-10-10"
BODY_COMPONENT_FACES = [4068, 150, 68, 42, 10, 10]  # shell, front plate, 4 port liners
KEYCAP_FACES = 64
GLYPH_FACES = {"a": 68, "b": 112, "x": 34, "y": 28}
VISUAL_DISC_FACES = 14
STICK_SHELL_FACES = [288, 318]  # antislip ring, stick body

DESCRIPTIONS = {
    "shell": "keep independent main shell; approved fold/round-opening/lower-interface patches; "
             "drop lining/tongue pieces",
    "shell_front_plate": "keep independent front plate; USB fill and back cap; no bridges",
}
KEYCAP_DESCRIPTION = "keep keycap; drop glyph piece and zero/near-zero-thickness visual disc"
STICK_DESCRIPTION = "keep main stick body and antislip ring as two overlapping closed shells"
CONTROL_DESCRIPTION = "keep complete control; close hidden openings"

CHANGES = (
    "Converted static visual geometry to simulation-frame metres; retained closed shell and "
    "front plate separately; applied reviewed fold repairs and interface/round-hole caps; "
    "excluded ABXY glyphs and visual discs and body linings/tongues; closed hidden control "
    "openings; retained both overlapping stick shells. No voxel mesh reconstruction or "
    "cross-link union."
)


def _load_part(visual: Path, part: dict, scale: float) -> trimesh.Trimesh:
    """Read one glTF part directly; map (x, y, z) -> (x, -z, y) and scale to metres."""

    document = json.loads((visual / part["file"]).read_text())
    if document["nodes"] != [{"mesh": 0, "name": part["name"]}]:
        raise ValueError(f"unexpected scene transform in {part['file']}")
    primitive = document["meshes"][0]["primitives"][0]

    def accessor(index: int) -> np.ndarray:
        record = document["accessors"][index]
        view = document["bufferViews"][record["bufferView"]]
        data = (visual / document["buffers"][view["buffer"]]["uri"]).read_bytes()
        dtype = {5126: "<f4", 5123: "<u2", 5125: "<u4"}[record["componentType"]]
        width = {"SCALAR": 1, "VEC2": 2, "VEC3": 3}[record["type"]]
        offset = view.get("byteOffset", 0) + record.get("byteOffset", 0)
        values = np.frombuffer(data, dtype=dtype, count=record["count"] * width, offset=offset)
        return values.reshape(-1, width).astype(float)

    vertices = accessor(primitive["attributes"]["POSITION"])
    faces = accessor(primitive["indices"]).astype(np.int64).reshape(-1, 3)
    vertices = np.column_stack((vertices[:, 0], -vertices[:, 2], vertices[:, 1])) * scale
    return trimesh.Trimesh(vertices, faces, process=False)


def _components(mesh: trimesh.Trimesh) -> tuple[list[trimesh.Trimesh], list[np.ndarray]]:
    """Split into face-connected pieces after merging seam-duplicated vertices, largest first."""

    mesh = mesh.copy()
    mesh.merge_vertices(merge_tex=True, merge_norm=True)
    groups = trimesh.graph.connected_components(mesh.face_adjacency, nodes=np.arange(len(mesh.faces)))
    groups = sorted(groups, key=lambda group: -len(group))
    pieces = [mesh.submesh([group], append=True, repair=False) for group in groups]
    return pieces, groups


def _boundary_loops(mesh: trimesh.Trimesh) -> list[np.ndarray]:
    """Closed boundary loops, each following the mesh's own boundary half-edges."""

    edges = np.asarray(mesh.edges)
    _, inverse, counts = np.unique(np.sort(edges, axis=1), axis=0, return_inverse=True, return_counts=True)
    if np.any(counts > 2):
        raise ValueError("non-manifold source edge")
    boundary = edges[counts[inverse] == 1]
    following = {int(a): int(b) for a, b in boundary}
    if len(following) != len(boundary):
        raise ValueError("inconsistent boundary half-edges")
    loops = []
    while following:
        start = next(iter(following))
        loop = [start]
        current = following.pop(start)
        while current != start:
            loop.append(current)
            current = following.pop(current)
        loops.append(np.array(loop))
    return loops


def _cap_shell(shell: trimesh.Trimesh) -> tuple[trimesh.Trimesh, int]:
    """Close every boundary loop with a centroid fan; returns the mesh and the loop count."""

    vertices = shell.vertices.tolist()
    faces = shell.faces.tolist()
    loops = _boundary_loops(shell)
    for loop in loops:
        center = len(vertices)
        vertices.append(shell.vertices[loop].mean(0).tolist())
        # A boundary half-edge a -> b on the shell needs b -> a on the patch.
        faces.extend([[int(b), int(a), center] for a, b in zip(loop, np.roll(loop, -1))])
    closed = trimesh.Trimesh(vertices, faces, process=False)
    if not (closed.is_watertight and closed.is_winding_consistent):
        raise RuntimeError("capped shell is not closed and consistently wound")
    return closed, len(loops)


def _replace_faces(
    mesh: trimesh.Trimesh,
    source_faces: np.ndarray,
    selected: np.ndarray,
) -> tuple[trimesh.Trimesh, np.ndarray]:
    """Delete the selected faces and close each resulting hole with a centroid fan."""

    selected = np.array(sorted(selected), dtype=int)
    keep = np.ones(len(mesh.faces), bool)
    keep[selected] = False
    vertices = mesh.vertices.tolist()
    faces = mesh.faces[keep].tolist()
    sources = source_faces[keep].tolist()
    mask = ~keep
    adjacency = mesh.face_adjacency
    adjacency = adjacency[np.all(mask[adjacency], axis=1)]
    for group in trimesh.graph.connected_components(adjacency, nodes=selected):
        used = np.unique(mesh.faces[group])
        removed = trimesh.Trimesh(mesh.vertices[used], np.searchsorted(used, mesh.faces[group]), process=False)
        for ring in _boundary_loops(removed):
            loop = used[ring]
            center = len(vertices)
            vertices.append(mesh.vertices[loop].mean(0).tolist())
            patch = [[int(a), int(b), center] for a, b in zip(loop, np.roll(loop, -1))]
            faces.extend(patch)
            sources.extend([-1] * len(patch))
    return trimesh.Trimesh(vertices, faces, process=False), np.array(sources)


def _crossings(a: trimesh.Trimesh, b: trimesh.Trimesh) -> list[tuple[int, int]]:
    """Face pairs whose interiors strictly cross (shared-vertex neighbours are ignored)."""

    triangles_a, triangles_b = np.asarray(a.triangles), np.asarray(b.triangles)
    lower, upper = triangles_b.min(1), triangles_b.max(1)
    edge_index = np.array([[0, 1], [1, 2], [2, 0]])

    # Tolerances only absorb floating-point roundoff (metres / barycentric units).
    def hits(segments: np.ndarray, triangles: np.ndarray) -> tuple[np.ndarray, np.ndarray]:
        origin = segments[:, 0]
        direction = segments[:, 1] - origin
        e1 = triangles[:, 1] - triangles[:, 0]
        e2 = triangles[:, 2] - triangles[:, 0]
        p = np.cross(direction, e2)
        det = np.einsum("ij,ij->i", e1, p)
        good = np.abs(det) > 1e-18
        inv = np.zeros_like(det)
        inv[good] = 1 / det[good]
        offset = origin - triangles[:, 0]
        u = np.einsum("ij,ij->i", offset, p) * inv
        q = np.cross(offset, e1)
        v = np.einsum("ij,ij->i", direction, q) * inv
        t = np.einsum("ij,ij->i", e2, q) * inv
        good &= (u > 1e-8) & (v > 1e-8) & (u + v < 1 - 1e-8) & (t > 1e-8) & (t < 1 - 1e-8)
        return good, origin + t[:, None] * direction

    pairs = []
    for i, triangle in enumerate(triangles_a):
        near = np.all(upper >= triangle.min(0), axis=1) & np.all(lower <= triangle.max(0), axis=1)
        for j in np.flatnonzero(near):
            if a is b and (j <= i or set(a.faces[i]) & set(b.faces[j])):
                continue
            points = []
            for first, second in ((triangle, triangles_b[j]), (triangles_b[j], triangle)):
                ok, crossing = hits(first[edge_index], np.broadcast_to(second, (3, 3, 3)))
                points.extend(crossing[ok].tolist())
            if len(points) >= 2:
                spread = np.asarray(points)
                if np.linalg.norm(spread[:, None] - spread[None, :], axis=2).max() > 1e-9:
                    pairs.append((i, int(j)))
    return pairs


def _close_control(piece: trimesh.Trimesh) -> trimesh.Trimesh:
    """Close a control piece's hidden openings; each centroid fan must not cross any face."""

    vertices = np.asarray(piece.vertices).copy()
    faces = piece.faces.tolist()
    for loop in _boundary_loops(piece):
        ring = loop[::-1]
        existing = np.array(faces)
        center = len(vertices)
        candidate = np.vstack((vertices, vertices[ring].mean(0)))
        patch = [[int(a), int(b), center] for a, b in zip(ring, np.roll(ring, -1))]
        combined = trimesh.Trimesh(candidate, np.vstack((existing, patch)), process=False)
        if any(i >= len(existing) or j >= len(existing) for i, j in _crossings(combined, combined)):
            raise RuntimeError("closure fan crosses existing faces; needs a reviewed closure")
        vertices = candidate
        faces.extend(patch)
    closed = trimesh.Trimesh(vertices, faces, process=False)
    if closed.volume < 0:
        closed.invert()
    return closed


def _vertex_manifold(mesh: trimesh.Trimesh) -> bool:
    # On a closed 2-manifold the link of every vertex is a single cycle.
    links: list[list[tuple[int, int]]] = [[] for _ in mesh.vertices]
    for face in mesh.faces:
        for i in range(3):
            links[int(face[i])].append((int(face[(i + 1) % 3]), int(face[(i + 2) % 3])))
    for edges in links:
        if not edges:
            return False
        graph: dict[int, list[int]] = {}
        for a, b in edges:
            graph.setdefault(a, []).append(b)
            graph.setdefault(b, []).append(a)
        if any(len(neighbours) != 2 for neighbours in graph.values()):
            return False
        seen: set[int] = set()
        stack = [next(iter(graph))]
        while stack:
            node = stack.pop()
            if node not in seen:
                seen.add(node)
                stack.extend(graph[node])
        if len(seen) != len(graph):
            return False
    return True


def _require_closed(name: str, mesh: trimesh.Trimesh) -> None:
    """Fail the build unless every shell is closed, manifold, consistent and positive."""

    _, counts = np.unique(mesh.edges_sorted, axis=0, return_counts=True)
    shells = trimesh.graph.connected_components(mesh.face_adjacency, nodes=np.arange(len(mesh.faces)))
    volumes = [mesh.submesh([shell], append=True, repair=False).volume for shell in shells]
    if not (
        mesh.is_watertight
        and not np.any(counts > 2)
        and _vertex_manifold(mesh)
        and mesh.is_winding_consistent
        and all(volume > 0 for volume in volumes)
    ):
        raise RuntimeError(f"{name}: not closed, manifold, consistently wound and positive")


def _obj_bytes(mesh: trimesh.Trimesh) -> bytes:
    lines = ["# Xbox One S collision mesh base; simulation coordinates; metres; Z up\n"]
    lines.extend("v %.9f %.9f %.9f\n" % tuple(vertex) for vertex in mesh.vertices)
    lines.extend("f %d %d %d\n" % tuple(face + 1) for face in mesh.faces)
    return "".join(lines).encode("ascii")


def _rounded(mesh: trimesh.Trimesh) -> trimesh.Trimesh:
    vertices = np.array([[float("%.9f" % x) for x in vertex] for vertex in mesh.vertices])
    return trimesh.Trimesh(vertices, mesh.faces.copy(), process=False)


def _shell_components(body: trimesh.Trimesh) -> dict[str, trimesh.Trimesh]:
    pieces, groups = _components(body)
    if [len(piece.faces) for piece in pieces] != BODY_COMPONENT_FACES:
        raise ValueError("controller body components differ from the reviewed source")
    shell, plate = pieces[:2]

    main, _ = _cap_shell(shell)
    sources = np.r_[groups[0], np.full(len(main.faces) - len(shell.faces), -1, int)]
    main, sources = _replace_faces(main, sources, np.flatnonzero(np.isin(sources, LOWER_INTERFACE_FACES)))
    main, sources = _replace_faces(main, sources, np.flatnonzero(np.isin(sources, FOLD_FACES)))
    main.remove_unreferenced_vertices()

    plate_sources = np.array(groups[1])
    plate, _ = _replace_faces(plate, plate_sources, np.flatnonzero(np.isin(plate_sources, USB_FACES)))
    plate, plate_loops = _cap_shell(plate)
    if plate_loops != 1:
        raise ValueError("front plate should have exactly one back opening")
    plate.remove_unreferenced_vertices()
    return {"shell": main, "shell_front_plate": plate}


def _control_component(control: str, mesh: trimesh.Trimesh) -> trimesh.Trimesh:
    pieces, _ = _components(mesh)
    counts = [len(piece.faces) for piece in pieces]
    keep = list(range(len(pieces)))
    if control in GLYPH_FACES:
        if sorted(counts) != sorted([KEYCAP_FACES, GLYPH_FACES[control], VISUAL_DISC_FACES]):
            raise ValueError(f"{control}: unexpected key pieces {counts}")
        keep = [counts.index(KEYCAP_FACES)]
    if control in ("left_stick", "right_stick") and sorted(counts) != STICK_SHELL_FACES:
        raise ValueError(f"{control}: unexpected stick pieces {counts}")
    return trimesh.util.concatenate([_close_control(pieces[i]) for i in keep])


def _description(name: str) -> str:
    if name in DESCRIPTIONS:
        return DESCRIPTIONS[name]
    if name in GLYPH_FACES:
        return KEYCAP_DESCRIPTION
    if name in ("left_stick", "right_stick"):
        return STICK_DESCRIPTION
    return CONTROL_DESCRIPTION


def build(output: Path = DEFAULT_OUTPUT, visual: Path | None = None) -> dict:
    visual = Path(visual or ROOT / VISUAL_REL)
    output = Path(output)
    visual_manifest = json.loads((visual / "manifest.json").read_text())
    scale = visual_manifest["meters_per_native_unit"]
    parts = {part["name"]: part for part in visual_manifest["parts"]}

    components = _shell_components(_load_part(visual, parts[PART_BY_CONTROL["shell"]], scale))
    for control, part_name in PART_BY_CONTROL.items():
        if control != "shell":
            components[control] = _control_component(control, _load_part(visual, parts[part_name], scale))
    for name, mesh in components.items():
        _require_closed(name, _rounded(mesh))

    (output / "meshes").mkdir(parents=True, exist_ok=True)
    meshes = {}
    for name, mesh in components.items():
        relative = f"meshes/{name}.obj"
        (output / relative).write_bytes(_obj_bytes(mesh))
        meshes[name] = relative
    manifest = {
        "meshes": meshes,
        "derived_from": {
            "source": "assets/xbox_one_s/source/xbox_one_s_controllergamepad_animated.glb "
                      f"(static bake in {VISUAL_REL})",
            "generator": GENERATOR_REL,
            "date": PROCESS_DATE,
        },
        "license": visual_manifest["license"],
        "author": visual_manifest["author"],
        "source_url": visual_manifest["source_url"],
        "changes": CHANGES,
        "coordinate_frame": "simulation: (x,-z,y); Z up; -y toward grip ends",
        "units": "m",
        "components": {name: _description(name) for name in components},
    }
    (output / "manifest.json").write_text(
        json.dumps(manifest, ensure_ascii=False, indent=2, allow_nan=False) + "\n"
    )
    return manifest


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--output", type=Path, default=DEFAULT_OUTPUT)
    parser.add_argument("--visual", type=Path)
    args = parser.parse_args()
    build(args.output, args.visual)


if __name__ == "__main__":
    main()
