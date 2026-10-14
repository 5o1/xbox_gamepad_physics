import * as T from 'three';
import {GLTFLoader} from 'three/addons/loaders/GLTFLoader.js';
import {OrbitControls} from 'three/addons/controls/OrbitControls.js';
import {RoomEnvironment} from 'three/addons/environments/RoomEnvironment.js';
const host=document.querySelector('#scene'), status=document.querySelector('#status');
const renderer=new T.WebGLRenderer({antialias:true,preserveDrawingBuffer:true});
renderer.setPixelRatio(Math.min(devicePixelRatio,2));renderer.outputColorSpace=T.SRGBColorSpace;
renderer.toneMapping=T.ACESFilmicToneMapping;host.append(renderer.domElement);
const scene=new T.Scene();scene.background=new T.Color('#707070');
const pmrem=new T.PMREMGenerator(renderer),room=new RoomEnvironment();
scene.environment=pmrem.fromScene(room).texture;room.dispose();
const camera=new T.PerspectiveCamera(35,1,.001,1000),orbit=new OrbitControls(camera,renderer.domElement);
function resize(){const w=host.clientWidth,h=host.clientHeight;renderer.setSize(w,h);camera.aspect=w/h;camera.updateProjectionMatrix();}
new ResizeObserver(resize).observe(host);resize();
const texture=t=>t?{colorSpace:t.colorSpace,flipY:t.flipY,channel:t.channel,width:t.image?.width,height:t.image?.height}:null;
try{
 const response=await fetch('/assets/xbox/xbox_one_s_controllergamepad_animated.glb');
 if(!response.ok)throw Error(`GLB HTTP ${response.status}`);
 const bytes=await response.arrayBuffer();
 const digest=[...new Uint8Array(await crypto.subtle.digest('SHA-256',bytes))].map(x=>x.toString(16).padStart(2,'0')).join('');
 if(digest!=='5c5671c83a9cf15db4b8399e7010aa7d5cde915687ceb348b583eb00b0ed24e2')throw Error('Source hash mismatch');
 const gltf=await new GLTFLoader().parseAsync(bytes,'');scene.add(gltf.scene);
 // Match the source animation at t=0 used by the Blender reference.
 const mixer=new T.AnimationMixer(gltf.scene);
 if(gltf.animations.length)mixer.clipAction(gltf.animations[0]).play();
 mixer.setTime(0);gltf.scene.updateMatrixWorld(true);
 const box=new T.Box3().setFromObject(gltf.scene),center=box.getCenter(new T.Vector3()),size=box.getSize(new T.Vector3()),extent=Math.max(...size);
 // glTF +Y maps to Blender +Z; glTF -Z maps to Blender +Y.
 camera.up.set(0,0,-1);orbit.target.copy(center);
 function view(offset){camera.position.copy(center).add(new T.Vector3(...offset).multiplyScalar(extent*2.3));camera.near=extent*.001;camera.far=extent*50;camera.updateProjectionMatrix();orbit.update();}
 document.querySelector('#front').onclick=()=>view([0,1,0]);
 document.querySelector('#angle').onclick=()=>view([.35,1,-.35]);view([0,1,0]);
 const records=[];gltf.scene.traverse(o=>{if(o.isMesh){const m=o.material;records.push({name:o.name,vertexColors:!!o.geometry.attributes.color,type:m.type,baseColor:texture(m.map),normal:texture(m.normalMap),metallic:texture(m.metalnessMap),roughness:texture(m.roughnessMap),ao:texture(m.aoMap),aoIntensity:m.aoMapIntensity,specular:texture(m.specularIntensityMap),specularIntensity:m.specularIntensity,emissive:texture(m.emissiveMap),emissiveIntensity:m.emissiveIntensity,transparent:m.transparent,side:m.side});}});
 const checks={sourceHash:digest,meshCount:records.length,noVertexColors:records.every(r=>!r.vertexColors),allPBRMapsPresent:records.every(r=>r.baseColor&&r.normal&&r.metallic&&r.roughness&&r.ao&&r.specular&&r.emissive),sourceAOIntensity:records.every(r=>Math.abs(r.aoIntensity-.7406035171729057)<1e-8),sourceEmission:records.every(r=>r.emissiveIntensity===10),alphaBlend:records.every(r=>r.transparent)};
 if(records.length!==16||!checks.allPBRMapsPresent||!checks.sourceAOIntensity||!checks.sourceEmission||!checks.alphaBlend)throw Error(JSON.stringify(checks));
 window.setDepthDiagnostic=enabled=>{gltf.scene.traverse(o=>{if(o.isMesh)o.material.depthWrite=enabled;});};
 window.materialAudit={checks,records,threeRevision:T.REVISION,environment:'RoomEnvironment',toneMapping:'ACESFilmic',geometryAndMaterialsModified:false};
 document.querySelector('#audit').textContent=JSON.stringify(window.materialAudit,null,2);
 status.textContent='Verified 16 meshes: base color, normal, metallic, roughness, AO, specular intensity and emissive textures are connected.';document.body.dataset.ready='true';
}catch(error){status.textContent=String(error);document.body.dataset.error=String(error);throw error;}
renderer.setAnimationLoop(()=>{orbit.update();renderer.render(scene,camera);});
