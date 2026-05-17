"""Минимальный ML-сервис с метриками для Prometheus.

Эндпойнты:
    GET  /          - health-check
    GET  /healthz   - liveness probe
    POST /predict   - предсказание sklearn-моделью Iris
    GET  /metrics   - метрики в формате Prometheus
    POST /slow      - искусственная задержка для проверки алерта
    POST /fail      - искусственная ошибка для проверки error-rate
"""
from __future__ import annotations

import os
import time
from typing import List

import numpy as np
from fastapi import FastAPI, HTTPException
from pydantic import BaseModel, Field
from sklearn.datasets import load_iris
from sklearn.linear_model import LogisticRegression
from prometheus_client import (
    CONTENT_TYPE_LATEST,
    Counter,
    Gauge,
    Histogram,
    generate_latest,
)
from starlette.requests import Request
from starlette.responses import Response

MODEL_VERSION = os.getenv("MODEL_VERSION", "iris-logreg-v1")

REQUEST_LATENCY = Histogram(
    "request_latency_seconds",
    "Время обработки HTTP-запроса (секунды)",
    labelnames=("method", "endpoint"),
    buckets=(0.005, 0.01, 0.025, 0.05, 0.1, 0.25, 0.5, 1.0, 2.5, 5.0, 10.0),
)
REQUESTS_TOTAL = Counter(
    "requests_total",
    "Количество HTTP-запросов",
    labelnames=("method", "endpoint", "status"),
)
PREDICTIONS_TOTAL = Counter(
    "predictions_total",
    "Количество предсказаний модели по классам",
    labelnames=("model_version", "predicted_class"),
)
PREDICTION_CONFIDENCE = Histogram(
    "prediction_confidence",
    "Уверенность модели (max softmax) на инференсе",
    labelnames=("model_version",),
    buckets=(0.0, 0.2, 0.4, 0.5, 0.6, 0.7, 0.8, 0.9, 0.95, 0.99, 1.0),
)
MODEL_INFO = Gauge(
    "model_info",
    "Информация о версии модели (значение всегда 1)",
    labelnames=("model_version",),
)
MODEL_INFO.labels(model_version=MODEL_VERSION).set(1)


def _train_model() -> LogisticRegression:
    data = load_iris()
    model = LogisticRegression(max_iter=200)
    model.fit(data.data, data.target)
    return model


MODEL = _train_model()
CLASS_NAMES = load_iris().target_names.tolist()


class PredictRequest(BaseModel):
    features: List[float] = Field(
        ...,
        min_length=4,
        max_length=4,
        description="Признаки Iris: sepal_length, sepal_width, petal_length, petal_width",
    )


class PredictResponse(BaseModel):
    predicted_class: str
    confidence: float
    model_version: str


app = FastAPI(title="ML service for hw8 monitoring")


@app.middleware("http")
async def prometheus_middleware(request: Request, call_next):
    if request.url.path == "/metrics":
        return await call_next(request)
    start = time.perf_counter()
    status_code = 500
    try:
        response = await call_next(request)
        status_code = response.status_code
        return response
    finally:
        elapsed = time.perf_counter() - start
        endpoint = request.url.path
        REQUEST_LATENCY.labels(method=request.method, endpoint=endpoint).observe(elapsed)
        REQUESTS_TOTAL.labels(
            method=request.method, endpoint=endpoint, status=str(status_code)
        ).inc()


@app.get("/")
def root() -> dict:
    return {"service": "ml-monitoring-demo", "model_version": MODEL_VERSION}


@app.get("/healthz")
def healthz() -> dict:
    return {"status": "ok"}


@app.post("/predict", response_model=PredictResponse)
def predict(payload: PredictRequest) -> PredictResponse:
    features = np.array(payload.features, dtype=float).reshape(1, -1)
    probs = MODEL.predict_proba(features)[0]
    idx = int(np.argmax(probs))
    cls = CLASS_NAMES[idx]
    confidence = float(probs[idx])
    PREDICTIONS_TOTAL.labels(model_version=MODEL_VERSION, predicted_class=cls).inc()
    PREDICTION_CONFIDENCE.labels(model_version=MODEL_VERSION).observe(confidence)
    return PredictResponse(
        predicted_class=cls, confidence=confidence, model_version=MODEL_VERSION
    )


@app.post("/slow")
def slow(seconds: float = 2.0) -> dict:
    """Имитация деградации latency: используется для проверки алерта."""
    if seconds < 0 or seconds > 30:
        raise HTTPException(status_code=400, detail="seconds must be in [0, 30]")
    time.sleep(seconds)
    return {"slept_seconds": seconds}


@app.post("/fail")
def fail() -> dict:
    raise HTTPException(status_code=500, detail="forced failure")


@app.get("/metrics")
def metrics() -> Response:
    return Response(generate_latest(), media_type=CONTENT_TYPE_LATEST)
