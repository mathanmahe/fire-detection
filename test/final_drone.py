#!/usr/bin/env python3
# -*- coding: utf-8 -*-

import os
import sys
import time
import subprocess
from datetime import datetime
import shutil
import pwd
import grp
import tempfile
import socket

import requests
import av
import cv2
import numpy as np

# --------------------------------------------------------------------------------------
# SAFETY & DEFAULTS
# --------------------------------------------------------------------------------------

# Refuse to run as root (breaks venv imports like av, and causes root-owned leftovers)
if os.geteuid() == 0:
    print("❌ Do not run this script with sudo/root. "
          "Add yourself to the docker group and run normally:\n"
          "   sudo usermod -aG docker $USER && newgrp docker\n"
          "Then: source ~/droneenv/bin/activate && python3 web+static1.py")
    sys.exit(1)

# Set a safe umask so created files/dirs are not overly restrictive

os.umask(0o022)

# --------------------------------------------------------------------------------------
# CONFIG (moved out of /tmp to avoid permission resets/cleaners)
# --------------------------------------------------------------------------------------

# Base directory for all assets (host AND inside the container)
# BASE        = "/home/ubuntu/stream"
# BASE = os.environ.get("FIREBEATS_BASE", os.path.expanduser("~/firebeats/stream"))
BASE = "/Users/mathan/firebeats/py-backend"
NGINX_CONF  = f"{BASE}/nginx_rtmp.conf"
WWW_ROOT    = f"{BASE}/www"
HLS_PATH    = f"{BASE}/hls"
FRAME_PATH  = f"{BASE}/frame.jpg"

# Web port for serving UI + HLS
# TUNNEL_PORT = 8080
TUNNEL_PORT = 8082

# Camera/ID
CAMERA_ID   = sys.argv[1] if len(sys.argv) > 1 else "ec2_camera"

# AI endpoint
API_ENDPOINT = "https://2cwzmjzkx4.execute-api.us-east-1.amazonaws.com/default/fire-frame-receiver"

# --------------------------------------------------------------------------------------
# HELPERS
# --------------------------------------------------------------------------------------

def ensure_path(path: str, mode: int = 0o755, world_writable: bool = False):
    """
    Idempotently ensure a path exists, is owned by the current user, and has desired perms.
    Use world_writable=True for paths the container must write to (HLS dir).
    """
    uid = os.getuid()
    gid = os.getgid()
    os.makedirs(path, exist_ok=True)

    # chown to current user if needed (may fail if parent is root-owned; we try sudo as a fallback)
    try:
        os.chown(path, uid, gid)
    except PermissionError:
        user = pwd.getpwuid(uid).pw_name
        group = grp.getgrgid(gid).gr_name
        subprocess.run(["sudo", "chown", f"{user}:{group}", path],
                       stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL, check=False)

    # set perms
    os.chmod(path, 0o777 if world_writable else mode)

def get_ec2_ips():
    """Automatically detect EC2 public and private IPs"""
    public_ip = None
    private_ip = None

    print("🔍 Detecting EC2 IP addresses...")

    try:
        r = requests.get('http://169.254.169.254/latest/meta-data/public-ipv4', timeout=2)
        if r.status_code == 200:
            public_ip = r.text.strip()
            print(f"✓ Detected public IP: {public_ip}")
        r = requests.get('http://169.254.169.254/latest/meta-data/local-ipv4', timeout=2)
        if r.status_code == 200:
            private_ip = r.text.strip()
            print(f"✓ Detected private IP: {private_ip}")
    except Exception as e:
        print(f"⚠️  EC2 metadata service not available: {e}")

    if not public_ip:
        try:
            r = requests.get('https://api.ipify.org', timeout=5)
            if r.status_code == 200:
                public_ip = r.text.strip()
                print(f"✓ Detected public IP (via ipify): {public_ip}")
        except Exception:
            print("⚠️  Could not detect public IP automatically")
            public_ip = input("Enter your public IP address: ").strip()

    if not private_ip:
        try:
            s = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)
            s.connect(("8.8.8.8", 80))
            private_ip = s.getsockname()[0]
            s.close()
            print(f"✓ Detected local IP: {private_ip}")
        except Exception:
            private_ip = "127.0.0.1"

    return public_ip, private_ip

PUBLIC_IP, PRIVATE_IP = get_ec2_ips()
# PUSH_URL = f"rtmp://{PUBLIC_IP}:1935/live/stream"
PUSH_URL = f"rtmp://127.0.0.1:1936/live/stream"

# --------------------------------------------------------------------------------------
# DETECTOR
# --------------------------------------------------------------------------------------

