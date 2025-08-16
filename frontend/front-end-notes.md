web/
├─ index.html
├─ styles.css
├─ config.js              # endpoints & cameraId
├─ app.js                 # wires UI → players → overlay
├─ player-hls.js          # HLS playback
├─ player-webrtc.js       # WebRTC relay (generic signaling)
├─ detection-overlay.js   # frame capture + draw boxes
└─ detector.worker.js     # optional off-main-thread detector calls


HLS in js is a library that incorporates HTTP live streaming client directly in browsers. 

startWebRtc, stopWebRtc. 

DetectionOverlay, that samples frames and draws boxes. 

tiny status and logging system and a few utility buttons. 

we are just setting up a test server, not something crazy. 

on the backend i ran these steps to setup:

```

(my_env) (base) mathan@Mathans-MacBook-Pro Firebeats % sed -i '' 's|^ *hls_path .*;|      hls_path /hls;|' "$FIREBEATS_BASE/nginx_rtmp.conf"

(my_env) (base) mathan@Mathans-MacBook-Pro Firebeats % grep -n 'hls_path' "$FIREBEATS_BASE/nginx_rtmp.conf"

21:      hls_path /hls;
(my_env) (base) mathan@Mathans-MacBook-Pro Firebeats % mkdir -p "$FIREBEATS_BASE/hls" "$FIREBEATS_BASE/www"

(my_env) (base) mathan@Mathans-MacBook-Pro Firebeats % docker rm -f rtmp-server 2>/dev/null || true

rtmp-server
(my_env) (base) mathan@Mathans-MacBook-Pro Firebeats % docker run -d --name rtmp-server --restart unless-stopped \
  -p 1935:1935 -p 8080:80 \
  -v "$FIREBEATS_BASE/nginx_rtmp.conf:/etc/nginx/nginx.conf:ro" \
  -v "$FIREBEATS_BASE/www:/usr/share/nginx/html:ro" \
  -v "$FIREBEATS_BASE/hls:/hls" \
  tiangolo/nginx-rtmp
5d70f073955e571683b8ec1b4fa2a37c8523dc5bfa126e9a76307063a69957ff
(my_env) (base) mathan@Mathans-MacBook-Pro Firebeats % docker logs --tail=50 rtmp-server
2025/08/13 19:51:38 [notice] 1#1: using the "epoll" event method
2025/08/13 19:51:38 [notice] 1#1: nginx/1.23.2
2025/08/13 19:51:38 [notice] 1#1: built by gcc 10.2.1 20210110 (Debian 10.2.1-6) 
2025/08/13 19:51:38 [notice] 1#1: OS: Linux 6.4.16-linuxkit
2025/08/13 19:51:38 [notice] 1#1: getrlimit(RLIMIT_NOFILE): 1048576:1048576
2025/08/13 19:51:38 [notice] 1#1: start worker processes
2025/08/13 19:51:38 [notice] 1#1: start worker process 7
2025/08/13 19:51:38 [notice] 1#1: start worker process 8
2025/08/13 19:51:38 [notice] 1#1: start worker process 9
2025/08/13 19:51:38 [notice] 1#1: start worker process 10
2025/08/13 19:51:38 [notice] 1#1: start worker process 11
2025/08/13 19:51:38 [notice] 1#1: start worker process 12
2025/08/13 19:51:38 [notice] 1#1: start worker process 13
2025/08/13 19:51:38 [notice] 1#1: start worker process 14
2025/08/13 19:51:38 [notice] 1#1: start worker process 15
2025/08/13 19:51:38 [notice] 1#1: start worker process 16
2025/08/13 19:51:38 [notice] 1#1: start worker process 17
2025/08/13 19:51:38 [notice] 1#1: start worker process 18
2025/08/13 19:51:38 [notice] 1#1: start worker process 19
2025/08/13 19:51:38 [notice] 1#1: start worker process 20
2025/08/13 19:51:38 [notice] 1#1: start cache manager process 21
(my_env) (base) mathan@Mathans-MacBook-Pro Firebeats % curl -sI http://localhost:8080/healthz        # should be 200 OK

HTTP/1.1 200 OK
Server: nginx/1.23.2
Date: Wed, 13 Aug 2025 19:52:06 GMT
Content-Type: application/octet-stream
Content-Length: 2
Connection: keep-alive
Content-Type: text/plain

(my_env) (base) mathan@Mathans-MacBook-Pro Firebeats % ffmpeg -re -f lavfi -i testsrc2=size=1280x720:rate=30 \
       -c:v libx264 -preset ultrafast -tune zerolatency -g 30 \
       -f flv rtmp://127.0.0.1:1935/live/stream

ffmpeg version 7.1.1 Copyright (c) 2000-2025 the FFmpeg developers
  built with Apple clang version 16.0.0 (clang-1600.0.26.6)
  configuration: --prefix=/usr/local/Cellar/ffmpeg/7.1.1_3 --enable-shared --enable-pthreads --enable-version3 --cc=clang --host-cflags= --host-ldflags='-Wl,-ld_classic' --enable-ffplay --enable-gnutls --enable-gpl --enable-libaom --enable-libaribb24 --enable-libbluray --enable-libdav1d --enable-libharfbuzz --enable-libjxl --enable-libmp3lame --enable-libopus --enable-librav1e --enable-librist --enable-librubberband --enable-libsnappy --enable-libsrt --enable-libssh --enable-libsvtav1 --enable-libtesseract --enable-libtheora --enable-libvidstab --enable-libvmaf --enable-libvorbis --enable-libvpx --enable-libwebp --enable-libx264 --enable-libx265 --enable-libxml2 --enable-libxvid --enable-lzma --enable-libfontconfig --enable-libfreetype --enable-frei0r --enable-libass --enable-libopencore-amrnb --enable-libopencore-amrwb --enable-libopenjpeg --enable-libspeex --enable-libsoxr --enable-libzmq --enable-libzimg --disable-libjack --disable-indev=jack --enable-videotoolbox --enable-audiotoolbox
  libavutil      59. 39.100 / 59. 39.100
  libavcodec     61. 19.101 / 61. 19.101
  libavformat    61.  7.100 / 61.  7.100
  libavdevice    61.  3.100 / 61.  3.100
  libavfilter    10.  4.100 / 10.  4.100
  libswscale      8.  3.100 /  8.  3.100
  libswresample   5.  3.100 /  5.  3.100
  libpostproc    58.  3.100 / 58.  3.100
Input #0, lavfi, from 'testsrc2=size=1280x720:rate=30':
  Duration: N/A, start: 0.000000, bitrate: N/A
  Stream #0:0: Video: wrapped_avframe, yuv420p, 1280x720 [SAR 1:1 DAR 16:9], 30 fps, 30 tbr, 30 tbn
Stream mapping:
  Stream #0:0 -> #0:0 (wrapped_avframe (native) -> h264 (libx264))
Press [q] to stop, [?] for help
[libx264 @ 0x7f82a89084c0] using SAR=1/1
[libx264 @ 0x7f82a89084c0] using cpu capabilities: MMX2 SSE2Fast SSSE3 SSE4.2
[libx264 @ 0x7f82a89084c0] profile Constrained Baseline, level 3.1, 4:2:0, 8-bit
[libx264 @ 0x7f82a89084c0] 264 - core 164 r3108 31e19f9 - H.264/MPEG-4 AVC codec - Copyleft 2003-2023 - http://www.videolan.org/x264.html - options: cabac=0 ref=1 deblock=0:0:0 analyse=0:0 me=dia subme=0 psy=1 psy_rd=1.00:0.00 mixed_ref=0 me_range=16 chroma_me=1 trellis=0 8x8dct=0 cqm=0 deadzone=21,11 fast_pskip=1 chroma_qp_offset=0 threads=11 lookahead_threads=11 sliced_threads=1 slices=11 nr=0 decimate=1 interlaced=0 bluray_compat=0 constrained_intra=0 bframes=0 weightp=0 keyint=30 keyint_min=3 scenecut=0 intra_refresh=0 rc=crf mbtree=0 crf=23.0 qcomp=0.60 qpmin=0 qpmax=69 qpstep=4 ip_ratio=1.40 aq=0
Output #0, flv, to 'rtmp://127.0.0.1:1935/live/stream':
  Metadata:
    encoder         : Lavf61.7.100
  Stream #0:0: Video: h264 ([7][0][0][0] / 0x0007), yuv420p(tv, progressive), 1280x720 [SAR 1:1 DAR 16:9], q=2-31, 30 fps, 1k tbn
      Metadata:
        encoder         : Lavc61.19.101 libx264
      Side data:
        cpb: bitrate max/min/avg: 0/0/0 buffer size: 0 vbv_delay: N/A
frame= 2767 fps= 30 q=20.0 size=   87185KiB time=00:01:32.23 bitrate=7743.6kbits/s speed=1.01x    
```
when using a new terminal, i was able to check out
        the stream details by running 
        export FIREBEATS_BASE="$HOME/firebeats/stream"
        (base) mathan@Mathans-MacBook-Pro Firebeats % ls -l "$FIREBEATS_BASE/hls" | head

        total 16928
        -rw-r--r--  1 mathan  staff   987188 Aug 13 13:42 stream-1755117721422.ts
        -rw-r--r--  1 mathan  staff   994708 Aug 13 13:42 stream-1755117722424.ts
        -rw-r--r--  1 mathan  staff   979668 Aug 13 13:42 stream-1755117723424.ts
        -rw-r--r--  1 mathan  staff   986248 Aug 13 13:42 stream-1755117724427.ts
        -rw-r--r--  1 mathan  staff   989632 Aug 13 13:42 stream-1755117725424.ts
        -rw-r--r--  1 mathan  staff  1016140 Aug 13 13:42 stream-1755117726426.ts
        -rw-r--r--  1 mathan  staff  1001476 Aug 13 13:42 stream-1755117727424.ts
        -rw-r--r--  1 mathan  staff   987000 Aug 13 13:42 stream-1755117728426.ts
        -rw-r--r--  1 mathan  staff   701052 Aug 13 13:42 stream-1755117729424.ts
        (base) mathan@Mathans-MacBook-Pro Firebeats % docker exec rtmp-server sh -c 'ls -l /hls | head'

        total 6416
        -rw-r--r-- 1 nobody nogroup  999784 Aug 13 20:42 stream-1755117734427.ts
        -rw-r--r-- 1 nobody nogroup  979856 Aug 13 20:42 stream-1755117735427.ts
        -rw-r--r-- 1 nobody nogroup  982112 Aug 13 20:42 stream-1755117736426.ts
        -rw-r--r-- 1 nobody nogroup  987188 Aug 13 20:42 stream-1755117737424.ts
        -rw-r--r-- 1 nobody nogroup 1017832 Aug 13 20:42 stream-1755117738421.ts
        -rw-r--r-- 1 nobody nogroup  999784 Aug 13 20:42 stream-1755117739427.ts
        -rw-r--r-- 1 root   root     579792 Aug 13 20:42 stream-1755117740425.ts
        -rw-r--r-- 1 root   root        193 Aug 13 20:42 stream.m3u8
        (base) mathan@Mathans-MacBook-Pro Firebeats % 


