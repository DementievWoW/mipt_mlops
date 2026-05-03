# app.py
import asyncio
import json
import uuid
import grpc
import redis.asyncio as redis
from concurrent import futures
import inference_pb2
import inference_pb2_grpc
from transformers import AutoTokenizer, AutoModel
import torch

# ---------- Model Holder (паттерн Lazy + keep in memory) ----------
class ModelHolder:
    def __init__(self):
        self.tokenizer = AutoTokenizer.from_pretrained("cointegrated/rubert-tiny2")
        self.model = AutoModel.from_pretrained("cointegrated/rubert-tiny2")
        self.model.eval()

    def preprocess(self, texts):
        if isinstance(texts, str):
            texts = [texts]
        return self.tokenizer(texts, return_tensors="pt", padding=True, truncation=True)

    def infer(self, inputs):
        with torch.no_grad():
            outputs = self.model(**inputs)
        return outputs.last_hidden_state.mean(dim=1).tolist()

# ---------- Batcher (накапливает батч из очереди) ----------
class Batcher:
    def __init__(self, model_holder, max_size=32, timeout=0.1):
        self.holder = model_holder
        self.max_size = max_size
        self.timeout = timeout
        self.buffer = []
        self.lock = asyncio.Lock()
        self.flush_event = asyncio.Event()

    async def add(self, item):
        async with self.lock:
            self.buffer.append(item)
            if len(self.buffer) >= self.max_size:
                self.flush_event.set()

    async def flush_loop(self, redis_conn):
        while True:
            try:
                await asyncio.wait_for(self.flush_event.wait(), timeout=self.timeout)
            except asyncio.TimeoutError:
                pass
            self.flush_event.clear()
            await self._process(redis_conn)

    async def _process(self, redis_conn):
        batch = []
        async with self.lock:
            if not self.buffer:
                return
            batch = self.buffer[:self.max_size]
            self.buffer = self.buffer[self.max_size:]

        texts = [item['text'] for item in batch]
        corr_ids = [item['corr_id'] for item in batch]

        inputs = self.holder.preprocess(texts)
        embeddings = self.holder.infer(inputs)

        # публикуем каждый результат в Redis List: "result:<correlation_id>"
        pipe = redis_conn.pipeline()
        for corr_id, emb in zip(corr_ids, embeddings):
            pipe.rpush(f"result:{corr_id}", json.dumps(emb))
        await pipe.execute()

# ---------- gRPC Servicer ----------
class InferenceServicer(inference_pb2_grpc.InferencePipelineServicer):
    def __init__(self, redis_conn, preprocess_queue):
        self.redis = redis_conn
        self.preprocess_queue = preprocess_queue  # Redis List ключ "text:preprocess"

    async def Predict(self, request, context):
        """Unary gRPC – клиент отправляет один текст, ждёт ответ."""
        corr_id = str(uuid.uuid4())
        # Публикуем сообщение в очередь препроцессинга
        await self.redis.rpush(self.preprocess_queue, json.dumps({
            "corr_id": corr_id,
            "text": request.text
        }))
        # Ждём результат в списке result:<corr_id> (блокирующее чтение)
        # BRPOP блокирует до появления элемента или таймаута (5 секунд)
        result = await self.redis.brpop(f"result:{corr_id}", timeout=5)
        if result is None:
            context.set_code(grpc.StatusCode.DEADLINE_EXCEEDED)
            context.set_details("Timeout waiting for inference result")
            return inference_pb2.PredictionResponse()
        _, data = result
        embedding = json.loads(data)
        return inference_pb2.PredictionResponse(
            correlation_id=corr_id,
            embedding=embedding
        )

# ---------- Фоновые обработчики ----------
async def preprocess_worker(redis_conn, model_holder, preprocess_queue, tokens_queue):
    """Читает из text:preprocess, токенизирует, кладёт в text:tokens"""
    while True:
        # BRPOP слева (очередь)
        msg = await redis_conn.brpop(preprocess_queue)
        if msg is None:
            continue
        _, data = msg
        req = json.loads(data)
        corr_id = req["corr_id"]
        text = req["text"]

        tokens = model_holder.preprocess(text)  # вернёт BatchEncoding
        # сериализуем тензоры в список (для передачи)
        payload = {
            "corr_id": corr_id,
            "input_ids": tokens["input_ids"].tolist(),
            "attention_mask": tokens["attention_mask"].tolist()
        }
        await redis_conn.rpush(tokens_queue, json.dumps(payload))

async def inference_worker(redis_conn, model_holder, tokens_queue, batcher):
    """Читает из text:tokens, добавляет в батчер, который сам сливает в result:*"""
    while True:
        msg = await redis_conn.brpop(tokens_queue)
        if msg is None:
            continue
        _, data = msg
        payload = json.loads(data)
        # Восстанавливаем тензоры
        input_ids = torch.tensor(payload["input_ids"])
        attention_mask = torch.tensor(payload["attention_mask"])
        # Добавляем в батчер
        await batcher.add({
            "corr_id": payload["corr_id"],
            "text": (input_ids, attention_mask)  # передаём уже токенизированное
        })