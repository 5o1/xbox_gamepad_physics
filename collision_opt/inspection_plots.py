"""Orthographic geometry inspection, separate from dynamics/contact validation."""
from pathlib import Path
import numpy as np
import matplotlib
matplotlib.use('Agg')
import matplotlib.pyplot as plt
from matplotlib.collections import PolyCollection


def _draw(ax, mesh_mm, axes, depth, sign, color, alpha):
    triangles=mesh_mm.triangles
    if not len(triangles):
        return
    order=np.argsort(sign*triangles[:,:,depth].mean(axis=1))
    ax.add_collection(PolyCollection(triangles[order][:,:,axes],facecolors=color,
                                     edgecolors='none',alpha=alpha,rasterized=True))


def render_inspection(sources, records, spaces, result, output):
    output=Path(output);output.mkdir(parents=True,exist_ok=True)
    paths=[]
    hit_keys={(r['component'],r['hull_index']) for r in result['intrusion_pairs'] if r['intrudes']}
    field_dir=output.parent/'fields'
    fields=[dict(np.load(field_dir/f'{name}.npz')) for name in sources]
    points=np.concatenate([f['points'] for f in fields])*1000
    errors=np.concatenate([f['outward_mm'] for f in fields])
    meshes={name:mesh.copy() for name,mesh in sources.items()}
    for mesh in meshes.values():
        mesh.vertices*=1000
    views=[('front',(0,1),2,1,'+Z button face'),
           ('top',(0,2),1,1,'+Y shoulder/trigger edge'),
           ('back',(0,1),2,-1,'-Z rear face')]
    for name,axes,depth,sign,label in views:
        fig,panels=plt.subplots(1,3,figsize=(19,6.2))
        for ax in panels:
            for mesh in meshes.values():
                _draw(ax,mesh,axes,depth,sign,'#b9bdc4',.5)
        combined=[(key,mesh) for key,mesh in spaces.items() if key.endswith(':combined')]
        colors=plt.get_cmap('tab20')
        for i,(key,mesh) in enumerate(combined):
            _draw(panels[0],mesh,axes,depth,sign,colors(i%20),.45)
            if len(mesh.faces):
                location=mesh.centroid[list(axes)]
                panels[0].annotate(key.split(':')[0],location,fontsize=6,
                    bbox=dict(facecolor='white',alpha=.7,edgecolor='none',pad=.6))
        for record in records:
            if (record['component'],record['hull_index']) in hit_keys:
                mesh=record['mesh'].copy();mesh.vertices*=1000
                _draw(panels[1],mesh,axes,depth,sign,'#ee482e',.58)
                if record['link']=='controller_body' and record['shape_index']==59:
                    panels[1].annotate('PhysX shape 59',mesh.centroid[list(axes)],fontsize=8,
                        bbox=dict(facecolor='white',edgecolor='#b71900',alpha=.9,pad=2))
        order=np.argsort(sign*points[:,depth])
        image=panels[2].scatter(points[order,axes[0]],points[order,axes[1]],
            c=errors[order],s=.65,cmap='turbo',vmin=0,vmax=3,linewidths=0,rasterized=True)
        for ax,title in zip(panels,['Protected free spaces (after subtracting B)',
                f'Intruding body hulls ({len(hit_keys)})','Sampled outward error']):
            ax.autoscale();ax.set_aspect('equal')
            ax.set_xlabel('XYZ'[axes[0]]+' (mm)');ax.set_ylabel('XYZ'[axes[1]]+' (mm)')
            ax.set_title(title,fontsize=11)
            if sign<0:
                ax.invert_xaxis()
        fig.colorbar(image,ax=panels[2],label='Outside-only triangle distance (mm)',shrink=.8)
        fig.suptitle(f'{name}: {label} | original meshbase and computed diagnostics | geometry only')
        fig.tight_layout()
        path=output/f'inspection_{name}.png';fig.savefig(path,dpi=170);plt.close(fig)
        paths.append(str(path))
    return paths
