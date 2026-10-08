// Screen-space constrained least squares. Numerical controls are UI tolerances,
// not mechanical constants. project([u,v]) uses the same pose model as rendering.
const clamp=x=>Math.max(-1,Math.min(1,x));
export function projectUnitDisk(values) {
  const radius=Math.max(1,Math.hypot(...values));
  return values.map(value=>value/radius);
}

export function solveDrag2D(project, initial, target, {constrain=values=>values.map(clamp)}={}) {
  // Keep the iterate in the same feasible domain as the displayed pose.
  // A point outside a radially clamped disk has no radial derivative.
  let q=constrain(initial), p=project(q), error=Math.hypot(p[0]-target[0],p[1]-target[1]);
  for(let iteration=0;iteration<20&&error>.1;iteration++){
    const columns=q.map((x,i)=>{
      const a=[...q],b=[...q];a[i]=clamp(x+1e-4);b[i]=clamp(x-1e-4);
      const pa=project(a),pb=project(b),span=a[i]-b[i];
      return [(pa[0]-pb[0])/span,(pa[1]-pb[1])/span];
    });
    const [[a,c],[b,d]]=columns,det=a*d-b*c;
    if(!Number.isFinite(det)||Math.abs(det)<1e-8)break;
    const ex=target[0]-p[0],ey=target[1]-p[1];
    const step=[(d*ex-b*ey)/det,(-c*ex+a*ey)/det];
    let accepted=false;
    for(let scale=1;scale>=1/128;scale/=2){
      const candidate=constrain(q.map((x,i)=>clamp(x+scale*step[i])));
      const next=project(candidate),e=Math.hypot(next[0]-target[0],next[1]-target[1]);
      if(Number.isFinite(e)&&e<error){q=candidate;p=next;error=e;accepted=true;break;}
    }
    if(!accepted)break;
  }
  return {values:q,errorPx:error,reached:error<=.1};
}
