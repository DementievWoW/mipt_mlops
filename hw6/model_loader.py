# model_loader.py
from transformers import AutoTokenizer, AutoModel
import torch

class ModelHolder:
    def __init__(self):
        self.tokenizer = None
        self.model = None

    def load(self):
        if self.model is None:
            self.tokenizer = AutoTokenizer.from_pretrained("cointegrated/rubert-tiny2")
            self.model = AutoModel.from_pretrained("cointegrated/rubert-tiny2")
            self.model.eval()
        return self.tokenizer, self.model

    def preprocess(self, texts):
        # Приводим к списку, если передана одна строка
        if isinstance(texts, str):
            texts = [texts]
        tokens = self.tokenizer(texts, return_tensors="pt", padding=True, truncation=True)
        return tokens

    def infer(self, inputs):
        with torch.no_grad():
            outputs = self.model(**inputs)
        # mean по токенам: (batch_size, 768)
        embeddings = outputs.last_hidden_state.mean(dim=1)
        # всегда возвращаем список списков: для batch=1 -> [[...]], для batch>1 -> [[...], ...]
        return embeddings.tolist()