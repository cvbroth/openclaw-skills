"""Research-only observation of installed native Paddle VL, no package edits.

Native output is never rewritten. Partial decoder-input IDs are diagnostics,
not a complete response. Nested wall/CPU timings must not be summed twice.
"""
import hashlib
import json
import resource
import time
from pathlib import Path
from types import MethodType


def cpu():
    use = resource.getrusage(resource.RUSAGE_SELF)
    return use.ru_utime + use.ru_stime


def serial(value):
    if hasattr(value, 'tolist'):
        return value.tolist()
    if hasattr(value, 'numpy'):
        return value.numpy().tolist()
    raise TypeError(type(value).__name__)


def repeating(ids):
    return len(ids) >= 512 and ids[-64:] == ids[-128:-64] == ids[-192:-128] == ids[-256:-192]


class Observer:
    def __init__(self, output):
        self.output = Path(output)
        self.output.mkdir(parents=True, exist_ok=True)
        self.page = None
        self.events = self.output / 'phase-events.jsonl'
        self.region = 0
        self.decode_ids = []
        self.counters = {}

    def event(self, name, state, **fields):
        data = {'page': self.page, 'region': self.region, 'name': name, 'state': state,
                'monotonic': time.monotonic(), 'process_cpu_seconds': cpu(), **fields}
        text = json.dumps(data, ensure_ascii=False, default=serial)
        with self.events.open('a') as incoming:
            incoming.write(text + '\n')
        target = self.output / 'activity.json'
        temporary = target.with_suffix('.tmp')
        temporary.write_text(text)
        temporary.replace(target)

    def timed(self, original, name, describe=None):
        def call(*args, **kwargs):
            self.event(name, 'started')
            start, start_cpu = time.monotonic(), cpu()
            result = original(*args, **kwargs)
            fields = describe(result) if describe else {}
            self.event(name, 'completed', wall_seconds=time.monotonic()-start,
                       cpu_seconds=cpu()-start_cpu, **fields)
            return result
        return call

    def install(self, pipeline):
        core = pipeline.paddlex_pipeline
        while not hasattr(core, 'vl_rec_model') and hasattr(core, '_pipeline'):
            core = core._pipeline
        vl = core.vl_rec_model
        layout = core.layout_det_model
        def layout_result(result):
            boxes = result.get('boxes', [])
            payload = {key:value for key,value in result.items() if key != 'input_img'}
            (self.output / f'page-{self.page}-layout.json').write_text(json.dumps(payload, ensure_ascii=False, default=serial))
            return {'batch_box_counts': [len(row) for row in boxes]}
        layout.process = self.timed(layout.process, 'layout_analysis', layout_result)
        def processed(result):
            return {'tensors': {k: {'shape': list(v.shape), 'dtype': str(v.dtype)}
                                 for k,v in result.items() if hasattr(v, 'shape')},
                    'image_grid_thw': serial(result['image_grid_thw']) if 'image_grid_thw' in result else None}
        vl.processor.preprocess = self.timed(vl.processor.preprocess, 'vl_preprocess', processed)
        original_process = vl.process
        def region(data, *args, **kwargs):
            self.region += 1
            self.decode_ids = []
            self.counters = {}
            records = []
            for row in data:
                im = row['image']
                records.append({'query': row['query'], 'image_shape': list(im.shape),
                                'array_bytes_sha256': hashlib.sha256(im.tobytes()).hexdigest()})
            self.event('region', 'started', input_regions=records, generation_arguments=kwargs)
            start = time.monotonic()
            result = original_process(data, *args, **kwargs)
            folder = self.output / f'page-{self.page}' / 'raw-regions'
            folder.mkdir(parents=True, exist_ok=True)
            (folder / f'{self.region:04}.json').write_text(json.dumps(result, ensure_ascii=False, default=serial))
            self.event('region', 'completed', wall_seconds=time.monotonic()-start)
            return result
        vl.process = region
        model = vl.infer
        observed_visual = self.timed(model.visual.forward, 'vision_encoding')
        model.visual.forward = MethodType(lambda _layer, *args, **kwargs: observed_visual(*args, **kwargs), model.visual)
        outer_forward = model.forward
        def observe_input(_layer, *args, **kwargs):
            ids = kwargs.get('input_ids', args[0] if args else None)
            if ids is not None and list(ids.shape) == [1,1]:
                self.decode_ids.append(int(ids.numpy()[0,0]))
            return outer_forward(*args, **kwargs)
        model.forward = MethodType(observe_input, model)
        original_forward = model.model.forward
        def language(_layer, *args, **kwargs):
            start, start_cpu = time.monotonic(), cpu()
            value = original_forward(*args, **kwargs)
            count = self.counters.get('language_steps',0)+1
            self.counters['language_steps'] = count
            self.counters['language_wall'] = self.counters.get('language_wall',0)+time.monotonic()-start
            self.counters['language_cpu'] = self.counters.get('language_cpu',0)+cpu()-start_cpu
            if count == 1 or count % 16 == 0:
                self.event('language_generation', 'progress', **self.counters)
                (self.output / 'decoder-input-ids.partial.json').write_text(json.dumps(self.decode_ids))
            if repeating(self.decode_ids):
                self.event('language_generation', 'aborted_repetition', **self.counters)
                raise RuntimeError('ABORTED_REPEATING_DECODER_INPUT_TOKENS')
            return value
        model.model.forward = MethodType(language, model.model)
        original_generate = model.generate
        def generated(inputs, **kwargs):
            self.event('generate', 'started', generation_arguments=kwargs)
            start = time.monotonic()
            value = original_generate(inputs, **kwargs)
            folder = self.output / f'page-{self.page}' / 'raw-generations'
            folder.mkdir(parents=True, exist_ok=True)
            (folder / f'{self.region:04}-tokens.json').write_text(json.dumps(value, default=serial))
            self.event('generate', 'completed', wall_seconds=time.monotonic()-start,
                       language_steps=self.counters.get('language_steps',0),
                       generated_token_shape=list(value[0].shape),
                       reached_configured_token_limit=value[0].shape[-1] >= kwargs.get('max_new_tokens',8192))
            return value
        model.generate = generated
        self.event('observer', 'installed', core_class=type(core).__name__, vl_class=type(vl).__name__)
        return self
