You’re seeing “container is restarting” because Nginx can’t load the config it’s being given. Let’s nuke any stray edits and put a **known-good config** back, validate it, then bring the server up cleanly and prove that 1935 is listening.

Follow these exact steps:

---

## 0) Sanity: that “permission denied” line is harmless

You ran `$FIREBEATS_BASE` as a command:

```
% $FIREBEATS_BASE
zsh: permission denied: /Users/mathan/firebeats/stream
```

Totally fine—just means you attempted to *execute* a directory. Ignore it.

---

## 1) Write a pristine Nginx config

This has RTMP on 1935 and HLS served from `/hls`. (It also puts `hls_cleanup off;` inside the right block.)

```bash
export FIREBEATS_BASE="$HOME/firebeats/stream"

cat > "$FIREBEATS_BASE/nginx_rtmp.conf" <<'NGINX'
worker_processes  auto;
events { worker_connections 1024; }

rtmp {
  server {
    listen 1935;
    chunk_size 4096;

    application live {
      live on;
      record off;

      # HLS output
      hls on;
      hls_path /hls;
      hls_fragment 2s;
      hls_playlist_length 12s;
      hls_cleanup off;   # keep segments during testing to avoid 404s
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
```

Ensure dirs exist:

```bash
mkdir -p "$FIREBEATS_BASE/hls" "$FIREBEATS_BASE/www"
```

---

## 2) Validate the config before starting

This runs `nginx -t` inside the image against your file:

```bash
docker run --rm \
  -v "$FIREBEATS_BASE/nginx_rtmp.conf:/etc/nginx/nginx.conf:ro" \
  tiangolo/nginx-rtmp nginx -t
```

**Expect:** `syntax is ok` and `test is successful`.
If it errors, copy the output here; otherwise continue.

---

## 3) Start the container cleanly

```bash
docker rm -f rtmp-server 2>/dev/null || true

docker run -d --name rtmp-server --restart unless-stopped \
  -p 1935:1935 -p 8080:80 \
  -v "$FIREBEATS_BASE/nginx_rtmp.conf:/etc/nginx/nginx.conf:ro" \
  -v "$FIREBEATS_BASE/www:/usr/share/nginx/html:ro" \
  -v "$FIREBEATS_BASE/hls:/hls" \
  tiangolo/nginx-rtmp
```

Check it’s stable:

```bash
docker ps
docker logs --tail=50 rtmp-server
curl -sI http://localhost:8080/healthz   # should return 200 OK
```

---

## 4) Prove RTMP 1935 is listening

```bash
# quick TCP probe
nc -vz 127.0.0.1 1935  # should say "succeeded"
```

If `nc` isn’t available, this tiny Python probe works:

```bash
python3 - <<'PY'
import socket
s=socket.socket(); s.settimeout(2)
try:
  s.connect(("127.0.0.1",1935))
  print("OK: connected to 127.0.0.1:1935")
except Exception as e:
  print("FAIL:", e)
finally:
  s.close()
PY
```

If this fails, run:

```bash
docker logs --tail=100 rtmp-server
```

and send me the output—Nginx will say exactly what it doesn’t like.

---

## 5) Push a fresh test stream and play it

Clear any stale files (optional):

```bash
rm -f "$FIREBEATS_BASE/hls"/*
```

Start ffmpeg **after** 1935 is confirmed listening:

```bash
ffmpeg -re -f lavfi -i testsrc2=size=1280x720:rate=30 \
       -c:v libx264 -preset ultrafast -tune zerolatency -g 30 \
       -f flv rtmp://127.0.0.1:1935/live/stream
```

In another terminal:

```bash
# should show stream.m3u8 + .ts parts appearing
ls -l "$FIREBEATS_BASE/hls" | head

# playlist should print text (not HTML 404)
curl http://localhost:8080/hls/stream.m3u8

# play
ffplay http://localhost:8080/hls/stream.m3u8
```

---

### Why it broke just now

Your container started crash-looping again (“Restarting (1)”). That means the config file—after the last round of `sed` edits—ended up with a directive in the wrong block or a syntax mismatch. Using the **pristine config** + **nginx -t validation** avoids chasing ghosts.

Run the exact sequence above. If **any single step** fails (especially the `nginx -t` validation or the `nc -vz 127.0.0.1 1935` probe), paste that one command’s output and I’ll pinpoint the fix.
