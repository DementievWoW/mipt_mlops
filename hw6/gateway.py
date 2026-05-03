import asyncio
import json
import uuid
import grpc
import redis.asyncio as redis
import inference_pb2
import inference_pb2_grpc

class ResultServicer(inference_pb2_grpc.ResultServiceServicer):
    def __init__(self, pending):
        self.pending = pending

    async def SendResult(self, request, context):
        corr_id = request.correlation_id
        emb = list(request.embedding)
        print(f"Gateway: received result for {corr_id}")
        future = self.pending.get(corr_id)
        if future:
            future['embedding'] = emb
            future['event'].set()
        else:
            print(f"Gateway: no pending request for {corr_id}")
        return inference_pb2.ResultResponse(status="OK")

class InferenceServicer(inference_pb2_grpc.InferenceServiceServicer):
    def __init__(self, redis_conn, pending):
        self.redis = redis_conn
        self.pending = pending

    async def Predict(self, request, context):
        corr_id = request.correlation_id or str(uuid.uuid4())
        event = asyncio.Event()
        self.pending[corr_id] = {'event': event, 'embedding': None}
        print(f"Gateway: received Predict, corr_id={corr_id}, text='{request.text}'")
        try:
            await self.redis.rpush("text:preprocess", json.dumps({
                "corr_id": corr_id,
                "text": request.text
            }))
            print("Gateway: pushed to Redis")
            await asyncio.wait_for(event.wait(), timeout=15.0)
        except asyncio.TimeoutError:
            print(f"Timeout waiting for result for {corr_id}")
            self.pending.pop(corr_id, None)
            context.set_code(grpc.StatusCode.DEADLINE_EXCEEDED)
            context.set_details("Timeout waiting for inference result")
            return inference_pb2.PredictionResponse()
        # Запись гарантированно существует, т.к. мы не удаляли её в SendResult
        emb = self.pending.pop(corr_id)['embedding']
        print(f"Gateway: returning result for {corr_id}, emb[:3]={emb[:3]}")
        return inference_pb2.PredictionResponse(correlation_id=corr_id, embedding=emb)

async def serve():
    redis_conn = redis.Redis(host='redis-service', port=6379, decode_responses=True)
    await redis_conn.ping()
    print("Gateway: connected to Redis")
    pending = {}
    server = grpc.aio.server()
    inference_pb2_grpc.add_InferenceServiceServicer_to_server(InferenceServicer(redis_conn, pending), server)
    inference_pb2_grpc.add_ResultServiceServicer_to_server(ResultServicer(pending), server)
    server.add_insecure_port('[::]:50051')
    await server.start()
    print("Gateway started on port 50051")
    await server.wait_for_termination()

if __name__ == "__main__":
    asyncio.run(serve())