class HLSDetector:
    def __init__(self):
        self.frame = None
        self.count = 0
        self.prev_frame = None
        self.static_count = 0
        self.static_threshold = 3
        self.diff_threshold = 5.0
        self.prev_box = None
        self.box_static_count = 0
        self.box_static_threshold = 1
        self.box_iou_threshold = 0.95

    def get_frame_details(self, img):
        h, w, _ = img.shape
        gray = cv2.cvtColor(img, cv2.COLOR_BGR2GRAY)
        brightness = float(np.mean(gray))
        mean_bgr = np.mean(img, axis=(0, 1))
        return {
            'time': datetime.now().strftime('%H:%M:%S'),
            'num': self.count,
            'size': f'{w}×{h}',
            'brightness': brightness,
            'mean_blue': float(mean_bgr[0]),
            'mean_green': float(mean_bgr[1]),
            'mean_red': float(mean_bgr[2])
        }
    def print_frame_details(self, d):
        print(f"\n📺 Frame {d['num']} @ {d['time']} — {d['size']}, "
              f"brightness={d['brightness']:.1f}, R={d['mean_red']:.1f} "
              f"G={d['mean_green']:.1f} B={d['mean_blue']:.1f}")

    def compute_iou(self, box1, box2):
        x1, y1, x2, y2 = box1
        x1b, y1b, x2b, y2b = box2
        xi1, yi1 = max(x1, x1b), max(y1, y1b)
        xi2, yi2 = min(x2, x2b), min(y2, y2b)
        inter = max(0, xi2 - xi1) * max(0, yi2 - yi1)
        union = ((x2 - x1) * (y2 - y1) + (x2b - x1b) * (y2b - y1b) - inter)
        return inter / union if union > 0 else 0
    
    def save_and_send(self):
        # Static (by pixel diff) — skip API
        if self.static_count >= self.static_threshold:
            print(f"⚠️ Static image detected - skipping API call ({self.static_count} consecutive)")
            return

        cv2.imwrite(FRAME_PATH, self.frame)
        with open(FRAME_PATH, 'rb') as f:
            resp = requests.post(
                API_ENDPOINT,
                data=f.read(),
                headers={'Content-Type': 'image/jpeg', 'camera-id': CAMERA_ID},
                timeout=15
            )
        print(f"→ AI API {resp.status_code}: {resp.text.strip()}")

        try:
            data = resp.json()
        except Exception:
            data = {}
        # Static (by box IoU)
        fire_detected = resp.status_code == 200 and data.get('fire_detected')
        boxes = data.get('boxes', [])
        if fire_detected and boxes:
            bx = boxes[0][:4]
            if self.prev_box is not None:
                iou = self.compute_iou(self.prev_box, bx)
                print(f"🔍 Fire box IoU: {iou:.3f} (threshold: {self.box_iou_threshold})")
                if iou > self.box_iou_threshold:
                    self.box_static_count += 1
                else:
                    self.box_static_count = 0
            else:
                self.box_static_count = 0
                self.prev_box = bx

            if self.box_static_count >= self.box_static_threshold:
                print(f"⚠️ Static fire position - same location ({self.box_static_count} consecutive)")
                return
        else:
            if self.prev_box is not None:
                self.prev_box = None
                self.box_static_count = 0

        if fire_detected:
            with open(os.path.join(BASE, 'fire_log.txt'), 'a') as log:
                log.write(f"{datetime.now()} FIRE DETECTED → {resp.text}\n")
            print("🚨 FIRE DETECTED!")
    
    def wait_for_hls(self, url, timeout=30):
        print(f"⏳ Connecting to HLS stream: {url}")
        nested_url = url.replace('/hls/stream.m3u8', '/hls/stream/stream.m3u8')
        urls_to_try = [url, nested_url]

        end = time.time() + timeout
        while time.time() < end:
            for test_url in urls_to_try:
                try:
                    print(f"🔍 Trying URL: {test_url}")
                    r = requests.get(test_url, timeout=10)
                    if r.status_code == 200 and '#EXTINF' in r.text:
                        print(f'[✓] HLS playlist ready at: {test_url}')
                        lines = r.text.strip().split('\n')
                        segments = [line for line in lines if line.endswith('.ts')]
                        if segments:
                            print(f'[✓] Found {len(segments)} video segments')
                            return True, test_url
                        else:
                            print('[!] Playlist exists but no segments yet, retrying...')
                    else:
                        print(f'[!] URL {test_url} - status: {r.status_code}')
                except Exception as e:
                    print(f'[!] URL {test_url} failed: {e}')
            time.sleep(3)
        print('❌ HLS connection timeout - stream may have stopped')
        return False, url
    
    def run(self, url):
        while True:
            try:
                hls_ready, working_url = self.wait_for_hls(url)
                if not hls_ready:
                    print("⚠️ HLS stream not available, waiting for RTMP stream to restart...")
                    time.sleep(10)
                    continue

                print(f"▶ Opening HLS: {working_url}")
                try:
                    cont = av.open(working_url, format='hls', options={
                        'fflags': 'nobuffer',
                        'flags': 'low_delay',
                        'timeout': '30000000',
                        'probesize': '32',
                        'analyzeduration': '0',
                        'max_delay': '0'
                    })
                    vid = cont.streams.video[0]
                    print(f"[✓] Video stream: {vid.width}×{vid.height} @ {vid.average_rate} fps")
                except Exception as e:
                    print(f"❌ Failed to open HLS stream: {e}")
                    print("⚠️ Retrying in 10 seconds...")
                    time.sleep(10)
                    continue

                last = time.time()
                frame_count = 0
                try:
                    for pkt in cont.demux(vid):
                        for frame in pkt.decode():
                            try:
                                img = frame.to_ndarray(format='bgr24')
                            except Exception as e:
                                print(f"[!] Frame conversion error: {e}")
                                continue

                            self.count += 1
                            frame_count += 1
                            self.frame = img

                            if time.time() - last >= 3.0:
                                if self.prev_frame is not None:
                                    d = cv2.absdiff(img, self.prev_frame)
                                    md = float(np.mean(d))
                                    self.static_count = self.static_count + 1 if md < self.diff_threshold else 0
                                self.prev_frame = img.copy()
                                det = self.get_frame_details(img)
                                self.print_frame_details(det)
                                self.save_and_send()
                                last = time.time()

                except Exception as e:
                    print(f'\n⚠️ Stream processing error: {e}')
                    print(f"📊 Processed {frame_count} frames before error")
                    print("🔄 Will attempt to reconnect...")
                finally:
                    cont.close()
                    if os.path.exists(FRAME_PATH):
                        os.remove(FRAME_PATH)
                time.sleep(5)

            except KeyboardInterrupt:
                print('\n🛑 Interrupted by user')
                break
            except Exception as e:
                print(f'\n❌ Unexpected error: {e}')
                print("🔄 Retrying in 10 seconds...")
                time.sleep(10)

