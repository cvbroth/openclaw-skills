"""Synthetic local files verify revision/hash gates without network or models."""
import importlib.util
import json
from pathlib import Path

import pytest

path = Path(__file__).resolve().parents[1] / 'scripts/prepare_paddleocr_vl_models.py'
spec = importlib.util.spec_from_file_location('models', path)
module = importlib.util.module_from_spec(spec)
spec.loader.exec_module(module)


def test_wrong_revision_rejected_before_download(tmp_path, monkeypatch):
    monkeypatch.setattr(module, 'MODELS', [('official/synthetic', 'expected', 'vl')])
    (tmp_path / 'model-info.json').write_text(json.dumps({'sha': 'other', 'siblings': []}))
    with pytest.raises(ValueError, match='OFFICIAL_REVISION_MISMATCH'):
        module.download(tmp_path / 'models', tmp_path)


def test_existing_weight_must_match_fixed_hash(tmp_path, monkeypatch):
    monkeypatch.setattr(module, 'MODELS', [('official/synthetic', 'expected', 'vl')])
    directory = tmp_path / 'models/vl'
    directory.mkdir(parents=True)
    (directory / 'weight').write_bytes(b'bad')
    (tmp_path / 'model-info.json').write_text(json.dumps({'sha': 'expected', 'siblings': [
        {'rfilename': 'weight', 'size': 3, 'lfs': {'sha256': '0' * 64}}]}))
    with pytest.raises(ValueError, match='MODEL_FILE_HASH_OR_SIZE_MISMATCH'):
        module.download(tmp_path / 'models', tmp_path)
    assert not (tmp_path / 'models/manifest.json').exists()


def test_same_size_configuration_must_match_revision_blob(tmp_path, monkeypatch):
    monkeypatch.setattr(module, 'MODELS', [('official/synthetic', 'expected', 'vl')])
    directory = tmp_path / 'models/vl'
    directory.mkdir(parents=True)
    (directory / 'config.json').write_bytes(b'{}')
    (tmp_path / 'model-info.json').write_text(json.dumps({'sha': 'expected', 'siblings': [
        {'rfilename': 'config.json', 'size': 2, 'blobId': '0' * 40}]}))
    with pytest.raises(ValueError, match='MODEL_FILE_HASH_OR_SIZE_MISMATCH'):
        module.download(tmp_path / 'models', tmp_path)
