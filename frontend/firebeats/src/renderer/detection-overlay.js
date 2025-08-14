export class DetectionOverlay{
  constructor({ video, canvas, endpoint, cameraId, onBoxes=()=>{}, onFps=()=>{} }){
    this.video = video; this.canvas = canvas; this.endpoint = endpoint; this.cameraId = cameraId;
    this.onBoxes = onBoxes; this.onFps = onFps; this.timer = null; this.ctx = canvas.getContext('2d');
    this.lastT = 0; this.off = document.createElement('canvas'); this.offCtx = this.off.getContext('2d');
  }
  start(){ this.stop(); this.loop(); }
  stop(){ if(this.timer) cancelAnimationFrame(this.timer); this.timer=null; this.ctx.clearRect(0,0,this.canvas.width,this.canvas.height); }
  async loop(){
    const draw = async ()=>{
      // Size once per frame in case layout changed
      const r = this.video.getBoundingClientRect(); this.canvas.width=r.width; this.canvas.height=r.height; this.off.width=r.width; this.off.height=r.height;
      // Draw current frame to offscreen
      this.offCtx.drawImage(this.video, 0, 0, r.width, r.height);
      const blob = await new Promise(res=> this.off.toBlob(res, 'image/jpeg', 0.7));
      if(blob){
        try{
          const ab = await blob.arrayBuffer();
          const resp = await fetch(this.endpoint, { method:'POST', headers: { 'Content-Type':'application/octet-stream','camera-id': this.cameraId }, body: ab });
          if(resp.ok){
            const data = await resp.json();
            this.drawBoxes(data.boxes||[], r.width, r.height);
            this.onBoxes((data.boxes||[]).length);
          }
        }catch(e){ /* silent; keep overlay alive */ }
      }
      // FPS
      const now = performance.now(); if(this.lastT){ this.onFps(1000/(now-this.lastT)); } this.lastT = now;
      this.timer = requestAnimationFrame(draw);
    };
    this.timer = requestAnimationFrame(draw);
  }
  drawBoxes(boxes, w, h){
    const ctx = this.ctx; ctx.clearRect(0,0,w,h); ctx.lineWidth=3; ctx.font='16px system-ui'; ctx.shadowColor='#000'; ctx.shadowBlur=2;
    boxes.forEach(b=>{
      const [x1,y1,x2,y2,label='fire',score] = b;
      const norm = (x1<=1 && y1<=1 && x2<=1 && y2<=1);
      const X1 = norm? x1*w : x1, Y1 = norm? y1*h : y1, X2 = norm? x2*w : x2, Y2 = norm? y2*h : y2;
      ctx.strokeStyle = '#ffe600'; ctx.strokeRect(X1,Y1,X2-X1,Y2-Y1);
      const text = `${label}${score?` ${(score*100).toFixed(0)}%`:''}`;
      const tw = ctx.measureText(text).width; ctx.fillStyle='#ffe600'; ctx.fillRect(X1, Math.max(0,Y1-20), tw+8, 20);
      ctx.fillStyle='#000'; ctx.fillText(text, X1+4, Math.max(12,Y1-6));
    });
  }
}