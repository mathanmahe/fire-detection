#!/usr/bin/env python3
import os
import base64
from datetime import datetime, timezone
from typing import List, Optional

import numpy as np
import cv2
import onnxruntime as ort
import asyncio
from fastapi import FastAPI, HTTPException, Header
from fastapi.middleware.cors import CORSMiddleware
from pydantic import BaseModel

# ──────────────────────────────────────────────────────────────
# Config
# ──────────────────────────────────────────────────────────────
MODEL_PATH     = os.getenv("MODEL_PATH", "./inference/yolov11n_bestFire.onnx")
PORT           = int(os.getenv("PORT", "9090"))
CONF_THR       = float(os.getenv("CONF", "0.25"))
IOU_THR        = float(os.getenv("IOU", "0.45"))
TOKEN          = os.getenv("INFER_TOKEN")            # optional bearer token
IMG_SIZE       = int(os.getenv("IMG_SIZE", "640"))
NUM_THREADS    = int(os.getenv("NUM_THREADS", "4"))  # ORT intra-op threads
MAX_CONC       = int(os.getenv("MAX_CONCURRENCY", "4"))  # async concurrency cap
# If you want multiple OS processes, set UVICORN_WORKERS when launching uvicorn or python (see notes)

providers_env = os.getenv("PROVIDERS")
if providers_env:
    PROVIDERS = [p.strip() for p in providers_env.split(',') if p.strip()]
else:
    PROVIDERS = ["CUDAExecutionProvider", "CPUExecutionProvider"] \
        if "CUDAExecutionProvider" in ort.get_available_providers() else ["CPUExecutionProvider"]

# ──────────────────────────────────────────────────────────────
# FastAPI app
# ──────────────────────────────────────────────────────────────
app = FastAPI(title="ONNX Fire Inference Service (Scaled)", version="1.1")
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

class InferBatchItem(BaseModel):
    camera_id: str
    image_base64: str

class InferBatchRequest(BaseModel):
    items: List[InferBatchItem]

# ──────────────────────────────────────────────────────────────
# Utils
# ──────────────────────────────────────────────────────────────
def utc_iso() -> str:
    return datetime.now(timezone.utc).replace(microsecond=0).isoformat()

def letterbox_bgr(img: np.ndarray, new_shape: int = 640, color=(114,114,114)):
    h, w = img.shape[:2]
    if isinstance(new_shape, int):
        new_shape = (new_shape, new_shape)
    r = min(new_shape[0]/h, new_shape[1]/w)
    nh, nw = int(round(h*r)), int(round(w*r))
    resized = cv2.resize(img, (nw, nh), interpolation=cv2.INTER_LINEAR)
    top    = (new_shape[0]-nh)//2
    bottom = new_shape[0]-nh-top
    left   = (new_shape[1]-nw)//2
    right  = new_shape[1]-nw-left
    padded = cv2.copyMakeBorder(resized, top, bottom, left, right,
                                cv2.BORDER_CONSTANT, value=color)
    return padded, r, (left, top)

def sigmoid(x: np.ndarray) -> np.ndarray:
    return 1.0/(1.0+np.exp(-x))

def bbox_iou(box: np.ndarray, boxes: np.ndarray) -> np.ndarray:
    x1 = np.maximum(box[0], boxes[:,0]); y1 = np.maximum(box[1], boxes[:,1])
    x2 = np.minimum(box[2], boxes[:,2]); y2 = np.minimum(box[3], boxes[:,3])
    inter = np.maximum(0, x2-x1) * np.maximum(0, y2-y1)
    area1 = (box[2]-box[0]) * (box[3]-box[1])
    area2 = (boxes[:,2]-boxes[:,0]) * (boxes[:,3]-boxes[:,1])
    union = area1 + area2 - inter + 1e-6
    return inter/union

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
# ONNX session (global, shared by requests)
# ──────────────────────────────────────────────────────────────
sess_opts = ort.SessionOptions()
sess_opts.intra_op_num_threads = NUM_THREADS  # parallelism inside a single inference
session = ort.InferenceSession(MODEL_PATH, sess_options=sess_opts, providers=PROVIDERS)
IN_NAME = session.get_inputs()[0].name
OUT_NAME = session.get_outputs()[0].name

# Concurrency limiter to cap in-flight inferences per process
CONC_SEMAPHORE = asyncio.Semaphore(MAX_CONC)

# (Optional) simple per-camera rate limiter (tokens per second)
# Set CAM_RATE=0 to disable. Example: CAM_RATE=2 means ~2 requests/sec per camera.
CAM_RATE = float(os.getenv("CAM_RATE", "0"))
_cam_tokens = {}   # camera_id -> (tokens, last_ts)
def _allow_camera(camera_id: str) -> bool:
    if CAM_RATE <= 0: return True
    import time as _t
    now = _t.time()
    tokens, last = _cam_tokens.get(camera_id, (CAM_RATE, now))
    # refill
    tokens = min(CAM_RATE, tokens + (now - last) * CAM_RATE)
    if tokens >= 1:
        _cam_tokens[camera_id] = (tokens - 1, now)
        return True
    _cam_tokens[camera_id] = (tokens, now)
    return False

