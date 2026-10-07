"""Ensure this trial only enables the fixed text-and-layout PP-StructureV3 route."""
from pathlib import Path
import sys
import yaml


CONFIG = Path(__file__).resolve().parents[1] / 'deploy/ppstructurev3-text-only.yaml'


def test_ppstructure_text_route_uses_pinned_models_and_disables_optional_modules():
    config = yaml.safe_load(CONFIG.read_text())
    assert config['engine'] == 'paddleocr.PPStructureV3'
    assert config['paddleocr_version'] == '3.4.0'
    assert config['paddlex_version'] == '3.4.0'
    assert config['paddlepaddle_version'] == '3.2.2'
    assert config['models'] == {
        'chart_recognition_model_name': 'PP-Chart2Table',
        'chart_recognition_model_dir': 'ppstructure/chart-initialization',
        'layout_detection_model_name': 'PP-DocLayout-L',
        'layout_detection_model_dir': 'ppstructure/layout',
        'text_detection_model_name': 'PP-OCRv5_server_det',
        'text_detection_model_dir': 'ppstructure/text-detection',
        'text_recognition_model_name': 'PP-OCRv5_server_rec',
        'text_recognition_model_dir': 'ppstructure/text-recognition',
    }
    assert config['options']['use_table_recognition'] is False
    assert config['options']['use_formula_recognition'] is False
    assert config['options']['use_seal_recognition'] is False
    assert config['options']['use_chart_recognition'] is False
    assert config['options']['markdown_ignore_labels'] == []
    assert config['device'] == 'cpu' and config['cpu_threads'] == 2
    assert config['compatibility_constraints']['disabled_chart_predictor_still_initialized'] is True
    assert config['compatibility_constraints']['status'] == 'authorized-official-auxiliary-model-local-only'
    assert config['models']['chart_recognition_model_dir'] == 'ppstructure/chart-initialization'


def test_ppstructure_missing_auxiliary_is_stopped_before_initialization():
    sys.path.insert(0, str(CONFIG.parents[1] / 'scripts'))
    import evaluate_paddleocr_vl

    config = yaml.safe_load(CONFIG.read_text())
    evaluate_paddleocr_vl.validate_ppstructure_compatibility(config)
    del config['models']['chart_recognition_model_dir']
    try:
        evaluate_paddleocr_vl.validate_ppstructure_compatibility(config)
    except RuntimeError as error:
        assert 'PPSTRUCTUREV3_CONFIG_BLOCKED' in str(error)
    else:
        raise AssertionError('PP-StructureV3 with disabled-but-unconditionally-initialized chart model must stop')
