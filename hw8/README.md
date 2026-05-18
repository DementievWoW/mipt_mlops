# HW8. Мониторинг и наблюдаемость ML-сервиса

Домашнее задание модуля 8: построить систему наблюдаемости для ML-сервиса на базе **Prometheus + Grafana**, определить SLO, настроить алерт, продемонстрировать дрифт данных, поднять Data Quality Ops и нарисовать архитектуру Virtual Product Placement.

---

## 1. Дерево метрик

Метрики сгруппированы по точкам зрения четырёх команд: продукт/бизнес, бэкенд, ML-команда и SRE/инфра.

```
ML-сервис (рекомендация / классификация)
│
├── 🎯 Бизнес-метрики              (продукт)
│    ├─ Конверсия (CTR / CR на рекомендации)
│    ├─ Выручка на 1000 запросов  (RPM)
│    ├─ Retention пользователей    (D1/D7/D30)
│    └─ Доля пользователей с активной рекомендацией
│
├── 🌐 Метрики приложения          (бэкенд)
│    ├─ RPS (requests_total[1m])
│    ├─ Latency p50 / p95 / p99   (request_latency_seconds)
│    ├─ Error rate (5xx / total)
│    └─ Availability (up == 1)
│
├── 🤖 ML-метрики                  (ML/DS)
│    ├─ Prediction confidence p50 / p05
│    ├─ Распределение классов (predictions_total)
│    ├─ Feature/Prediction drift (EvidentlyAI, отдельно)
│    ├─ Accuracy / F1 на свежей разметке
│    └─ Доля fallback'ов
│
└── 🖥 Метрики инфраструктуры       (SRE)
     ├─ CPU / RAM / GPU utilization
     ├─ Disk I/O, свободное место
     ├─ Network I/O
     └─ Состояние контейнеров (restarts, OOM)
```

## 2. SLO

| Категория      | SLI                              | SLO                    | Алерт |
|----------------|----------------------------------|------------------------|-------|
| Latency        | `histogram_quantile(0.95, ...)`  | p95 < **1 сек**        | `HighLatencyP95` — > 1s в течение 1 мин |
| Reliability    | `5xx / total`                    | error rate < **1%**    | `HighErrorRate` — > 1% в течение 2 мин |
| Availability   | `up{job="ml_service"}`           | uptime > **99%** / 30d | `ServiceDown` — `up == 0` 1 мин |

Все три SLO зашиты в [prometheus/alert_rules.yml](prometheus/alert_rules.yml).

---

## 3. Что в репозитории

```
hw8/
├── docker-compose.yml          # ml_service + prometheus + alertmanager + grafana
├── .env                        # секреты Telegram (НЕ коммитим, в .gitignore)
├── .env.example                # шаблон секретов для других участников
├── ml_service/
│   ├── app.py                  # FastAPI + sklearn (Iris) + /metrics + /slow + /fail
│   ├── requirements.txt
│   └── Dockerfile
├── prometheus/
│   ├── prometheus.yml          # scrape config + alerting → alertmanager:9093
│   └── alert_rules.yml         # 3 SLO алерта
├── alertmanager/
│   └── alertmanager.yml.template   # шаблон с ${TELEGRAM_*} плейсхолдерами
├── grafana/
│   ├── provisioning/           # datasource + dashboard loader
│   └── dashboards/ml_service.json   # экспортируемый дашборд
├── drift/                      # Шаг 3: EvidentlyAI
│   ├── drift_demo.ipynb        # ноутбук: эксперимент + HTML отчёты + JSON
│   ├── requirements.txt        # evidently, sklearn, pandas
│   ├── data_drift_report.html  # отчёт о data drift (6 из 13 фич дрифтнули)
│   ├── model_performance_report.html  # деградация модели по классам
│   └── metrics_summary.json    # acc/F1 на reference vs current
├── dqops/                      # Шаг 4: DQOps (заглушка, реализуется)
├── diagrams/                   # Шаг 5: схема VPP (заглушка, реализуется)
├── screenshots/                # дашборд, алерт, Telegram, drift, инцидент
├── README.md                   # этот файл
└── EXPLANATION.md              # построчные пояснения для учёбы
```