had to cat and use this:
        cat > "$FIREBEATS_BASE/nginx_rtmp.conf" <<'NGINX'

        heredoc> >....                                                                                                                                                                            
            hls_fragment 1s;
            hls_playlist_length 6s;
            hls_nested off;
            }
        }
        }

        http {
        include       /etc/nginx/mime.types;
        default_type  application/octet-stream;
        sendfile      on;

        server {
            listen 80;

            root /usr/share/nginx/html;
            index index.html;

            # Serve HLS from the mounted /hls directory
            location /hls/ {
            types {
                application/vnd.apple.mpegurl m3u8;
                video/mp2t ts;
            }
            add_header Cache-Control no-cache;
            add_header Access-Control-Allow-Origin *;
            alias /hls/;
            expires -1;
            }

            location = /healthz { return 200 'ok'; add_header Content-Type text/plain; }
        }
        }
        NGINX




to restart the container
        docker rm -f rtmp-server 2>/dev/null || true


        docker run -d --name rtmp-server --restart unless-stopped \
        -p 1935:1935 -p 8080:80 \
        -v "$FIREBEATS_BASE/nginx_rtmp.conf:/etc/nginx/nginx.conf:ro" \
        -v "$FIREBEATS_BASE/www:/usr/share/nginx/html:ro" \
        -v "$FIREBEATS_BASE/hls:/hls" \
        tiangolo/nginx-rtmp        