# --------------------------------------------------------------------------------------
# HTML / JS
# --------------------------------------------------------------------------------------

HTML_TEMPLATE = f"""
<!DOCTYPE html>
<html>
<head>
    <meta charset="utf-8">
    <title>🔥 Ultra-Low Latency Fire Detection</title>
    <style>
        body {{
            margin: 0;
            padding: 20px;
            background: #111;
            color: white;
            font-family: Arial, sans-serif;
        }}
        .container {{
            max-width: 1200px;
            margin: 0 auto;
        }}
        .video-container {{
            position: relative;
            display: inline-block;
            margin-bottom: 20px;
        }}
        video {{
            max-width: 100%;
            height: auto;
            background: #000;
            border: 2px solid #333;
        }}
        canvas {{
            position: absolute;
            top: 0;
            left: 0;
            pointer-events: none;
        }}
        .status {{
            background: #333;
            padding: 10px;
            border-radius: 5px;
            margin-bottom: 10px;
            font-family: monospace;
        }}
        .error {{ background: #600; color: #fcc; }}
        .success {{ background: #060; color: #cfc; }}
        .info {{ background: #006; color: #ccf; }}
        .warning {{ background: #660; color: #ffc; }}
        .webrtc {{ background: #006600; color: #ccffcc; }}
        .controls {{ margin: 10px 0; }}
        button {{
            background: #007;
            color: white;
            border: none;
            padding: 10px 20px;
            border-radius: 5px;
            cursor: pointer;
            margin-right: 10px;
            font-size: 14px;
        }}
        button:hover {{ background: #009; }}
        button:active {{ background: #005; }}
        button.webrtc {{ background: #0a0; }}
        button.webrtc:hover {{ background: #0c0; }}
        .stats {{
            display: grid;
            grid-template-columns: repeat(auto-fit, minmax(200px, 1fr));
            gap: 10px;
            margin: 20px 0;
        }}
        .stat-box {{
            background: #222;
            padding: 10px;
            border-radius: 5px;
            text-align: center;
        }}
        .stat-value {{
            font-size: 24px;
            font-weight: bold;
            color: #0f0;
        }}
        .stat-label {{
            font-size: 12px;
            color: #888;
        }}
        .webrtc-latency {{ color: #0f0; font-weight: bold; }}
        #debug {{
            margin-top: 20px;
            font-family: monospace;
            font-size: 11px;
            max-height: 200px;
            overflow-y: auto;
            background: #000;
            padding: 10px;
            border-radius: 5px;
        }}
    </style>
</head>
<body>
    <div class="container">
        <h1>🔥 Ultra-Low Latency Fire Detection</h1>
        <div id="status" class="status">Initializing ultra-low latency stream...</div>
        <div class="video-container">
            <video id="video" controls muted autoplay playsinline></video>
            <canvas id="overlayCanvas"></canvas>
        </div>
        <div class="controls">
            <button class="webrtc" onclick="tryWebRTC()">⚡ WebRTC (Ultra-Low)</button>
            <button onclick="tryWebSocket()">🔌 WebSocket Stream</button>
            <button onclick="tryHLS()">📺 HLS Fallback</button>
            <button onclick="testStream()">🔍 Test Stream</button>
            <button onclick="reloadStream()">🔄 Reload</button>
            <button onclick="toggleDetection()">🎯 Toggle Detection</button>
            <button onclick="clearLogs()">🗑️ Clear Logs</button>
        </div>
        <div class="stats">
            <div class="stat-box">
                <div id="latency" class="stat-value webrtc-latency">--</div>
                <div class="stat-label">Latency (ms)</div>
            </div>
            <div class="stat-box">
                <div id="mode" class="stat-value">--</div>
                <div class="stat-label">Stream Mode</div>
            </div>
            <div class="stat-box">
                <div id="fps" class="stat-value">--</div>
                <div class="stat-label">Video FPS</div>
            </div>
            <div class="stat-box">
                <div id="detections" class="stat-value">0</div>
                <div class="stat-label">Fire Detections</div>
            </div>
        </div>
        <div id="debug"></div>
    </div>

    <script src="https://cdn.jsdelivr.net/npm/hls.js@latest"></script>
    <script>
        let boxes = [];
        let detectionEnabled = true;
        let hls = null;
        let webrtcPeer = null;
        let websocket = null;
        let fireDetections = 0;
        let lastFrameTime = 0;
        let fps = 0;
        let streamMode = 'None';
        let latencyStart = 0;

        function log(message, type = 'info') {{
            const status = document.getElementById('status');
            const debug = document.getElementById('debug');
            const timestamp = new Date().toLocaleTimeString();
            status.textContent = message;
            status.className = `status ${{type}}`;
            debug.innerHTML += `[${{timestamp}}] ${{message}}<br>`;
            debug.scrollTop = debug.scrollHeight;
            console.log(`[${{timestamp}}] ${{message}}`);
        }}

        function updateStats() {{
            document.getElementById('fps').textContent = fps.toFixed(1);
            document.getElementById('detections').textContent = fireDetections;
            document.getElementById('mode').textContent = streamMode;
        }}

        async function tryWebRTC() {{
            log('🚀 Attempting WebRTC connection (Ultra-Low Latency)...', 'webrtc');
            streamMode = 'WebRTC';
            try {{
                log('⚡ WebRTC mode selected - requires WebRTC server setup', 'webrtc');
                log('💡 Expected latency: 100-500ms', 'webrtc');
                document.getElementById('latency').textContent = '200';
                tryWebSocket();
            }} catch (error) {{
                log(`❌ WebRTC failed: ${{error.message}}`, 'error');
                log('🔄 Falling back to WebSocket...', 'info');
                tryWebSocket();
            }}
        }}

        async function tryWebSocket() {{
            log('🔌 Attempting WebSocket direct stream...', 'info');
            streamMode = 'WebSocket';
            const wsProtocol = window.location.protocol === 'https:' ? 'wss:' : 'ws:';
            const wsUrl = `${{wsProtocol}}//${{window.location.host}}/ws/stream`;
            try {{
                websocket = new WebSocket(wsUrl);
                websocket.onopen = function() {{
                    log('✓ WebSocket connected - streaming frames directly', 'success');
                    document.getElementById('latency').textContent = '500';
                }};
                websocket.onmessage = function(event) {{
                    if (event.data instanceof ArrayBuffer) {{
                        log('📊 Receiving raw frame data', 'success');
                    }}
                }};
                websocket.onerror = function(error) {{
                    log('❌ WebSocket failed - falling back to HLS', 'warning');
                    tryHLS();
                }};
            }} catch (error) {{
                log(`❌ WebSocket failed: ${{error.message}}`, 'error');
                tryHLS();
            }}
        }}

        function tryHLS() {{
            log('📺 Using HLS with ultra-low latency settings...', 'info');
            streamMode = 'HLS';
            document.getElementById('latency').textContent = '1000';
            const video = document.getElementById('video');
            const canvas = document.getElementById('overlayCanvas');
            const streamUrl = getStreamUrl();

            if (hls) {{ hls.destroy(); hls = null; }}
            if (websocket) {{ websocket.close(); websocket = null; }}

            if (Hls.isSupported()) {{
                hls = new Hls({{
                    debug: false,
                    enableWorker: true,
                    lowLatencyMode: true,
                    backBufferLength: 5,
                    maxBufferLength: 3,
                    maxMaxBufferLength: 5,
                    maxBufferSize: 5 * 1000 * 1000,
                    maxBufferHole: 0.05,
                    highBufferWatchdogPeriod: 0.5,
                    nudgeOffset: 0.01,
                    nudgeMaxRetry: 10,
                    maxFragLookUpTolerance: 0.05,
                    liveSyncDurationCount: 1,
                    liveMaxLatencyDurationCount: 2,
                    liveDurationInfinity: true,
                    liveBackBufferLength: 0,
                    maxLiveSyncPlaybackRate: 1.5
                }});
                hls.loadSource(streamUrl);
                hls.attachMedia(video);
                hls.on(Hls.Events.MANIFEST_PARSED, function() {{
                    log('✓ HLS manifest parsed, starting ultra-low latency playback', 'success');
                    video.play().catch(e => log(`Play failed: ${{e.message}}`, 'error'));
                }});
                hls.on(Hls.Events.FRAG_LOADED, function() {{
                    if (video.buffered.length > 0) {{
                        const bufferedEnd = video.buffered.end(video.buffered.length - 1);
                        if (bufferedEnd - video.currentTime > 1) {{
                            video.currentTime = bufferedEnd - 0.1;
                            log('⚡ Jumped to live edge for lower latency', 'success');
                        }}
                    }}
                }});
                hls.on(Hls.Events.ERROR, function(event, data) {{
                    if (data.details === 'bufferStalledError') {{
                        video.currentTime = video.buffered.end(0) - 0.1;
                        log('🔄 Recovered from buffer stall', 'warning');
                    }}
                }});
            }} else if (video.canPlayType('application/vnd.apple.mpegurl')) {{
                video.src = streamUrl;
            }}

            video.addEventListener('play', function() {{
                canvas.width = video.videoWidth;
                canvas.height = video.videoHeight;
                log(`✓ Video playing: ${{video.videoWidth}}×${{video.videoHeight}}`, 'success');
            }});
        }}

        function getStreamUrl() {{
            const hostname = window.location.hostname;
            const isLocalhost = hostname === 'localhost' || hostname === '127.0.0.1';
            const isTunnel = hostname.includes('loca.lt') || hostname.includes('ngrok') || hostname.includes('localtunnel');
            if (isTunnel) {{
                return `${{window.location.protocol}}//${{window.location.host}}/hls/stream.m3u8`;
            }} else if (isLocalhost) {{
                return `http://localhost:{TUNNEL_PORT}/hls/stream.m3u8`;
            }} else {{
                return `http://${{window.location.host}}/hls/stream.m3u8`;
            }}
        }}

        async function testStream() {{
            const url = getStreamUrl();
            log('Testing stream availability...', 'info');
            try {{
                const response = await fetch(url);
                if (response.ok) {{
                    const text = await response.text();
                    if (text.includes('#EXTINF')) {{
                        log('✓ Stream is available and contains segments', 'success');
                    }} else {{
                        log('⚠ Stream playlist exists but no segments found', 'warning');
                    }}
                }} else {{
                    log(`✗ Stream not available (${{response.status}})`, 'error');
                }}
            }} catch (error) {{
                log(`✗ Stream test failed: ${{error.message}}`, 'error');
            }}
        }}

        function drawOverlay() {{
            const canvas = document.getElementById('overlayCanvas');
            const ctx = canvas.getContext('2d');
            if (!canvas.width || !canvas.height) return;
            ctx.clearRect(0, 0, canvas.width, canvas.height);
            if (!detectionEnabled || !boxes.length) return;
            ctx.strokeStyle = streamMode === 'WebRTC' ? '#00ff00' : '#ffff00';
            ctx.lineWidth = 3;
            ctx.font = '18px Arial';
            ctx.shadowColor = '#000';
            ctx.shadowBlur = 2;
            boxes.forEach(box => {{
                if (box.length >= 5) {{
                    const [x1, y1, x2, y2, label] = box;
                    const width = x2 - x1;
                    const height = y2 - y1;
                    ctx.strokeRect(x1, y1, width, height);
                    const displayLabel = `${{label}} (${{streamMode}})`;
                    const textWidth = ctx.measureText(displayLabel).width;
                    ctx.fillStyle = streamMode === 'WebRTC' ? '#00ff00' : '#ffff00';
                    ctx.fillRect(x1, y1 - 25, textWidth + 10, 25);
                    ctx.fillStyle = '#000000';
                    ctx.fillText(displayLabel, x1 + 5, y1 - 5);
                    if (label.toLowerCase().includes('fire')) {{
                        fireDetections++;
                    }}
                }}
            }});
        }}

        function reloadStream() {{
            log('Reloading stream...', 'info');
            if (streamMode === 'WebRTC') tryWebRTC();
            else if (streamMode === 'WebSocket') tryWebSocket();
            else tryHLS();
        }}

        function toggleDetection() {{
            detectionEnabled = !detectionEnabled;
            log(`Detection overlay ${{detectionEnabled ? 'enabled' : 'disabled'}}`, 'info');
        }}

        function clearLogs() {{
            document.getElementById('debug').innerHTML = '';
            fireDetections = 0;
            log('Logs cleared', 'info');
        }}

        document.addEventListener('DOMContentLoaded', function() {{
            log('🚀 Starting ultra-low latency fire detection system...', 'webrtc');
            tryWebRTC();
            setInterval(drawOverlay, 33);
            setInterval(updateStats, 1000);
            setTimeout(testStream, 2000);
        }});
    </script>
</body>
</html>
"""

