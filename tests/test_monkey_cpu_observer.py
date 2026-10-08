"""Synthetic observation checks, no private book content or model weights."""
import concurrent.futures
import json
import sys
import threading
import time
from pathlib import Path
from types import SimpleNamespace

from PIL import Image

sys.path.insert(0, str(Path(__file__).parents[1]/'scripts'))
from monkey_cpu_observer import Observer


def test_observer_preserves_input_output_and_concurrent_ids(tmp_path):
    state = {'active':0,'peak':0}
    lock = threading.Lock()
    core = SimpleNamespace(load_image=lambda image, **kwargs: image,
                           get_layout=lambda *a, **kw: None,
                           result2md=lambda *a, **kw: None)
    model = SimpleNamespace(vision_tower=SimpleNamespace(forward=lambda *a, **kw: None),
                            model=SimpleNamespace(forward=lambda *a, **kw: None),
                            generate=lambda *a, **kw: None)
    incoming = Image.new('RGB',(28,56),'white')
    def original(image, prompt, *parameters):
        assert image is incoming
        assert parameters == (None,77,None,None)
        assert core.load_image(image) is incoming
        with lock:
            state['active'] += 1
            state['peak'] = max(state['peak'],state['active'])
        time.sleep(.03)
        with lock:
            state['active'] -= 1
        return 'unchanged:'+prompt
    backend = SimpleNamespace(model=model, _generate_one=original)
    preprocessing = SimpleNamespace(preprocess_images=lambda *a, **kw: None)
    Observer(tmp_path,lambda:12).install(core, preprocessing, backend)
    with concurrent.futures.ThreadPoolExecutor(max_workers=4) as executor:
        results=list(executor.map(lambda n:backend._generate_one(incoming,str(n),max_tokens=77),range(12)))
    assert state['peak'] > 1  # instrumentation must not serialize inference
    assert results == ['unchanged:'+str(n) for n in range(12)]
    raw = list((tmp_path/'page-12/raw-generations').glob('*-text.txt'))
    assert len(raw)==12 and {p.read_text() for p in raw}==set(results)
    events=[json.loads(row) for row in (tmp_path/'phase-events.jsonl').read_text().splitlines()]
    assert len({r['call'] for r in events if r['name']=='request' and r['state']=='started'})==12
    assert len(list((tmp_path/'page-12/raw-generations').glob('*-input.png')))==12
    assert incoming.size == (28,56)


def test_sanitized_summary_excludes_queries_and_raw_text(tmp_path):
    from summarize_paddle_vl_trial import summarize
    (tmp_path/'metrics.json').write_text('{"backend":"monkey"}')
    event={'name':'request','state':'completed','call':1,'wall_seconds':3,'query':'private prompt','raw_text':'private response'}
    (tmp_path/'phase-events.jsonl').write_text(json.dumps(event)+'\n')
    result=summarize(tmp_path)
    assert result['receipt'] is None
    assert result['phases'][0]['call']==1
    assert result['phases'][0]['wall_seconds']==3
    assert 'private' not in json.dumps(result)
