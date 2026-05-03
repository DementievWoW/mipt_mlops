# server.py
import asyncio
import grpc
import redis.asyncio as redis
import inference_pb2_grpc
from app import (
    ModelHolder, Batcher, InferenceServicer,
    preprocess_worker, inference_worker
)

QUEUE_PREPROCESS = "text:preprocess"
QUEUE_TOKENS = "text:tokens"

async def serve():
    # Подключаемся к Redis (localhost:6379)
    r = redis.Redis(host='localhost', port=6379, decode_responses=True)
    # Инициализируем модель
    model_holder = ModelHolder()
    batcher = Batcher(model_holder)  # max_size=32, timeout=0.1

    # Запускаем gRPC сервер
    server = grpc.aio.server()
    servicer = InferenceServicer(r, QUEUE_PREPROCESS)
    inference_pb2_grpc.add_InferencePipelineServicer_to_server(servicer, server)
    server.add_insecure_port('[::]:50051')
    await server.start()
    print("gRPC server started on port 50051")

    # Запускаем фоновые обработчики
    asyncio.create_task(preprocess_worker(r, model_holder, QUEUE_PREPROCESS, QUEUE_TOKENS))
    asyncio.create_task(inference_worker(r, model_holder, QUEUE_TOKENS, batcher))
    asyncio.create_task(batcher.flush_loop(r))

    await server.wait_for_termination()

if __name__ == "__main__":
    asyncio.run(serve())