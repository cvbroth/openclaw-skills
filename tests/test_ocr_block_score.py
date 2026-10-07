import importlib.util
from pathlib import Path

p=Path(__file__).resolve().parents[1]/'scripts/score_ocr_blocks.py'
spec=importlib.util.spec_from_file_location('score',p)
module=importlib.util.module_from_spec(spec)
spec.loader.exec_module(module)


def test_negation_and_number_errors_are_counted():
    result=module.character_errors('不能改为12','能改为13')
    assert result['edit_distance']==2
    assert result['reference_characters']==6
    assert module.character_errors('① A.甲\n② B.乙','① A.甲② B.乙')['cer']==0
    assert module.character_errors('①甲','1甲')['edit_distance']==1
