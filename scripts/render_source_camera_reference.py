"""Use public camera position as a diagnostic view; retain studio illumination."""
import bpy,json,sys,math
from pathlib import Path
from mathutils import Vector
root=Path(sys.argv[sys.argv.index('--')+1])
out=root/'official_import_4.5.9_LTS'
bpy.ops.wm.open_mainfile(filepath=str(out/'Xbox_One_S_BatonyRobson_MATERIAL_REVIEW_UNCALIBRATED.blend'),use_scripts=False)
settings=json.loads((root/'review/public_viewer_settings.json').read_text())
cam=bpy.context.scene.camera;raw=settings['options']['camera']
cam.data.type='PERSP';cam.data.angle=math.radians(raw['fov']);cam.location=Vector(raw['position'])
cam.rotation_euler=(Vector(raw['target'])-cam.location).to_track_quat('-Z','Y').to_euler()
scene=bpy.context.scene;scene.render.resolution_x=1600;scene.render.resolution_y=900
scene.render.filepath=str(out/'source_camera_studio.png');bpy.ops.render.render(write_still=True)
(out/'source_camera_caveats.json').write_text(json.dumps({'camera_position_target_fov':raw,'camera_coordinate_registration_verified':False,'lighting':'unchanged diagnostic area light, NOT Sketchfab environment','postprocessing':'Filmic, NOT site settings','purpose':'oblique view to examine source texture detail, not pixel-matched reproduction'},indent=2))
