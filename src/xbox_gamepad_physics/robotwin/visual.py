"""Native SAPIEN visuals shared by inspection and physical articulations."""
from dataclasses import dataclass
from importlib import import_module
import json
import math
from pathlib import Path
from typing import Mapping

from xbox_gamepad_physics.resources import load_json_resource, resource_path
from xbox_gamepad_physics.backends.common.appearance import group_opacity, part_records, visual_assignments


@dataclass
class XboxOneSVisual:
    entities: dict
    manifest: dict
    _sapien: object

    def set_pose(self, pose):
        conversion=self._sapien.Pose(q=[math.sqrt(.5),math.sqrt(.5),0,0])
        for entity in self.entities.values():
            entity.pose=pose*conversion


@dataclass
class XboxOneSArticulationVisual:
    components: dict
    manifest: dict


def _visual_resources(directory=None):
    if directory is None:
        manifest=load_json_resource('common','xbox_one_s','visual/manifest.json')
        root=resource_path('common','xbox_one_s','visual/manifest.json').parent
    else:
        root=Path(directory).resolve()
        manifest=json.loads((root/'manifest.json').read_text(encoding='utf-8'))
    return root,manifest


def _render_material(render, root, manifest, *, opacity=1, textures=None):
    textures=textures if textures is not None else {name:render.RenderTexture2D(str(root/path),mipmap_levels=12,
                srgb=name in ('base_color_texture','emission_texture'))
              for name,path in manifest['sapien_material']['textures'].items()}
    record=manifest['sapien_material']
    base_color=[*record['base_color'][:3],opacity]
    material=render.RenderMaterial(base_color=base_color,emission=record['emission'],
            specular=record['specular'],roughness=record['roughness'],metallic=record['metallic'],
            ior=record['ior'],transmission=0)
    for name,texture in textures.items():
        setattr(material,name,texture)
    return material


def _render_materials(render, root, manifest):
    opaque=_render_material(render,root,manifest)
    # In SAPIEN 3.0.3 constant alpha selects the transparent pass; texture RGBA
    # supplies coverage unchanged. Do not multiply the texture alpha again.
    opacity=group_opacity(manifest,'BLEND')
    textures={name:getattr(opaque,name) for name in manifest['sapien_material']['textures']}
    return {'OPAQUE':opaque,'BLEND':_render_material(render,root,manifest,opacity=opacity,textures=textures)}


def _part_shapes(render, root, part, scale, materials):
    groups=part.get('groups',[{'file':part['file'],'alpha_mode':'OPAQUE'}])
    return [render.RenderShapeTriangleMesh(str(root/group['file']),scale=[scale]*3,
            material=materials[group['alpha_mode']]) for group in groups]


def _part_records(manifest):
    return part_records(manifest)


def _link(articulation, name):
    finder=getattr(articulation,'find_link_by_name',None)
    if callable(finder):
        found=finder(name)
        if found is not None:
            return found
    getter=getattr(articulation,'get_links',None)
    links=getter() if callable(getter) else getattr(articulation,'links',())
    for candidate in links:
        value=getattr(candidate,'name',None)
        if value==name:
            return candidate
    raise ValueError(f'articulation has no link {name!r}')


def _link_entity(link, name):
    entity=getattr(link,'entity',None)
    if entity is None:
        getter=getattr(link,'get_entity',None)
        entity=getter() if callable(getter) else None
    if entity is None or not callable(getattr(entity,'add_component',None)):
        raise TypeError(f'articulation link {name!r} has no mutable SAPIEN entity')
    return entity


def attach_visual_to_articulation(articulation, binding: Mapping, *, directory=None):
    """Attach the approved PBR parts to named physical articulation links."""

    sapien=import_module('sapien')
    render=sapien.render
    root,manifest=_visual_resources(directory)
    materials=_render_materials(render,root,manifest)
    records=_part_records(manifest)
    scale=manifest['meters_per_native_unit']
    conversion=sapien.Pose(q=[math.sqrt(.5),math.sqrt(.5),0,0])
    assignments=visual_assignments(binding,records)

    grouped={}
    for part_name,(link_name,pivot) in assignments.items():
        grouped.setdefault(link_name,[]).append((part_name,pivot))
    components={}
    for link_name,items in grouped.items():
        body=render.RenderBodyComponent()
        for part_name,pivot in items:
            record=records[part_name]
            for shape in _part_shapes(render,root,record,scale,materials):
                if pivot is None:
                    shape.local_pose=conversion
                else:
                    shape.local_pose=sapien.Pose(p=[-float(value) for value in pivot])*conversion
                body.attach(shape)
        entity=_link_entity(_link(articulation,link_name),link_name)
        entity.add_component(body)
        components[link_name]=body
    return XboxOneSArticulationVisual(components,manifest)


def load_visual_into_scene(scene, pose=None, *, directory=None):
    """Add 16 render-only entities to a SAPIEN scene or a RoboTwin task.

    Geometry, normals and UVs are reused. Width-fit scale is the existing visual
    estimate. This entry never creates collision shapes or supplies inertial data.
    """
    sapien=import_module('sapien')
    render=sapien.render
    target=getattr(scene,'scene',scene)
    root,manifest=_visual_resources(directory)
    materials=_render_materials(render,root,manifest)
    scale=manifest['meters_per_native_unit']
    entities={}
    for part in manifest['parts']:
        body=render.RenderBodyComponent()
        for shape in _part_shapes(render,root,part,scale,materials):
            body.attach(shape)
        entity=sapien.Entity();entity.name=part['name'];entity.add_component(body)
        target.add_entity(entity);entities[part['name']]=entity
    visual=XboxOneSVisual(entities,manifest,sapien)
    visual.set_pose(pose or sapien.Pose())
    return visual