to check the health
    curl -sI http://localhost:8080/healthz   # should be 200 OK



    docker exec rtmp-server sh -c 'grep -n "location /hls" -n /etc/nginx/nginx.conf && grep -n "alias /hls/" -n /etc/nginx/nginx.conf'


we need to restart the stream 
        ffmpeg -re -f lavfi -i testsrc2=size=1280x720:rate=30 \
            -c:v libx264 -preset ultrafast -tune zerolatency -g 30 \
            -f flv rtmp://127.0.0.1:1935/live/stream


# playlist should return plain text, not HTML 404
        curl http://localhost:8080/hls/stream.m3u8

# (while your ffmpeg is still pushing)
        ffplay http://localhost:8080/hls/stream.m3u8


results 

```
docker run -d --name rtmp-server --restart unless-stopped \
  -p 1935:1935 -p 8080:80 \
  -v "$FIREBEATS_BASE/nginx_rtmp.conf:/etc/nginx/nginx.conf:ro" \
  -v "$FIREBEATS_BASE/www:/usr/share/nginx/html:ro" \
  -v "$FIREBEATS_BASE/hls:/hls" \
  tiangolo/nginx-rtmp
193d7db1860280b173657e7b5377b75a228f4b0b1391e3ac0e3af3f641e9dc4a
(base) mathan@Mathans-MacBook-Pro Firebeats % curl -sI http://localhost:8080/healthz   # should be 200 OK

HTTP/1.1 200 OK
Server: nginx/1.23.2
Date: Wed, 13 Aug 2025 23:01:00 GMT
Content-Type: application/octet-stream
Content-Length: 2
Connection: keep-alive
Content-Type: text/plain

(base) mathan@Mathans-MacBook-Pro Firebeats % docker exec rtmp-server sh -c 'grep -n "location /hls" -n /etc/nginx/nginx.conf && grep -n "alias /hls/" -n /etc/nginx/nginx.conf'

36:    location /hls/ {
43:      alias /hls/;
(base) mathan@Mathans-MacBook-Pro Firebeats % docker exec rtmp-server sh -c 'ls -l /hls | head'

total 10596
-rw-r--r-- 1 nobody nogroup  974968 Aug 13 23:01 stream-0.ts
-rw-r--r-- 1 nobody nogroup  982864 Aug 13 23:01 stream-1.ts
-rw-r--r-- 1 root   root     919696 Aug 13 23:01 stream-10.ts
-rw-r--r-- 1 nobody nogroup  984932 Aug 13 23:01 stream-2.ts
-rw-r--r-- 1 nobody nogroup 1018208 Aug 13 23:01 stream-3.ts
-rw-r--r-- 1 nobody nogroup 1003356 Aug 13 23:01 stream-4.ts
-rw-r--r-- 1 root   root     982676 Aug 13 23:01 stream-5.ts
-rw-r--r-- 1 root   root     993956 Aug 13 23:01 stream-6.ts
-rw-r--r-- 1 root   root    1010312 Aug 13 23:01 stream-7.ts
(base) mathan@Mathans-MacBook-Pro Firebeats % ls -l "$FIREBEATS_BASE/hls" | head

total 24592
-rw-r--r--  1 mathan  staff   983804 Aug 13 16:01 stream-10.ts
-rw-r--r--  1 mathan  staff   995648 Aug 13 16:01 stream-11.ts
-rw-r--r--  1 mathan  staff   984180 Aug 13 16:01 stream-12.ts
-rw-r--r--  1 mathan  staff   981736 Aug 13 16:01 stream-13.ts
-rw-r--r--  1 mathan  staff   984180 Aug 13 16:01 stream-14.ts
-rw-r--r--  1 mathan  staff  1017644 Aug 13 16:01 stream-15.ts
-rw-r--r--  1 mathan  staff  1003168 Aug 13 16:01 stream-16.ts
-rw-r--r--  1 mathan  staff   665332 Aug 13 16:01 stream-17.ts
-rw-r--r--  1 mathan  staff   982676 Aug 13 16:01 stream-5.ts
(base) mathan@Mathans-MacBook-Pro Firebeats % curl http://localhost:8080/hls/stream.m3u8     # should print a small text manifest

#EXTM3U
#EXT-X-VERSION:3
#EXT-X-MEDIA-SEQUENCE:17
#EXT-X-TARGETDURATION:1
#EXTINF:1.000,
stream-17.ts
#EXTINF:1.000,
stream-18.ts
#EXTINF:1.000,
stream-19.ts
#EXTINF:1.000,
stream-20.ts
#EXTINF:1.000,
stream-21.ts
#EXTINF:1.000,
stream-22.ts
curl: (3) URL rejected: No host part in the URL
curl: (6) Could not resolve host: should
curl: (6) Could not resolve host: print
curl: (6) Could not resolve host: a
curl: (6) Could not resolve host: small
curl: (6) Could not resolve host: text
curl: (6) Could not resolve host: manifest
(base) mathan@Mathans-MacBook-Pro Firebeats % ffplay http://localhost:8080/hls/stream.m3u8                           

ffplay version 7.1.1 Copyright (c) 2003-2025 the FFmpeg developers
  built with Apple clang version 16.0.0 (clang-1600.0.26.6)
  configuration: --prefix=/usr/local/Cellar/ffmpeg/7.1.1_3 --enable-shared --enable-pthreads --enable-version3 --cc=clang --host-cflags= --host-ldflags='-Wl,-ld_classic' --enable-ffplay --enable-gnutls --enable-gpl --enable-libaom --enable-libaribb24 --enable-libbluray --enable-libdav1d --enable-libharfbuzz --enable-libjxl --enable-libmp3lame --enable-libopus --enable-librav1e --enable-librist --enable-librubberband --enable-libsnappy --enable-libsrt --enable-libssh --enable-libsvtav1 --enable-libtesseract --enable-libtheora --enable-libvidstab --enable-libvmaf --enable-libvorbis --enable-libvpx --enable-libwebp --enable-libx264 --enable-libx265 --enable-libxml2 --enable-libxvid --enable-lzma --enable-libfontconfig --enable-libfreetype --enable-frei0r --enable-libass --enable-libopencore-amrnb --enable-libopencore-amrwb --enable-libopenjpeg --enable-libspeex --enable-libsoxr --enable-libzmq --enable-libzimg --disable-libjack --disable-indev=jack --enable-videotoolbox --enable-audiotoolbox
  libavutil      59. 39.100 / 59. 39.100
  libavcodec     61. 19.101 / 61. 19.101
  libavformat    61.  7.100 / 61.  7.100
  libavdevice    61.  3.100 / 61.  3.100
  libavfilter    10.  4.100 / 10.  4.100
  libswscale      8.  3.100 /  8.  3.100
  libswresample   5.  3.100 /  5.  3.100
  libpostproc    58.  3.100 / 58.  3.100
[hls @ 0x7f9a1006c400] Skip ('#EXT-X-VERSION:3')
[hls @ 0x7f9a1006c400] Opening 'http://localhost:8080/hls/stream-37.ts' for reading
[hls @ 0x7f9a1006c400] Opening 'http://localhost:8080/hls/stream-38.ts' for reading
[http @ 0x7f9a1022c2c0] HTTP error 404 Not FoundB sq=    0B 
[hls @ 0x7f9a1006c400] Failed to open segment 38 of playlist 0
[hls @ 0x7f9a1006c400] Opening 'http://localhost:8080/hls/stream-38.ts' for reading
[http @ 0x7f9a10406800] HTTP error 404 Not Found
[hls @ 0x7f9a1006c400] Failed to open segment 38 of playlist 0
[hls @ 0x7f9a1006c400] Opening 'http://localhost:8080/hls/stream-38.ts' for reading
[http @ 0x7f99e8b043c0] HTTP error 404 Not Found
[hls @ 0x7f9a1006c400] Failed to open segment 38 of playlist 0
[hls @ 0x7f9a1006c400] Opening 'http://localhost:8080/hls/stream-38.ts' for reading
[http @ 0x7f99e8b05340] HTTP error 404 Not Found
[hls @ 0x7f9a1006c400] Failed to open segment 38 of playlist 0
[hls @ 0x7f9a1006c400] Opening 'http://localhost:8080/hls/stream-38.ts' for reading
[http @ 0x7f9a10406780] HTTP error 404 Not Found
[hls @ 0x7f9a1006c400] Failed to open segment 38 of playlist 0
[hls @ 0x7f9a1006c400] Opening 'http://localhost:8080/hls/stream-38.ts' for reading
[http @ 0x7f9a10406a80] HTTP error 404 Not Found
[hls @ 0x7f9a1006c400] Failed to open segment 38 of playlist 0
[hls @ 0x7f9a1006c400] Opening 'http://localhost:8080/hls/stream-38.ts' for reading
[http @ 0x7f9a10120880] HTTP error 404 Not Found
[hls @ 0x7f9a1006c400] Failed to open segment 38 of playlist 0
[hls @ 0x7f9a1006c400] Opening 'http://localhost:8080/hls/stream-38.ts' for reading
[http @ 0x7f999f7049c0] HTTP error 404 Not Found
[hls @ 0x7f9a1006c400] Failed to open segment 38 of playlist 0
[hls @ 0x7f9a1006c400] Opening 'http://localhost:8080/hls/stream-38.ts' for reading
[http @ 0x7f99ef804b40] HTTP error 404 Not Found
[hls @ 0x7f9a1006c400] Failed to open segment 38 of playlist 0
[hls @ 0x7f9a1006c400] Opening 'http://localhost:8080/hls/stream-38.ts' for reading
[http @ 0x7f99ef804f00] HTTP error 404 Not Found
[hls @ 0x7f9a1006c400] Failed to open segment 38 of playlist 0
[hls @ 0x7f9a1006c400] Opening 'http://localhost:8080/hls/stream-38.ts' for reading
[http @ 0x7f99e8b05180] HTTP error 404 Not Found
[hls @ 0x7f9a1006c400] Failed to open segment 38 of playlist 0
[hls @ 0x7f9a1006c400] Opening 'http://localhost:8080/hls/stream-38.ts' for reading
[http @ 0x7f99ef7048c0] HTTP error 404 Not Found
[hls @ 0x7f9a1006c400] Failed to open segment 38 of playlist 0
[hls @ 0x7f9a1006c400] Opening 'http://localhost:8080/hls/stream-38.ts' for reading
[http @ 0x7f99ef704a40] HTTP error 404 Not Found
[hls @ 0x7f9a1006c400] Failed to open segment 38 of playlist 0
[hls @ 0x7f9a1006c400] Opening 'http://localhost:8080/hls/stream-38.ts' for reading
[http @ 0x7f9a10406bc0] HTTP error 404 Not Found
[hls @ 0x7f9a1006c400] Failed to open segment 38 of playlist 0
[hls @ 0x7f9a1006c400] Opening 'http://localhost:8080/hls/stream-38.ts' for reading
[http @ 0x7f99e8b05b80] HTTP error 404 Not Found
[hls @ 0x7f9a1006c400] Failed to open segment 38 of playlist 0
[hls @ 0x7f9a1006c400] Opening 'http://localhost:8080/hls/stream-38.ts' for reading
[http @ 0x7f9a0f73a400] HTTP error 404 Not Found
[hls @ 0x7f9a1006c400] Failed to open segment 38 of playlist 0
[hls @ 0x7f9a1006c400] Opening 'http://localhost:8080/hls/stream-38.ts' for reading
[http @ 0x7f9a10120800] HTTP error 404 Not Found
[hls @ 0x7f9a1006c400] Failed to open segment 38 of playlist 0
[http @ 0x7f9a10322240] Stream ends prematurely at 555128, should be 986060
[hls @ 0x7f9a1006c400] Opening 'http://localhost:8080/hls/stream-38.ts' for reading
[http @ 0x7f99e8b04c80] HTTP error 404 Not FoundB sq=    0B 
[hls @ 0x7f9a1006c400] Failed to open segment 38 of playlist 0
[hls @ 0x7f9a1006c400] Skip ('#EXT-X-VERSION:3')
[hls @ 0x7f9a1006c400] skipping 61 segments ahead, expired from playlists
[http @ 0x7f9a12036600] Opening 'http://localhost:8080/hls/stream-99.ts' for reading
[hls @ 0x7f9a1006c400] Opening 'http://localhost:8080/hls/stream-99.ts' for reading
[hls @ 0x7f9a1006c400] Opening 'http://localhost:8080/hls/stream-100.ts' for reading
[mpegts @ 0x7f9a1031d4c0] PES packet size mismatch
[mpegts @ 0x7f9a1031d4c0] Packet corrupt (stream = 0, dts = 3440970).
[hls @ 0x7f9a1006c400] Packet corrupt (stream = 0, dts = 3438000).
[hls @ 0x7f9a1006c400] DTS discontinuity in stream 0: packet 16 with DTS 3440970, packet 17 with DTS 8973000
[http @ 0x7f99f8017c00] Opening 'http://localhost:8080/hls/stream-101.ts' for reading
[http @ 0x7f99ef704b80] HTTP error 404 Not FoundB sq=    0B 
[hls @ 0x7f9a1006c400] keepalive request failed for 'http://localhost:8080/hls/stream-101.ts' with error: 'Server returned 404 Not Found' when opening url, retrying with new connection
[hls @ 0x7f9a1006c400] Opening 'http://localhost:8080/hls/stream-101.ts' for reading
[http @ 0x7f99e8a083c0] HTTP error 404 Not Found
[hls @ 0x7f9a1006c400] Failed to open segment 101 of playlist 0
```