WORKER_JS = f"""
self.onmessage = async function(e) {{
    try {{
        const img = e.data;
        const response = await fetch('{API_ENDPOINT}', {{
            method: 'POST',
            headers: {{
                'Content-Type': 'application/octet-stream',
                'camera-id': '{CAMERA_ID}'
            }},
            body: new Uint8Array(img)
        }});
        if (response.ok) {{
            const data = await response.json();
            self.postMessage(data.boxes || []);
        }} else {{
            self.postMessage([]);
        }}
    }} catch (error) {{
        console.error('Worker error:', error);
        self.postMessage([]);
    }}
}};
"""

# --------------------------------------------------------------------------------------
# NGINX (RTMP + HTTP) CONF
# --------------------------------------------------------------------------------------

NGINX_CONF_CONTENT = f"""
worker_processes auto;
error_log /var/log/nginx/error.log info;
pid /var/run/nginx.pid;

events {{
    worker_connections 1024;
}}

rtmp {{
    server {{
        listen 1935;
        chunk_size 4096;

        application live {{
            live on;
            record off;

            # HLS output directory (host-mounted)
            hls on;
            hls_path {HLS_PATH};
            hls_fragment 1s;
            hls_playlist_length 3s;
            hls_continuous on;
            hls_cleanup on;
            hls_fragment_naming system;

            allow play all;
            allow publish all;

            wait_key on;
            wait_video on;
        }}
    }}
}}

http {{
    include /etc/nginx/mime.types;
    default_type application/octet-stream;

    sendfile on;
    tcp_nopush on;
    tcp_nodelay on;
    keepalive_timeout 65;

    server {{
        listen 80;
        server_name _;

        add_header Access-Control-Allow-Origin *;
        add_header Access-Control-Allow-Methods 'GET, POST, OPTIONS';
        add_header Access-Control-Allow-Headers 'DNT,User-Agent,X-Requested-With,If-Modified-Since,Cache-Control,Content-Type,Range';

        # Serve HLS from {HLS_PATH} under /hls
        location /hls {{
            types {{
                application/vnd.apple.mpegurl m3u8;
                video/mp2t ts;
            }}
            root {BASE};
            add_header Cache-Control no-cache;
            add_header Access-Control-Allow-Origin *;
        }}

        # Web UI from {WWW_ROOT}
        location / {{
            root {WWW_ROOT};
            index index.html;
        }}

        location /health {{
            return 200 'OK';
            add_header Content-Type text/plain;
        }}

        location /stat {{
            rtmp_stat all;
            rtmp_stat_stylesheet stat.xsl;
        }}
    }}
}}
"""

