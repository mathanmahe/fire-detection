let pc = null; let stream = null;
export async function startWebRtc(video, { cameraId, offerUrl, onLog = ()=>{} }){
  pc = new RTCPeerConnection({ iceServers: [] });
  stream = new MediaStream();
  pc.addEventListener('track', (ev)=>{ stream.addTrack(ev.track); video.srcObject = stream; });
  pc.addEventListener('iceconnectionstatechange', ()=> onLog('ICE: '+pc.iceConnectionState));

  // Create an offer for a **receive-only** connection
  const offer = await pc.createOffer({ offerToReceiveAudio:true, offerToReceiveVideo:true });
  await pc.setLocalDescription(offer);

  // Ask your control plane to talk to AWS (e.g., Kinesis WebRTC) and return { sdpAnswer, iceServers }
  const res = await fetch(offerUrl, { method:'POST', headers:{'Content-Type':'application/json'}, body: JSON.stringify({ cameraId, sdp: offer.sdp }) });
  if(!res.ok) throw new Error('Signaling failed: '+res.status);
  const { sdpAnswer, iceServers } = await res.json();
  if(iceServers) iceServers.forEach(s=>pc.getConfiguration().iceServers.push(s));

  await pc.setRemoteDescription({ type:'answer', sdp: sdpAnswer });
}

export function stopWebRtc(){ if(pc){ pc.getSenders().forEach(s=>s.track&&s.track.stop()); pc.close(); } pc = null; }