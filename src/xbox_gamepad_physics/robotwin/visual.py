"""Native SAPIEN visuals for appearance inspection; no rigid-body components."""
from dataclasses import dataclass
from importlib import import_module
import math
from pathlib import Path

from xbox_gamepad_physics.resources import load_json_resource, resource_path


@dataclass
class XboxOneSVisual:
    entities: dict
    manifest: dict
    _sapien: object

    def set_pose(self, pose):
        conversion=self._sapien.Pose(q=[math.sqrt(.5),math.sqrt(.5),0,0])
        for entity in self.entities.values():
            entity.pose=pose*conversion

    @property
    def physics_ready(self):
        return False


def load_visual_into_scene(scene, pose=None, *, directory=None):
    """Add 16 render-only entities to a SAPIEN scene or a RoboTwin task.

    Geometry, normals and UVs are reused. Width-fit scale is the existing visual
    estimate. This entry never creates collision shapes or supplies inertial data.
    """
    sapien=import_module('sapien')
    render=sapien.render
    target=getattr(scene,'scene',scene)
    if directory is None:
        manifest=load_json_resource('common','xbox_one_s','visual/manifest.json')
        root=resource_path('common','xbox_one_s','visual/manifest.json').parent
    else:
        import json
        root=Path(directory).resolve()
        manifest=json.loads((root/'manifest.json').read_text())
    textures={name:render.RenderTexture2D(str(root/path),mipmap_levels=12,
                srgb=name in ('base_color_texture','emission_texture'))
              for name,path in manifest['sapien_material']['textures'].items()}
    record=manifest['sapien_material']
    material=render.RenderMaterial(base_color=record['base_color'],emission=record['emission'],
            specular=record['specular'],roughness=record['roughness'],metallic=record['metallic'],
            ior=record['ior'],transmission=0)
    for name,texture in textures.items():
        setattr(material,name,texture)
    scale=manifest['meters_per_native_unit']
    entities={}
    for part in manifest['parts']:
        shape=render.RenderShapeTriangleMesh(str(root/part['file']),scale=[scale]*3,material=material)
        body=render.RenderBodyComponent();body.attach(shape)
        entity=sapien.Entity();entity.name=part['name'];entity.add_component(body)
        target.add_entity(entity);entities[part['name']]=entity
    visual=XboxOneSVisual(entities,manifest,sapien)
    visual.set_pose(pose or sapien.Pose())
    return visual
