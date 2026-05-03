import asyncio
from collections import deque

class Batcher:
    def __init__(self, model_holder, max_batch_size=32, timeout=0.1):
        self.holder = model_holder
        self.max_batch_size = max_batch_size
        self.timeout = timeout
        self.buffer = deque()
        self.results = {}           # correlation_id -> Future
        self.lock = asyncio.Lock()
        self.flush_event = asyncio.Event()

    async def add_request(self, correlation_id, text):
        fut = asyncio.get_event_loop().create_future()
        async with self.lock:
            self.buffer.append((correlation_id, text, fut))
            if len(self.buffer) >= self.max_batch_size:
                self.flush_event.set()
        # запускаем таймер, если ещё не запущен
        return await fut

    async def flush_loop(self):
        """Фоновый цикл, сливающий буфер по событию или таймауту."""
        while True:
            try:
                await asyncio.wait_for(self.flush_event.wait(), timeout=self.timeout)
            except asyncio.TimeoutError:
                pass
            self.flush_event.clear()
            await self._process_batch()

    async def _process_batch(self):
        batch = []
        async with self.lock:
            if not self.buffer:
                return
            for _ in range(min(len(self.buffer), self.max_batch_size)):
                batch.append(self.buffer.popleft())

        corr_ids = [item[0] for item in batch]
        texts = [item[1] for item in batch]
        futures = [item[2] for item in batch]

        # препроцессинг + инференс сразу для всего батча
        tokenized = self.holder.preprocess(texts)   # батчевая токенизация
        embeddings = self.holder.infer(tokenized)    # один эмбеддинг на каждый текст

        # раскладываем результаты по фьючам
        for corr_id, emb, fut in zip(corr_ids, embeddings, futures):
            fut.set_result(emb)