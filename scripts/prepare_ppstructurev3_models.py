"""Fetch pinned official PP-StructureV3 archives and verify before extraction."""
import argparse
import hashlib
import json
import shutil
import subprocess
import tarfile
import tempfile
from pathlib import Path, PurePosixPath


def digest(path):
    with path.open('rb') as stream:
        return hashlib.file_digest(stream, 'sha256').hexdigest()


def prepare(lock_path, archive_root, model_root):
    lock = json.loads(lock_path.read_bytes())
    manifest = {'lock_sha256': digest(lock_path), 'models': []}
    for model in lock['models']:
        archive = archive_root / model['archive']
        if not archive.exists():
            temporary = archive.with_suffix(archive.suffix + '.partial')
            subprocess.run(['curl', '--fail', '--location', '--silent', '--show-error',
                '--connect-timeout', '20', '--max-time', '600', '--retry', '1',
                '-o', str(temporary), model['url']], check=True, timeout=1250)
            temporary.replace(archive)
        if archive.stat().st_size != model['archive_bytes'] or digest(archive) != model['archive_sha256']:
            raise ValueError('OFFICIAL_ARCHIVE_HASH_OR_SIZE_MISMATCH: ' + model['name'])
        target = model_root / model['directory']
        target.parent.mkdir(parents=True, exist_ok=True)
        with tempfile.TemporaryDirectory(dir=target.parent) as temporary_dir:
            temporary = Path(temporary_dir)
            with tarfile.open(archive, 'r:*') as bundle:
                members = bundle.getmembers()
                for member in members:
                    path = PurePosixPath(member.name)
                    if path.is_absolute() or '..' in path.parts or member.issym() or member.islnk():
                        raise ValueError('UNSAFE_OFFICIAL_ARCHIVE_PATH: ' + model['name'])
                bundle.extractall(temporary, filter='data')
            inference_files = list(temporary.rglob('inference.yml'))
            if len(inference_files) != 1:
                raise ValueError('UNEXPECTED_MODEL_LAYOUT: ' + model['name'])
            source_dir = inference_files[0].parent
            if not (source_dir / 'inference.json').is_file() or not (source_dir / 'inference.pdiparams').is_file():
                raise ValueError('MODEL_REQUIRED_FILES_MISSING: ' + model['name'])
            if target.exists():
                shutil.rmtree(target)
            shutil.copytree(source_dir, target)
        files = sorted(target.rglob('*'))
        manifest['models'].append({
            'name': model['name'], 'official_url': model['url'], 'archive_bytes': archive.stat().st_size,
            'archive_sha256': digest(archive), 'directory': model['directory'],
            'files': [{'path': path.relative_to(target).as_posix(), 'bytes': path.stat().st_size,
                       'sha256': digest(path)} for path in files if path.is_file()]})
        print(json.dumps({'model': model['name'], 'verified_bytes': archive.stat().st_size,
                          'files': len(manifest['models'][-1]['files'])}), flush=True)
    output = model_root / 'ppstructure-manifest.json'
    output.write_text(json.dumps(manifest, indent=2) + '\n')
    return output


if __name__ == '__main__':
    parser = argparse.ArgumentParser()
    parser.add_argument('--lock', type=Path, required=True)
    parser.add_argument('--archives', type=Path, required=True)
    parser.add_argument('--models', type=Path, required=True)
    args = parser.parse_args()
    prepare(args.lock, args.archives, args.models)
