// Experimental bridge. Never exposes arbitrary CDP or arbitrary JavaScript to Python.
const BASE = 'http://127.0.0.1:19876';
let session = null;
let desiredTab = null;
let connectionGeneration = 0;
const pause = ms => new Promise(resolve => setTimeout(resolve, ms));
function isGame(url) {
  try { const u = new URL(url); return u.origin === 'https://mc.kurogames.com' && u.pathname === '/cloud/index.html'; }
  catch { return false; }
}
function surfaceMetrics(capture = false) {
  const candidates = [...document.querySelectorAll('#sr-canvas, video')].map(e => {
    const r = e.getBoundingClientRect(), s = getComputedStyle(e), canvas = e.tagName === 'CANVAS';
    const source = canvas ? [e.width, e.height] : [e.videoWidth, e.videoHeight];
    return {ready: (canvas || e.readyState >= 2) && source[0] > 0 && source[1] > 0 &&
      r.width > 100 && r.height > 100 && s.display !== 'none' && s.visibility !== 'hidden' && Number(s.opacity) > 0,
      element:e, kind: canvas ? 'canvas' : 'video', rect: [r.x,r.y,r.width,r.height], source,
      fit: s.objectFit, position: s.objectPosition, viewport: [innerWidth, innerHeight],
      pointerLock: !!document.pointerLockElement,
      stream: canvas ? null : {time:e.currentTime,paused:e.paused,ended:e.ended,
        frames:e.getVideoPlaybackQuality?.().totalVideoFrames},
      visibility:document.visibilityState};
  }).filter(m => m.ready);
  const selected = candidates.find(m => m.kind === 'video') || candidates[0];
  if (!selected) {
    if (capture) throw new Error('游戏画面尚未就绪');
    return {ready:false};
  }
  const {element,...metrics} = selected;
  if (!capture) return metrics;
  function copy(freshness) {
    const output = document.createElement('canvas');
    [output.width,output.height] = metrics.source;
    output.getContext('2d').drawImage(element,0,0);
    return {data:output.toDataURL('image/png').split(',')[1],format:'png',gameSurface:true,metrics,freshness};
  }
  if (metrics.kind === 'canvas') return new Promise((resolve,reject) => {
    // WebGL buffers may be cleared after compositing. Read in the render
    // callback, not from a timer between frames.
    const timer=setTimeout(() => { cancelAnimationFrame(id); reject(new Error('Canvas frame stalled')); },1500);
    const id=requestAnimationFrame(() => {
      clearTimeout(timer);
      try { resolve(copy(null)); } catch(error) { reject(error); }
    });
  });
  // Wait for a newly presented video frame instead of repeatedly copying a
  // previously decoded loading screen. Never fall back to page screenshots.
  if (!element.requestVideoFrameCallback) throw new Error('Fresh video frame API unavailable');
  return new Promise((resolve,reject) => {
    const timer=setTimeout(() => {
      element.cancelVideoFrameCallback(id);
      reject(new Error('Video frame stalled'));
    },1500);
    const id=element.requestVideoFrameCallback((now,meta) => {
      clearTimeout(timer);
      try { resolve(copy({mediaTime:meta.mediaTime,presentedFrames:meta.presentedFrames})); }
      catch(error) { reject(error); }
    });
  });
}
async function cdp(s, method, params = {}) { return chrome.debugger.sendCommand({tabId:s.tabId}, method, params); }
async function release(s) {
  const errors = [];
  for (const payload of s.keys.values()) {
    try { await cdp(s, 'Input.dispatchKeyEvent', {...payload, type:'keyUp', modifiers:0}); }
    catch(e) { errors.push(e); }
  }
  for (const button of s.buttons) {
    try { await cdp(s,'Input.dispatchMouseEvent',{type:'mouseReleased',button,buttons:0,x:s.x,y:s.y,clickCount:1}); }
    catch(e) { errors.push(e); }
  }
  s.keys.clear(); s.buttons.clear();
  if (errors.length) throw new Error('按键释放未全部确认；请在游戏内检查。');
}
async function disconnect(s) {
  if (!s) return;
  s.stopped = true;
  if (session === s) session = null;
  // Let an already dispatched event finish, then release it. No new input can start.
  try { await s.inflight; } catch {}
  try { await release(s); } finally {
    try { await cdp(s,'Emulation.clearDeviceMetricsOverride'); } catch {}
    try { await chrome.debugger.detach({tabId:s.tabId}); } catch {}
  }
}
async function request(s, path, data) {
  const response = await fetch(BASE + path, {method:'POST', headers:{'Content-Type':'application/json',
    Authorization:'Bearer '+s.token},body:JSON.stringify(data),signal:AbortSignal.timeout(2500)});
  if (!response.ok) throw new Error('本机连接已停止或配对码不正确。');
  return response.json();
}
async function execute(s, job) {
  if (s.stopped || Date.now()/1000 > job.expires) throw new Error('Command expired');
  const tab = await chrome.tabs.get(s.tabId);
  if (!isGame(tab.url)) throw new Error('已离开云鸣潮，连接停止。');
  const p = job.params;
  if (job.op === 'metrics') {
    if (p.diagnostics) {
      const result=await cdp(s,'Runtime.evaluate',{expression:'({inner:[innerWidth,innerHeight],outer:[outerWidth,outerHeight],dpr:devicePixelRatio,visual:visualViewport?{width:visualViewport.width,height:visualViewport.height,scale:visualViewport.scale,offsetLeft:visualViewport.offsetLeft,offsetTop:visualViewport.offsetTop}:null})',returnByValue:true});
      return {...result.result.value,zoom:await chrome.tabs.getZoom(s.tabId),window:await chrome.windows.get(tab.windowId)};
    }
    const result = await cdp(s,'Runtime.evaluate',{expression:'('+surfaceMetrics.toString()+')()',returnByValue:true});
    if (result.exceptionDetails) throw new Error('无法检测游戏画面');
    return result.result.value;
  }
  if (job.op === 'frame') {
    if (p.mode === 'page') {
      const shot = await cdp(s,'Page.captureScreenshot',{format:'jpeg',quality:95});
      return {...shot, fullViewport:true};
    }
    const result = await cdp(s,'Runtime.evaluate',{
      expression:'('+surfaceMetrics.toString()+')(true)',returnByValue:true,awaitPromise:true});
    if (result.exceptionDetails) throw new Error('读取游戏视频帧失败；已停止输入');
    return result.result.value;
  }
  if (job.op === 'focus') {
    await chrome.windows.update(tab.windowId,{state:'normal',focused:true});
    await chrome.tabs.update(s.tabId,{active:true});
    return {};
  }
  if (job.op === 'enter') {
    const result = await cdp(s,'Runtime.evaluate',{expression:`(() => {
      const b=[...document.querySelectorAll('button')].find(e=>e.textContent.trim()==='进入游戏'&&!e.disabled&&e.getBoundingClientRect().width>0);
      if(!b)return null;const r=b.getBoundingClientRect();return {x:r.x+r.width/2,y:r.y+r.height/2};})()`,returnByValue:true});
    const pt = result.result.value;
    if (!pt) throw new Error('未找到可点击的进入游戏按钮');
    s.x=pt.x; s.y=pt.y; s.buttons.add('left');
    try { await cdp(s,'Input.dispatchMouseEvent',{type:'mousePressed',button:'left',buttons:1,clickCount:1,...pt}); }
    finally {
      await cdp(s,'Input.dispatchMouseEvent',{type:'mouseReleased',button:'left',buttons:0,clickCount:1,...pt});
      s.buttons.delete('left');
    }
    return {};
  }
  if (job.op === 'release') { await release(s); return {}; }
  if (job.op !== 'input') throw new Error('Unsupported operation');
  if (s.stopped) throw new Error('Input stopped');
  const {method, params} = p;
  if (method === 'Input.insertText') {
    if (typeof params.text !== 'string' || params.text.length > 256) throw new Error('Invalid game text');
    await cdp(s,method,{text:params.text});
  } else if (method === 'Input.dispatchKeyEvent') {
    if (!['keyDown','keyUp'].includes(params.type) || !/^(Key[A-Z]|Digit[0-9]|F([1-9]|1[0-2])|Escape|Enter|Space|Tab|Backspace|Delete|Shift(Left|Right)|Control(Left|Right)|Alt(Left|Right)|Arrow(Up|Down|Left|Right))$/.test(params.code)) throw new Error('Unsupported key');
    if (params.type === 'keyDown') s.keys.set(params.code,params);
    await cdp(s,method,params);
    if (params.type === 'keyUp') s.keys.delete(params.code);
  } else if (method === 'Input.dispatchMouseEvent') {
    if (!['mouseMoved','mousePressed','mouseReleased','mouseWheel'].includes(params.type) ||
      !Number.isFinite(params.x) || !Number.isFinite(params.y) || params.x < 0 || params.y < 0 || params.x > 1280 || params.y > 720) throw new Error('Invalid mouse event');
    s.x=params.x; s.y=params.y;
    if (params.type === 'mousePressed') s.buttons.add(params.button);
    await cdp(s,method,params);
    if (params.type === 'mouseReleased') s.buttons.delete(params.button);
  } else throw new Error('CDP method not allowed');
  return {};
}
async function poll(s) {
  try {
    while (!s.stopped) {
      const {command} = await request(s,'/poll',{});
      if (command) {
        let result, error;
        try { s.inflight = execute(s,command); result = await s.inflight; }
        catch(e) { error=e.message; }
        await request(s,'/result',{id:command.id,result,error});
        if (error && ['input','enter'].includes(command.op)) { desiredTab = null; throw new Error(error); }
      }
      await pause(30);
    }
  } catch {
    await disconnect(s).catch(()=>{});
    if (desiredTab === s.tabId) reconnect(s.tabId, connectionGeneration);
  }
}
async function connect(tabId, generation) {
  const tab = await chrome.tabs.get(tabId);
  if (!isGame(tab.url)) { desiredTab = null; throw new Error('请先选择已登录的官方云鸣潮标签页'); }
  const {token} = await request({token:''},'/connect',{});
  if (generation !== connectionGeneration || desiredTab !== tabId) return;
  const s={tabId:tab.id,token,keys:new Map(),buttons:new Set(),x:640,y:360,stopped:false};
  await chrome.debugger.attach({tabId:tab.id},'1.3');
  if (generation !== connectionGeneration || desiredTab !== tabId) { await disconnect(s); return; }
  session=s;
  try {
    await cdp(s,'Emulation.setDeviceMetricsOverride',{width:1280,height:720,deviceScaleFactor:1,mobile:false});
    poll(s);
  } catch(e) { await disconnect(s); throw e; }
}
async function reconnect(tabId, generation) {
  while (desiredTab === tabId && generation === connectionGeneration && !session) {
    await pause(1500);
    if (desiredTab !== tabId || generation !== connectionGeneration) return;
    try { await connect(tabId,generation); return; } catch {}
  }
}
chrome.runtime.onMessage.addListener((message, sender, reply) => {
  (async () => {
    if (message.op === 'stop') { desiredTab=null; connectionGeneration++; await disconnect(session); return {}; }
    if (message.op !== 'connect') throw new Error('Unknown action');
    if (session && session.tabId === message.tabId) return {};
    if (session) throw new Error('请先停止当前连接');
    desiredTab=message.tabId;
    const generation=++connectionGeneration;
    try {
      await connect(message.tabId,generation);
      return {};
    } catch(e) { desiredTab=null; throw e; }
  })().then(reply,e=>reply({error:e.message}));
  return true;
});
chrome.debugger.onDetach.addListener(source => {
  if (session && source.tabId===session.tabId) { desiredTab=null; connectionGeneration++; session.stopped=true; session=null; }
});