# Warmup run (loads kernels, JITs, allocates memory)
def _warmup():
    dummy = np.zeros((IMG_SIZE, IMG_SIZE, 3), dtype=np.uint8)
    lb, _, _ = letterbox_bgr(dummy, IMG_SIZE)
    x = np.transpose(lb.astype(np.float32)/255.0, (2,0,1))[None, ...]
    _ = session.run([OUT_NAME], {IN_NAME: x})

_warmup()

# ──────────────────────────────────────────────────────────────
# Core inference (single image)
# ──────────────────────────────────────────────────────────────
def _infer_one(camera_id: str, image_b64: str):
    try:
        jpg = base64.b64decode(image_b64)
        arr = np.frombuffer(jpg, np.uint8)
        bgr = cv2.imdecode(arr, cv2.IMREAD_COLOR)
        if bgr is None:
            raise ValueError("decode failed")
    except Exception as e:
        raise HTTPException(status_code=400, detail=f"bad image: {e}")

    H, W = bgr.shape[:2]
    lb, scale, (left, top) = letterbox_bgr(bgr, IMG_SIZE)
    rgb = cv2.cvtColor(lb, cv2.COLOR_BGR2RGB).astype(np.float32) / 255.0
    x = np.transpose(rgb, (2,0,1))[None, ...]

    out = session.run([OUT_NAME], {IN_NAME: x})[0]
    if out.ndim == 3 and out.shape[1] < out.shape[2]:
        out = np.transpose(out, (0,2,1))
    preds = out[0]

    if preds.shape[1] < 5:
        detections = []
    else:
        boxes_xywh = preds[:, :4]
        obj = preds[:, 4]
        obj = sigmoid(obj) if obj.max() > 1 else obj
        conf = obj
        m = conf >= CONF_THR
        boxes_xywh, conf = boxes_xywh[m], conf[m]
        if boxes_xywh.size == 0:
            detections = []
        else:
            xyxy = np.empty_like(boxes_xywh)
            xyxy[:,0] = boxes_xywh[:,0] - boxes_xywh[:,2]/2
            xyxy[:,1] = boxes_xywh[:,1] - boxes_xywh[:,3]/2
            xyxy[:,2] = boxes_xywh[:,0] + boxes_xywh[:,2]/2
            xyxy[:,3] = boxes_xywh[:,1] + boxes_xywh[:,3]/2

            keep = nms(xyxy, conf, IOU_THR)
            xyxy, conf = xyxy[keep], conf[keep]

            dets = []
            for (x1, y1, x2, y2), c in zip(xyxy, conf):
                x1 = (x1 - left) / scale; y1 = (y1 - top) / scale
                x2 = (x2 - left) / scale; y2 = (y2 - top) / scale
                x1 = float(max(0, min(W-1, x1)))
                y1 = float(max(0, min(H-1, y1)))
                x2 = float(max(0, min(W-1, x2)))
                y2 = float(max(0, min(H-1, y2)))
                dets.append({"box":[x1,y1,x2,y2], "conf": float(c), "cls": 0})
            detections = dets

    return {"detections": detections, "model": os.path.basename(MODEL_PATH), "ts": utc_iso()}

# ──────────────────────────────────────────────────────────────
# Endpoints
# ──────────────────────────────────────────────────────────────
@app.get("/healthz")
def healthz():
    return {
        "ok": True,
        "model": os.path.basename(MODEL_PATH),
        "providers": PROVIDERS,
        "num_threads": NUM_THREADS,
        "max_concurrency": MAX_CONC
    }

@app.get("/readyz")
def readyz():
    return {"ready": True}

@app.post("/infer")
async def infer(body: InferRequest, authorization: Optional[str] = Header(default=None)):
    # Optional bearer
    if TOKEN:
        if not authorization or not authorization.lower().startswith("bearer "):
            raise HTTPException(status_code=401, detail="missing bearer token")
        if authorization.split(" ", 1)[1] != TOKEN:
            raise HTTPException(status_code=403, detail="invalid token")

    # Simple per-camera rate limiter (optional)
    if not _allow_camera(body.camera_id):
        raise HTTPException(status_code=429, detail="camera rate limited")

    async with CONC_SEMAPHORE:
        # run sync compute in a thread; ORT releases GIL in C++ kernels
        loop = asyncio.get_running_loop()
        result = await loop.run_in_executor(None, _infer_one, body.camera_id, body.image_base64)
        return result

@app.post("/infer_batch")
async def infer_batch(body: InferBatchRequest, authorization: Optional[str] = Header(default=None)):
    
    if TOKEN:
        if not authorization or not authorization.lower().startswith("bearer "):
            raise HTTPException(status_code=401, detail="missing bearer token")
        if authorization.split(" ", 1)[1] != TOKEN:
            raise HTTPException(status_code=403, detail="invalid token")

    # Enforce a global concurrency window; process items sequentially inside it.
    # (You can parallelize inside if you know your device can handle it.)
    async with CONC_SEMAPHORE:
        loop = asyncio.get_running_loop()
        results = []
        for it in body.items:
            if not _allow_camera(it.camera_id):
                results.append({"camera_id": it.camera_id, "error": "rate_limited"})
                continue
            out = await loop.run_in_executor(None, _infer_one, it.camera_id, it.image_base64)
            out["camera_id"] = it.camera_id
            results.append(out)
        return {"results": results}

if __name__ == "__main__":
    import uvicorn
    workers = int(os.getenv("UVICORN_WORKERS", "1"))
    uvicorn.run(app, host="0.0.0.0", port=PORT, workers=workers)
