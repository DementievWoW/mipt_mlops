"""Обучает RandomForest на Iris и сохраняет модель в model.joblib."""
import os
import joblib
from sklearn.datasets import load_iris
from sklearn.ensemble import RandomForestClassifier
from sklearn.model_selection import train_test_split
from sklearn.metrics import accuracy_score

VERSION = os.getenv("MODEL_VERSION", "v1.0.0")
N_ESTIMATORS = 100 if VERSION == "v1.0.0" else 300

iris = load_iris()
X_train, X_test, y_train, y_test = train_test_split(
    iris.data, iris.target, test_size=0.2, random_state=42
)
model = RandomForestClassifier(n_estimators=N_ESTIMATORS, random_state=42)
model.fit(X_train, y_train)
accuracy = accuracy_score(y_test, model.predict(X_test))
print(f"version={VERSION} accuracy={accuracy:.4f}")

joblib.dump(model, "model.joblib")
