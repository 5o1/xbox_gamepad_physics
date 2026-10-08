// Compare the actual browser shader against samples saved by Blender 4.5.9.
import assert from 'node:assert/strict';
import {writeFile} from 'node:fs/promises';
import {connectCdp,evaluateCdp,closeCdpTarget} from './cdp_client.mjs';
const viewer=process.argv[2]??'http://127.0.0.1:18768/v0.html';
const endpoint=process.argv[3]??'http://127.0.0.1:19310';
const page=await (await fetch(endpoint+'/json/new?about:blank',{method:'PUT'})).json();
const client=await connectCdp(page.webSocketDebuggerUrl);
try {
  await client.call('Page.enable');
  await client.call('Page.navigate',{url:viewer});
  for(let i=0;i<100;i++){
    if(await evaluateCdp(client,'document.body?.dataset.ready === "true"'))break;
    await new Promise(r=>setTimeout(r,100));
  }
  const result=await evaluateCdp(client,`(async()=>{
    const T=await import('three');
    const {FullScreenQuad}=await import('three/addons/postprocessing/Pass.js');
    const {loadFilmicMaterial}=await import('/saved_render.mjs');
    const samples=await (await fetch('/render-settings/color_samples.json')).json();
    const data=Float32Array.from(samples.flatMap(rgb=>[...rgb,1]));
    const input=new T.DataTexture(data,samples.length,1,T.RGBAFormat,T.FloatType);input.needsUpdate=true;
    const renderer=new T.WebGLRenderer();
    const output=new T.WebGLRenderTarget(samples.length,1,{type:T.UnsignedByteType});
    const material=await loadFilmicMaterial();material.uniforms.tDiffuse.value=input;
    const quad=new FullScreenQuad(material);renderer.setRenderTarget(output);quad.render(renderer);
    const actual=new Uint8Array(samples.length*4);renderer.readRenderTargetPixels(output,0,0,samples.length,1,actual);
    const image=new Image();image.src='/render-settings/blender_color_samples.png';await image.decode();
    const canvas=document.createElement('canvas');canvas.width=image.width;canvas.height=1;
    const ctx=canvas.getContext('2d');ctx.drawImage(image,0,0);const expected=ctx.getImageData(0,0,image.width,1).data;
    const maxError=Math.max(...actual.map((v,i)=>Math.abs(v-expected[i])));
    quad.dispose();material.dispose();input.dispose();output.dispose();renderer.dispose();renderer.forceContextLoss();
    return {samples,expected:Array.from(expected),actual:Array.from(actual),max_channel_error_8bit:maxError};
  })()`);
  console.log(JSON.stringify(result));
  if(process.argv[4])await writeFile(process.argv[4],JSON.stringify(result,null,2)+'\n');
  assert.ok(result.max_channel_error_8bit<=1,'Filmic output differs from Blender by more than 1/255');
}finally{client.close();await closeCdpTarget(endpoint,page.id);}
