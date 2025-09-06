#!/usr/bin/env python
"""
Universal RTSP/Webcam Web Streamer with AI Fire Detection (Webcam-enabled)
- Keeps the same Flask endpoints (/ , /video_feed/<stream>, /api/*)
- Adds webcam support so you can run this on a host machine with a local camera

Based on: camera_fire_final_local.py
"""

# ═══════════════════════════════════════════════════════════════
# IMPORTS
# ═══════════════════════════════════════════════════════════════
import cv2
import threading
import time
import signal
import sys
import base64
import requests
import numpy as np
from datetime import datetime
from flask import Flask, Response, render_template_string, jsonify
from flask_cors import CORS

# ═══════════════════════════════════════════════════════════════
# CAMERA CONFIG (original RTSP config is still here for compatibility)
# ═══════════════════════════════════════════════════════════════
CAMERA_IP = "192.168.1.50"         # ← Ignored in webcam mode
USERNAME  = "admin"
PASSWORD  = "CCTVCheck@123"        # ← Change to your password
WEB_PORT  = 8085
FRAME_RATE = 15
STREAM_QUALITY = 80                # JPEG quality 1–100

# AI Fire Detection Settings (from drone code)
FIRE_DETECTION_ENABLED = True       # ← Enable/disable fire detection
CAMERA_ID = "rtsp_camera_1"         # ← Camera identifier for AI
API_ENDPOINT = "https://2cwzmjzkx4.execute-api.us-east-1.amazonaws.com/default/fire-frame-receiver"
FIRE_CHECK_INTERVAL = 3             # ← Check for fire every N seconds

import os

INFERENCE_URL = os.getenv("INFER_URL", "http://127.0.0.1:9090/infer")
INFERENCE_AUTH = os.getenv("INFER_TOKEN")          # optional bearer token
INFERENCE_TIMEOUT = float(os.getenv("INFER_TIMEOUT", "1.5"))
# Optional: if you want to require a min conf again (the service already filters)
INFER_LOCAL_CONF = float(os.getenv("INFER_LOCAL_CONF", "0.25"))


# Webcam mode (set to True to use local webcam instead of RTSP)
USE_WEBCAM = True            # ← Set True to use the host machine's webcam
WEBCAM_INDEX = 0             # ← Usually 0 for default webcam

# ═══════════════════════════════════════════════════════════════
# AUTO-GENERATED RTSP URLS (ignored when USE_WEBCAM=True)
# ═══════════════════════════════════════════════════════════════
RTSP_URLS = {} if USE_WEBCAM else {
    'main': f"rtsp://{USERNAME}:{PASSWORD}@{CAMERA_IP}:554/h264Preview_01_main",
    'sub':  f"rtsp://{USERNAME}:{PASSWORD}@{CAMERA_IP}:554/h264Preview_01_sub",
    # Common alternatives (auto-tested)
    'alt1': f"rtsp://{USERNAME}:{PASSWORD}@{CAMERA_IP}:554/stream1",
    'alt2': f"rtsp://{USERNAME}:{PASSWORD}@{CAMERA_IP}:554/cam/realmonitor?channel=1&subtype=0",
    'alt3': f"rtsp://{USERNAME}:{PASSWORD}@{CAMERA_IP}:554/live/ch1"
}

# ═══════════════════════════════════════════════════════════════
# GLOBALS
# ═══════════════════════════════════════════════════════════════
fire_detection_stats = {
    'total_detections': 0,
    'last_detection': None,
    'current_fire_detected': False,
    'last_check_time': None,
    'total_frames_processed': 0,
    'ai_responses': []
}

