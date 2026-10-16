"""Read-only integration diagnostics for caller-owned SAPIEN scenes."""

from __future__ import annotations

from .loader import _resolve_scene
from .scene import require_sapien


_LOADS_ATTRIBUTE = "_xbox_gamepad_physics_loads"


def _mark_loaded(scene, articulation, *, profile, collision, attach_visual):
    # Scene is SAPIEN's Python wrapper; native Entity objects do not allow attrs.
    records = getattr(scene, _LOADS_ATTRIBUTE, None)
    if records is None:
        records = {}
        setattr(scene, _LOADS_ATTRIBUTE, records)
    records[articulation] = {"profile": profile, "collision": collision,
                             "attach_visual": attach_visual}


def _name(value):
    return str(getattr(value, "name", ""))


def _components(entity):
    return getattr(entity, "components", ())


def _shapes(entity):
    for component in _components(entity):
        yield from getattr(component, "collision_shapes", ())


def _gamepad_articulation(art):
    links = {_name(link) for link in art.get_links()}
    joints = {_name(joint) for joint in art.get_active_joints()}
    return "controller_body" in links and "left_stick_x" in joints


def _box_support_between(entities, origin, normal, plane_distance, physx):
    """Check whether a static box intercepts the downward ray before the plane."""
    for entity in entities:
        for component in _components(entity):
            if not isinstance(component, physx.PhysxRigidStaticComponent):
                continue
            for shape in component.collision_shapes:
                if not isinstance(shape, physx.PhysxCollisionShapeBox):
                    continue
                world = entity.pose * shape.local_pose
                matrix = world.to_transformation_matrix()
                # Rotate the world ray into the oriented box's local frame.
                local = [sum(matrix[i][j] * (origin[i] - world.p[i]) for i in range(3)) for j in range(3)]
                direction = [-sum(matrix[i][j] * normal[i] for i in range(3)) for j in range(3)]
                near, far = 0.0, plane_distance
                for axis, half in enumerate(shape.half_size):
                    if abs(direction[axis]) < 1e-12:
                        if abs(local[axis]) > half:
                            far = -1.0
                            break
                    else:
                        first = (-half - local[axis]) / direction[axis]
                        second = (half - local[axis]) / direction[axis]
                        near = max(near, min(first, second))
                        far = min(far, max(first, second))
                if 0 <= near <= far and near < plane_distance:
                    return True
    return False


def diagnose_scene(scene):
    """Return a read-only dict of gamepad loading, support and shader findings.

    Official loads are recorded on the scene, without renaming links/entities.
    Unmarked controller_body/left_stick_x articulations are suspected raw URDF
    imports. Raw mesh detection uses source filenames, so renamed/copied meshes
    with no identifying source path cannot be recognized. A plane below an SDF
    root, without an intervening static box, is a potential unsupported support;
    raw URDF imports receive the same compatibility warning with collision
    explicitly unverified, rather than claiming their shapes were cooked as SDF.
    Intervening static boxes (oriented) are found by casting along the plane
    normal from the gamepad root. This is a geometric
    warning, not a contact validation. This function never alters the scene,
    global renderer settings, or PhysX configuration.
    """
    scene = _resolve_scene(scene)
    sapien = require_sapien()
    records = getattr(scene, _LOADS_ATTRIBUTE, {})
    findings = []
    gamepads = []
    official_entities = set()
    articulations = scene.get_all_articulations()
    for art in articulations:
        record = records.get(art)
        if record is None and not _gamepad_articulation(art):
            continue
        links = list(art.get_links())
        official = record is not None
        if official:
            official_entities.update(link.entity for link in links)
        else:
            findings.append({"code": "direct_urdf", "severity": "warning",
                             "message": "Suspected direct gamepad URDF import: use load_into_scene for materials, SDF setup and signal mapping."})
        gamepads.append({"name": _name(art), "via_load_into_scene": official,
                         "collision": record["collision"] if official else "unknown",
                         "profile": record["profile"] if official else None})
        if official and not record["attach_visual"]:
            findings.append({"code": "visual_disabled", "severity": "info",
                             "message": "Gamepad was loaded with attach_visual=False."})

    entities = list(scene.get_entities())
    for entity in entities:
        if entity in official_entities:
            continue
        for component in _components(entity):
            for shape in getattr(component, "render_shapes", ()):
                filename = str(getattr(shape, "filename", "")).replace("\\", "/")
                if any(token in filename.lower() for token in ("xbox_one_s", "visual_meshbase", "sim_visual")):
                    findings.append({"code": "direct_mesh", "severity": "warning",
                                     "entity": _name(entity), "source": filename,
                                     "message": "Suspected direct package mesh import: use load_into_scene to preserve the complete integration."})

    plane_type = sapien.physx.PhysxCollisionShapePlane
    for art in articulations:
        record = records.get(art)
        if record is None:
            if not _gamepad_articulation(art):
                continue
        elif record["collision"] != "sdf":
            continue
        root = art.get_links()[0]
        root_position = root.entity.pose.p
        for entity in entities:
            for shape in _shapes(entity):
                if not isinstance(shape, plane_type):
                    continue
                world = entity.pose * shape.local_pose
                matrix = world.to_transformation_matrix()
                normal = [matrix[i][0] for i in range(3)]
                distance = sum((root_position[i] - world.p[i]) * normal[i] for i in range(3))
                if (normal[2] > 0.9 and distance >= 0 and
                        not _box_support_between(entities, root_position, normal, distance, sapien.physx)):
                    findings.append({"code": "sdf_plane_support", "severity": "warning",
                                     "entity": _name(entity),
                                     "message": (
                                         "A ground plane lies below a directly imported gamepad; its collision setup is unverified. "
                                         "SDF cannot collide with add_ground planes; use load_into_scene and a static box as support."
                                         if record is None else
                                         "A ground plane lies below an SDF gamepad. SDF cannot collide with add_ground planes; provide a static box as support.")})

    shader = str(sapien.render.get_camera_shader_dir())
    shader_name = shader.rstrip("/").split("/")[-1]
    mode = "ray_tracing" if shader_name == "rt" else "raster" if shader_name == "default" else "custom"
    return {"gamepads": gamepads, "findings": findings,
            "rendering": {"camera_shader": shader, "mode": mode,
                          "appearance": "Frozen split materials support raster and ray tracing; lighting and renderer change image appearance. Review RT is optional."},
            "collision_groups": {"groups[2]_reserved_bit": "0x80000000", "groups[3]": "0x5842"}}
