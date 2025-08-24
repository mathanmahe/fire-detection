const HLS_PORT   = 8080; 
const RTMP_PORT  = 1935; 
const rtsp_port = 8082; 
const API_PORT   = 9000;   // detection server
const USE_TUNNEL = false;  

export const config = {
  rtmp: () => `rtmp://${location.hostname}:${RTMP_PORT}/live/stream`,
  hls:  () => `${location.protocol}//${location.hostname}:${HLS_PORT}/hls/stream.m3u8`,
  detectionEndpoint: `http://${location.hostname}:${API_PORT}/detect`,
  webrtcOfferUrl: `${location.protocol}//${location.hostname}:${HLS_PORT}/webrtc/offer`,
};


// cctv config
const host = (location.hostname && location.hostname.length) ? location.hostname : 'localhost';
const proto = (location.protocol === 'file:') ? 'http:' : location.protocol;

export const cctv = {
  base:       `${proto}//${host}:${rtsp_port}`,
  streamUrl:  (name) => `${proto}//${host}:${rtsp_port}/video_feed/${encodeURIComponent(name)}`,
  status:     ()      => `${proto}//${host}:${rtsp_port}/api/status`,
  fireStatus: ()      => `${proto}//${host}:${rtsp_port}/api/fire_status`,
  testDetect: ()      => `${proto}//${host}:${rtsp_port}/api/test_fire_detection`,
};

// for testing on Mathan's machine
// const HLS_PORT   = 8082;   // change to 8080
// const RTMP_PORT  = 1936;   // change to 1935
// const rtsp_port = 8083 // change to 8082