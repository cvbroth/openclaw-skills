#!/usr/bin/env bash
# Explicit one-page detached research run; no production settings or API keys.
set -euo pipefail
if [[ $# -lt 3 || $# -gt 4 ]]; then
  echo 'usage: bash scripts/launch_glm_ocr_cpu.sh EXPERIMENT_DIR IMAGE_SHA256 PHYSICAL_PAGE [WALL_TIMEOUT_SECONDS]' >&2
  exit 2
fi
experiment_dir=$(realpath "$1")
image_id=$2
physical_page=$3
wall_timeout=${4:-1800}
repo_dir=$(cd "$(dirname "$0")/.." && pwd)
[[ "$image_id" =~ ^sha256:[0-9a-f]{64}$ ]]
[[ "$physical_page" =~ ^[1-9][0-9]*$ ]]
[[ "$wall_timeout" =~ ^[1-9][0-9]*$ && "$wall_timeout" -le 1800 ]]
python3 - "$experiment_dir" "$physical_page" <<'PY'
import hashlib,json,sys
from pathlib import Path
root=Path(sys.argv[1]);page=int(sys.argv[2])
manifest=json.loads((root/'manifest.json').read_bytes())
image=next(x for x in manifest['images'] if x['physical_page']==page)
assert hashlib.sha256((root/image['image']).read_bytes()).hexdigest()==image['sha256']
assert not (root/'results/glm-ocr'/f'page-{page}').exists(), 'existing attempt must be preserved explicitly'
if page==23:
    prior=json.loads((root/'results/glm-ocr/page-12/receipt.json').read_bytes())
    assert prior['status']=='SUCCEEDED', 'first authorized pilot must complete before second'
assert int(next(line.split()[1] for line in Path('/proc/meminfo').read_text().splitlines() if line.startswith('MemAvailable:')))>18*1024*1024, 'insufficient actual available memory'
PY
mkdir -p "$experiment_dir/results/glm-ocr"
docker run -d --name "filetools-glm-cpu-p${physical_page}" \
  --network none --read-only --user 1000:1000 --cpus 2 \
  --memory 16g --memory-swap 16g --cap-drop ALL \
  --security-opt no-new-privileges --tmpfs /tmp:rw,size=256m \
  -e OLLAMA_DEBUG=1 \
  -v "$repo_dir/scripts:/scripts:ro" \
  -v "$experiment_dir/images:/images:ro" \
  -v "$experiment_dir/models:/models:rw" \
  -v "$experiment_dir/results/glm-ocr:/outputs:rw" \
  "$image_id" /scripts/run_glm_ocr_cpu.py \
  --image "/images/page-${physical_page}.png" \
  --output "/outputs/page-${physical_page}" --page "$physical_page" \
  --threads 2 --timeout "$wall_timeout"
