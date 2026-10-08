import * as T from 'three';
import {LUTCubeLoader} from 'three/addons/loaders/LUTCubeLoader.js';
import {RectAreaLightUniformsLib} from 'three/addons/lights/RectAreaLightUniformsLib.js';
import {EffectComposer} from 'three/addons/postprocessing/EffectComposer.js';
import {RenderPass} from 'three/addons/postprocessing/RenderPass.js';
import {ShaderPass} from 'three/addons/postprocessing/ShaderPass.js';

// Blender 4.5 Filmic, Look=None. The log ranges, LUTs and their order come
// directly from its config.ocio. Tetrahedral interpolation matches OCIO.
export const filmicFragment = `
precision highp sampler3D;
uniform sampler2D tDiffuse;
uniform sampler3D desaturation;
uniform sampler2D displayCurve;
uniform float exposure;
in vec2 vUv;
out vec4 outputColor;
vec3 lookup(ivec3 p) { return texelFetch(desaturation,p,0).rgb; }
vec3 tetrahedral(vec3 value) {
  vec3 p=clamp(value,0.0,1.0)*32.0;
  ivec3 base=min(ivec3(floor(p)),ivec3(31));
  vec3 f=p-vec3(base), a=lookup(base), d=lookup(base+ivec3(1));
  if(f.r>=f.g) {
    if(f.g>=f.b) return a+f.r*(lookup(base+ivec3(1,0,0))-a)+f.g*(lookup(base+ivec3(1,1,0))-lookup(base+ivec3(1,0,0)))+f.b*(d-lookup(base+ivec3(1,1,0)));
    if(f.r>=f.b) return a+f.r*(lookup(base+ivec3(1,0,0))-a)+f.b*(lookup(base+ivec3(1,0,1))-lookup(base+ivec3(1,0,0)))+f.g*(d-lookup(base+ivec3(1,0,1)));
    return a+f.b*(lookup(base+ivec3(0,0,1))-a)+f.r*(lookup(base+ivec3(1,0,1))-lookup(base+ivec3(0,0,1)))+f.g*(d-lookup(base+ivec3(1,0,1)));
  }
  if(f.b>=f.g) return a+f.b*(lookup(base+ivec3(0,0,1))-a)+f.g*(lookup(base+ivec3(0,1,1))-lookup(base+ivec3(0,0,1)))+f.r*(d-lookup(base+ivec3(0,1,1)));
  if(f.b>=f.r) return a+f.g*(lookup(base+ivec3(0,1,0))-a)+f.b*(lookup(base+ivec3(0,1,1))-lookup(base+ivec3(0,1,0)))+f.r*(d-lookup(base+ivec3(0,1,1)));
  return a+f.g*(lookup(base+ivec3(0,1,0))-a)+f.r*(lookup(base+ivec3(1,1,0))-lookup(base+ivec3(0,1,0)))+f.b*(d-lookup(base+ivec3(1,1,0)));
}
float curve(float v) {
  float p=clamp(v,0.0,1.0)*4095.0;
  int lo=int(floor(p));
  return mix(texelFetch(displayCurve,ivec2(lo,0),0).r,texelFetch(displayCurve,ivec2(min(lo+1,4095),0),0).r,fract(p));
}
void main() {
  vec4 inputColor=texture(tDiffuse,vUv);
  vec3 logColor=(log2(max(inputColor.rgb*exp2(exposure),vec3(1e-10)))+12.473931188)/25.0;
  vec3 mapped=tetrahedral(logColor)/0.66;
  outputColor=vec4(curve(mapped.r),curve(mapped.g),curve(mapped.b),inputColor.a);
}`;

export async function loadFilmicMaterial(base='/render-settings/') {
  const [lut, response]=await Promise.all([
    new LUTCubeLoader().setType(T.FloatType).loadAsync(base+'filmic_desat_33.cube'),
    fetch(base+'filmic_to_0-70_1-03.spi1d'),
  ]);
  if(!response.ok)throw Error('无法读取已归档 Filmic 曲线');
  const text=await response.text(), data=Float32Array.from(text.slice(text.indexOf('{')+1,text.indexOf('}')).trim().split(/\s+/).map(Number));
  if(lut.size!==33||data.length!==4096)throw Error('Filmic LUT 尺寸不符');
  const curve=new T.DataTexture(data,4096,1,T.RedFormat,T.FloatType);curve.needsUpdate=true;
  return new T.ShaderMaterial({
    glslVersion:T.GLSL3, depthTest:false, depthWrite:false, toneMapped:false,
    uniforms:{tDiffuse:{value:null},desaturation:{value:lut.texture3D},displayCurve:{value:curve},exposure:{value:0}},
    vertexShader:'out vec2 vUv; void main(){vUv=uv;gl_Position=projectionMatrix*modelViewMatrix*vec4(position,1.0);}',
    fragmentShader:filmicFragment,
  });
}

export async function installSavedRender(renderer,scene,camera,scale) {
  const response=await fetch('/render-settings/settings.json');
  if(!response.ok)throw Error('无法读取旧 Blender 渲染设置');
  const settings=await response.json();
  if(settings.color.view!=='Filmic'||settings.color.look!=='None'||settings.color.gamma!==1)throw Error('未支持的旧场景色彩变换');
  renderer.toneMapping=T.NoToneMapping;
  const worldColor=new T.Color().fromArray(settings.world.color_linear).multiplyScalar(settings.world.strength);
  scene.background=worldColor;
  const worldScene=new T.Scene();worldScene.background=worldColor;
  const pmrem=new T.PMREMGenerator(renderer);scene.environment=pmrem.fromScene(worldScene).texture;pmrem.dispose();
  RectAreaLightUniformsLib.init();
  for(const record of settings.lights){
    // Both engines use Lambertian radiance: power / (pi * area).
    // Scaling every position and light dimension preserves solid angles.
    const radiance=record.power/(Math.PI*record.width*record.height);
    const light=new T.RectAreaLight(new T.Color().fromArray(record.color_linear),radiance,record.width*scale,record.height*scale);
    light.position.fromArray(record.position).multiplyScalar(scale);
    light.quaternion.fromArray(record.quaternion_xyzw);scene.add(light);
  }
  const target=new T.WebGLRenderTarget(1,1,{type:T.HalfFloatType,samples:4});
  const composer=new EffectComposer(renderer,target);
  composer.addPass(new RenderPass(scene,camera));
  const material=await loadFilmicMaterial();material.uniforms.exposure.value=settings.color.exposure;
  composer.addPass(new ShaderPass(material));
  return {composer,settings};
}
