#!/usr/bin/env python
"""
Universal RTSP Web Streamer with AI Fire Detection
Plug-and-play solution: Just change CAMERA_IP and run!
Works with any RTSP camera (Reolink, Hikvision, Dahua, etc.)
Includes AI-powered fire detection from drone code
"""

# ═══════════════════════════════════════════════════════════════
# IMPORTS
# ═══════════════════════════════════════════════════════════════
import cv2
import threading
import time
import signal
import sys
import os
import requests
import numpy as np
import json
from flask import Flask, render_template_string, Response, jsonify
from flask_cors import CORS

from datetime import datetime

# ═══════════════════════════════════════════════════════════════
# CONFIGURATION - CHANGE ONLY THESE VALUES
# ═══════════════════════════════════════════════════════════════

# Camera Settings
# CAMERA_IP = "192.168.1.201"          # ← Change this to your camera IP
# USERNAME = "admin"                  # ← Change if different
# PASSWORD = "CCTVCheck@123"          # ← Change to your password

CAMERA_IP = "10.0.0.142"          # ← Change this to your camera IP
USERNAME = "admin"                  # ← Change if different
PASSWORD = "CCTVCheck@123"          # ← Change to your password
WEB_PORT = 8083                     # ← Web interface port
STREAM_QUALITY = 80                 # ← JPEG quality (1-100)
FRAME_RATE = 20                     # ← Target FPS for web stream

# AI Fire Detection Settings (from drone code)
FIRE_DETECTION_ENABLED = True       # ← Enable/disable fire detection
CAMERA_ID = "rtsp_camera_1"         # ← Camera identifier for AI
API_ENDPOINT = "https://2cwzmjzkx4.execute-api.us-east-1.amazonaws.com/default/fire-frame-receiver"
FIRE_CHECK_INTERVAL = 3             # ← Check for fire every N seconds

# ═══════════════════════════════════════════════════════════════
# AUTO-GENERATED RTSP URLS
# ═══════════════════════════════════════════════════════════════
# RTSP_URLS = {
#     'main': f"rtsp://{USERNAME}:{PASSWORD}@{CAMERA_IP}:554/h264Preview_01_main",
#     'sub': f"rtsp://{USERNAME}:{PASSWORD}@{CAMERA_IP}:554/h264Preview_01_sub",
#     # Common alternatives (auto-tested)
#     'alt1': f"rtsp://{USERNAME}:{PASSWORD}@{CAMERA_IP}:554/stream1",
#     'alt2': f"rtsp://{USERNAME}:{PASSWORD}@{CAMERA_IP}:554/cam/realmonitor?channel=1&subtype=0",
#     'alt3': f"rtsp://{USERNAME}:{PASSWORD}@{CAMERA_IP}:554/live/ch1"
# }

RTSP_URLS = {
    # 'iphone': "rtsp://10.0.0.142:8554/stream"
    'iphone': f"rtsp://{USERNAME}:{PASSWORD}@10.0.0.142:8554/live"
}


os.environ["OPENCV_FFMPEG_CAPTURE_OPTIONS"] = (
    "rtsp_transport;tcp"          # force TCP (interleaved)
    "|stimeout;30000000"          # 30s socket open/read timeout (µs)
    "|rw_timeout;30000000"        # 30s read/write timeout (µs)
    "|max_delay;0"                # reduce interleaving delay
    "|reorder_queue_size;0"       # drop deep packet queues
    "|buffer_size;1024000"        # sane buffer
)

# ═══════════════════════════════════════════════════════════════
# GLOBAL VARIABLES
# ═══════════════════════════════════════════════════════════════
fire_detection_stats = {
    'total_detections': 0,
    'last_detection': None,
    'current_fire_detected': False,
    'last_check_time': None,
    'total_frames_processed': 0,
    'ai_responses': [],
    'last_ai_response': None
}

