// cctv.js
import { cctv } from './config.js';

const els = {
  img:      document.getElementById('cctvImg'),
  sel:      document.getElementById('cctvStreamSel'),
  loadBtn:  document.getElementById('cctvLoad'),
  stopBtn:  document.getElementById('cctvStop'),
  testBtn:  document.getElementById('cctvTest'),
  camId:    document.getElementById('cctvCamId'),
  streams:  document.getElementById('cctvStreams'),
  active:   document.getElementById('cctvActive'),
  fire:     document.getElementById('cctvFire'),
  last:     document.getElementById('cctvLast'),
  log:      document.getElementById('cctvLog'),
};

let pollTimer = null;

function log(msg){
  const ts = new Date().toLocaleTimeString();
  els.log.textContent += `[${ts}] ${msg}\n`;
  els.log.scrollTop = els.log.scrollHeight;
}

async function fetchJson(url){
  const r = await fetch(url, { cache: 'no-store' });
  if(!r.ok) throw new Error(`${r.status} ${r.statusText}`);
  return r.json();
}

async function populateStreams(names) {
  // Always replace options with what backend reports
  els.sel.innerHTML = '';
  for (const n of names) {
    const opt = document.createElement('option');
    opt.value = opt.textContent = n;
    els.sel.appendChild(opt);
  }
}

async function refreshStatus(){
  try{
    const s = await fetchJson(cctv.status());
    els.camId.textContent   = s.camera_id ?? '—';
    els.streams.textContent = (s.streams || []).join(', ') || '—';
    els.active.textContent  = Object.keys(s.active_streams || {}).join(', ') || '—';

    if (Array.isArray(s.streams) && s.streams.length) {
      await populateStreams(s.streams);       // <— always sync dropdown
    }
  }catch(e){ log('status error: '+e.message); }
}

async function refreshFire(){
  try{
    const f = await fetchJson(cctv.fireStatus());
    els.fire.textContent = String(f.fire_detected ?? false);
    els.last.textContent = f.last_check ?? '—';
  }catch(e){ log('fire status error: '+e.message); }
}

function startPolling(){
  stopPolling();
  pollTimer = setInterval(()=>{ refreshStatus(); refreshFire(); }, 2000);
}
function stopPolling(){ if(pollTimer){ clearInterval(pollTimer); pollTimer=null; } }

function loadStream(){
  const which = els.sel.value;                      // <— use the right element
  if (!which) { log('no stream selected'); return; }
  els.img.src = cctv.streamUrl(which) + `?t=${Date.now()}`; // cache-bust
  log(`loading /video_feed/${which}`);
  startPolling();
}

function stopStream(){
  els.img.src = '';
  stopPolling();
  log('stopped stream');
}

async function testDetection(){
  try{
    const r = await fetchJson(cctv.testDetect());
    log('test detection: '+JSON.stringify(r));
    await refreshFire();
  }catch(e){ log('test error: '+e.message); }
}

export function initCctv(){
  els.loadBtn.addEventListener('click', loadStream);
  els.stopBtn.addEventListener('click', stopStream);
  els.testBtn.addEventListener('click', testDetection);

  refreshStatus(); 
  refreshFire();
}
