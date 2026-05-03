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
            self.model.eval()   # инференс, не тренировка
        return self.tokenizer, self.model

    def preprocess(self, text):
        # шаг 1: препроцессинг (в терминах задания – событие text.preprocess)
        tokens = self.tokenizer(text, return_tensors="pt", padding=True, truncation=True)
        return tokens

    def infer(self, inputs):
        # шаг 2: инференс (событие model.inference)
        with torch.no_grad():
            outputs = self.model(**inputs)
        # Усредняем по токенам для получения эмбеддинга
        embeddings = outputs.last_hidden_state.mean(dim=1).squeeze().tolist()
        return embeddings