# ═══════════════════════════════════════════════════════════════
# HTML (unchanged endpoints/UI)
# ═══════════════════════════════════════════════════════════════
HTML_TEMPLATE = r"""
<!DOCTYPE html>
<html lang="en">
<head>
<meta charset="UTF-8" />
<meta name="viewport" content="width=device-width, initial-scale=1.0" />
<title>Universal RTSP/Webcam Streamer + Fire Detection</title>
<style>
  body { font-family: Arial, sans-serif; color: #eee; background: #0b1220; margin: 0; }
  .container { max-width: 1200px; margin: 40px auto; padding: 20px; }
  .header { text-align: center; margin-bottom: 30px; background: rgba(0,0,0,0.3); padding: 20px; border-radius: 10px; backdrop-filter: blur(10px); }
  h1 { margin: 0 0 10px; }
  .grid { display: grid; grid-template-columns: 2fr 1fr; gap: 20px; }
  .card { background: rgba(255,255,255,0.06); border: 1px solid rgba(255,255,255,0.1); border-radius: 12px; padding: 16px; }
  .badge { display: inline-block; padding: 4px 10px; border-radius: 9999px; border: 1px solid rgba(255,255,255,0.2); font-size: 12px; }
  .ok { color: #7CFC00; }
  .warn { color: #FFD700; }
  .err { color: #FF6347; }
  video, img { width: 100%; border-radius: 10px; background: #000; }
  .row { display: grid; grid-template-columns: 1fr 1fr; gap: 12px; }
  .stats { font-family: ui-monospace, SFMono-Regular, Menlo, Monaco, Consolas, "Liberation Mono", "Courier New", monospace; font-size: 13px; line-height: 1.6; }
  .muted { color: #aaa; }
</style>
</head>
<body>
  <div class="container">
    <div class="header">
      <h1>Universal RTSP/Webcam Streamer + Fire Detection</h1>
      <div class="muted">Device: <b>{{ 'WEBCAM' if USE_WEBCAM else camera_ip }}</b> • Camera ID: <b>{{ camera_id }}</b> • Server Port: <b>{{ web_port }}</b> • Started: <b>{{ start_time }}</b></div>
    </div>

    <div class="grid">
      <div class="card">
        <h3>Live Streams</h3>
        <div class="row">
          <div>
            <div class="badge">Main</div>
            <img src="/video_feed/main" alt="Loading live stream..." />
          </div>
          <div>
            <div class="badge">Sub</div>
            <img src="/video_feed/sub" alt="Loading live stream..." />
          </div>
        </div>
      </div>

      <div class="card">
        <h3>Fire Detection</h3>
        <div class="stats">
          <div>Enabled: <span class="badge {{ 'ok' if fire_enabled else 'err' }}">{{ 'Yes' if fire_enabled else 'No' }}</span></div>
          <div>AI Endpoint: <span class="muted">{{ api_endpoint }}</span></div>
          <div>Interval: <b>{{ fire_interval }}</b> sec</div>
          <div>Total Frames Processed: <b id="frames">0</b></div>
          <div>Current Fire Detected: <b id="current">False</b></div>
          <div>Last Detection: <b id="last">—</b></div>
        </div>
      </div>
    </div>

    <div class="card">
      <h3>API</h3>
      <div class="stats">
        <div>• <a href="/api/status" target="_blank">/api/status</a></div>
        <div>• <a href="/api/fire_status" target="_blank">/api/fire_status</a></div>
        <div>• <a href="/api/test_fire_detection" target="_blank">/api/test_fire_detection</a></div>
      </div>
    </div>
  </div>

<script>
async function refresh() {
  try {
    const r = await fetch('/api/fire_status');
    const j = await r.json();
    document.getElementById('frames').textContent = j.total_frames_processed;
    document.getElementById('current').textContent = j.fire_detected;
    document.getElementById('last').textContent = j.last_detection || '—';
  } catch (e) {}
}
setInterval(refresh, 1500);
refresh();
</script>
</body>
</html>
"""

