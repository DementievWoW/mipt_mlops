import asyncio
import grpc
import inference_pb2
import inference_pb2_grpc

async def run():
    async with grpc.aio.insecure_channel('localhost:50051') as channel:
        stub = inference_pb2_grpc.InferencePipelineStub(channel)
        # Открываем bidirectional stream
        call = stub.StreamPredictions()
        # Отправляем несколько сообщений
        texts = ["Привет", "Как дела?", "Машинное обучение"]
        for i, text in enumerate(texts):
            req = inference_pb2.PredictionRequest(correlation_id=str(i), text=text)
            await call.write(req)
            print(f"Sent: {text}")
        await call.done_writing()
        # Читаем ответы
        async for resp in call:
            print(f"Received for {resp.correlation_id}: {resp.embedding[:5]}...")

if __name__ == "__main__":
    asyncio.run(run())