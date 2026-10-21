"""Plot the completed single-engine trace; no missing-engine curves are inferred."""
import argparse
import csv
from pathlib import Path
import numpy as np
import matplotlib
matplotlib.use('Agg')
import matplotlib.pyplot as plt
p=argparse.ArgumentParser();p.add_argument('directory',type=Path);a=p.parse_args()
with (a.directory/'QS_CONTACT.csv').open() as source:rows=list(csv.DictReader(source))
values=lambda key:np.array([float(row[key]) if row[key] else np.nan for row in rows])
s=values('actual_s_m')*1000;q=values('q_m')*1000;steps=values('step')
fig,axes=plt.subplots(1,2,figsize=(11,4.2))
press=np.array([row['phase'] in ['press','hold'] for row in rows])
axes[0].plot(s[press],q[press],lw=1,label='Isaac SDF 0.5 mm')
for label,step in [('Guide motion >1 um',501),('First shell contact',541)]:
 i=int(step);axes[0].scatter(s[i],q[i],s=22);axes[0].annotate(label,(s[i],q[i]),xytext=(6,-17),textcoords='offset points',fontsize=8)
axes[0].set(xlabel='Actual sphere advance s (mm)',ylabel='Guide displacement q (mm)');axes[0].legend()
for key,label in [('guide_separation_m','Guide'),('shell_separation_m','Shell')]:axes[1].plot(steps,values(key)*1000,lw=.7,label=label)
axes[1].set(xlabel='Replay step (dt = 4 ms)',ylabel='Native contact separation (mm)');axes[1].legend()
for axis in axes:axis.grid(alpha=.25)
fig.suptitle('Isaac completed; SAPIEN replay blocked — cross-engine diagnosis pending',fontsize=11)
fig.tight_layout();fig.savefig(a.directory/'QS_CONTACT.png',dpi=170);fig.savefig(a.directory/'QS_CONTACT.svg');plt.close(fig)
