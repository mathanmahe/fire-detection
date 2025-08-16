import { config } from './config.js';
import { HlsPlayer } from './player-hls.js';
import { startWebRtc, stopWebRtc } from './player-webrtc.js';
import { DetectionOverlay } from './detection-overlay.js';

// getting elements from the dom
const els = {
  video: document.getElementById('video'),
  overlay: document.getElementById('overlay'),
  playHls: document.getElementById('playHls'),
  startRtc: document.getElementById('startRtc'),
  stop: document.getElementById('stop'),
  rtmpUrl: document.getElementById('rtmpUrl'),
  hlsUrl: document.getElementById('hlsUrl'),
  copyRtmp: document.getElementById('copyRtmp'),
  copyHls: document.getElementById('copyHls'),
  testHls: document.getElementById('testHls'),
  cameraId: document.getElementById('cameraId'),
  toggleDet: document.getElementById('toggleDet'),
  status: document.getElementById('status'),
  log: document.getElementById('log'),
  fps: document.getElementById('fps'),
  live: document.getElementById('live'),
  mode: document.getElementById('mode'),
  lastDet: document.getElementById('lastDet'),
};

let hlsPlayer = null;
let overlay = null;
let mode = 'idle';

function log(msg){
  const ts = new Date().toLocaleTimeString();
  els.log.textContent += `[${ts}] ${msg}
`;
  els.log.scrollTop = els.log.scrollHeight;
  els.status.textContent = msg;
}

function setMode(m){ mode = m; els.mode.textContent = m; }

function updateUrls(){
  els.rtmpUrl.value = config.rtmp();
  els.hlsUrl.value = config.hls();
}

async function testHls(){
  try{
    const res = await fetch(els.hlsUrl.value, { cache: 'no-store' });
    if(!res.ok) throw new Error(res.status + ' ' + res.statusText);
    const txt = await res.text();
    const ok = /#EXTINF/.test(txt);
    log(ok ? 'HLS OK: segments present' : 'HLS playlist exists but no segments yet');
  }catch(e){ log('HLS test failed: ' + e.message); }
}

function sizeOverlay(){
  const r = els.video.getBoundingClientRect();
  els.overlay.width = Math.round(r.width);
  els.overlay.height = Math.round(r.height);
}

window.addEventListener('resize', sizeOverlay);

// Wire UI
updateUrls();
els.cameraId.value = 'ec2_camera';
els.copyRtmp.onclick = () => navigator.clipboard.writeText(els.rtmpUrl.value);
els.copyHls.onclick = () => navigator.clipboard.writeText(els.hlsUrl.value);
els.testHls.onclick = testHls;

els.playHls.onclick = async () => {
  stopAll();
  setMode('HLS');
  hlsPlayer = new HlsPlayer(els.video, log, (liveLagMs)=> els.live.textContent = liveLagMs.toFixed(0)+' ms');
  await hlsPlayer.play(els.hlsUrl.value);
  sizeOverlay();
  startOverlayIfEnabled();
};

els.startRtc.onclick = async () => {
  stopAll();
  setMode('WebRTC');
  try{
    await startWebRtc(els.video, { cameraId: els.cameraId.value, offerUrl: config.webrtcOfferUrl, onLog: log });
    sizeOverlay();
    startOverlayIfEnabled();
  }catch(e){ log('WebRTC failed: '+e.message); setMode('idle'); }
};

els.stop.onclick = () => stopAll();

function resetUiStats() {
  els.mode.textContent = 'idle';
  els.status.textContent = 'Stopped';
  els.fps.textContent = '—';
  els.live.textContent = '—';
  els.lastDet.textContent = '—';
}

function clearVideoElement() {
  try { els.video.pause(); } catch {}
  // Remove any active stream/source
  els.video.srcObject = null;
  els.video.removeAttribute('src');
  els.video.load(); // force the element to reset its internal state
}


function stopAll(){
  if(hlsPlayer){ hlsPlayer.destroy(); hlsPlayer = null; }
  stopWebRtc();
  if(overlay){ overlay.stop(); overlay = null; }
  clearVideoElement();
  resetUiStats();
  setMode('idle');
}

function startOverlayIfEnabled(){
  if(!els.toggleDet.checked) return;
  overlay = new DetectionOverlay({
    video: els.video,
    canvas: els.overlay,
    cameraId: els.cameraId.value,
    endpoint: config.detectionEndpoint,
    onBoxes: (count)=> { els.lastDet.textContent = new Date().toLocaleTimeString(); },
    onFps: (fps)=> { els.fps.textContent = fps.toFixed(1); }
  });
  overlay.start();
}

els.toggleDet.onchange = () => {
  if(els.toggleDet.checked){ startOverlayIfEnabled(); }
  else if(overlay){ overlay.stop(); overlay = null; }
};

// keyboard shortcuts
window.addEventListener('keydown', (e)=>{
  if(e.key.toLowerCase()==='d') els.toggleDet.click();
  if(e.key.toLowerCase()==='l') testHls();
});