# ═══════════════════════════════════════════════════════════════
# CAMERA STREAMER
# ═══════════════════════════════════════════════════════════════
class UniversalCameraStream:
    def __init__(self):
        self.streams = {}
        self.active_streams = {}
        self.start_time = datetime.now()
        self.frame_lock = threading.Lock()
        self.fire_detection_thread = None
        self.last_detections = []
        self.last_det_size = None

    def test_rtsp_url(self, url, timeout=5):
        """Test if a stream source is accessible (RTSP URL or webcam index)."""
        cap = cv2.VideoCapture(url)
        cap.set(cv2.CAP_PROP_BUFFERSIZE, 1)
        ok = False
        if cap.isOpened():
            ret, frame = cap.read()
            ok = ret and frame is not None
        cap.release()
        return ok

    def find_working_streams(self):
        """Auto-detect working streams (RTSP or local webcam)"""
        print("🔍 Auto-detecting camera streams...")

        if USE_WEBCAM:
            # Try a few common indices
            for idx in [WEBCAM_INDEX, 0, 1, 2]:
                print(f"   Testing webcam index {idx}...")
                if self.test_rtsp_url(idx):
                    self.streams['main'] = idx
                    self.streams['sub']  = idx  # reuse same device; we will downscale SUB in software
                    print(f"   ✅ Webcam index {idx} working")
                    break
            if not self.streams:
                print("   ❌ No working webcam found")
            return len(self.streams) > 0

        # RTSP mode
        for name, url in RTSP_URLS.items():
            print(f"   Testing {name}: {str(url).replace(PASSWORD, '***')}")
            if self.test_rtsp_url(url):
                print(f"   ✅ {name} stream working")
                self.streams[name] = url
            else:
                print(f"   ❌ {name} stream failed")

        if not self.streams:
            # Fallback to basic URLs
            basic_url = f"rtsp://{USERNAME}:{PASSWORD}@{CAMERA_IP}:554/"
            if self.test_rtsp_url(basic_url):
                self.streams['main'] = basic_url
                print(f"   ✅ Basic RTSP stream working")

        return len(self.streams) > 0

    def get_frame_details(self, frame):
        gray = cv2.cvtColor(frame, cv2.COLOR_BGR2GRAY)
        brightness = float(np.mean(gray))
        mean_bgr = np.mean(frame, axis=(0, 1))
        h, w, c = frame.shape
        return {
            'timestamp': datetime.now().strftime("%H:%M:%S"),
            'frame_number': fire_detection_stats['total_frames_processed'],
            'width': int(w), 'height': int(h), 'channels': int(c),
            'brightness': brightness,
            'mean_blue': float(mean_bgr[0]),
            'mean_green': float(mean_bgr[1]),
            'mean_red': float(mean_bgr[2]),
        }

    def print_frame_details(self, d):
        print(f"[Frame {d['frame_number']}] {d['width']}x{d['height']} | B={d['brightness']:.1f} | BGR=({d['mean_blue']:.1f},{d['mean_green']:.1f},{d['mean_red']:.1f}) @ {d['timestamp']}")


    def call_inference_jpeg(self, camera_id: str, jpg_bytes: bytes):
        """POST a JPEG to the local inference service. Returns dict with detections + model + ts."""
        payload = {
            "camera_id": camera_id,
            "image_base64": base64.b64encode(jpg_bytes).decode("utf-8"),
        }
        headers = {"Content-Type": "application/json"}
        if INFERENCE_AUTH:
            headers["Authorization"] = f"Bearer {INFERENCE_AUTH}"
        r = requests.post(INFERENCE_URL, json=payload, headers=headers, timeout=INFERENCE_TIMEOUT)
        r.raise_for_status()
        return r.json()

    def send_frame_to_ai(self, frame):
        try:
            _, buf = cv2.imencode('.jpg', frame, [cv2.IMWRITE_JPEG_QUALITY, STREAM_QUALITY])
            b64 = base64.b64encode(buf.tobytes()).decode('utf-8')
            payload = {
                'camera_id': CAMERA_ID,
                'timestamp': datetime.utcnow().isoformat() + 'Z',
                'image_base64': b64
            }
            r = requests.post(API_ENDPOINT, json=payload, timeout=10)
            if r.ok:
                fire_detection_stats['ai_responses'].append(r.json())
            else:
                fire_detection_stats['ai_responses'].append({'error': r.text})
        except Exception as e:
            fire_detection_stats['ai_responses'].append({'exception': str(e)})

    def fire_detection_worker(self):
        print("[🔥] Starting fire detection worker...")
        # print(f"🤖 Using AI model at: {API_ENDPOINT}")
        print(f"🤖 Using local inference model at: {INFERENCE_URL}")
        print(f"📷 Camera ID: {CAMERA_ID}")
        print(f"🔥 Using SUB STREAM for fire detection (faster, no lag)")
        print(f"🔥 Checking for fire every {FIRE_CHECK_INTERVAL} seconds...")

        while FIRE_DETECTION_ENABLED:
            try:
                # Prefer SUB stream for speed
                src = None
                if 'sub' in self.active_streams and self.active_streams['sub']['frame'] is not None:
                    with self.frame_lock:
                        src = self.active_streams['sub']['frame'].copy()
                elif 'main' in self.active_streams and self.active_streams['main']['frame'] is not None:
                    with self.frame_lock:
                        src = self.active_streams['main']['frame'].copy()

                if src is not None:
                    details = self.get_frame_details(src)
                    self.print_frame_details(details)
                    fire_detection_stats['total_frames_processed'] += 1
                    #self.send_frame_to_ai(src)
                    # self.call_inference_jpeg(CAMERA_ID, src)
                    # fire_detection_stats['last_check_time'] = datetime.now()
                    ok, buf = cv2.imencode('.jpg', src, [cv2.IMWRITE_JPEG_QUALITY, STREAM_QUALITY])
                    if ok:
                        try:
                            out = self.call_inference_jpeg(CAMERA_ID, buf.tobytes())

                            # Expect: {"detections":[{"box":[x1,y1,x2,y2],"conf":...,"cls":0}], "model":"...", "ts":"..."}
                            detections = out.get("detections", [])
                            # Cache recent responses (for debugging/visibility)
                            fire_detection_stats['ai_responses'].append(out)
                            fire_detection_stats['ai_responses'] = fire_detection_stats['ai_responses'][-10:]

                            # Update flags using CAPTURE time as ground truth
                            now_local = datetime.now()
                            fire_detection_stats['last_check_time'] = now_local
                            has_fire = any(d.get('conf', 0.0) >= INFER_LOCAL_CONF for d in detections)
                            fire_detection_stats['current_fire_detected'] = has_fire
                            if has_fire:
                                fire_detection_stats['total_detections'] += 1
                                fire_detection_stats['last_detection'] = now_local.isoformat()

                            # (Optional) keep latest detections in the camera for drawing
                            if not hasattr(self, 'last_detections'):
                                self.last_detections = []
                            self.last_detections = detections

                            h, w = src.shape[:2]
                            self.last_det_size = (w, h)

                        except Exception as e:
                            print(f"[infer] error: {e}")
                else:
                    print("[🔥] No frame yet; waiting...")

                time.sleep(FIRE_CHECK_INTERVAL)
            except Exception as e:
                print(f"[🔥] Fire detection error: {e}")
                time.sleep(5)

    def start_stream(self, stream_name):
        """Start a specific stream (string RTSP URL or webcam index)."""
        if stream_name not in self.streams:
            return False
        if stream_name in self.active_streams:
            return True  # Already running

        url = self.streams[stream_name]
        print(f"🎬 Starting {stream_name} stream -> {url}")
        cap = cv2.VideoCapture(url)
        cap.set(cv2.CAP_PROP_BUFFERSIZE, 1)
        if not cap.isOpened():
            print(f"❌ Failed to start {stream_name} stream")
            return False

        stream_data = {
            'cap': cap,
            'frame': None,
            'running': True,
            'thread': None
        }
        self.active_streams[stream_name] = stream_data

        def update_frames():
            while stream_data['running']:
                ret, frame = stream_data['cap'].read()
                if ret:
                    # For SUB stream, downscale to ~640px width for speed
                    if stream_name == 'sub' and frame is not None:
                        h, w = frame.shape[:2]
                        if w > 640:
                            scale = 640 / w
                            frame = cv2.resize(frame, (int(w*scale), int(h*scale)))
                    else:
                        # Auto-resize very large frames for the web
                        if frame is not None:
                            height, width = frame.shape[:2]
                            if width > 1920:
                                scale = 1920 / width
                                new_width = int(width * scale)
                                new_height = int(height * scale)
                                frame = cv2.resize(frame, (new_width, new_height))
                    with self.frame_lock:
                        stream_data['frame'] = frame
                time.sleep(1.0 / FRAME_RATE)

        t = threading.Thread(target=update_frames, daemon=True)
        stream_data['thread'] = t
        t.start()
        print(f"✅ {stream_name} stream started")

        # Start fire detection once on first stream
        if FIRE_DETECTION_ENABLED and self.fire_detection_thread is None:
            self.fire_detection_thread = threading.Thread(target=self.fire_detection_worker, daemon=True)
            self.fire_detection_thread.start()
        return True

    def get_frame(self, stream_name):
        if stream_name not in self.active_streams:
            if not self.start_stream(stream_name):
                return None
        stream_data = self.active_streams[stream_name]
        if stream_data['frame'] is not None:
            with self.frame_lock:
                frame = stream_data['frame'].copy()

            # draw last detections (if any)
            if hasattr(self, 'last_detections') and self.last_detections:
                curr_h, curr_w = frame.shape[:2]
                src_w, src_h = self.last_det_size if self.last_det_size else (curr_w, curr_h)
                sx = curr_w / float(src_w)
                sy = curr_h / float(src_h)

                for det in self.last_detections:
                    x1, y1, x2, y2 = det["box"]
                    # scale from inference-source size -> current frame size
                    x1 = int(round(x1 * sx)); y1 = int(round(y1 * sy))
                    x2 = int(round(x2 * sx)); y2 = int(round(y2 * sy))
                    conf = det.get("conf", 0.0)
                    cv2.rectangle(frame, (x1, y1), (x2, y2), (0,255,0), 2)
                    cv2.putText(frame, f"fire {conf:.2f}", (x1, max(0, y1-6)),
                                cv2.FONT_HERSHEY_SIMPLEX, 0.5, (0,255,0), 1, cv2.LINE_AA)

            ret, buffer = cv2.imencode('.jpg', frame, [cv2.IMWRITE_JPEG_QUALITY, STREAM_QUALITY])
            if ret:
                return buffer.tobytes()
        return None

    def stop_all_streams(self):
        global FIRE_DETECTION_ENABLED
        FIRE_DETECTION_ENABLED = False
        for _, sd in self.active_streams.items():
            sd['running'] = False
            if sd['cap']:
                sd['cap'].release()
        self.active_streams.clear()

