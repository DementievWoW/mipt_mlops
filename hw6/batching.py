import asyncio
from collections import deque

class Batcher:
    def __init__(self, model_holder, max_batch_size=32, timeout=0.1):
        self.holder = model_holder
        self.max_size = max_batch_size
        self.timeout = timeout
        self.buffer = deque()
        self.lock = asyncio.Lock()
        self.flush_event = asyncio.Event()
        self.process_callback = None   # async callable (corr_ids, embeddings)

    async def add(self, corr_id, text):
        async with self.lock:
            self.buffer.append({'corr_id': corr_id, 'text': text})
            if len(self.buffer) >= self.max_size:
                self.flush_event.set()

    async def flush_loop(self):
        while True:
            try:
                await asyncio.wait_for(self.flush_event.wait(), timeout=self.timeout)
            except asyncio.TimeoutError:
                pass
            self.flush_event.clear()
            await self._process()

    async def _process(self):
        batch = []
        async with self.lock:
            if not self.buffer:
                return
            batch = [self.buffer.popleft() for _ in range(min(len(self.buffer), self.max_size))]
        if not batch:
            return
        corr_ids = [item['corr_id'] for item in batch]
        texts = [item['text'] for item in batch]
        try:
            inputs = self.holder.preprocess(texts)
            embeddings = self.holder.infer(inputs)
        except Exception as e:
            print(f"Batcher error: {e}")
            return
        if self.process_callback:
            await self.process_callback(corr_ids, embeddings)
