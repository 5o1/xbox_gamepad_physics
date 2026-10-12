/** Pointer-lock input; pixels are converted to world commands by the physics owner. */
export function installCursor(canvas,{send,isConnected,mode,error}) {
  let armed=false, keys=new Set(), motion=null, focusSeq=0;
  const fine=()=>keys.has('ShiftLeft')||keys.has('ShiftRight');
  function flushMouse(){
    const pending=motion;motion=null;
    if(pending&&(pending.x||pending.y)&&armed&&document.pointerLockElement===canvas&&isConnected())
      send('delta',{screen_pixels:[pending.x,pending.y],fine:pending.fine,event_time_ms:pending.eventTime});
  }
  function stop(reason){
    const active=armed;armed=false;keys.clear();motion=null;
    if(active)send('stop',{reason});
    if(document.pointerLockElement===canvas)document.exitPointerLock();
    mode('已停住 · 点击画面锁定指针');
  }
  canvas.addEventListener('click',async()=>{
    if(!armed&&isConnected()){
      canvas.focus();
      try {await canvas.requestPointerLock();} catch(e){error(String(e));stop('pointer-lock-error');}
    }
  });
  document.addEventListener('pointerlockchange',()=>{
    if(document.pointerLockElement===canvas&&isConnected()){
      armed=true;keys.clear();motion=null;canvas.focus();focusSeq=send('focus');
      mode('夹爪光标 · 鼠标平移 / 左闭右开');
    } else if(armed)stop('pointer-unlocked');
  });
  document.addEventListener('pointerlockerror',()=>{error('Pointer Lock failed');stop('pointer-lock-error');});
  canvas.addEventListener('blur',()=>stop('blur'));
  window.addEventListener('blur',()=>stop('window-blur'));
  document.addEventListener('visibilitychange',()=>{if(document.hidden)stop('hidden');});
  window.addEventListener('keydown',e=>{
    if(e.code==='Escape'){stop('escape');return;}
    if(!armed||document.pointerLockElement!==canvas)return;
    if(!['KeyW','KeyA','KeyS','KeyD','KeyQ','KeyE','ShiftLeft','ShiftRight','Tab','KeyG'].includes(e.code))return;
    e.preventDefault();flushMouse();
    if(e.code==='KeyG'){if(!e.repeat)send('delta',{toggle_gamepad:true});return;}
    if(e.code==='Tab'){if(!e.repeat)send('delta',{toggle:true});return;}
    // Browser key repeat is ignored; the owner repeats in simulation time.
    if(!keys.has(e.code)){keys.add(e.code);send('keys',{keys:[...keys]});}
  });
  window.addEventListener('keyup',e=>{
    if(!keys.has(e.code))return;
    flushMouse();keys.delete(e.code);
    if(armed)send('keys',{keys:[...keys]});
  });
  canvas.addEventListener('mousemove',e=>{
    if(!armed||document.pointerLockElement!==canvas||!isConnected())return;
    if(motion&&motion.fine!==fine())flushMouse();
    motion??={x:0,y:0,fine:fine(),eventTime:performance.now()};motion.x+=e.movementX;motion.y+=e.movementY;
  });
  canvas.addEventListener('mousedown',e=>{
    if(!armed||document.pointerLockElement!==canvas)return;
    if(e.button===0||e.button===2){e.preventDefault();flushMouse();send('delta',{grip:e.button===0?'close':'open',fine:fine()});}
  });
  canvas.addEventListener('contextmenu',e=>e.preventDefault());
  // Wheel no longer drives the gripper; suppress page scrolling while locked.
  canvas.addEventListener('wheel',e=>{if(armed)e.preventDefault();},{passive:false});
  return {flushMouse,stop,get armed(){return armed;},get focusSeq(){return focusSeq;}};
}