# ═══════════════════════════════════════════════════════════════
# FLASK APP
# ═══════════════════════════════════════════════════════════════
app = Flask(__name__)
# Allow cross-origin calls from your frontend to /api/*
CORS(app, resources={r"/api/*": {"origins": "*"}})

@app.route('/')
def index():
    return render_template_string(
        HTML_TEMPLATE,
        USE_WEBCAM=USE_WEBCAM,
        camera_ip=('WEBCAM' if USE_WEBCAM else CAMERA_IP),
        camera_id=CAMERA_ID,
        web_port=WEB_PORT,
        fire_enabled=FIRE_DETECTION_ENABLED,
        api_endpoint=API_ENDPOINT,
        fire_interval=FIRE_CHECK_INTERVAL,
        start_time=camera.start_time.strftime("%H:%M:%S")
    )

@app.route('/video_feed/<stream>')
def video_feed(stream):
    def generate():
        while True:
            frame = camera.get_frame(stream)
            if frame:
                yield (b'--frame\r\n'
                       b'Content-Type: image/jpeg\r\n\r\n' + frame + b'\r\n')
            time.sleep(1.0 / FRAME_RATE)
    return Response(generate(), mimetype='multipart/x-mixed-replace; boundary=frame')

@app.route('/api/status')
def api_status():
    return jsonify({
        'use_webcam': USE_WEBCAM,
        'camera_ip': (None if USE_WEBCAM else CAMERA_IP),
        'camera_id': CAMERA_ID,
        'streams': list(camera.streams.keys()),
        'active_streams': {k: True for k in camera.active_streams.keys()},
        'start_time': camera.start_time.isoformat(),
        'frame_rate': FRAME_RATE,
        'stream_quality': STREAM_QUALITY
    })

