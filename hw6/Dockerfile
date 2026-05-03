FROM pytorch/pytorch:2.4.0-cuda12.1-cudnn9-runtime

WORKDIR /app

RUN apt-get update && apt-get install -y --no-install-recommends \
    build-essential \
    && rm -rf /var/lib/apt/lists/*

COPY requirements.txt .
RUN pip install --no-cache-dir -r requirements.txt

COPY inference_pb2.py inference_pb2_grpc.py /app/
COPY *.py /app/
COPY proto/ /app/proto/

EXPOSE 50051

CMD ["python", "server.py"]