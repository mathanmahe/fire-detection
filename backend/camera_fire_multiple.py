#!/usr/bin/env python3
"""
Multi-camera RTSP/Webcam streamer + local ONNX fire detection (per-camera)
- One process manages N cameras concurrently
- Keeps endpoints stable and adds a camera dimension
- Works with your existing infer_server.py (POST /infer)

Endpoints
---------
GET  /video_feed/<cam>/<stream>       # MJPEG for 'main' or 'sub'
GET  /api/status                      # all cameras & stream states
GET  /api/fire_status?camera=<cam>    # flags + latest detections
POST/GET /api/test_fire_detection?camera=<cam>
GET  /api/snapshot/<cam>?w=320        # downscaled JPEG for thumbnails

Quick start
-----------
1) Edit CAMERAS below.
2) Ensure infer_server.py is running (default http://127.0.0.1:9090/infer)
3) pip install flask flask-cors opencv-python requests numpy
4) python camera_hub.py
"""

# ──────────────────────────────────────────────────────────────
# Imports
# ──────────────────────────────────────────────────────────────
import os
import cv2
import time
import sys
import base64
import json
import threading
import requests
import numpy as np
from datetime import datetime
from flask import Flask, Response, jsonify, request, abort
from flask_cors import CORS
from dotenv import load_dotenv
import threading, time, base64, requests

load_dotenv()

# ──────────────────────────────────────────────────────────────
# Config
# ──────────────────────────────────────────────────────────────
CAMERA_IP = "192.168.1.50"
USERNAME  = "admin"
PASSWORD  = "CCTVCheck@123"

# Define your 4 cameras here. Sources can be webcam indices or RTSP URLs.
# If only one source exists, reuse it for 'sub'; we'll downscale in software.
CAMERAS = {
    # Examples:
    "cam1": {"src_main": 0, "src_sub": 0},  # default host webcam
    # "cam2": {"src_main": f"rtsp://{USERNAME}:{PASSWORD}@{CAMERA_IP}:554/h264Preview_01_main", "src_sub": f"rtsp://{USERNAME}:{PASSWORD}@{CAMERA_IP}:554/h264Preview_01_sub"},
    # "cam3": {"src_main": "rtsp://...", "src_sub": "rtsp://..."},
    # "cam4": {"src_main": "rtsp://...", "src_sub": "rtsp://..."},
    "cam2": {"src_main": 0, "src_sub": 0},  # same webcam
    "cam3": {"src_main": 0, "src_sub": 0},  # same webcam  
    "cam4": {"src_main": 0, "src_sub": 0},  # same webcam
}



WEB_PORT        = int(os.getenv("WEB_PORT", "8085"))
FRAME_RATE      = float(os.getenv("FRAME_RATE", "15"))
STREAM_QUALITY  = int(os.getenv("STREAM_QUALITY", "80"))  # JPEG 1–100
FIRE_ENABLED    = os.getenv("FIRE_ENABLED", "true").lower() == "true"
FIRE_INTERVAL   = float(os.getenv("FIRE_INTERVAL", "2.0"))  # seconds per camera
INFER_URL       = os.getenv("INFER_URL", "http://127.0.0.1:9090/infer")
INFER_TOKEN     = os.getenv("INFER_TOKEN")
INFER_TIMEOUT   = float(os.getenv("INFER_TIMEOUT", "1.5"))
INFER_MIN_CONF  = float(os.getenv("INFER_MIN_CONF", "0.25"))




class BatchInferClient:
    def __init__(self, infer_url, token=None, timeout=1.5, interval=2.0):
        self.url = infer_url
        self.token = token
        self.timeout = timeout
        self.interval = interval
        self._cams = {}       # cam_id -> {"get_frame": callable, "on_result": callable}
        self._stop = threading.Event()
        self._thr = None

    def register(self, cam_id, get_frame_fn, on_result_fn):
        """get_frame_fn -> np.ndarray BGR or None; on_result_fn -> takes response dict"""
        self._cams[cam_id] = {"get_frame": get_frame_fn, "on_result": on_result_fn}

    def start(self):
        if self._thr and self._thr.is_alive(): return
        self._thr = threading.Thread(target=self._loop, daemon=True)
        self._thr.start()

    def stop(self):
        self._stop.set()

    def _loop(self):
        headers = {"Content-Type": "application/json"}
        if self.token:
            headers["Authorization"] = f"Bearer {self.token}"
        while not self._stop.is_set():
            items = []
            order = []  # keep order to route results back
            # collect one JPEG per camera
            for cam_id, ent in self._cams.items():
                frame = ent["get_frame"]()
                if frame is None: 
                    continue
                ok, buf = cv2.imencode(".jpg", frame, [cv2.IMWRITE_JPEG_QUALITY, 80])
                if not ok:
                    continue
                items.append({
                    "camera_id": cam_id,
                    "image_base64": base64.b64encode(buf.tobytes()).decode("utf-8")
                })
                order.append(cam_id)

            if items:
                try:
                    r = requests.post(
                        self.url.replace("/infer", "/infer_batch"),
                        json={"items": items},
                        headers=headers,
                        timeout=self.timeout
                    )
                    r.raise_for_status()
                    data = r.json()
                    # data = {"results": [ {camera_id, detections, model, ts} ... ]}
                    results = data.get("results", [])
                    by_cam = {}
                    for res in results:
                        cid = res.get("camera_id")
                        if cid: by_cam[cid] = res
                    # dispatch
                    for cam_id in order:
                        ent = self._cams.get(cam_id)
                        if not ent: continue
                        ent["on_result"](by_cam.get(cam_id, {"detections": []}))
                except Exception as e:
                    print(f"[batch] error: {e}")

            time.sleep(self.interval)

