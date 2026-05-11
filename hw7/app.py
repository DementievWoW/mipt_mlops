"""FastAPI: /health и /predict."""
import os
import joblib
from fastapi import FastAPI
from pydantic import BaseModel

VERSION = os.getenv("MODEL_VERSION", "v1.0.0")
model = joblib.load("model.joblib")
app = FastAPI()


class Req(BaseModel):
    x: list[float]


@app.get("/health")
def health():
    return {"status": "ok", "version": VERSION}


@app.post("/predict")
def predict(req: Req):
    return {"prediction": int(model.predict([req.x])[0]), "version": VERSION}
