#!/usr/bin/env python3
"""
Minimal Python inference microservice for YOLO ONNX (fire detection)
------------------------------------------------------------------
Contract (drop-in replacement for AWS-style call):

POST /infer
{ "camera_id": "rtsp_camera_1", "image_base64": "<JPEG b64>" }

Response 200:
{ "detections": [ {"box":[x1,y1,x2,y2], "conf":0.87, "cls":0} ],
  "model": "yolov11n_bestFire.onnx",
  "ts": "2025-08-28T01:23:45Z" }

Notes
- Maps boxes back to the ORIGINAL image size (no letterbox coords leaked)
- Works CPU-only (default) or CUDA if available
- Optional bearer token auth via INFER_TOKEN
- Health endpoints: GET /healthz, GET /readyz

Run
----
# deps
pip install fastapi "uvicorn[standard]" onnxruntime numpy opencv-python
# or with GPU: pip install onnxruntime-gpu

# env (optional)
export MODEL_PATH=yolov11n_bestFire.onnx
export PORT=9090
export CONF=0.25
export IOU=0.45
export PROVIDERS="CUDAExecutionProvider,CPUExecutionProvider"
export INFER_TOKEN="secret123"

# start
python infer_server.py

"""
import os
import base64
from datetime import datetime, timezone

import numpy as np
import cv2
import onnxruntime as ort
from fastapi import FastAPI, HTTPException, Header
from fastapi.middleware.cors import CORSMiddleware
from pydantic import BaseModel

# ──────────────────────────────────────────────────────────────
# Config
# ──────────────────────────────────────────────────────────────
MODEL_PATH = os.getenv("MODEL_PATH", "./inference/yolov11n_bestFire.onnx")
PORT = int(os.getenv("PORT", "9090"))
CONF_THR = float(os.getenv("CONF", "0.25"))
IOU_THR = float(os.getenv("IOU", "0.45"))
TOKEN = os.getenv("INFER_TOKEN")  # optional bearer token

# providers: e.g. "CUDAExecutionProvider,CPUExecutionProvider"
providers_env = os.getenv("PROVIDERS")
if providers_env:
    PROVIDERS = [p.strip() for p in providers_env.split(',') if p.strip()]
else:
    # Prefer CUDA if present; else CPU
    have_cuda = "CUDAExecutionProvider" in ort.get_available_providers()
    PROVIDERS = ["CUDAExecutionProvider", "CPUExecutionProvider"] if have_cuda else ["CPUExecutionProvider"]

IMG_SIZE = int(os.getenv("IMG_SIZE", "640"))

# ──────────────────────────────────────────────────────────────
# FastAPI app
# ──────────────────────────────────────────────────────────────
app = FastAPI(title="ONNX Fire Inference Service", version="1.0")
# CORS: adjust as needed
app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_credentials=False,
    allow_methods=["*"],
    allow_headers=["*"]
)

# ──────────────────────────────────────────────────────────────
# Models
# ──────────────────────────────────────────────────────────────
class InferRequest(BaseModel):
    camera_id: str
    image_base64: str

# ──────────────────────────────────────────────────────────────
# Utils
# ──────────────────────────────────────────────────────────────
def utc_iso() -> str:
    return datetime.now(timezone.utc).replace(microsecond=0).isoformat()


def letterbox_bgr(img: np.ndarray, new_shape: int = 640, color=(114, 114, 114)):
    h, w = img.shape[:2]
    if isinstance(new_shape, int):
        new_shape = (new_shape, new_shape)
    r = min(new_shape[0] / h, new_shape[1] / w)
    nh, nw = int(round(h * r)), int(round(w * r))
    resized = cv2.resize(img, (nw, nh), interpolation=cv2.INTER_LINEAR)
    top = (new_shape[0] - nh) // 2
    bottom = new_shape[0] - nh - top
    left = (new_shape[1] - nw) // 2
    right = new_shape[1] - nw - left
    padded = cv2.copyMakeBorder(resized, top, bottom, left, right, cv2.BORDER_CONSTANT, value=color)
    return padded, r, (left, top)


def sigmoid(x: np.ndarray) -> np.ndarray:
    return 1.0 / (1.0 + np.exp(-x))


def bbox_iou(box: np.ndarray, boxes: np.ndarray) -> np.ndarray:
    # box: (4,), boxes: (N,4)
    x1 = np.maximum(box[0], boxes[:, 0])
    y1 = np.maximum(box[1], boxes[:, 1])
    x2 = np.minimum(box[2], boxes[:, 2])
    y2 = np.minimum(box[3], boxes[:, 3])
    inter = np.maximum(0, x2 - x1) * np.maximum(0, y2 - y1)
    area1 = (box[2] - box[0]) * (box[3] - box[1])
    area2 = (boxes[:, 2] - boxes[:, 0]) * (boxes[:, 3] - boxes[:, 1])
    union = area1 + area2 - inter + 1e-6
    return inter / union