# ──────────────────────────────────────────────────────────────
# Per-camera worker
# ──────────────────────────────────────────────────────────────
class CameraWorker:
    """
    Owns capture threads for main/sub and one fire-detection thread.
    Stores last detections and draws them on outgoing frames.
    """
    def __init__(self, cam_id: str, src_main, src_sub):
        self.cam_id = cam_id
        self.sources = {"main": src_main, "sub": src_sub if src_sub is not None else src_main}
        self.active_streams = {}   # name -> {cap, frame, running, thread}
        self.frame_lock = threading.Lock()

        # Detection state
        self.last_detections = []      # [{"box":[x1,y1,x2,y2], "conf":..., "cls":0}, ...] in SOURCE COORDS
        self.last_det_size = None      # (w,h) of source frame used for detection
        self.last_check_time = None
        self.last_detection_ts = None
        self.total_detections = 0
        self.total_frames_processed = 0
        self.fire_now = False

        self.fire_thread = None
        self._stop = threading.Event()

    # ── Video capture management ───────────────────────────────
    def _open_cap(self, src):
        cap = cv2.VideoCapture(src)
        cap.set(cv2.CAP_PROP_BUFFERSIZE, 1)
        return cap if cap.isOpened() else None

    def start_stream(self, name: str):
        if name in self.active_streams:
            return True
        src = self.sources.get(name)
        if src is None:
            return False

        cap = self._open_cap(src)
        if cap is None:
            print(f"[{self.cam_id}] ❌ Failed to open {name}: {src}")
            return False

        stream_data = {"cap": cap, "frame": None, "running": True, "thread": None}
        self.active_streams[name] = stream_data

        def pump():
            while stream_data["running"] and not self._stop.is_set():
                ret, frame = cap.read()
                if ret:
                    # downscale SUB to ~640px width for speed
                    if name == "sub" and frame is not None:
                        h, w = frame.shape[:2]
                        if w > 640:
                            scale = 640.0 / w
                            frame = cv2.resize(frame, (int(w * scale), int(h * scale)))
                    else:
                        # safety clamp huge frames for web
                        h, w = frame.shape[:2]
                        if w > 1920:
                            scale = 1920.0 / w
                            frame = cv2.resize(frame, (int(w * scale), int(h * scale)))
                    with self.frame_lock:
                        stream_data["frame"] = frame
                time.sleep(max(0.0, 1.0 / FRAME_RATE))

        t = threading.Thread(target=pump, daemon=True)
        stream_data["thread"] = t
        t.start()
        print(f"[{self.cam_id}] ✅ started stream {name} -> {src}")
        return True

    def ensure_started(self):
        for s in ("main", "sub"):
            self.start_stream(s)

    def peek_frame(self, name: str):
        sd = self.active_streams.get(name)
        if not sd: return None
        with self.frame_lock:
            if sd["frame"] is None: return None
            return sd["frame"].copy()

    def get_frame(self, name: str):
        sd = self.active_streams.get(name)
        if not sd:
            if not self.start_stream(name):
                return None
            sd = self.active_streams.get(name)
        with self.frame_lock:
            frame = sd["frame"].copy() if sd["frame"] is not None else None
        if frame is None:
            return None

        # draw boxes (scale from detection source size)
        if self.last_detections and self.last_det_size:
            curr_h, curr_w = frame.shape[:2]
            src_w, src_h = self.last_det_size
            sx = curr_w / float(src_w)
            sy = curr_h / float(src_h)
            for det in self.last_detections:
                x1, y1, x2, y2 = det["box"]
                x1 = int(round(x1 * sx)); y1 = int(round(y1 * sy))
                x2 = int(round(x2 * sx)); y2 = int(round(y2 * sy))
                conf = det.get("conf", 0.0)
                cv2.rectangle(frame, (x1, y1), (x2, y2), (0,255,0), 2)
                cv2.putText(frame, f"fire {conf:.2f}", (x1, max(0, y1-6)),
                            cv2.FONT_HERSHEY_SIMPLEX, 0.5, (0,255,0), 1, cv2.LINE_AA)

        ok, buf = cv2.imencode(".jpg", frame, [cv2.IMWRITE_JPEG_QUALITY, STREAM_QUALITY])
        return buf.tobytes() if ok else None

    # ── Inference ──────────────────────────────────────────────
    def _post_infer(self, jpg_bytes: bytes):
        payload = {
            "camera_id": self.cam_id,
            "image_base64": base64.b64encode(jpg_bytes).decode("utf-8")
        }
        headers = {"Content-Type": "application/json"}
        if INFER_TOKEN:
            headers["Authorization"] = f"Bearer {INFER_TOKEN}"  # same name used by infer_server.py
        r = requests.post(INFER_URL, json=payload, headers=headers, timeout=INFER_TIMEOUT)
        r.raise_for_status()
        return r.json()

    def _detect_loop(self, phase_delay: float):
        print(f"[{self.cam_id}] 🔥 detection loop every {FIRE_INTERVAL:.2f}s (phase {phase_delay:.2f}s)")
        time.sleep(phase_delay)
        while not self._stop.is_set():
            try:
                # Prefer sub for inference
                src = self.peek_frame("sub")
                if src is None:
                    src = self.peek_frame("main")
                if src is None:
                    time.sleep(0.2)
                    continue

                self.total_frames_processed += 1
                ok, buf = cv2.imencode(".jpg", src, [cv2.IMWRITE_JPEG_QUALITY, STREAM_QUALITY])
                if not ok:
                    time.sleep(FIRE_INTERVAL)
                    continue

                out = self._post_infer(buf.tobytes())
                detections = out.get("detections", [])
                now = datetime.now()
                self.last_check_time = now
                self.fire_now = any(d.get("conf", 0.0) >= INFER_MIN_CONF for d in detections)
                if self.fire_now:
                    self.total_detections += 1
                    self.last_detection_ts = now.isoformat()

                # Remember detection source size for scaling when drawing
                h, w = src.shape[:2]
                self.last_det_size = (w, h)
                self.last_detections = detections

            except Exception as e:
                print(f"[{self.cam_id}] [infer] error: {e}")

            # cadence
            time.sleep(FIRE_INTERVAL)

    def start_detection(self, phase_delay: float = 0.0):
        if not FIRE_ENABLED: return
        if self.fire_thread and self.fire_thread.is_alive(): return
        self.fire_thread = threading.Thread(target=self._detect_loop, args=(phase_delay,), daemon=True)
        self.fire_thread.start()

    # For /api/test_fire_detection
    def test_once(self):
        src = self.peek_frame("sub")
        if src is None:
            src = self.peek_frame("main")
        if src is None:
            return {"ok": False, "error": "no frame"}
        ok, buf = cv2.imencode(".jpg", src, [cv2.IMWRITE_JPEG_QUALITY, STREAM_QUALITY])
        if not ok:
            return {"ok": False, "error": "encode failed"}
        out = self._post_infer(buf.tobytes())
        detections = out.get("detections", [])
        now = datetime.now()
        self.last_check_time = now
        self.fire_now = any(d.get("conf", 0.0) >= INFER_MIN_CONF for d in detections)
        if self.fire_now:
            self.total_detections += 1
            self.last_detection_ts = now.isoformat()
        h, w = src.shape[:2]
        self.last_det_size = (w, h)
        self.last_detections = detections
        return {"ok": True, "count": len(detections), "detections": detections}

    def stats(self):
        return {
            "camera_id": self.cam_id,
            "streams": list(self.sources.keys()),
            "active_streams": {k: bool(v["frame"] is not None) for k, v in self.active_streams.items()},
            "fire_detected": self.fire_now,
            "last_check": self.last_check_time.isoformat() if self.last_check_time else None,
            "last_detection": self.last_detection_ts,
            "total_detections": self.total_detections,
            "total_frames_processed": self.total_frames_processed,
            "detections": self.last_detections[-10:],
        }

    def get_infer_frame(self):
        # prefer sub for detection (smaller/faster)
        f = self.peek_frame("sub")
        if f is None:
            f = self.peek_frame("main")
        return f

    def apply_infer_result(self, result: dict):
        # result: {"detections":[...], "model":"...", "ts":"..."} or {}
        dets = result.get("detections", [])
        now = datetime.now()
        self.last_check_time = now
        self.fire_now = any(d.get("conf", 0.0) >= INFER_MIN_CONF for d in dets)
        if self.fire_now:
            self.total_detections += 1
            self.last_detection_ts = now.isoformat()
        # remember size we inferred on (for scaling in get_frame)
        src = self.peek_frame("sub")
        if src is None:
            src = self.peek_frame("main")
        if src is not None:
            h, w = src.shape[:2]
            self.last_det_size = (w, h)
        self.last_detections = dets

    def stop(self):
        self._stop.set()
        for s, sd in self.active_streams.items():
            sd["running"] = False
            try:
                if sd["cap"]: sd["cap"].release()
            except Exception:
                pass
        self.active_streams.clear()

