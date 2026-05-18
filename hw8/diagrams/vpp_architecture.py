"""Шаг 5 ДЗ-8. Архитектура ML-системы для Virtual Product Placement (Netflix-style).

Архитектура — Kappa: единый стриминговый pipeline, без отдельного batch-слоя.
Обоснование выбора см. в diagrams/README.md.

Запуск:
    pip install -r requirements.txt
    # системно нужен graphviz: `sudo apt install graphviz`  ИЛИ  `conda install -c conda-forge graphviz`
    python vpp_architecture.py

Артефакт:
    vpp_architecture.png
"""
from diagrams import Cluster, Diagram, Edge
from diagrams.aws.network import CloudFront
from diagrams.aws.storage import S3
from diagrams.generic.device import Mobile, Tablet
from diagrams.generic.network import Router
from diagrams.onprem.analytics import Spark
from diagrams.onprem.client import Users
from diagrams.onprem.compute import Server
from diagrams.onprem.database import PostgreSQL
from diagrams.onprem.gitops import ArgoCD
from diagrams.onprem.inmemory import Redis
from diagrams.onprem.mlops import Mlflow
from diagrams.onprem.monitoring import Grafana, Prometheus
from diagrams.onprem.queue import Kafka
from diagrams.programming.framework import Fastapi
from diagrams.programming.language import Python

GRAPH_ATTR = {
    "fontsize": "18",
    "bgcolor": "white",
    "pad": "0.6",
    "splines": "spline",
}

NODE_ATTR = {
    "fontsize": "12",
}

EDGE_STREAM = {"color": "darkblue", "style": "bold"}
EDGE_BATCH = {"color": "gray40", "style": "dashed"}
EDGE_CONTROL = {"color": "darkgreen", "style": "dotted"}

with Diagram(
    "Virtual Product Placement — Kappa Architecture",
    filename="vpp_architecture",
    show=False,
    direction="LR",
    graph_attr=GRAPH_ATTR,
    node_attr=NODE_ATTR,
):
    # === Источники и потребители ===
    with Cluster("Viewers (по странам, A/B-сегментам)"):
        viewers_phone = Mobile("Mobile app")
        viewers_tv = Tablet("Smart TV / Web")

    with Cluster("Content Sources"):
        catalog = S3("Original video catalog\n(S3, 4K master)")
        metadata_db = PostgreSQL("Scene & brand\nmetadata")

    # === Stream Ingest ===
    with Cluster("Stream Ingest (Kappa: single source of truth)"):
        kafka = Kafka("Kafka\nvideo_segments")
        kafka_meta = Kafka("Kafka\nuser_events")

    # === Stream Processing + ML ===
    with Cluster("Stream Processing & ML Inference"):
        with Cluster("Real-time pipeline"):
            flink = Spark("Flink / Spark\nStreaming")
            scene_detect = Python("Scene detection\n(object/segmentation)")
            brand_swap = Python("GenAI brand swap\n(Stable Diffusion / SDXL)")
            qa_filter = Python("Visual QA filter\n(no artifacts, lip-sync)")
            flink >> Edge(**EDGE_STREAM) >> scene_detect
            scene_detect >> Edge(**EDGE_STREAM) >> brand_swap
            brand_swap >> Edge(**EDGE_STREAM) >> qa_filter

        with Cluster("Personalization"):
            features = Redis("Feature store\n(per-user country, brand affinity)")
            ab = Server("A/B router\n(brand variant per cohort)")

    # === ML Platform (вокруг основного потока) ===
    with Cluster("ML Platform"):
        mlflow = Mlflow("Model Registry\n(MLflow)")
        retrain = ArgoCD("Auto retraining\n(Argo Workflows)")
        drift = Server("Drift / quality\nmonitor\n(Evidently)")

    # === Observability — то же, что мы подняли в Шаге 2 ===
    with Cluster("Observability (Шаг 2)"):
        prom = Prometheus("Prometheus")
        graf = Grafana("Grafana")
        alerts = Server("Alertmanager\n→ Telegram")

    # === Serving / Delivery ===
    with Cluster("Edge Serving"):
        api = Fastapi("Inference API\n(personalized stream)")
        cdn = CloudFront("CDN / Edge cache")
        edge_router = Router("Edge router")

    # === Stream-поток (основная стрелка) ===
    catalog >> Edge(**EDGE_STREAM, label="raw segments") >> kafka
    metadata_db >> Edge(**EDGE_STREAM, label="scene markup") >> kafka
    kafka >> Edge(**EDGE_STREAM) >> flink

    viewers_phone >> Edge(**EDGE_STREAM, label="play events") >> kafka_meta
    viewers_tv >> Edge(**EDGE_STREAM, label="play events") >> kafka_meta
    kafka_meta >> Edge(**EDGE_STREAM) >> features

    qa_filter >> Edge(**EDGE_STREAM, label="branded segments") >> ab
    features >> Edge(**EDGE_STREAM) >> ab
    ab >> Edge(**EDGE_STREAM) >> api
    api >> Edge(**EDGE_STREAM) >> cdn >> edge_router
    edge_router >> Edge(**EDGE_STREAM) >> viewers_phone
    edge_router >> Edge(**EDGE_STREAM) >> viewers_tv

    # === ML Platform — управляющие связи (зелёные пунктиры) ===
    mlflow >> Edge(**EDGE_CONTROL, label="model artifact") >> brand_swap
    mlflow >> Edge(**EDGE_CONTROL, label="model artifact") >> scene_detect
    retrain >> Edge(**EDGE_CONTROL, label="train job") >> mlflow

    # === Drift / monitoring — серые пунктиры ===
    qa_filter >> Edge(**EDGE_BATCH, label="inference logs") >> drift
    drift >> Edge(**EDGE_BATCH, label="drift score") >> prom
    drift >> Edge(**EDGE_BATCH, label="retrain trigger") >> retrain

    # === Метрики приложения в Prometheus ===
    flink >> Edge(**EDGE_BATCH, label="/metrics") >> prom
    api >> Edge(**EDGE_BATCH, label="/metrics") >> prom
    prom >> Edge(**EDGE_BATCH) >> graf
    prom >> Edge(**EDGE_BATCH, label="alerts") >> alerts
