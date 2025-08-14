export class HlsPlayer{
  constructor(video, log = ()=>{}, onLiveLag = ()=>{}){
    this.video = video; this.hls = null; this.onLiveLag = onLiveLag; this.log = log;
  }
  async play(m3u8){
    const v = this.video;
    if(window.Hls && window.Hls.isSupported()){
      this.hls = new window.Hls({ lowLatencyMode:true, liveBackBufferLength:0, maxLiveSyncPlaybackRate:1.5 });
      this.hls.on(window.Hls.Events.ERROR, (_e,data)=>{ this.log('HLS error: '+data?.details); });
      this.hls.on(window.Hls.Events.FRAG_BUFFERED, ()=>{
        if(v.buffered.length){
          const end = v.buffered.end(v.buffered.length-1);
          const lag = (end - v.currentTime)*1000;
          this.onLiveLag(lag);
          if(end - v.currentTime > 1) v.currentTime = end - 0.1; // jump to live edge
        }
      });
      this.hls.loadSource(m3u8);
      this.hls.attachMedia(v);
      await v.play();
    }else{
      // Safari: native HLS
      v.src = m3u8; await v.play();
    }
  }
  destroy(){ if(this.hls){ this.hls.destroy(); this.hls=null; } this.video.removeAttribute('src'); this.video.load(); }
}