# ──────────────────────────────────────────────────────────────
# App init
# ──────────────────────────────────────────────────────────────
app = Flask(__name__)
CORS(app, resources={r"/api/*": {"origins": "*"}})

# camera registry
CAM = {}  # cam_id -> CameraWorker

def start_all_cameras():
    # Stagger detection phases to avoid bursts
    n = max(1, len(CAMERAS))
    for idx, (cam_id, cfg) in enumerate(CAMERAS.items()):
        w = CameraWorker(cam_id, cfg.get("src_main"), cfg.get("src_sub"))
        CAM[cam_id] = w
        w.ensure_started()
    # start detectors with phase offsets
    for idx, cam_id in enumerate(CAM):
        phase = (FIRE_INTERVAL / max(1, len(CAM))) * idx
        CAM[cam_id].start_detection(phase_delay=phase)
        print(f"[boot] {cam_id} detection phase = {phase:.2f}s")



# ──────────────────────────────────────────────────────────────
# Routes
# ──────────────────────────────────────────────────────────────
@app.route("/api/status")
def api_status():
    return jsonify({
        "inference_url": INFER_URL,
        "fire_enabled": FIRE_ENABLED,
        "frame_rate": FRAME_RATE,
        "cameras": {cam_id: CAM[cam_id].stats() for cam_id in CAM}
    })

