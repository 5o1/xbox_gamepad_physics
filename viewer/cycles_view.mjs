// The browser performs picking and sends poses. Blender/Cycles draws the image.
export class CyclesView {
  constructor(host) {
    this.domElement=document.createElement('canvas');
    this.image=document.createElement('img');this.image.alt='Blender Cycles controller preview';
    this.image.style.cssText='position:absolute;top:50%;left:50%;transform:translate(-50%,-50%);pointer-events:none;border-radius:0';
    host.style.cssText='position:relative;display:grid;place-items:center';host.append(this.domElement,this.image);
    this.pending=null;this.running=false;this.frame=0;this.request=0;this.lastError=null;
    this.doneState=null;
  }
  getPixelRatio(){return 1;}
  setPixelRatio(){}
  setSize(width,height){this.domElement.width=width;this.domElement.height=height;this.image.style.width=width+'px';this.image.style.height=height+'px';}
  render(parts,camera,scale){
    const width=this.domElement.width,height=this.domElement.height;
    const ratio=Math.min(1,1600/width,1200/height);
    const state={
      size:[Math.max(1,Math.round(width*ratio)),Math.max(1,Math.round(height*ratio))],
      camera:{position:camera.position.toArray().map(v=>v/scale),quaternion:camera.quaternion.toArray(),fov:camera.fov},
      parts:Object.fromEntries([...parts].map(([name,node])=>[name,node.matrix.toArray()])),
    };
    const key=JSON.stringify(state);
    if(key===this.latestKey)return;
    this.latestKey=key;this.pending={state,id:++this.request};
    this.flush();
  }
  async flush(){
    if(this.running||!this.pending)return;
    const job=this.pending;this.pending=null;this.running=true;
    try{
      const response=await fetch('/cycles/frame',{method:'POST',headers:{'Content-Type':'application/json'},body:JSON.stringify(job.state)});
      if(!response.ok)throw Error(await response.text());
      const url=URL.createObjectURL(await response.blob());
      const decoded=new Image();decoded.src=url;await decoded.decode();
      const old=this.image.src;this.image.src=url;if(old.startsWith('blob:'))URL.revokeObjectURL(old);
      this.frame=job.id;this.doneState=job.state;this.lastError=null;
      document.body.dataset.renderReady='true';
    }catch(error){this.lastError=String(error);document.body.dataset.error=this.lastError;}
    finally{this.running=false;if(this.pending)this.flush();}
  }
}