after these steps it worked. 

### to restart the backend container
```

docker rm -f rtmp-server
docker run -d --name rtmp-server --restart unless-stopped \
  -p 1935:1935 -p 8080:80 \
  -v "$FIREBEATS_BASE/nginx_rtmp.conf:/etc/nginx/nginx.conf:ro" \
  -v "$FIREBEATS_BASE/www:/usr/share/nginx/html:ro" \
  -v "$FIREBEATS_BASE/hls:/hls" \
  tiangolo/nginx-rtmp

```


```npx http-server . -p 8000```

then open ```http://localhost:8000/``` in browser

```npm create electron-vite@latest firebeats```

```npm run dev```

```BUILD_TARGET=web npm run dev:web```

<!-- to run in browser -->

### TESTING FLOW

Components in use:

Docker RTMP server (nginx-rtmp) – This is just a mock backend for streaming.

Frontend (browser or Electron) – This is your app’s UI that can play an HLS stream.

Test Stream Source – Something like FFmpeg generating color bars and sending them to rtmp://localhost:1935/live/stream.

Flow:

FFmpeg pushes the test video into the RTMP server.

RTMP server converts the stream into .m3u8 playlist + .ts segment files in /hls.

Frontend requests http://localhost:8080/hls/stream.m3u8.

Player shows the video


<!-- to send the ffmpeg to some stream -->
ffmpeg -re -f lavfi -i testsrc2=size=1280x720:rate=30 \
       -c:v libx264 -preset ultrafast -tune zerolatency -g 30 \
       -f flv rtmp://127.0.0.1:1935/live/stream

       # to send some stream to the python backend
       ffmpeg -re -f lavfi -i testsrc2=size=1280x720:rate=30 \
  -c:v libx264 -preset ultrafast -tune zerolatency -g 30 \
  -f flv rtmp://localhost:1936/live/stream

# to send the demo drone fire video. 
```ffmpeg -stream_loop -1 -re -i ./drone-fire.mp4 \
  -c:v libx264 -preset ultrafast -tune zerolatency -g 30 -keyint_min 30 -sc_threshold 0 \
  -c:a aac -b:a 128k -ar 44100 -ac 2 \
  -f flv rtmp://127.0.0.1:1936/live/stream```

<!-- Plans for extension -->

1. when we want to incorporate many cameras, we may need some kind of sqlite. db to store the camera data locally. 
2. or we may need something that queries from aws. the data. 