@app.route("/video_feed/<cam>/<stream>")
def video_feed(cam, stream):
    if cam not in CAM or stream not in ("main", "sub"):
        abort(404)
    worker = CAM[cam]

    def gen():
        while True:
            frame = worker.get_frame(stream)
            if frame:
                yield (b"--frame\r\nContent-Type: image/jpeg\r\n\r\n" + frame + b"\r\n")
            time.sleep(max(0.0, 1.0 / FRAME_RATE))
    return Response(gen(), mimetype="multipart/x-mixed-replace; boundary=frame")

@app.route("/api/fire_status")
def api_fire_status():
    cam = request.args.get("camera")
    if not cam:
        # pick first as default to keep old callers working
        cam = next(iter(CAM.keys()), None)
    if cam not in CAM:
        abort(404)
    return jsonify(CAM[cam].stats())

@app.route("/api/test_fire_detection", methods=["GET", "POST"])
def api_test_fire_detection():
    cam = request.args.get("camera")
    if not cam:
        cam = next(iter(CAM.keys()), None)
    if cam not in CAM:
        abort(404)
    return jsonify(CAM[cam].test_once())

@app.route("/api/snapshot/<cam>")
def api_snapshot(cam):
    if cam not in CAM:
        abort(404)
    w = request.args.get("w", default=320, type=int)
    frame = CAM[cam].peek_frame("sub")
    if frame is None:
        frame = CAM[cam].peek_frame("main")
    if frame is None:
        abort(503)
    h, ww = frame.shape[:2]
    scale = w / float(ww)
    thumb = cv2.resize(frame, (w, int(h * scale)))
    ok, buf = cv2.imencode(".jpg", thumb, [cv2.IMWRITE_JPEG_QUALITY, 70])
    return Response(buf.tobytes(), mimetype="image/jpeg")

# ──────────────────────────────────────────────────────────────
# Main
# ──────────────────────────────────────────────────────────────
if __name__ == "__main__":
    print(f"[init] Inference: {INFER_URL}  |  Cameras: {list(CAMERAS.keys()) or ['(none)']}")
    start_all_cameras()

    BATCH = BatchInferClient(
    infer_url=INFER_URL,
    token=INFER_TOKEN,
    timeout=INFER_TIMEOUT,
    interval=FIRE_INTERVAL          # e.g., 2.0s -> one batch every 2s
    )   

    # Register all cameras
    for cam_id, worker in CAM.items():
        BATCH.register(
            cam_id,
            get_frame_fn=worker.get_infer_frame,
            on_result_fn=worker.apply_infer_result
        )
    BATCH.start()

    try:
        app.run(host="0.0.0.0", port=WEB_PORT, threaded=True)
    finally:
        BATCH.stop()
        for c in CAM.values():
            c.stop()