@app.route('/api/fire_status')
def api_fire_status():
    # return jsonify({
    #     'fire_detected': fire_detection_stats['current_fire_detected'],  # placeholder flag
    #     'last_check': fire_detection_stats['last_check_time'].isoformat() if fire_detection_stats['last_check_time'] else None,
    #     'total_frames_processed': fire_detection_stats['total_frames_processed'],
    #     'ai_responses': fire_detection_stats['ai_responses'][-3:],
    # })

    # Optional: expose latest detections (empty list if none yet)
    latest_dets = []
    try:
        latest = fire_detection_stats['ai_responses'][-1]
        latest_dets = latest.get('detections', [])
    except Exception:
        pass

    return jsonify({
        'fire_detected': fire_detection_stats['current_fire_detected'],
        'last_check': fire_detection_stats['last_check_time'].isoformat() if fire_detection_stats['last_check_time'] else None,
        'last_detection': fire_detection_stats['last_detection'],
        'total_frames_processed': fire_detection_stats['total_frames_processed'],
        'total_detections': fire_detection_stats['total_detections'],
        'detections': latest_dets,                # [{box:[x1,y1,x2,y2], conf, cls}, ...]
        'ai_responses': fire_detection_stats['ai_responses'][-3:],  # keep small
    })

@app.route('/api/test_fire_detection')
# def api_test_fire_detection():
#     try:
#         # Use sub stream if available
#         src = None
#         if 'sub' in camera.active_streams and camera.active_streams['sub']['frame'] is not None:
#             with camera.frame_lock:
#                 src = camera.active_streams['sub']['frame'].copy()
#         elif 'main' in camera.active_streams and camera.active_streams['main']['frame'] is not None:
#             with camera.frame_lock:
#                 src = camera.active_streams['main']['frame'].copy()
#         else:
#             return jsonify({'ok': False, 'error': 'No frame available yet'}), 503
#         camera.send_frame_to_ai(src)
#         return jsonify({'ok': True})
#     except Exception as e:
#         return jsonify({'ok': False, 'error': str(e)}), 500

