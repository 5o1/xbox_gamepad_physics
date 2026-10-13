"""Orthographic shell error projections (not contact or full protection validation)."""
from pathlib import Path
import numpy as np
import matplotlib
matplotlib.use('Agg')
import matplotlib.pyplot as plt
from matplotlib.collections import PolyCollection


def error_projections(source, field, output, vmax_mm=3):
    output = Path(output)
    output.mkdir(parents=True,exist_ok=True)
    for name, axes, depth, reverse in [('front',(0,1),2,False),('top',(0,2),1,False),('back',(0,1),2,True)]:
        fig,ax = plt.subplots(figsize=(9,6))
        order = np.argsort(source.triangles[:,:,depth].mean(1))
        pts_order = np.argsort(field['points'][:,depth])
        if reverse:
            order,pts_order = order[::-1],pts_order[::-1]
        ax.add_collection(PolyCollection(source.triangles[order][:,:,axes]*1000,facecolors='#dddddd',edgecolors='none'))
        pts = field['points'][pts_order]
        im = ax.scatter(pts[:,axes[0]]*1000,pts[:,axes[1]]*1000,c=field['outward_mm'][pts_order],
                        s=1,cmap='turbo',vmin=0,vmax=vmax_mm,linewidths=0,rasterized=True)
        if reverse:
            ax.invert_yaxis()
        ax.autoscale()
        ax.set_aspect('equal')
        ax.set_xlabel('X (mm)')
        ax.set_ylabel(('Y' if axes[1]==1 else 'Z')+' (mm)')
        ax.set_title('Shell sampled outward error / '+name+' / diagnostic only')
        fig.colorbar(im,ax=ax,label='Outside-only triangle distance (mm)')
        fig.tight_layout()
        fig.savefig(output/f'shell_error_{name}.png',dpi=160)
        plt.close(fig)
