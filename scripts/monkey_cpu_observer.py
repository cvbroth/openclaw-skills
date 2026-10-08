"""Development-only native Monkey CPU observation. No prompt/pixel/result edits.

Call IDs use thread-local storage; the event lock never spans model execution.
Nested wall/CPU measurements overlap and must not be summed indiscriminately.
"""
import hashlib
import json
import resource
import threading
import time
from pathlib import Path


def cpu():
    r = resource.getrusage(resource.RUSAGE_SELF)
    return r.ru_utime + r.ru_stime


class Observer:
    def __init__(self, output, get_page):
        self.output = Path(output)
        self.get_page = get_page
        self.local = threading.local()
        self.lock = threading.Lock()
        self.index = 0

    def event(self, name, state, **fields):
        row = {'page': self.get_page(), 'call': getattr(self.local, 'call', None),
               'name': name, 'state': state, 'monotonic': time.monotonic(),
               'process_cpu_seconds': cpu(), **fields}
        text = json.dumps(row, ensure_ascii=False)
        with self.lock:
            with (self.output/'phase-events.jsonl').open('a') as f:
                f.write(text+'\n')
            tmp = self.output/'activity.tmp'
            tmp.write_text(text)
            tmp.replace(self.output/'activity.json')

    def timed(self, original, name):
        def run(*args, **kwargs):
            self.event(name, 'started')
            start, c = time.monotonic(), cpu()
            value = original(*args, **kwargs)
            self.event(name, 'completed', wall_seconds=time.monotonic()-start, cpu_seconds=cpu()-c)
            return value
        return run

    def install(self, core, preprocessor, backend):
        original = backend._generate_one
        def call(image, question, min_pixels=None, max_tokens=None, temperature=None, top_p=None):
            with self.lock:
                self.index += 1
                identity = self.index
            self.local.call = identity
            self.local.steps = 0
            folder = self.output/f'page-{self.get_page()}'/'raw-generations'
            folder.mkdir(parents=True, exist_ok=True)
            self.local.folder = folder
            self.event('request', 'started', query=question, source_size=list(image.size),
                       min_pixels=min_pixels, max_tokens=max_tokens, temperature=temperature, top_p=top_p)
            start = time.monotonic()
            value = original(image, question, min_pixels, max_tokens, temperature, top_p)
            (folder/f'{identity:04}-text.txt').write_text(value)
            self.event('request', 'completed', wall_seconds=time.monotonic()-start,
                       output_characters=len(value), output_sha256=hashlib.sha256(value.encode()).hexdigest())
            self.local.call = None
            return value
        backend._generate_one = call
        load = core.load_image
        def image(*args, **kwargs):
            value = load(*args, **kwargs)
            identity = getattr(self.local, 'call', None)
            if identity is not None:
                p = self.local.folder/f'{identity:04}-input.png'
                start = time.monotonic()
                value.copy().save(p, compress_level=1)
                self.event('prepared_image', 'saved', size=list(value.size),
                           sha256=hashlib.sha256(p.read_bytes()).hexdigest(), capture_seconds=time.monotonic()-start)
            return value
        core.load_image = image
        preprocessor.preprocess_images = self.timed(preprocessor.preprocess_images, 'page_preprocessing')
        core.get_layout = self.timed(core.get_layout, 'layout_analysis')
        core.result2md = self.timed(core.result2md, 'markdown_export')
        backend.model.vision_tower.forward = self.timed(backend.model.vision_tower.forward, 'vision_encoding')
        forward = backend.model.model.forward
        def language(*args, **kwargs):
            value = forward(*args, **kwargs)
            self.local.steps = getattr(self.local, 'steps', 0)+1
            if self.local.steps == 1 or self.local.steps % 32 == 0:
                self.event('language_generation', 'progress', steps=self.local.steps)
            return value
        backend.model.model.forward = language
        generate = backend.model.generate
        def generation(*args, **kwargs):
            shapes = {k: {'shape':list(v.shape), 'dtype':str(v.dtype)} for k,v in kwargs.items() if hasattr(v,'shape')}
            grid = kwargs.get('image_grid_thw')
            self.event('generate', 'started', tensors=shapes,
                       image_grid_thw=grid.tolist() if grid is not None else None,
                       max_new_tokens=kwargs.get('max_new_tokens'), do_sample=kwargs.get('do_sample'),
                       effective_use_cache=kwargs.get('use_cache',backend.model.generation_config.use_cache))
            start, c = time.monotonic(), cpu()
            value = generate(*args, **kwargs)
            tokens = value[:,kwargs['input_ids'].shape[1]:]
            (self.local.folder/f'{self.local.call:04}-tokens.json').write_text(json.dumps(tokens.tolist()))
            self.event('generate','completed',wall_seconds=time.monotonic()-start,cpu_seconds=cpu()-c,
                       generated_tokens=tokens.shape[-1], steps=self.local.steps,
                       reached_configured_token_limit=tokens.shape[-1]>=kwargs['max_new_tokens'])
            return value
        backend.model.generate = generation
        self.event('observer','installed')
        return self