def api_test_fire_detection():
    try:
        src = None
        if 'sub' in camera.active_streams and camera.active_streams['sub']['frame'] is not None:
            with camera.frame_lock: src = camera.active_streams['sub']['frame'].copy()
        elif 'main' in camera.active_streams and camera.active_streams['main']['frame'] is not None:
            with camera.frame_lock: src = camera.active_streams['main']['frame'].copy()
        else:
            return jsonify({'ok': False, 'error': 'No frame available yet'}), 503

        ok, buf = cv2.imencode('.jpg', src, [cv2.IMWRITE_JPEG_QUALITY, STREAM_QUALITY])
        if not ok:
            return jsonify({'ok': False, 'error': 'JPEG encode failed'}), 500

        out = camera.call_inference_jpeg(CAMERA_ID, buf.tobytes())
        detections = out.get("detections", [])
        now_local = datetime.now()
        fire_detection_stats['last_check_time'] = now_local
        has_fire = any(d.get('conf', 0.0) >= INFER_LOCAL_CONF for d in detections)
        fire_detection_stats['current_fire_detected'] = has_fire
        if has_fire:
            fire_detection_stats['total_detections'] += 1
            fire_detection_stats['last_detection'] = now_local.isoformat()
        fire_detection_stats['ai_responses'].append(out)
        fire_detection_stats['ai_responses'] = fire_detection_stats['ai_responses'][-10:]
        camera.last_detections = detections
        return jsonify({'ok': True, 'count': len(detections)})
    except Exception as e:
        return jsonify({'ok': False, 'error': str(e)}), 500

# ═══════════════════════════════════════════════════════════════
# RUNTIME / ENTRYPOINT
# ═══════════════════════════════════════════════════════════════
camera = UniversalCameraStream()

def start_all():
    if not camera.find_working_streams():
        print("No working stream found. Exiting.")
        sys.exit(1)
    # Eager-start both logical streams (pointing to the same webcam when in webcam mode)
    for s in ['main', 'sub']:
        camera.start_stream(s)


def shutdown_handler(signum, frame):
    print("\nShutting down...")
    camera.stop_all_streams()
    sys.exit(0)

signal.signal(signal.SIGINT, shutdown_handler)
signal.signal(signal.SIGTERM, shutdown_handler)

if __name__ == '__main__':
    start_all()
    print(f"\n✅ Server running at http://127.0.0.1:{WEB_PORT}")
    print("   • /  (dashboard)")
    print("   • /video_feed/main  (MJPEG)")
    print("   • /video_feed/sub   (MJPEG, downscaled)")
    print("   • /api/status | /api/fire_status | /api/test_fire_detection")
    try:
        app.run(host='0.0.0.0', port=WEB_PORT, threaded=True)
    finally:
        camera.stop_all_streams()