# ═══════════════════════════════════════════════════════════════
# HTML TEMPLATE - Modern Responsive Design
# ═══════════════════════════════════════════════════════════════
HTML_TEMPLATE = """
<!DOCTYPE html>
<html lang="en">
<head>
    <meta charset="UTF-8">
    <meta name="viewport" content="width=device-width, initial-scale=1.0">
    <title>RTSP AI Fire Detection System</title>
    <style>
        /* =========================== */
        /* GLOBAL STYLES */
        /* =========================== */
        * { 
            margin: 0; 
            padding: 0; 
            box-sizing: border-box; 
        }
        
        body { 
            font-family: 'Segoe UI', Tahoma, Geneva, Verdana, sans-serif;
            background: linear-gradient(135deg, #1e3c72 0%, #2a5298 100%);
            color: white; 
            min-height: 100vh;
        }
        
        .container { 
            max-width: 1400px; 
            margin: 0 auto; 
            padding: 20px;
        }

        /* =========================== */
        /* HEADER SECTION */
        /* =========================== */
        .header {
            text-align: center;
            margin-bottom: 30px;
            background: rgba(0,0,0,0.3);
            padding: 20px;
            border-radius: 10px;
            backdrop-filter: blur(10px);
        }
        
        .header h1 {
            font-size: 2.5em;
            margin-bottom: 10px;
            text-shadow: 2px 2px 4px rgba(0,0,0,0.5);
        }

        /* =========================== */
        /* VIDEO STREAM SECTION */
        /* =========================== */
        .stream-container {
            background: rgba(0,0,0,0.4);
            border-radius: 15px;
            padding: 20px;
            margin: 20px 0;
            backdrop-filter: blur(10px);
            box-shadow: 0 8px 32px rgba(0,0,0,0.3);
        }
        
        .video-wrapper {
            position: relative;
            width: 100%;
            max-width: 1200px;
            margin: 0 auto;
            border-radius: 10px;
            overflow: hidden;
            box-shadow: 0 4px 20px rgba(0,0,0,0.5);
        }
        
        #live-stream {
            width: 100%;
            height: auto;
            display: block;
            background: #000;
        }
        
        .fire-overlay {
            position: absolute;
            top: 10px;
            right: 10px;
            background: rgba(255, 0, 0, 0.9);
            color: white;
            padding: 15px 20px;
            border-radius: 8px;
            font-weight: bold;
            font-size: 16px;
            display: none;
            animation: fire-pulse 1s infinite;
            box-shadow: 0 4px 20px rgba(255, 0, 0, 0.5);
        }

        /* =========================== */
        /* CONTROLS SECTION */
        /* =========================== */
        .controls {
            display: flex;
            justify-content: center;
            gap: 10px;
            margin: 20px 0;
            flex-wrap: wrap;
        }
        
        .btn {
            background: #4CAF50;
            color: white;
            border: none;
            padding: 12px 24px;
            border-radius: 25px;
            cursor: pointer;
            font-size: 14px;
            font-weight: 600;
            transition: all 0.3s ease;
            box-shadow: 0 4px 15px rgba(76, 175, 80, 0.4);
        }
        
        .btn:hover {
            background: #45a049;
            transform: translateY(-2px);
            box-shadow: 0 6px 20px rgba(76, 175, 80, 0.6);
        }
        
        .btn.active {
            background: #2196F3;
            box-shadow: 0 4px 15px rgba(33, 150, 243, 0.4);
        }
        
        .btn.fire-btn {
            background: #ff6b6b;
            box-shadow: 0 4px 15px rgba(255, 107, 107, 0.4);
        }
        
        .btn.fire-btn:hover {
            background: #ff5252;
        }

        /* =========================== */
        /* INFO CARDS SECTION */
        /* =========================== */
        .info-grid {
            display: grid;
            grid-template-columns: repeat(auto-fit, minmax(300px, 1fr));
            gap: 20px;
            margin: 20px 0;
        }
        
        .info-card {
            background: rgba(0,0,0,0.3);
            padding: 20px;
            border-radius: 10px;
            backdrop-filter: blur(5px);
        }
        
        .info-card h3 {
            color: #4CAF50;
            margin-bottom: 15px;
            font-size: 1.2em;
        }
        
        .info-card.fire-card h3 {
            color: #ff6b6b;
        }
        
        .info-item {
            display: flex;
            justify-content: space-between;
            margin: 10px 0;
            padding: 8px;
            background: rgba(255,255,255,0.1);
            border-radius: 5px;
        }
        
        .status-indicator {
            display: inline-block;
            width: 12px;
            height: 12px;
            border-radius: 50%;
            background: #4CAF50;
            animation: pulse 2s infinite;
            margin-right: 8px;
        }
        
        .status-indicator.fire {
            background: #ff6b6b;
            animation: fire-pulse 1s infinite;
        }
        
        .ai-response {
            background: rgba(0,0,0,0.2);
            padding: 10px;
            border-radius: 5px;
            margin: 10px 0;
            font-family: monospace;
            font-size: 12px;
            max-height: 100px;
            overflow-y: auto;
        }

        /* =========================== */
        /* ANIMATIONS */
        /* =========================== */
        @keyframes pulse {
            0% { opacity: 1; }
            50% { opacity: 0.5; }
            100% { opacity: 1; }
        }
        
        @keyframes fire-pulse {
            0% { opacity: 1; transform: scale(1); }
            50% { opacity: 0.7; transform: scale(1.1); }
            100% { opacity: 1; transform: scale(1); }
        }

        /* =========================== */
        /* RESPONSIVE DESIGN */
        /* =========================== */
        @media (max-width: 768px) {
            .container { 
                padding: 10px; 
            }
            
            .header h1 { 
                font-size: 2em; 
            }
            
            .controls { 
                gap: 5px; 
            }
            
            .btn { 
                padding: 10px 16px; 
                font-size: 12px; 
            }
        }
    </style>
</head>
<body>
    <div class="container">
        <!-- ================================ -->
        <!-- HEADER SECTION -->
        <!-- ================================ -->
        <div class="header">
            <h1>🤖 RTSP AI Fire Detection</h1>
            <p>AI-Powered Fire Detection • Camera: {{ camera_ip }}</p>
        </div>
        
        <!-- ================================ -->
        <!-- VIDEO STREAM SECTION -->
        <!-- ================================ -->
        <div class="stream-container">
            <div class="video-wrapper">
                <img id="live-stream" 
                     src="/video_feed/main" 
                     alt="Loading live stream..." 
                     onerror="handleStreamError()" 
                     onload="handleStreamLoad()">
                <div class="fire-overlay" id="fire-alert">🔥 FIRE DETECTED!</div>
            </div>
            
            <div class="controls">
                <button class="btn active" id="btn-main" onclick="switchStream('main')">
                    🎬 Main Stream
                </button>
                <button class="btn" id="btn-sub" onclick="switchStream('sub')">
                    📱 Sub Stream
                </button>
                <button class="btn fire-btn" onclick="testFireDetection()">
                    🤖 Test AI Now
                </button>
                <button class="btn" onclick="refreshStream()">
                    🔄 Refresh
                </button>
                <button class="btn" onclick="toggleFullscreen()">
                    ⛶ Fullscreen
                </button>
            </div>
        </div>
        
        <!-- ================================ -->
        <!-- INFO CARDS SECTION -->
        <!-- ================================ -->
        <div class="info-grid">
            <!-- Stream Status Card -->
            <div class="info-card">
                <h3>📊 Stream Status</h3>
                <div class="info-item">
                    <span>Status:</span>
                    <span><span class="status-indicator"></span>Live</span>
                </div>
                <div class="info-item">
                    <span>Camera:</span>
                    <span>{{ camera_ip }}</span>
                </div>
                <div class="info-item">
                    <span>Protocol:</span>
                    <span>RTSP</span>
                </div>
                <div class="info-item">
                    <span>Quality:</span>
                    <span id="current-quality">Auto</span>
                </div>
            </div>
            
            <!-- AI Fire Detection Card -->
            <div class="info-card fire-card">
                <h3>🤖 AI Fire Detection</h3>
                <div class="info-item">
                    <span>AI Status:</span>
                    <span id="ai-status"><span class="status-indicator"></span>Active</span>
                </div>
                <div class="info-item">
                    <span>Detection Stream:</span>
                    <span>Sub Stream (Fast)</span>
                </div>
                <div class="info-item">
                    <span>Last Check:</span>
                    <span id="last-check">Never</span>
                </div>
                <div class="info-item">
                    <span>Total Checks:</span>
                    <span id="total-checks">0</span>
                </div>
                <div class="info-item">
                    <span>Fire Detected:</span>
                    <span id="fire-status">No</span>
                </div>
                <div class="ai-response" id="ai-response">Waiting for AI response...</div>
            </div>
            
            <!-- System Info Card -->
            <div class="info-card">
                <h3>🔧 System Info</h3>
                <div class="info-item">
                    <span>Web Port:</span>
                    <span>{{ web_port }}</span>
                </div>
                <div class="info-item">
                    <span>Started:</span>
                    <span id="start-time">{{ start_time }}</span>
                </div>
                <div class="info-item">
                    <span>Uptime:</span>
                    <span id="uptime">0m</span>
                </div>
                <div class="info-item">
                    <span>Camera ID:</span>
                    <span>{{ camera_id }}</span>
                </div>
            </div>
        </div>
    </div>

    <script>
        // ================================
        // GLOBAL VARIABLES
        // ================================
        let currentStream = 'main';
        let startTime = Date.now();
        
        // ================================
        // STREAM CONTROL FUNCTIONS
        // ================================
        function switchStream(stream) {
            currentStream = stream;
            const img = document.getElementById('live-stream');
            img.src = `/video_feed/${stream}?t=${Date.now()}`;
            
            // Update button states
            document.querySelectorAll('.btn').forEach(btn => btn.classList.remove('active'));
            document.getElementById(`btn-${stream}`).classList.add('active');
            
            // Update quality indicator
            document.getElementById('current-quality').textContent = 
                stream === 'main' ? 'HD' : 'SD';
        }
        
        function refreshStream() {
            const img = document.getElementById('live-stream');
            img.src = `/video_feed/${currentStream}?t=${Date.now()}`;
        }
        
        function toggleFullscreen() {
            const img = document.getElementById('live-stream');
            if (img.requestFullscreen) {
                img.requestFullscreen();
            } else if (img.webkitRequestFullscreen) {
                img.webkitRequestFullscreen();
            }
        }
        
        // ================================
        // AI FIRE DETECTION FUNCTIONS
        // ================================
        function testFireDetection() {
            fetch('/api/test_fire_detection')
                .then(response => response.json())
                .then(data => {
                    if (data.success) {
                        alert('🤖 Fire detection test sent to AI! Check the AI response panel for results.');
                    } else {
                        alert('❌ Fire detection test failed: ' + data.error);
                    }
                });
        }
        
        function updateFireStatus(data) {
            document.getElementById('last-check').textContent = data.last_check || 'Never';
            document.getElementById('total-checks').textContent = data.total_checks || 0;
            document.getElementById('fire-status').textContent = data.fire_detected ? 'YES' : 'No';
            
            // Update AI response
            if (data.last_ai_response) {
                document.getElementById('ai-response').textContent = data.last_ai_response;
            }
            
            const fireAlert = document.getElementById('fire-alert');
            const aiStatus = document.getElementById('ai-status');
            
            if (data.fire_detected) {
                fireAlert.style.display = 'block';
                aiStatus.innerHTML = '<span class="status-indicator fire"></span>FIRE DETECTED!';
            } else {
                fireAlert.style.display = 'none';
                aiStatus.innerHTML = '<span class="status-indicator"></span>Active';
            }
        }
        
        // ================================
        // ERROR HANDLING FUNCTIONS
        // ================================
        function handleStreamError() {
            const img = document.getElementById('live-stream');
            img.style.background = '#333';
            img.alt = 'Stream unavailable - Click refresh to retry';
        }
        
        function handleStreamLoad() {
            // Stream loaded successfully
        }
        
        // ================================
        // AUTO-UPDATE TIMERS
        // ================================
        
        // Update fire status every 5 seconds
        setInterval(() => {
            fetch('/api/fire_status')
                .then(response => response.json())
                .then(data => updateFireStatus(data));
        }, 5000);
        
        // Update uptime every minute
        setInterval(() => {
            const uptimeMinutes = Math.floor((Date.now() - startTime) / 60000);
            document.getElementById('uptime').textContent = `${uptimeMinutes}m`;
        }, 60000);
        
        // Auto-refresh stream every 30 seconds
        setInterval(refreshStream, 30000);
        
        // ================================
        // KEYBOARD SHORTCUTS
        // ================================
        document.addEventListener('keydown', (e) => {
            switch(e.key) {
                case '1': switchStream('main'); break;
                case '2': switchStream('sub'); break;
                case 't': testFireDetection(); break;
                case 'r': refreshStream(); break;
                case 'f': toggleFullscreen(); break;
            }
        });
    </script>
</body>
</html>
"""

