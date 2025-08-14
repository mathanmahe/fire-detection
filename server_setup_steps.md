```echo $HOME
/Users/mathan
(base) mathan@Mathans-MacBook-Pro Firebeats % export FIREBEATS_BASE="$HOME/firebeats/stream"

(base) mathan@Mathans-MacBook-Pro Firebeats % cat > "$FIREBEATS_BASE/nginx_rtmp.conf" <<'NGINX'

heredoc> >....                                                                             
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
(base) mathan@Mathans-MacBook-Pro Firebeats % mkdir -p "$FIREBEATS_BASE/hls" "$FIREBEATS_BASE/www"

(base) mathan@Mathans-MacBook-Pro Firebeats % docker run --rm \
  -v "$FIREBEATS_BASE/nginx_rtmp.conf:/etc/nginx/nginx.conf:ro" \
  tiangolo/nginx-rtmp nginx -t
nginx: the configuration file /etc/nginx/nginx.conf syntax is ok
nginx: configuration file /etc/nginx/nginx.conf test is successful
(base) mathan@Mathans-MacBook-Pro Firebeats % docker rm -f rtmp-server 2>/dev/null || true

rtmp-server
(base) mathan@Mathans-MacBook-Pro Firebeats % docker run -d --name rtmp-server --restart unless-stopped \
  -p 1935:1935 -p 8080:80 \
  -v "$FIREBEATS_BASE/nginx_rtmp.conf:/etc/nginx/nginx.conf:ro" \
  -v "$FIREBEATS_BASE/www:/usr/share/nginx/html:ro" \
  -v "$FIREBEATS_BASE/hls:/hls" \
  tiangolo/nginx-rtmp
df452da49ad5265bf521c79620d22bed6c7405c080751a6e6d4bfad4d2f29328
(base) mathan@Mathans-MacBook-Pro Firebeats % docker ps

CONTAINER ID   IMAGE                 COMMAND                  CREATED         STATUS         PORTS                                          NAMES
df452da49ad5   tiangolo/nginx-rtmp   "nginx -g 'daemon of…"   5 seconds ago   Up 4 seconds   0.0.0.0:1935->1935/tcp, 0.0.0.0:8080->80/tcp   rtmp-server
(base) mathan@Mathans-MacBook-Pro Firebeats % docker logs --tail=50 rtmp-server

(base) mathan@Mathans-MacBook-Pro Firebeats % curl -sI http://localhost:8080/healthz   # should return 200 OK

HTTP/1.1 200 OK
Server: nginx/1.23.2
Date: Thu, 14 Aug 2025 00:50:46 GMT
Content-Type: application/octet-stream
Content-Length: 2
Connection: keep-alive
Content-Type: text/plain
```


in a diff terminal i ran
```ffmpeg -re -f lavfi -i testsrc2=size=1280x720:rate=30 \
       -c:v libx264 -preset ultrafast -tune zerolatency -g 30 \
       -f flv rtmp://127.0.0.1:1935/live/stream
    ```



back to main terminal
```
(base) mathan@Mathans-MacBook-Pro Firebeats % ls -l "$FIREBEATS_BASE/hls" | head

total 71392
-rw-r--r--  1 mathan  staff  1957456 Aug 13 17:51 stream-0.ts
-rw-r--r--  1 mathan  staff  2002764 Aug 13 17:51 stream-1.ts
-rw-r--r--  1 mathan  staff  1955200 Aug 13 17:52 stream-10.ts
-rw-r--r--  1 mathan  staff  1979828 Aug 13 17:52 stream-11.ts
-rw-r--r--  1 mathan  staff  1964788 Aug 13 17:52 stream-12.ts
-rw-r--r--  1 mathan  staff  2003892 Aug 13 17:52 stream-13.ts
-rw-r--r--  1 mathan  staff  1988664 Aug 13 17:52 stream-14.ts
-rw-r--r--  1 mathan  staff  2008592 Aug 13 17:52 stream-15.ts
-rw-r--r--  1 mathan  staff  1957080 Aug 13 17:52 stream-16.ts
(base) mathan@Mathans-MacBook-Pro Firebeats % curl http://localhost:8080/hls/stream.m3u8

#EXTM3U
#EXT-X-VERSION:3
#EXT-X-MEDIA-SEQUENCE:24
#EXT-X-TARGETDURATION:2
#EXTINF:2.000,
stream-24.ts
#EXTINF:2.000,
stream-25.ts
#EXTINF:2.000,
stream-26.ts
#EXTINF:2.000,
stream-27.ts
#EXTINF:2.000,
stream-28.ts
#EXTINF:2.000,
stream-29.ts
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
[hls @ 0x7fc50b82e6c0] Skip ('#EXT-X-VERSION:3')
[hls @ 0x7fc50b82e6c0] Opening 'http://localhost:8080/hls/stream-29.ts' for reading
[hls @ 0x7fc50b82e6c0] Opening 'http://localhost:8080/hls/stream-30.ts' for readi
```