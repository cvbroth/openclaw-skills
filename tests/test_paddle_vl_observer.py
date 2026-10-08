"""Synthetic observer checks, not model recognition acceptance."""
import importlib.util
import sys
from pathlib import Path
from types import MethodType

sys.path.insert(0,str(Path(__file__).parents[1]/'scripts'))
from paddle_vl_observer import Observer, repeating


def test_repeat_abort_is_bounded_and_not_short_legitimate_repetition():
    assert not repeating([1]*511)
    assert repeating(list(range(64))*8)
    assert not repeating(list(range(512)))


def test_timing_preserves_arguments_and_result(tmp_path):
    observer=Observer(tmp_path)
    value={'raw':'不改写'}
    seen=[]
    def original(arg,*,flag):
        seen.append((arg,flag))
        return value
    wrapped=observer.timed(original,'synthetic')
    assert wrapped(12,flag=False) is value
    assert seen==[(12,False)]
    assert 'completed' in observer.events.read_text()


def test_bound_layer_observer_does_not_inject_self_twice(tmp_path):
    # Installed Paddle tokenizer patch inserts self for plain functions, but
    # treats already bound methods differently. Retain that binding contract.
    class Layer:
        def forward(self,*,input_ids):
            return input_ids
    layer=Layer()
    observer=Observer(tmp_path)
    original=layer.forward
    timed=observer.timed(original,'forward')
    layer.forward=MethodType(lambda _self,*a,**kw:timed(*a,**kw),layer)
    assert layer.forward(input_ids=[1,2])==[1,2]


def test_public_asset_stream_hash_rejects_tampering(tmp_path):
    import hashlib
    spec=importlib.util.spec_from_file_location('assets',Path(__file__).parents[1]/'scripts/prepare_ocr_comparison_assets.py')
    module=importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    incoming=tmp_path/'asset'
    incoming.write_bytes(b'synthetic'*100000)
    metadata={'size':incoming.stat().st_size,'lfs':{'sha256':hashlib.sha256(incoming.read_bytes()).hexdigest()}}
    assert module.verify(incoming,metadata)
    with incoming.open('r+b') as output:
        output.write(b'changed!!')
    assert not module.verify(incoming,metadata)