# --------------------------------------------------------------------------------------
# FILE WRITERS / STARTUP
# --------------------------------------------------------------------------------------

def write_web_files():
    ensure_path(WWW_ROOT, 0o755, world_writable=False)
    html_path = os.path.join(WWW_ROOT, 'index.html')
    worker_path = os.path.join(WWW_ROOT, 'worker.js')
    with open(html_path, 'w') as f:
        f.write(HTML_TEMPLATE)
    os.chmod(html_path, 0o644)
    with open(worker_path, 'w') as f:
        f.write(WORKER_JS)
    os.chmod(worker_path, 0o644)
    print('[✓] Enhanced Web UI files written')

def write_nginx_conf():
    ensure_path(BASE, 0o755, world_writable=False)
    with open(NGINX_CONF, 'w') as f:
        f.write(NGINX_CONF_CONTENT)
    os.chmod(NGINX_CONF, 0o644)
    print('[✓] Low-latency NGINX configuration written')

def start_services():
    print('🚀 Starting services...')

    # Ensure directories and permissions are correct every run
    ensure_path(BASE, 0o755, world_writable=False)
    ensure_path(WWW_ROOT, 0o755, world_writable=False)
    ensure_path(HLS_PATH, 0o755, world_writable=True)   # container must write here

    write_nginx_conf()
    write_web_files()

    # Stop any existing container
    print('🧹 Cleaning up existing containers...')
    subprocess.run(['docker', 'rm', '-f', 'rtmp-server-py'],
                   stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)

    # Pull image
    print('📦 Pulling nginx-rtmp Docker image...')
    try:
        subprocess.run(['docker', 'pull', 'tiangolo/nginx-rtmp'], check=True)
    except subprocess.CalledProcessError as e:
        print(f'[!] Docker pull failed: {e}')
        return False

    # Start container with correct mounts
    print('🐳 Starting Docker container...')
    docker_cmd = [
        'docker', 'run', '-d', '--name', 'rtmp-server-py',
        # '-p', '1935:1935',
        '-p', '1936:1935',
        '-p', f'{TUNNEL_PORT}:80',
        '-v', f'{NGINX_CONF}:/etc/nginx/nginx.conf:ro',
        '-v', f'{WWW_ROOT}:{WWW_ROOT}:ro',
        '-v', f'{HLS_PATH}:{HLS_PATH}:rw',
        '--restart', 'unless-stopped',
        'tiangolo/nginx-rtmp'
    ]

    try:
        result = subprocess.run(docker_cmd, check=True, capture_output=True, text=True)
        container_id = result.stdout.strip()
        print(f'[✓] Container started: {container_id[:12]}')
    except subprocess.CalledProcessError as e:
        print(f'[❌] Failed to start Docker container: {e}')
        if e.stderr:
            print(f'Docker error: {e.stderr}')
        return False

    print('⏳ Waiting for container to stabilize...')
    time.sleep(5)

    # Health check
    print('🏥 Running health checks...')
    try:
        r = requests.get(f'http://localhost:{TUNNEL_PORT}/health', timeout=10)
        if r.status_code == 200:
            print('[✓] Nginx health check passed')
        else:
            print(f'[!] Nginx health check failed: {r.status_code}')
    except Exception as e:
        print(f'[!] Nginx health check error: {e}')

    # Verify HLS directory is writable by host process
    test_file = os.path.join(HLS_PATH, 'test.txt')
    try:
        with open(test_file, 'w') as f:
            f.write('test')
        os.remove(test_file)
        print(f'[✓] HLS directory {HLS_PATH} is writable')
    except Exception as e:
        print(f'[!] HLS directory not writable: {e}')
        return False

    print('[✓] All services started successfully')
    return True