# ═══════════════════════════════════════════════════════════════
# CAMERA STREAM CLASS
# ═══════════════════════════════════════════════════════════════

class UniversalCameraStream:
    def __init__(self):
        self.streams = {}
        self.active_streams = {}
        self.start_time = datetime.now()
        self.frame_lock = threading.Lock()
        self.fire_detection_thread = None
        
    def test_rtsp_url(self, url, timeout=5):
        """Test if RTSP URL is accessible"""
        cap = cv2.VideoCapture(url)
        cap.set(cv2.CAP_PROP_BUFFERSIZE, 1)
        
        if cap.isOpened():
            ret, frame = cap.read()
            cap.release()
            return ret and frame is not None
        return False
    
    def find_working_streams(self):
        """Auto-detect working RTSP streams"""
        print("🔍 Auto-detecting camera streams...")
        
        for name, url in RTSP_URLS.items():
            print(f"   Testing {name}: {url.replace(PASSWORD, '***')}")
            if self.test_rtsp_url(url):
                print(f"   ✅ {name} stream working")
                self.streams[name] = url
            else:
                print(f"   ❌ {name} stream failed")
        
        if not self.streams:
            # Fallback to basic URLs
            # basic_url = f"rtsp://{USERNAME}:{PASSWORD}@{CAMERA_IP}:554/"
            # basic_url = "rtsp://10.0.0.142:8554/stream"
            basic_url = f"rtsp://{USERNAME}:{PASSWORD}@10.0.0.142:8554/live"
            if self.test_rtsp_url(basic_url):
                self.streams['main'] = basic_url
                print(f"   ✅ Basic RTSP stream working")
        
        return len(self.streams) > 0
    
    def get_frame_details(self, frame):
        """Extract frame details (from drone code)"""
        if frame is None:
            return None
            
        height, width, channels = frame.shape
        
        # Calculate color stats
        mean_bgr = np.mean(frame, axis=(0, 1))
        
        # Brightness
        gray = cv2.cvtColor(frame, cv2.COLOR_BGR2GRAY)
        brightness = np.mean(gray)
        
        details = {
            'timestamp': datetime.now().strftime("%H:%M:%S"),
            'frame_number': fire_detection_stats['total_frames_processed'],
            'width': int(width),
            'height': int(height), 
            'channels': int(channels),
            'brightness': float(brightness),
            'mean_blue': float(mean_bgr[0]),
            'mean_green': float(mean_bgr[1]),
            'mean_red': float(mean_bgr[2])
        }
        
        return details

    def print_frame_details(self, details):
        """Print frame details (from drone code)"""
        if details is None:
            print("[!] No frame details available")
            return
            
        print(f"\n📺 FRAME DETAILS:")
        print(f"   Time: {details['timestamp']}")
        print(f"   Frame #: {details['frame_number']}")
        print(f"   Size: {details['width']}x{details['height']}")
        print(f"   Channels: {details['channels']}")
        print(f"   Brightness: {details['brightness']:.1f}")
        print(f"   RGB: R={details['mean_red']:.1f} G={details['mean_green']:.1f} B={details['mean_blue']:.1f}")

    def send_frame_to_ai(self, frame):
        """Send frame directly to AI fire detection API (no file saving)"""
        if frame is None:
            print("[!] No frame to send.")
            return None

        print(f"[🤖] Sending frame to AI model (Camera: {CAMERA_ID})...")
        try:
            # Encode frame directly to JPEG bytes
            ret, buffer = cv2.imencode('.jpg', frame, [cv2.IMWRITE_JPEG_QUALITY, 85])
            if not ret:
                print("[!] Failed to encode frame")
                return None
                
            res = requests.post(
                API_ENDPOINT,
                data=buffer.tobytes(),
                headers={
                    "Content-Type": "image/jpeg",
                    "camera-id": CAMERA_ID 
                },
                timeout=10
            )
            
            if res.status_code == 200:
                print(f"[🔥] AI Response: {res.text}")
                
                # Parse JSON response properly
                try:
                    response_data = json.loads(res.text)
                    fire_detected = response_data.get('fire_detected', False)
                except json.JSONDecodeError:
                    # Fallback to text parsing if not JSON
                    response_text = res.text.lower()
                    fire_detected = 'fire_detected": true' in response_text or '"fire": true' in response_text
                
                # Update stats
                fire_detection_stats['current_fire_detected'] = fire_detected
                fire_detection_stats['last_ai_response'] = res.text
                fire_detection_stats['ai_responses'].append({
                    'timestamp': datetime.now(),
                    'response': res.text,
                    'fire_detected': fire_detected
                })
                
                # Keep only last 10 responses
                if len(fire_detection_stats['ai_responses']) > 10:
                    fire_detection_stats['ai_responses'] = fire_detection_stats['ai_responses'][-10:]
                
                # Only print fire alert when fire is actually detected
                if fire_detected:
                    fire_detection_stats['total_detections'] += 1
                    fire_detection_stats['last_detection'] = datetime.now()
                    print("🚨 FIRE DETECTED BY AI! 🚨")
                
                return fire_detected
            else:
                print(f"[⚠️] AI API Error: {res.status_code} - {res.text}")
                fire_detection_stats['last_ai_response'] = f"API Error: {res.status_code}"
                return None
                
        except requests.exceptions.Timeout:
            print("[!] AI API timeout - request took too long")
            fire_detection_stats['last_ai_response'] = "API Timeout"
            return None
        except Exception as e:
            print(f"[!] AI API error: {e}")
            fire_detection_stats['last_ai_response'] = f"Error: {str(e)}"
            return None

    def fire_detection_worker(self):
        """Background worker for fire detection - using sub stream for speed"""
        print("[🔥] Starting fire detection worker...")
        print(f"🤖 Using AI model at: {API_ENDPOINT}")
        print(f"📷 Camera ID: {CAMERA_ID}")
        print(f"🔥 Using SUB STREAM for fire detection (faster, no lag)")
        print(f"🔥 Checking for fire every {FIRE_CHECK_INTERVAL} seconds...")
        
        while FIRE_DETECTION_ENABLED:
            try:
                # Get current frame directly from SUB stream (faster)
                if 'sub' in self.active_streams and self.active_streams['sub']['frame'] is not None:
                    with self.frame_lock:
                        current_frame = self.active_streams['sub']['frame'].copy()
                    
                    # Get frame details
                    details = self.get_frame_details(current_frame)
                    self.print_frame_details(details)
                    fire_detection_stats['total_frames_processed'] += 1
                    
                    # Send frame directly to AI (no file saving)
                    self.send_frame_to_ai(current_frame)
                    fire_detection_stats['last_check_time'] = datetime.now()
                else:
                    # Fallback to main stream if sub not available
                    if 'main' in self.active_streams and self.active_streams['main']['frame'] is not None:
                        with self.frame_lock:
                            current_frame = self.active_streams['main']['frame'].copy()
                        
                        # Get frame details
                        details = self.get_frame_details(current_frame)
                        self.print_frame_details(details)
                        fire_detection_stats['total_frames_processed'] += 1
                        
                        # Send frame directly to AI (no file saving)
                        self.send_frame_to_ai(current_frame)
                        fire_detection_stats['last_check_time'] = datetime.now()
                    else:
                        print("[!] No sub or main stream frame available")
                
                # Wait for next check
                time.sleep(FIRE_CHECK_INTERVAL)
                
            except Exception as e:
                print(f"[❌] Fire detection error: {e}")
                time.sleep(5)  # Wait before retrying
    
    def start_stream(self, stream_name):
        """Start a specific stream"""
        if stream_name not in self.streams:
            return False
            
        if stream_name in self.active_streams:
            return True  # Already running
        
        url = self.streams[stream_name]
        print(f"🎬 Starting {stream_name} stream...")
        
        # cap = cv2.VideoCapture(url)
        # cap.set(cv2.CAP_PROP_BUFFERSIZE, 1)

        cap = cv2.VideoCapture(url, cv2.CAP_FFMPEG)
        cap.set(cv2.CAP_PROP_BUFFERSIZE, 1)   # keep your low-latency buffer
        
        if not cap.isOpened():
            print(f"❌ Failed to start {stream_name} stream")
            return False
        
        stream_data = {
            'cap': cap,
            'frame': None,
            'running': True,
            'thread': None
        }
        
        # def update_frames():
        #     while stream_data['running']:
        #         ret, frame = stream_data['cap'].read()
        #         if ret:
        #             # Auto-resize large frames for web
        #             height, width = frame.shape[:2]
        #             if width > 1920:
        #                 scale = 1920 / width
        #                 new_width = int(width * scale)
        #                 new_height = int(height * scale)
        #                 frame = cv2.resize(frame, (new_width, new_height))
                    
        #             with self.frame_lock:
        #                 stream_data['frame'] = frame
        #         time.sleep(1.0 / FRAME_RATE)

        def update_frames():
            failures = 0
            last_ok = time.time()
            while stream_data['running']:
                ret, frame = stream_data['cap'].read()
                if ret and frame is not None:
                    failures = 0
                    last_ok = time.time()
                    h, w = frame.shape[:2]
                    if w > 1920:
                        scale = 1920 / w
                        frame = cv2.resize(frame, (int(w*scale), int(h*scale)))
                    with self.frame_lock:
                        stream_data['frame'] = frame
                else:
                    failures += 1

                # Reconnect if we haven’t seen a good frame for ~3s or many failures
                if failures >= 30 or (time.time() - last_ok) > 3:
                    try:
                        print(f"[RTSP] reconnecting {stream_name}...")
                        stream_data['cap'].release()
                    except: pass
                    time.sleep(0.5)
                    stream_data['cap'] = cv2.VideoCapture(url, cv2.CAP_FFMPEG)
                    stream_data['cap'].set(cv2.CAP_PROP_BUFFERSIZE, 1)
                    failures = 0
                    last_ok = time.time()

                time.sleep(1.0 / FRAME_RATE)

        def update_frames(stream_name, rtsp_url):
            sd = streams[stream_name]         # your per-stream dict
            failures = 0
            last_ok = time.time()

            def open_cap():
                cap = cv2.VideoCapture(rtsp_url, cv2.CAP_FFMPEG)
                cap.set(cv2.CAP_PROP_BUFFERSIZE, 1)
                return cap

            sd['cap'] = open_cap()

            while sd['running']:
                ret, frame = sd['cap'].read()
                if ret and frame is not None:
                    failures = 0
                    last_ok = time.time()
                    sd['frame'] = frame
                else:
                    failures += 1

                # if many consecutive failures or >3s since last good frame → reconnect
                if failures >= 30 or (time.time() - last_ok) > 3:
                    try:
                        print(f"[RTSP] reconnecting {stream_name}…")
                        sd['cap'].release()
                    except: pass
                    time.sleep(0.5)
                    sd['cap'] = open_cap()
                    failures = 0
                    last_ok = time.time()

                time.sleep(1.0 / FRAME_RATE)

        
        stream_data['thread'] = threading.Thread(target=update_frames, daemon=True)
        stream_data['thread'].start()
        
        self.active_streams[stream_name] = stream_data
        print(f"✅ {stream_name} stream started")
        
        # Start fire detection if this is the first stream and fire detection is enabled
        if FIRE_DETECTION_ENABLED and self.fire_detection_thread is None:
            self.fire_detection_thread = threading.Thread(target=self.fire_detection_worker, daemon=True)
            self.fire_detection_thread.start()
        
        return True
    
    def get_frame(self, stream_name):
        """Get current frame from stream"""
        if stream_name not in self.active_streams:
            if not self.start_stream(stream_name):
                return None
        
        stream_data = self.active_streams[stream_name]
        if stream_data['frame'] is not None:
            with self.frame_lock:
                ret, buffer = cv2.imencode('.jpg', stream_data['frame'], 
                                         [cv2.IMWRITE_JPEG_QUALITY, STREAM_QUALITY])
                return buffer.tobytes()
        return None
    
    def stop_all_streams(self):
        """Stop all active streams"""
        global FIRE_DETECTION_ENABLED
        FIRE_DETECTION_ENABLED = False  # Stop fire detection
        
        for stream_name, stream_data in self.active_streams.items():
            stream_data['running'] = False
            if stream_data['cap']:
                stream_data['cap'].release()
        self.active_streams.clear()

