"""Check mirror wheel/sdist hashes against official PyPI metadata, no secrets."""
import argparse
import concurrent.futures
import json
import urllib.parse
import urllib.request


def check(item):
    meta = item['metadata']
    info = item['download_info']
    url = info['url']
    filename = urllib.parse.unquote(urllib.parse.urlsplit(url).path.split('/')[-1])
    digest = info['archive_info']['hashes']['sha256']
    record = {'name': meta['name'], 'version': meta['version'], 'file': filename, 'sha256': digest}
    if urllib.parse.urlsplit(url).hostname in {'download.pytorch.org', 'download-r2.pytorch.org'}:
        return {**record, 'status': 'official PyTorch CPU index; no mirror substitution'}
    with urllib.request.urlopen(f"https://pypi.org/pypi/{meta['name']}/{meta['version']}/json", timeout=30) as response:
        official = json.load(response)
    match = any(x['filename'] == filename and x['digests']['sha256'] == digest for x in official['urls'])
    if not match:
        raise ValueError(f"OFFICIAL_PYPI_HASH_MISMATCH: {meta['name']}")
    return {**record, 'status': 'official PyPI filename and SHA256 matched'}


if __name__ == '__main__':
    parser = argparse.ArgumentParser()
    parser.add_argument('report')
    parser.add_argument('output')
    args = parser.parse_args()
    with open(args.report) as stream:
        items = json.load(stream)['install']
    with concurrent.futures.ThreadPoolExecutor(max_workers=4) as pool:
        result = list(pool.map(check, items))
    with open(args.output, 'w') as stream:
        json.dump(result, stream, indent=2)
    print(json.dumps({'verified_files': len(result)}))
