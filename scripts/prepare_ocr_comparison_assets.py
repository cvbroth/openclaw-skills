"""Explicit public model/code download; no document input or inference API.

Metadata must be saved first from the official HF API with blobs=true. Every
asset is checked against that fixed revision, including Git blob IDs for code.
"""
import argparse
import base64
import hashlib
import json
import shutil
import subprocess
import time
import urllib.request
from pathlib import Path


def verify(path, item):
    if path.stat().st_size != item['size']:
        return False
    expected = item.get('lfs', {}).get('sha256')
    digest = hashlib.sha256() if expected else hashlib.sha1()
    if not expected:
        digest.update(f"blob {item['size']}\0".encode())
    with path.open('rb') as incoming:
        while chunk := incoming.read(4 * 1024 * 1024):
            digest.update(chunk)
    return digest.hexdigest() == (expected or item['blobId'])


def download(url, partial):
    if shutil.which('curl'):
        subprocess.run(['curl', '--http1.1', '--fail', '--location', '--silent', '--show-error',
                        '--connect-timeout', '20', '--max-time', '600', '--retry', '1',
                        '-o', str(partial), url], check=True, timeout=1250)
        return
    # Minimal preparation containers need no extra curl installation. Only
    # public assets are fetched; inference containers still have no network.
    deadline = time.monotonic() + 600
    with urllib.request.urlopen(url, timeout=30) as incoming, partial.open('wb') as outgoing:
        while chunk := incoming.read(1024 * 1024):
            if time.monotonic() > deadline:
                raise TimeoutError('PUBLIC_ASSET_DOWNLOAD_EXCEEDED_600_SECONDS')
            outgoing.write(chunk)


def models(metadata, target, mirror=False):
    info = json.loads(metadata.read_bytes())
    records = []
    for item in info['siblings']:
        name = item['rfilename']
        if name.startswith('.') or name == 'README.md':
            continue
        if Path(name).is_absolute() or '..' in Path(name).parts:
            raise ValueError('UNSAFE_ASSET_PATH')
        dest = target / name
        dest.parent.mkdir(parents=True, exist_ok=True)
        if not dest.exists() or not verify(dest, item):
            url = f"https://huggingface.co/{info['id']}/resolve/{info['sha']}/{name}"
            # Mirrors may have changed Python/config files even when weights
            # match. Only LFS assets can use the README-linked weight mirror;
            # source/config always come from the pinned official HF revision.
            if mirror and item.get('lfs'):
                url = f"https://modelscope.cn/models/{info['id']}/resolve/master/{name}"
            partial = dest.with_name(dest.name + '.partial')
            download(url, partial)
            if not verify(partial, item):
                raise ValueError(f'ASSET_HASH_MISMATCH: {name}')
            partial.replace(dest)
        with dest.open('rb') as incoming:
            digest = hashlib.file_digest(incoming, 'sha256').hexdigest()
        records.append({'file': name, 'bytes': dest.stat().st_size, 'sha256': digest})
        print(json.dumps(records[-1]), flush=True)
    (target / 'verified-assets.json').write_text(json.dumps(
        {'repository': info['id'], 'revision': info['sha'], 'files': records}, indent=2))


def monkey_code(tree, target):
    info = json.loads(tree.read_bytes())
    paths = ['parsing/cpu/core_runner.py', 'parsing/cpu/parse_cpu.py',
             'parsing/modeling/__init__.py', 'parsing/modeling/modeling_preprocessor.py']
    records = []
    for path in paths:
        url = f"https://api.github.com/repos/Yuliang-Liu/MonkeyOCRv2/contents/{path}?ref={info['sha']}"
        with urllib.request.urlopen(url, timeout=30) as response:
            item = json.load(response)
        data = base64.b64decode(item['content'])
        blob = hashlib.sha1(f'blob {len(data)}\0'.encode() + data).hexdigest()
        if blob != item['sha']:
            raise ValueError('SOURCE_BLOB_MISMATCH')
        dest = target / path
        dest.parent.mkdir(parents=True, exist_ok=True)
        dest.write_bytes(data)
        records.append({'file': path, 'blob': blob, 'sha256': hashlib.sha256(data).hexdigest()})
    (target / 'source-manifest.json').write_text(json.dumps({'revision': info['sha'], 'files': records}, indent=2))


if __name__ == '__main__':
    parser = argparse.ArgumentParser()
    parser.add_argument('kind', choices=['models', 'monkey-code'])
    parser.add_argument('metadata', type=Path)
    parser.add_argument('target', type=Path)
    parser.add_argument('--official-mirror', action='store_true')
    args = parser.parse_args()
    args.target.mkdir(parents=True, exist_ok=True)
    if args.kind == 'models':
        models(args.metadata, args.target, args.official_mirror)
    else:
        monkey_code(args.metadata, args.target)
