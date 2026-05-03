import grpc
import inference_pb2
import inference_pb2_grpc

def run():
    with grpc.insecure_channel('localhost:50051') as channel:
        stub = inference_pb2_grpc.InferenceServiceStub(channel)
        texts = ["Привет", "Как дела?", "Машинное обучение"]
        for i, text in enumerate(texts):
            req = inference_pb2.PredictionRequest(correlation_id=str(i), text=text)
            resp = stub.Predict(req)
            print(f"Text: {text}, embedding[:3] = {resp.embedding[:3]}...")

if __name__ == "__main__":
    run()