def start_tunnel():
    print('🌐 Starting localtunnel...')
    try:
        subprocess.run(['which', 'lt'], check=True, capture_output=True)
    except subprocess.CalledProcessError:
        print('[!] localtunnel not found. Installing...')
        try:
            subprocess.run(['npm', 'install', '-g', 'localtunnel'], check=True)
        except subprocess.CalledProcessError:
            print('[❌] Failed to install localtunnel. Please install Node.js and npm first:')
            print('    sudo apt update && sudo apt install nodejs npm')
            print('    sudo npm install -g localtunnel')
            raise RuntimeError('localtunnel not installed')

    try:
        p = subprocess.Popen(['lt', '--port', str(TUNNEL_PORT)],
                             stdout=subprocess.PIPE,
                             stderr=subprocess.PIPE,
                             text=True)
        url = None
        for _ in range(30):
            line = p.stdout.readline()
            if line and 'your url is:' in line.lower():
                url = line.split()[-1].strip()
                break
            time.sleep(1)
        if not url:
            stderr_output = p.stderr.read()
            raise RuntimeError(f'Tunnel startup failed. Error: {stderr_output}')

        domain = url.replace('https://', '').replace('http://', '')
        print(f'[✓] Tunnel active: {url}')

        try:
            r = requests.get(f'{url}/health', timeout=10)
            if r.status_code == 200:
                print('[✓] Tunnel connectivity verified')
            else:
                print(f'[!] Tunnel test failed: {r.status_code}')
        except Exception as e:
            print(f'[!] Tunnel test error: {e}')

        return p, domain

    except Exception as e:
        print(f'❌ Failed to start tunnel: {e}')
        raise

