"""Download two explicitly pinned official model revisions; never user documents."""
import argparse
import hashlib
import json
import subprocess
from pathlib import Path

MODELS = (
    ('PaddlePaddle/PaddleOCR-VL-1.5', '2a4195faa5e7914c12f2fc601d72c81caf8d2da5', 'vl'),
    ('PaddlePaddle/PP-DocLayoutV3', '241f8bdfc77a7c7bee915a5057aaee58c235a8d3', 'layout'),
)


def download(root, metadata_root, official_weight_mirror=False):
    manifest = []
    metadata_root.mkdir(parents=True, exist_ok=True)
    for repo, revision, folder in MODELS:
        metadata_path = metadata_root / ('model-info.json' if folder == 'vl' else 'layout-info.json')
        if not metadata_path.exists():
            subprocess.run(['curl', '--fail', '--location', '--silent', '--show-error',
                '--connect-timeout', '20', '--max-time', '120', '-o', str(metadata_path),
                f'https://huggingface.co/api/models/{repo}/revision/{revision}?blobs=true'],
                check=True, timeout=130)
        metadata = json.loads(metadata_path.read_bytes())
        if metadata['sha'] != revision:
            raise ValueError('OFFICIAL_REVISION_MISMATCH')
        directory = root / folder
        directory.mkdir(parents=True, exist_ok=True)
        for item in metadata['siblings']:
            name = item['rfilename']
            if '/' in name or name.startswith('.') or name.endswith('.py'):
                continue
            target = directory / name
            expected = item.get('lfs', {}).get('sha256')
            if not target.exists():
                temporary = target.with_suffix(target.suffix + '.partial')
                url = f'https://huggingface.co/{repo}/resolve/{revision}/{name}'
                if official_weight_mirror and expected:
                    # Official README links this mirror. Its moving branch is accepted
                    # only when bytes match the pinned revision's LFS hash and size.
                    url = f'https://modelscope.cn/models/{repo}/resolve/master/{name}'
                subprocess.run(['curl', '--http1.1', '--fail', '--location', '--silent', '--show-error',
                    '--connect-timeout', '20', '--max-time', '600', '--retry', '1',
                    '-o', str(temporary), url],
                    check=True, timeout=1250)
                temporary.replace(target)
            with target.open('rb') as stream:
                digest = hashlib.file_digest(stream, 'sha256').hexdigest()
            small_blob_mismatch = False
            if not expected and item.get('blobId'):
                data = target.read_bytes()
                git_blob = hashlib.sha1(f'blob {len(data)}\0'.encode() + data).hexdigest()
                small_blob_mismatch = git_blob != item['blobId']
            if target.stat().st_size != item['size'] or expected and digest != expected or small_blob_mismatch:
                raise ValueError('MODEL_FILE_HASH_OR_SIZE_MISMATCH: ' + name)
            manifest.append({'repository': repo, 'revision': revision, 'file': folder + '/' + name,
                             'bytes': target.stat().st_size, 'sha256': digest})
            print(json.dumps({'downloaded': folder + '/' + name, 'bytes': target.stat().st_size}), flush=True)
    (root / 'manifest.json').write_text(json.dumps(manifest, indent=2))


if __name__ == '__main__':
    parser = argparse.ArgumentParser()
    parser.add_argument('--models', type=Path, required=True)
    parser.add_argument('--metadata', type=Path, required=True)
    parser.add_argument('--official-weight-mirror', action='store_true',
                        help='Official README-linked ModelScope weights; pinned HF hashes remain mandatory')
    args = parser.parse_args()
    download(args.models, args.metadata, args.official_weight_mirror)
