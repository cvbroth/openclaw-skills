#!/usr/bin/env bash
# Single offline attempt. Model/image preparation is a separate authorized step.
set -euo pipefail
if [[ $# != 6 ]]; then
  echo 'usage: run_ocr_cpu_trial.sh ENGINE IMAGE MODELS IMAGES NEW_RESULT_DIR PHYSICAL_PAGE' >&2
  exit 2
fi
engine=$1
image=$2
models=$(realpath "$3")
images=$(realpath "$4")
results=$5
page=$6
[[ "$page" =~ ^[0-9]+$ ]] || { echo "invalid physical page" >&2; exit 2; }
repo=$(cd "$(dirname "$0")/.." && pwd)
[[ ! -e "$results" ]] || { echo 'Refusing to overwrite an attempt' >&2; exit 2; }
available_kib=$(awk '/MemAvailable:/ {print $2}' /proc/meminfo)
[[ "$available_kib" -ge 18874368 ]] || { echo 'Less than 18GiB host available; do not start' >&2; exit 3; }
mkdir -p "$results"
results=$(realpath "$results")
free -m > "$results/host-memory-before.txt"
cat /proc/loadavg > "$results/host-load-before.txt"
docker stats --no-stream --format '{{.Name}} {{.MemUsage}} {{.CPUPerc}}' > "$results/service-load-before.txt"
# Human operator checks service load before invoking. Host memory is not Worker quota.
name="filetools-ocr-trial-$(date +%s)"
docker run --name "$name" --cpus 2 --memory 16g --memory-swap 16g \
  --pids-limit 96 --network none --read-only --user 1000:1000 \
  --cap-drop ALL --security-opt no-new-privileges --tmpfs /tmp:rw,size=2g \
  -e OMP_NUM_THREADS=2 -e MKL_NUM_THREADS=2 -e OPENBLAS_NUM_THREADS=2 \
  -e PADDLE_PDX_CACHE_HOME=/tmp/paddlex -e HF_HOME=/tmp/huggingface \
  -e HF_HUB_OFFLINE=1 -e TRANSFORMERS_OFFLINE=1 \
  -e PADDLE_PDX_DISABLE_MODEL_SOURCE_CHECK=True \
  -v "$repo:/eval:ro" -v "$images:/images:ro" -v "$models:/models:ro" \
  -v "$results:/results:rw" "$image" -B /eval/scripts/evaluate_paddleocr_vl.py \
  --engine "$engine" --images /images --models /models --output /results \
  --load-timeout 180 --page-timeout 300 --pages "$page" || status=$?
docker inspect --format '{{json .State}}' "$name" > "$results/container-state.json"
docker inspect --format '{{.Image}} {{.HostConfig.Memory}} {{.HostConfig.MemorySwap}} {{.HostConfig.NanoCpus}} {{.HostConfig.NetworkMode}}' "$name" > "$results/container-limits.txt"
exit "${status:-0}"