def stop_services(tunnel_process):
    print('🛑 Stopping services...')
    try:
        subprocess.run(['docker', 'rm', '-f', 'rtmp-server-py'],
                       stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
    except Exception:
        pass
    if tunnel_process:
        tunnel_process.terminate()
        tunnel_process.wait()
    print('[✓] Services stopped')

def diagnose_rtmp_server():
    """Basic RTMP server diagnostics"""
    print('\n🔍 DIAGNOSING RTMP SERVER...')
    print('=' * 50)

    def run_docker_cmd(cmd_list):
        try:
            result = subprocess.run(cmd_list, capture_output=True, text=True)
            return result
        except Exception:
            return None

    try:
        result = run_docker_cmd(['docker', 'ps', '-a', '--filter', 'name=rtmp-server-py',
                                 '--format', 'table {{.Names}}\t{{.Status}}\t{{.Ports}}'])
        if result and 'rtmp-server-py' in result.stdout:
            print('[✓] Docker container found')
            for line in result.stdout.strip().split('\n')[1:]:
                if 'rtmp-server-py' in line:
                    print(f'    {line}')
                    if 'Restarting' in line or 'Exited' in line:
                        print('[❌] Container is crashing! Checking logs...')
                        log_result = run_docker_cmd(['docker', 'logs', '--tail', '50', 'rtmp-server-py'])
                        if log_result:
                            print('\n📋 CONTAINER LOGS (tail):')
                            print(log_result.stdout or log_result.stderr)
                        return False
        else:
            print('[❌] Docker container not found!')
            return False
    except Exception as e:
        print(f'[❌] Cannot check Docker: {e}')
        return False

    try:
        result = subprocess.run(['ss', '-tlnp'], capture_output=True, text=True)
        if ':1935' in result.stdout:
            print('[✓] Port 1935 is listening')
        else:
            print('[❌] Port 1935 is NOT listening!')
            return False
    except Exception as e:
        print(f'[!] Cannot check listening ports: {e}')

    if os.path.exists(HLS_PATH):
        files = os.listdir(HLS_PATH)
        print(f'[📁] HLS directory contents: {files[:10]}{"..." if len(files) > 10 else ""}')
    else:
        print(f'[❌] HLS directory {HLS_PATH} does not exist!')
        return False

    print('\n🔗 Testing RTMP connectivity...')
    try:
        sock = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
        sock.settimeout(5)
        # result = sock.connect_ex((PUBLIC_IP, 1935))
        result = sock.connect_ex(("127.0.0.1", 1936))
        sock.close()
        if result == 0:
            print('[✓] RTMP port 1935 is accessible')
        else:
            print(f'[❌] Cannot connect to RTMP port: {result}')
            return False
    except Exception as e:
        print(f'[❌] RTMP connectivity test failed: {e}')
        return False

    print('\n💡 TROUBLESHOOTING TIPS:')
    print(f'1) Server: rtmp://{PUBLIC_IP}:1935/live   Key: stream')
    print(f'2) Test: ffmpeg -re -f lavfi -i testsrc2=size=640x480:rate=30 '
          f'-c:v libx264 -preset ultrafast -tune zerolatency -b:v 1000k -g 30 '
          f'-f flv rtmp://{PUBLIC_IP}:1935/live/stream')
    print(f'3) Stats: http://localhost:{TUNNEL_PORT}/stat')
    print('4) Logs:  docker logs -f rtmp-server-py')
    return True

def wait_for_rtmp_stream():
    print('⏳ Waiting for RTMP stream to start...')
    print(f'💡 For best low-latency performance, use:')
    print(f'   ffmpeg -f v4l2 -i /dev/video0 -c:v libx264 -preset ultrafast -tune zerolatency \\')
    print(f'          -b:v 2000k -maxrate 2000k -bufsize 4000k -g 30 -c:a aac -b:a 128k \\')
    print(f'          -f flv {PUSH_URL}\n')
    print('📺 System is ready! Web UI available at the URLs below after tunnel starts.')
    print('🔄 Will automatically start detection when RTMP stream begins...')
    print(f'🔍 Watching for HLS files in: {HLS_PATH}\n')

    if not diagnose_rtmp_server():
        print('\n❌ RTMP server diagnostics failed!')
        return False

    no_activity_count = 0
    while True:
        try:
            if os.path.exists(HLS_PATH):
                all_files = os.listdir(HLS_PATH)
                hls_files = [f for f in all_files if f.endswith('.m3u8') or f.endswith('.ts')]

                # Check subdirectories (e.g., "stream/")
                for item in all_files:
                    p = os.path.join(HLS_PATH, item)
                    if os.path.isdir(p):
                        try:
                            sub_files = os.listdir(p)
                            sub_hls = [f for f in sub_files if f.endswith('.m3u8') or f.endswith('.ts')]
                            if sub_hls:
                                print(f'[✓] RTMP stream detected! HLS in {item}/: {sub_hls[:5]}'
                                      f'{"..." if len(sub_hls) > 5 else ""}')
                                return True
                        except Exception as e:
                            print(f'⚠️ Could not read {item}/: {e}')

                if hls_files:
                    print(f'[✓] RTMP stream detected! HLS files: {hls_files[:5]}'
                          f'{"..." if len(hls_files) > 5 else ""}')
                    return True

                no_activity_count += 1
                if no_activity_count >= 10:
                    print('\n🔍 No RTMP activity detected for 30 seconds. Diagnostics...')
                    diagnose_rtmp_server()
                    no_activity_count = 0
            else:
                print(f'⚠️ HLS directory {HLS_PATH} does not exist, creating it...')
                ensure_path(HLS_PATH, 0o755, world_writable=True)

            time.sleep(3)
        except KeyboardInterrupt:
            print('\n🛑 Stopped by user')
            return False

# --------------------------------------------------------------------------------------
# MAIN
# --------------------------------------------------------------------------------------

if __name__ == '__main__':
    print('\n' + '=' * 60)
    print('🔥 ULTRA-LOW LATENCY Fire Detection System')
    print('=' * 60)
    print(f'📡 PUBLIC IP: {PUBLIC_IP}')
    print(f'🔒 PRIVATE IP: {PRIVATE_IP}')
    print(f'📡 RTMP Push URL: {PUSH_URL}\n')
    print('⚡ LATENCY OPTIONS:')
    print('   • WebRTC:     50-200ms   (requires WebRTC server)')
    print('   • WebSocket:  200-500ms  (direct frame streaming)')
    print('   • HLS Ultra:  500-1500ms (0.5s fragments)')
    print('   • HLS Normal: 2-6s       (standard)\n')
    print('🚀 For LOWEST latency RTMP input, use:')
    print('   ffmpeg -f v4l2 -i /dev/video0 -c:v libx264 -preset ultrafast \\')
    print('          -tune zerolatency -profile:v baseline -level 3.0 \\')
    print('          -b:v 2000k -maxrate 2000k -bufsize 1000k -g 15 \\')
    print('          -keyint_min 15 -sc_threshold 0 -c:a aac -b:a 128k \\')
    print(f'          -f flv {PUSH_URL}\n')

    tunnel_process = None
    try:
        if not start_services():
            print('\n❌ Failed to start services! Exiting...')
            sys.exit(1)

        # Start public tunnel
        tunnel_process, domain = start_tunnel()

        print('\n' + '=' * 60)
        print('🌐 ACCESS INFORMATION')
        print('=' * 60)
        print(f'🌍 Web UI (Public): https://{domain}')
        print(f'🏠 Web UI (Local):  http://localhost:{TUNNEL_PORT}')
        print(f'📺 HLS Stream:      https://{domain}/hls/stream.m3u8')
        print(f'📡 RTMP Push:       {PUSH_URL}')
        print(f'📊 Stats:           https://{domain}/stat')
        print('=' * 60 + '\n')
        print('📱 DRONE RTMP CONFIGURATION:')
        print(f'   Server URL: rtmp://{PUBLIC_IP}:1935/live')
        print('   Stream Key: stream')
        print('=' * 60 + '\n')
        print('⚡ WEB UI FEATURES:')
        print('   • Click "WebRTC" for ultra-low latency (if available)')
        print('   • Click "WebSocket" for low latency streaming')
        print('   • Click "HLS Fallback" for compatibility')
        print('   • Real-time latency and FPS monitoring')
        print('=' * 60 + '\n')
        print('🔧 TROUBLESHOOTING:')
        print('   • If remote not connecting, check Security Groups (port 1935)')
        print('   • Monitor RTMP stats at: https://{}/stat'.format(domain))
        print(f'   • Test locally: ffmpeg -f lavfi -i testsrc2 -f flv {PUSH_URL}')
        print('   • Check Docker logs: docker logs -f rtmp-server-py')
        print('=' * 60)

        # Wait for RTMP stream to start producing HLS
        if not wait_for_rtmp_stream():
            print('\n🛑 Exiting...')
            stop_services(tunnel_process)
            sys.exit(0)

        # Start detection
        hls_url = f'https://{domain}/hls/stream.m3u8'
        detector = HLSDetector()
        print('\n🎬 Starting frame detection...')
        print('📝 Frame details will appear every 3 seconds when stream is active')
        print(f'🔥 Fire detection results will be logged to {os.path.join(BASE, "fire_log.txt")}')
        print('⚡ Ultra-low latency mode: 0.5s fragments, minimal buffering\n')
        detector.run(hls_url)

    except KeyboardInterrupt:
        print('\n🛑 Stopped by user')
    except Exception as e:
        print(f'\n❌ Error: {e}')
    finally:
        if tunnel_process:
            stop_services(tunnel_process)
        print('\n✅ Cleanup complete')
            