---

## 4. Запуск стека

```bash
cd hw8
docker compose up --build -d
```

После запуска:

| Сервис      | URL                              | Логин           |
|-------------|----------------------------------|-----------------|
| ML service  | http://localhost:8000            | —               |
| Swagger UI  | http://localhost:8000/docs       | —               |
| Prometheus  | http://localhost:9090            | —               |
| Grafana     | http://localhost:3000            | `admin / admin` |

Дашборд `ML Service — SLO & Monitoring` автоматически загрузится в папку **ML Service** в Grafana через provisioning.

### Проверка таргетов Prometheus

```bash
curl -s http://localhost:9090/api/v1/targets | jq '.data.activeTargets[] | {job:.labels.job, health:.health}'
```

Ожидаемый вывод:

```
{"job": "prometheus", "health": "up"}
{"job": "ml_service", "health": "up"}
```

### Генерация полезной нагрузки

```bash
# Нормальный трафик
while true; do
  curl -s -X POST http://localhost:8000/predict \
    -H "Content-Type: application/json" \
    -d '{"features":[5.1,3.5,1.4,0.2]}' > /dev/null
  sleep 0.1
done
```

### Срабатывание алерта `HighLatencyP95`

```bash
# Деградация: каждый запрос отвечает 2 секунды
while true; do
  curl -s -X POST "http://localhost:8000/slow?seconds=2" > /dev/null
done
```

Через 1–2 минуты в Prometheus (`http://localhost:9090/alerts`) и в Grafana алерт переходит в состояние **Firing**.

### Срабатывание алерта `HighErrorRate`

```bash
while true; do
  curl -s -X POST http://localhost:8000/fail > /dev/null
  sleep 0.1
done
```

---

## 5. Telegram-уведомления

Алерты Prometheus → Alertmanager → Telegram (бот, личный чат).

```bash
# секреты (.env в .gitignore, права 600)
TELEGRAM_BOT_TOKEN=...   # @BotFather → /newbot
TELEGRAM_CHAT_ID=...     # @userinfobot
```

Конфиг бота — [alertmanager/alertmanager.yml.template](alertmanager/alertmanager.yml.template). При запуске init-контейнер `alertmanager-init` через `envsubst` подставляет секреты и кладёт готовый конфиг в named volume.

Проверка:
```bash
curl -s http://localhost:9090/api/v1/alertmanagers     # должен быть activeAlertmanagers
curl -s http://localhost:9093/api/v2/status            # cluster: ready
curl -s http://localhost:9093/api/v2/alerts            # текущие алерты в Alertmanager
sudo docker logs hw8_alertmanager --tail 30            # логи (если Telegram ругается)
```

## 6. Следующие шаги (модули задания)

- [x] Шаг 1 — Дерево метрик и SLO → раздел 1 README
- [x] Шаг 2 — Prometheus + Grafana + 3 алерта + Telegram → `docker-compose.yml`
- [x] Шаг 3 — Drift demo + деградация модели через EvidentlyAI → [drift/](drift/)
- [ ] Шаг 4 — Data Quality инцидент в DQOps → [dqops/](dqops/)
- [ ] Шаг 5 — Архитектурная схема Virtual Product Placement (Kappa) → [diagrams/](diagrams/)
- [ ] Скриншоты: дашборд, Pending/Firing алерта, Telegram, drift-отчёт, инцидент DQOps, диаграмма → [screenshots/](screenshots/)

---

## 6. Критерии оценки (самопроверка)

| Критерий | Артефакт | Балл |
|----------|----------|------|
| Дерево метрик с 4 ветвями | Раздел 1 README | 2 |
| Развёрнутый Prometheus+Grafana, таргеты UP, дашборд | `docker-compose.yml`, скриншоты | 2 |
| Дрифт данных и деградация модели | `drift/` | 2 |
| Инцидент Data Quality в DQOps | `dqops/` | 2 |
| Схема ML-системы VPP со стримами | `diagrams/` | 2 |
| **Итого** |  | **10** |
