#!/usr/bin/env bash
# Independent DEV container. Optional single credential arrives via stdin, never argv.
set -euo pipefail
[[ $# -ge 4 && $# -le 5 ]] || { echo 'usage: STORE CONFIG IMAGE_ID CONTAINER_NAME [CREDENTIAL_ENV]' >&2; exit 2; }
store=$(realpath "$1")
config=$(realpath "$2")
image=$3
name=$4
credential=${5:--}
[[ "$image" =~ ^sha256:[0-9a-f]{64}$ && "$name" =~ ^filetools-http-dev-[a-z0-9-]+$ ]]
[[ "$credential" == '-' || "$credential" =~ ^[A-Z][A-Z0-9_]{1,80}$ ]]
repo=$(cd "$(dirname "$0")/.." && pwd)
# Check chosen port first. Never stop whatever owns a conflicting listener.
python3 - "$config" <<'PY'
import json,socket,sys
config=json.load(open(sys.argv[1]));assert config['service']['bind']=='127.0.0.1'
with socket.socket() as sock:
 sock.setsockopt(socket.SOL_SOCKET,socket.SO_REUSEADDR,1)
 sock.bind(('127.0.0.1',config['service']['port']))
PY
docker run -d --name "$name" --network host --read-only --user 1000:1000 \
 --cap-drop ALL --security-opt no-new-privileges --cpus 2 --memory 4g --memory-swap 4g \
 --tmpfs /tmp:rw,size=256m -e PYTHONPATH=/repo/src -e PYTHONDONTWRITEBYTECODE=1 \
 -v "$repo:/repo:ro" -v "$store:/data:rw" -v "$config:/config.json:ro" \
 --entrypoint /bin/sh "$image" -c '
 if [ "$1" != "-" ]; then
   mkfifo -m 600 /tmp/credential
   exec /opt/nas-filetools/.venv/bin/python -m nas_filetools.standalone.http --root /data --config /config.json --credential-stdin "$1" < /tmp/credential
 fi
 exec /opt/nas-filetools/.venv/bin/python -m nas_filetools.standalone.http --root /data --config /config.json
 ' sh "$credential"
if [[ "$credential" != '-' ]]; then
 docker exec -i "$name" /bin/sh -c 'cat > /tmp/credential'
fi
