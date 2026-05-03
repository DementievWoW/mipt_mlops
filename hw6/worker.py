import asyncio
import json
import grpc
import redis.asyncio as redis
import inference_pb2
import inference_pb2_grpc
from model_loader import ModelHolder
from batching import Batcher

GATEWAY_ADDR = "grpc-gateway-service:50051"

async def send_result(correlation_id, embedding):
    async with grpc.aio.insecure_channel(GATEWAY_ADDR) as channel:
        stub = inference_pb2_grpc.ResultServiceStub(channel)
        await stub.SendResult(inference_pb2.ResultRequest(
            correlation_id=correlation_id,
            embedding=embedding
        ))
    print(f"Worker: sent result for {correlation_id}")

async def inference_worker(redis_conn, batcher):
    print("Worker: listening on text:preprocess")
    while True:
        msg = await redis_conn.blpop("text:preprocess", timeout=0.1)
        if msg is not None:
            _, data = msg
            req = json.loads(data)
            print(f"Worker: received {req['corr_id']}")
            await batcher.add(req["corr_id"], req["text"])

async def main():
    redis_conn = redis.Redis(host='redis-service', port=6379, decode_responses=True)
    await redis_conn.ping()
    print("Worker: connected to Redis")
    model_holder = ModelHolder()
    model_holder.load()
    print("Worker: model loaded")
    batcher = Batcher(model_holder)
    async def on_batch_processed(cids, embeddings):
        print(f"Worker: processing batch of size {len(cids)}")
        tasks = [send_result(cid, emb) for cid, emb in zip(cids, embeddings)]
        await asyncio.gather(*tasks)
    batcher.process_callback = on_batch_processed
    asyncio.create_task(batcher.flush_loop())
    await inference_worker(redis_conn, batcher)

if __name__ == "__main__":
    asyncio.run(main())
