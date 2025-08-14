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
export const config = {
  rtmp: () => `rtmp://${location.hostname}:1935/live/stream`,
  hls:  () => `${location.protocol}//${location.hostname}:8080/hls/stream.m3u8`,
  // If you don’t have signaling yet, leave this as a dummy (you won’t click WebRTC)
  webrtcOfferUrl: `${location.protocol}//${location.hostname}:8080/webrtc/offer`,
  // Point to your detector (real Lambda or a local mock – see Optionals below)
  detectionEndpoint: `http://${location.hostname}:9000/detect`
};