def nms(boxes: np.ndarray, scores: np.ndarray, iou_thres: float) -> np.ndarray:
    idxs = scores.argsort()[::-1]
    keep = []
    while idxs.size > 0:
        i = idxs[0]
        keep.append(i)
        if idxs.size == 1:
            break
        ious = bbox_iou(boxes[i], boxes[idxs[1:]])
        idxs = idxs[1:][ious < iou_thres]
    return np.array(keep, dtype=np.int32)

# ──────────────────────────────────────────────────────────────
# Load ONNX
# ──────────────────────────────────────────────────────────────
sess_opts = ort.SessionOptions()
sess_opts.intra_op_num_threads = int(os.getenv("NUM_THREADS", "4"))
session = ort.InferenceSession(MODEL_PATH, sess_options=sess_opts, providers=PROVIDERS)
IN_NAME = session.get_inputs()[0].name
OUT_NAME = session.get_outputs()[0].name

# ──────────────────────────────────────────────────────────────
# Endpoints
# ──────────────────────────────────────────────────────────────
@app.get("/healthz")
def healthz():
    return {"ok": True, "model": os.path.basename(MODEL_PATH), "providers": PROVIDERS}


@app.get("/readyz")
def readyz():
    return {"ready": True}


@app.post("/infer")
def infer(body: InferRequest, authorization: str | None = Header(default=None)):
    # Optional token check
    if TOKEN:
        if not authorization or not authorization.lower().startswith("bearer "):
            raise HTTPException(status_code=401, detail="missing bearer token")
        if authorization.split(" ", 1)[1] != TOKEN:
            raise HTTPException(status_code=403, detail="invalid token")

    # Decode JPEG
    try:
        jpg_bytes = base64.b64decode(body.image_base64)
        arr = np.frombuffer(jpg_bytes, np.uint8)
        bgr = cv2.imdecode(arr, cv2.IMREAD_COLOR)
        if bgr is None:
            raise ValueError("decode failed")
    except Exception as e:
        raise HTTPException(status_code=400, detail=f"bad image: {e}")

    H, W = bgr.shape[:2]

    # Preprocess
    lb, scale, (left, top) = letterbox_bgr(bgr, IMG_SIZE)
    rgb = cv2.cvtColor(lb, cv2.COLOR_BGR2RGB).astype(np.float32) / 255.0
    x = np.transpose(rgb, (2, 0, 1))[None, ...]  # NCHW float32

    # Inference
    out = session.run([OUT_NAME], {IN_NAME: x})[0]

    # Normalize output shape to (N, C)
    if out.ndim == 3 and out.shape[1] < out.shape[2]:
        out = np.transpose(out, (0, 2, 1))  # (1,84,8400)->(1,8400,84)
    preds = out[0]  # (N, C)

    # Parse predictions
    if preds.shape[1] < 5:
        detections = []
    else:
        boxes_xywh = preds[:, :4]
        obj = preds[:, 4]
        obj = sigmoid(obj) if obj.max() > 1 else obj
        conf = obj  # single-class; if multi-class, multiply by max class prob

        m = conf >= CONF_THR
        boxes_xywh, conf = boxes_xywh[m], conf[m]
        if boxes_xywh.size == 0:
            detections = []
        else:
            # xywh -> xyxy in letterbox coords
            xyxy = np.empty_like(boxes_xywh)
            xyxy[:, 0] = boxes_xywh[:, 0] - boxes_xywh[:, 2] / 2
            xyxy[:, 1] = boxes_xywh[:, 1] - boxes_xywh[:, 3] / 2
            xyxy[:, 2] = boxes_xywh[:, 0] + boxes_xywh[:, 2] / 2
            xyxy[:, 3] = boxes_xywh[:, 1] + boxes_xywh[:, 3] / 2

            keep = nms(xyxy, conf, IOU_THR)
            xyxy, conf = xyxy[keep], conf[keep]

            # Map back to original image size
            dets = []
            for (x1, y1, x2, y2), c in zip(xyxy, conf):
                x1 = (x1 - left) / scale
                y1 = (y1 - top) / scale
                x2 = (x2 - left) / scale
                y2 = (y2 - top) / scale
                x1 = float(max(0, min(W - 1, x1)))
                y1 = float(max(0, min(H - 1, y1)))
                x2 = float(max(0, min(W - 1, x2)))
                y2 = float(max(0, min(H - 1, y2)))
                dets.append({"box": [x1, y1, x2, y2], "conf": float(c), "cls": 0})
            detections = dets

    return {"detections": detections, "model": os.path.basename(MODEL_PATH), "ts": utc_iso()}


if __name__ == "__main__":
    import uvicorn
    uvicorn.run(app, host="0.0.0.0", port=PORT)
