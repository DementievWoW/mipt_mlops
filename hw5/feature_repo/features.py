from feast import Entity, FeatureView, FileSource, Field
from feast.types import Float32
import pandas as pd
from datetime import timedelta, datetime

df = pd.read_csv("../data/iris.csv")
df["event_timestamp"] = datetime.now()
df["id"] = range(len(df))

# Приводим имена колонок к нужному виду
df.rename(columns={
    'sepal.length': 'sepal_length',
    'sepal.width': 'sepal_width',
    'petal.length': 'petal_length',
    'petal.width': 'petal_width'
}, inplace=True)

df.to_parquet("data/iris.parquet", index=False)

iris_entity = Entity(name="iris_id", join_keys=["id"])

iris_source = FileSource(
    path="data/iris.parquet",
    timestamp_field="event_timestamp",
)

iris_features = FeatureView(
    name="iris_features",
    entities=[iris_entity],
    ttl=timedelta(days=1),
    schema=[
        Field(name="sepal_length", dtype=Float32),
        Field(name="sepal_width", dtype=Float32),
        Field(name="petal_length", dtype=Float32),
        Field(name="petal_width", dtype=Float32),
    ],
    source=iris_source,
)
