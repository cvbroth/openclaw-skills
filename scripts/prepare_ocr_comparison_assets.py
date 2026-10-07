"""Explicit public model/code download; no document input or inference API.

Metadata must be saved first from the official HF API with blobs=true. Every
asset is checked against that fixed revision, including Git blob IDs for code.
"""
import argparse
import base64
import hashlib
import json
import subprocess
import urllib.request
from pathlib import Path


def verify(path, item):
    data = path.read_bytes()
    if len(data) != item['size']:
        return False
    expected = item.get('lfs', {}).get('sha256')
    return (hashlib.sha256(data).hexdigest() == expected if expected else
            hashlib.sha1(f'blob {len(data)}\0'.encode() + data).hexdigest() == item['blobId'])


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
            subprocess.run(['curl', '--http1.1', '--fail', '--location', '--silent', '--show-error',
                            '--connect-timeout', '20', '--max-time', '600', '--retry', '1',
                            '-o', str(partial), url], check=True, timeout=1250)
            if not verify(partial, item):
                raise ValueError(f'ASSET_HASH_MISMATCH: {name}')
            partial.replace(dest)
        records.append({'file': name, 'bytes': dest.stat().st_size,
                        'sha256': hashlib.sha256(dest.read_bytes()).hexdigest()})
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
