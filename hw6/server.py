import asyncio
import grpc
from concurrent.futures import ThreadPoolExecutor
import inference_pb2
import inference_pb2_grpc
from model_loader import ModelHolder
from batching import Batcher

class InferenceServicer(inference_pb2_grpc.InferencePipelineServicer):
    def __init__(self):
        self.holder = ModelHolder()
        self.holder.load()
        self.batcher = Batcher(self.holder)

    async def StreamPredictions(self, request_iterator, context):
        # читаем входящий поток и отправляем запросы батчеру
        async def produce():
            async for req in request_iterator:
                # Отправляем на батчинг и возвращаем результат, когда будет готов
                future = await self.batcher.add_request(req.correlation_id, req.text)
                emb = await future
                yield inference_pb2.PredictionResponse(
                    correlation_id=req.correlation_id,
                    embedding=emb
                )
        # Запускаем parallel flush loop
        flush_task = asyncio.create_task(self.batcher.flush_loop())
        try:
            async for resp in produce():
                await context.write(resp)
        finally:
            flush_task.cancel()

async def serve():
    server = grpc.aio.server()
    inference_pb2_grpc.add_InferencePipelineServicer_to_server(InferenceServicer(), server)
    server.add_insecure_port('[::]:50051')
    await server.start()
    print("gRPC server started on port 50051")
    await server.wait_for_termination()

if __name__ == "__main__":
    asyncio.run(serve())