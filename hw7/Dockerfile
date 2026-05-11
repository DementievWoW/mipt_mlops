FROM python:3.11-slim
WORKDIR /app

COPY requirements.txt .
RUN pip install --no-cache-dir -r requirements.txt

COPY ml_pipeline.py app.py ./

ARG MODEL_VERSION=v1.0.0
ENV MODEL_VERSION=${MODEL_VERSION}
RUN python ml_pipeline.py

EXPOSE 8000
CMD ["uvicorn", "app:app", "--host", "0.0.0.0", "--port", "8000"]
