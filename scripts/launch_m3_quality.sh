#!/usr/bin/env bash
# Authorized existing single-key channel only. Key travels in a memory pipe/FIFO.
set -euo pipefail
[[ $# == 6 ]] || { echo 'usage: EXPERIMENT_DIR IMAGE_SHA256 GATEWAY SECRET_READER_MODULE pilot|remainder CONTAINER_NAME' >&2; exit 2; }
experiment_dir=$(realpath "$1")
image_id=$2
gateway=$3
reader_module=$4
phase=$5
name=$6
repo_dir=$(cd "$(dirname "$0")/.." && pwd)
[[ "$image_id" =~ ^sha256:[0-9a-f]{64}$ ]]
[[ "$gateway" =~ ^[a-zA-Z0-9_-]+$ && "$name" =~ ^[a-zA-Z0-9_-]+$ ]]
[[ "$reader_module" =~ ^/app/dist/secret-store-[a-zA-Z0-9_-]+\.mjs$ ]]
[[ "$phase" == pilot || "$phase" == remainder ]]
limit=3
if [[ "$phase" == remainder ]]; then limit=47; fi
# The worker script also checks sample, pilot results and cumulative 60-call cap.
docker run -d --name "$name" --network bridge --read-only --user 1000:1000 \
 --cap-drop ALL --security-opt no-new-privileges --cpus 2 --memory 2g --memory-swap 2g \
 --tmpfs /tmp:rw,size=128m -v "$repo_dir/scripts:/scripts:ro" \
 -v "$experiment_dir:/experiment:rw" --entrypoint /bin/sh "$image_id" \
 -c 'mkfifo -m 600 /tmp/key; exec /opt/nas-filetools/.venv/bin/python /scripts/m3_transcription_quality.py run --directory /experiment --phase "$1" --limit "$2" --timeout 180 < /tmp/key' sh "$phase" "$limit"
# No secret is a command argument, environment variable, log or regular file.
docker exec "$gateway" node --input-type=module -e 'const {readSecretStoreValue}=await import(process.argv[1]);const r=readSecretStoreValue({name:"MINIMAX_API_KEY"});if(!r.ok||!r.value)process.exit(2);process.stdout.write(r.value+"\n");' "$reader_module" |
 docker exec -i "$name" /bin/sh -c 'cat > /tmp/key'
