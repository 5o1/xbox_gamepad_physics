"""Native cap geometry and recorded force/trajectory schematics, no sphere."""
import argparse,json
from pathlib import Path
import numpy as np
import matplotlib
matplotlib.use('Agg')
import matplotlib.pyplot as plt
from mpl_toolkits.mplot3d.art3d import Poly3DCollection
from trimesh.transformations import quaternion_matrix

def plot(root,out,model):
 results=json.loads((root/'results.json').read_text())['results'];out.mkdir(parents=True,exist_ok=True);files=[]
 for result in results:
  side=result['side'];fv=result['vertical_force_n'];folder=root/(side+'_'+str(fv));plan=json.loads((folder/'point.json').read_text());rows=[json.loads(l) for l in (folder/'trace.jsonl').read_text().splitlines()];hold=[r for r in rows if r['phase']=='hold'];chosen=hold[-1];origin=np.array(rows[0]['cap_pose'][:3]);vertices=np.array(plan['vertices_local_m']);faces=np.array(plan['triangles']);fig=plt.figure(figsize=(11,5),constrained_layout=True);ax=fig.add_subplot(121,projection='3d')
  allpoints=[]
  for row,color,alpha in [(rows[0],'#aaaaaa',.08),(chosen,'#2876a6',.30)]:
   pose=row['cap_pose'];rotation=quaternion_matrix(pose[3:])[:3,:3];v=(vertices@rotation.T+np.array(pose[:3])-origin)*1000;tri=v[faces[::max(1,len(faces)//500)]];ax.add_collection3d(Poly3DCollection(tri,facecolors=color,alpha=alpha,edgecolors='none'));allpoints.append(v)
  point=(np.array(chosen['application_point_world_m'])-origin)*1000;h=np.array(chosen['horizontal_unit_world'])*2;v=np.array(chosen['vertical_unit_world'])*2*fv
  ax.scatter(*point,color='red',s=80,depthshade=False,zorder=100,label='Force point')
  for vector,color,label in [(h,'#e07a16','Horizontal 1 N'),(v,'#263a9c',f'Downward {fv:g} N')]:
   ax.quiver(*point,*vector,color=color,arrow_length_ratio=.18,linewidth=2,label=label);ax.text(*(point+vector),label,fontsize=7);allpoints.append(np.array([point,point+vector]))
  trajectory=np.array([r['application_point_world_m'] for r in rows[::10]])*1000-origin*1000;ax.plot(*trajectory.T,color='#1d8c52',lw=2,label='Recorded point path');allpoints.append(trajectory)
  data=np.concatenate(allpoints);lo=data.min(0)-2;hi=data.max(0)+2;ax.set(xlim=(lo[0],hi[0]),ylim=(lo[1],hi[1]),zlim=(lo[2],hi[2]),xlabel='X (mm)',ylabel='Y (mm)',zlabel='Z (mm)');ax.set_box_aspect(np.maximum(hi-lo,1));ax.view_init(22,-58);ax.legend(fontsize=7,loc='upper left')
  graph=fig.add_subplot(122);t=np.arange(1,len(rows)+1)*.004;graph.plot(t,[r['angle_deg'] for r in rows],label='Tilt (deg)',color='#2876a6');graph.set(xlabel='Time (s)',ylabel='Tilt angle (deg)');other=graph.twinx();other.plot(t,[r['signal'] for r in rows],label='Click signal',color='#c56711');other.plot(t,[r['raw_fraction'] for r in rows],ls=':',color='#ad337c',label='Raw travel fraction');other.axhline(.05,ls='--',color='grey',lw=.6);other.axhline(.95,ls='--',color='grey',lw=.6);other.set(ylabel='Click fraction',ylim=(-.05,1.1));graph.axvspan(1.5,2.5,alpha=.08,color='green');graph.grid(alpha=.2);other.legend(fontsize=7,loc='upper right')
  fig.suptitle(f'{model} | {side} | Fh=1 N, Fv={fv:g} N | {result["status"]}\nNative mesh + measured pose schematic (not renderer screenshot)',fontsize=10)
  path=out/f'{model}_{side}_Fv{fv:g}.png';fig.savefig(path,dpi=145);plt.close(fig);files.append(str(path.resolve()))
 return files
if __name__=='__main__':
 p=argparse.ArgumentParser();p.add_argument('--root',type=Path,required=True);p.add_argument('--output',type=Path,required=True);p.add_argument('--model',required=True);a=p.parse_args();files=plot(a.root,a.output,a.model);(a.output/(a.model+'_files.json')).write_text(json.dumps(files,indent=2)+'\n')
