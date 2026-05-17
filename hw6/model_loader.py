from transformers import AutoTokenizer, AutoModel
import torch

class ModelHolder:
    def __init__(self):
        self.tokenizer = None
        self.model = None
        self.load()   # сразу загружаем при создании

    def load(self):
        if self.model is None:
            self.tokenizer = AutoTokenizer.from_pretrained("cointegrated/rubert-tiny2")
            self.model = AutoModel.from_pretrained("cointegrated/rubert-tiny2")
            self.model.eval()

    def preprocess(self, texts):
        if isinstance(texts, str):
            texts = [texts]
        return self.tokenizer(texts, return_tensors="pt", padding=True, truncation=True)

    def infer(self, inputs):
        with torch.no_grad():
            outputs = self.model(**inputs)
        # средний эмбеддинг по всем токенам
        embeddings = outputs.last_hidden_state.mean(dim=1)
        return embeddings.tolist()