# ═══════════════════════════════════════════════════════════════
# FLASK WEB APPLICATION
# ═══════════════════════════════════════════════════════════════

# Global camera manager
camera = UniversalCameraStream()

def create_app():
    app = Flask(__name__)
    app.logger.disabled = True

    CORS(app, resources={r"/api/*": {"origins": "*"}},
     supports_credentials=False)
    
    CORS(app, resources={r"/video_feed/*": {"origins": "*"}})

    
    @app.route('/')
    def index():
        return render_template_string(HTML_TEMPLATE,
            camera_ip=CAMERA_IP,
            camera_id=CAMERA_ID,
            web_port=WEB_PORT,
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
        
        return Response(generate(),
                       mimetype='multipart/x-mixed-replace; boundary=frame')
    
    @app.route('/api/status')
    def api_status():
        return jsonify({
            'camera_ip': CAMERA_IP,
            'camera_id': CAMERA_ID,
            'streams': list(camera.streams.keys()),
            'active_streams': list(camera.active_streams.keys()),
            'uptime': str(datetime.now() - camera.start_time),
            'fire_detection_enabled': FIRE_DETECTION_ENABLED
        })
    
    @app.route('/api/fire_status')
    def api_fire_status():
        return jsonify({
            'fire_detected': fire_detection_stats['current_fire_detected'],
            'last_check': fire_detection_stats['last_check_time'].strftime("%H:%M:%S") if fire_detection_stats['last_check_time'] else None,
            'total_checks': fire_detection_stats['total_frames_processed'],
            'total_detections': fire_detection_stats['total_detections'],
            'last_detection': fire_detection_stats['last_detection'].strftime("%H:%M:%S") if fire_detection_stats['last_detection'] else None,
            'last_ai_response': fire_detection_stats['last_ai_response']
        })
    
    @app.route('/api/test_fire_detection')
    def api_test_fire_detection():
        try:
            # Use sub stream for testing (same as fire detection worker)
            if 'sub' in camera.active_streams and camera.active_streams['sub']['frame'] is not None:
                with camera.frame_lock:
                    current_frame = camera.active_streams['sub']['frame'].copy()
                result = camera.send_frame_to_ai(current_frame)
                return jsonify({'success': True, 'fire_detected': result, 'stream_used': 'sub'})
            # Fallback to main stream
            elif 'main' in camera.active_streams and camera.active_streams['main']['frame'] is not None:
                with camera.frame_lock:
                    current_frame = camera.active_streams['main']['frame'].copy()
                result = camera.send_frame_to_ai(current_frame)
                return jsonify({'success': True, 'fire_detected': result, 'stream_used': 'main'})
            else:
                return jsonify({'success': False, 'error': 'No sub or main stream frame available'})
        except Exception as e:
            return jsonify({'success': False, 'error': str(e)})
    
    return app

# ═══════════════════════════════════════════════════════════════
# SIGNAL HANDLERS AND MAIN FUNCTION
# ═══════════════════════════════════════════════════════════════

def signal_handler(signum, frame):
    print("\n🛑 Stopping all streams and fire detection...")
    camera.stop_all_streams()
    print("👋 Goodbye!")
    sys.exit(0)

def main():
    signal.signal(signal.SIGINT, signal_handler)
    
    print("🤖 RTSP AI Fire Detection System")
    print("=" * 60)
    print(f"📡 Camera IP: {CAMERA_IP}")
    print(f"📷 Camera ID: {CAMERA_ID}")
    print(f"👤 Username: {USERNAME}")
    print(f"🔒 Password: {'*' * len(PASSWORD)}")
    print(f"🌐 Web Port: {WEB_PORT}")
    print(f"🤖 AI Endpoint: {API_ENDPOINT}")
    print(f"🔥 Fire Detection: {'Enabled' if FIRE_DETECTION_ENABLED else 'Disabled'}")
    print("=" * 60)
    
    # Auto-detect working streams
    if not camera.find_working_streams():
        print("\n❌ No working RTSP streams found!")
        print("\n🔧 Troubleshooting:")
        print("1. Check camera IP address")
        print("2. Verify username/password")
        print("3. Ensure RTSP is enabled on camera")
        print("4. Check network connectivity")
        return 1
    
    print(f"\n✅ Found {len(camera.streams)} working stream(s)")
    
    # Start web server
    app = create_app()
    print(f"\n🌐 Starting web server with AI fire detection...")
    print(f"✅ Open http://localhost:{WEB_PORT} to view live stream")
    print(f"🎯 Available streams: {', '.join(camera.streams.keys())}")
    print(f"🤖 AI fire detection using SUB STREAM (faster, no lag)")
    print(f"🔥 Fire detection checks every {FIRE_CHECK_INTERVAL} seconds")
    print("⌨️  Keyboard shortcuts: 1=Main, 2=Sub, T=Test AI, R=Refresh, F=Fullscreen")
    print("⏹️  Press Ctrl+C to stop")
    
    try:
        app.run(host='0.0.0.0', port=WEB_PORT, debug=False, threaded=True)
    except KeyboardInterrupt:
        signal_handler(signal.SIGINT, None)

# ═══════════════════════════════════════════════════════════════
# DEPENDENCY MANAGEMENT AND ENTRY POINT
# ═══════════════════════════════════════════════════════════════

if __name__ == "__main__":
    # Auto-install dependencies
    required_packages = ['opencv-python', 'flask', 'requests', 'numpy']
    for package in required_packages:
        try:
            __import__(package.replace('-', '_'))
        except ImportError:
            print(f"📦 Installing {package}...")
            import subprocess
            subprocess.run([sys.executable, '-m', 'pip', 'install', package], check=True)
    
    # Import after installation
    import cv2
    from flask import Flask, render_template_string, Response, jsonify
    import requests
    import numpy as np
    
    sys.exit(main())