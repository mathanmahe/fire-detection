// export const config = {
//   // HLS playlist served by your backend container (final_drone.py)
//   hls: () => `${location.protocol}//${location.host}/hls/stream.m3u8`,
//   // RTMP publish target to show to the operator/drone pilot
//   rtmp: () => `rtmp://${location.hostname}:1935/live/stream`,
//   // Lambda (or API GW) endpoint that accepts raw image bytes & returns boxes
//   detectionEndpoint: 'https://2cwzmjzkx4.execute-api.us-east-1.amazonaws.com/default/fire-frame-receiver',
//   // Control‑plane endpoint that proxies AWS WebRTC signaling - TODO
//   webrtcOfferUrl: '/api/webrtc/offer',
// };


//attempt to connect to backend
// export const config = {
//   rtmp: () => `rtmp://${location.hostname}:1935/live/stream`,
//   hls:  () => `${location.protocol}//${location.hostname}:8080/hls/stream.m3u8`,
//   // If you don’t have signaling yet, leave this as a dummy (you won’t click WebRTC)
//   webrtcOfferUrl: `${location.protocol}//${location.hostname}:8080/webrtc/offer`,
//   // Point to your detector (real Lambda or a local mock – see Optionals below)
//   detectionEndpoint: `http://${location.hostname}:9000/detect`
// };


//connection with the python version
// export const config = {
//   hls:  () => 'http://localhost:8082/hls/stream.m3u8',
//   rtmp: () => 'rtmp://localhost:1936/live/stream',
//   detectionEndpoint: 'http://localhost:9000/detect',       // or your Lambda
//   webrtcOfferUrl: 'http://localhost:8082/webrtc/offer'      // when implemented
// };

const HLS_PORT   = 8082;   // change to 8080
const RTMP_PORT  = 1936;   // change to 1935
const API_PORT   = 9000;   // detection server
const USE_TUNNEL = false;  // e.g. local dev tunnel

export const config = {
  rtmp: () => `rtmp://${location.hostname}:${RTMP_PORT}/live/stream`,
  hls:  () => `${location.protocol}//${location.hostname}:${HLS_PORT}/hls/stream.m3u8`,
  detectionEndpoint: `http://${location.hostname}:${API_PORT}/detect`,
  webrtcOfferUrl: `${location.protocol}//${location.hostname}:${HLS_PORT}/webrtc/offer`,

  // // cctv 
  // hlsBase: () => 'http://localhost:8082/hls/live',
  // // API endpoints (local edge)
  // api: {
  //   list:  () => 'http://localhost:8082/api/cameras',
  //   add:   () => 'http://localhost:8082/api/cameras',
  //   start: (id)=> `http://localhost:8082/api/cameras/${id}/start`,
  //   stop:  (id)=> `http://localhost:8082/api/cameras/${id}/stop`,
  //   test:  (id)=> `http://localhost:8082/api/cameras/${id}/test`,
  // }
};


// export const cctv = {
//   base: `${location.protocol}//${location.hostname}:8083`, // flask port in camera_fire_final_local.py
//   // streamUrl: (which = 'sub') => `${location.protocol}//${location.hostname}:8083/video_feed/${which}`,
//   streamUrl: (name) => `${HTTP}:8083/video_feed/${name}`,
//   status:     () => `${location.protocol}//${location.hostname}:8083/api/status`,
//   fireStatus: () => `${location.protocol}//${location.hostname}:8083/api/fire_status`,
//   testDetect: () => `${location.protocol}//${location.hostname}:8083/api/test_fire_detection`,
// };

// config.js
const host = (location.hostname && location.hostname.length) ? location.hostname : 'localhost';
const proto = (location.protocol === 'file:') ? 'http:' : location.protocol;
const rtsp_port = 8083
export const cctv = {
  base:       `${proto}//${host}:${rtsp_port}`,
  streamUrl:  (name) => `${proto}//${host}:${rtsp_port}/video_feed/${encodeURIComponent(name)}`,
  status:     ()      => `${proto}//${host}:${rtsp_port}/api/status`,
  fireStatus: ()      => `${proto}//${host}:${rtsp_port}/api/fire_status`,
  testDetect: ()      => `${proto}//${host}:${rtsp_port}/api/test_fire_detection`,
};