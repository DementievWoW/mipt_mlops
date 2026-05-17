# HW8 — построчные пояснения

Файл собран как «учебный комментарий» к коду и конфигам hw8. Здесь объясняется **зачем** написана каждая нетривиальная строка, а не только что она делает. Структура повторяет порядок Этапов из плана.

---

## Этап 1. ML-сервис (`ml_service/app.py`)

### Импорты

- `prometheus_client.Histogram / Counter / Gauge` — три типа метрик Prometheus:
  - **Counter** — только растёт (число запросов, ошибок). Сбрасывается только при рестарте процесса; Prometheus сам вычисляет производную через `rate()`.
  - **Gauge** — мгновенное значение (число активных коннектов, версия модели). Может расти и убывать.
  - **Histogram** — распределение по бакетам. Главная фишка — позволяет считать перцентили на стороне Prometheus через `histogram_quantile()`. Бакеты задаются заранее и сильно влияют на точность.
- `starlette.requests.Request` / `Response` — низкоуровневые типы, нужны для middleware и для `/metrics`-эндпойнта (там нельзя возвращать обычный pydantic-объект, нужен сырой текст с правильным `Content-Type`).

### Описание метрик

```python
REQUEST_LATENCY = Histogram(
    "request_latency_seconds",
    "Время обработки HTTP-запроса (секунды)",
    labelnames=("method", "endpoint"),
    buckets=(0.005, 0.01, 0.025, 0.05, 0.1, 0.25, 0.5, 1.0, 2.5, 5.0, 10.0),
)
```

- **Имя `*_seconds`** — конвенция Prometheus: время в секундах, размеры в байтах, без единиц измерения в имени метрики типа `_ms` или `_mb`.
- **`labelnames`** — измерения, по которым потом можно фильтровать/группировать. Важно: каждая комбинация лейблов создаёт **отдельный временной ряд**, поэтому туда нельзя класть высокоарность (user_id, trace_id и т. п.) — Prometheus захлебнётся.
- **`buckets`** — выбраны вокруг порога SLO 1 сек: близко к 1 сек гранулярность выше (`0.5, 1.0, 2.5`), чтобы p95 считался точно. Лишние бакеты на хвостах (`5.0, 10.0`) нужны, чтобы выбросы не «налипали» на последний бакет.

```python
PREDICTIONS_TOTAL = Counter(
    "predictions_total",
    "Количество предсказаний модели по классам",
    labelnames=("model_version", "predicted_class"),
)
```

- ML-метрика: распределение по классам. Если внезапно в проде стало 99% одного класса — это либо drift во входных данных, либо деградация модели.
- `model_version` в лейблах позволяет различать версии модели на одном дашборде (A/B).

```python
MODEL_INFO = Gauge("model_info", "...", labelnames=("model_version",))
MODEL_INFO.labels(model_version=MODEL_VERSION).set(1)
```

- Классический паттерн «info-метрика»: значение всегда 1, вся информация в лейблах. В Grafana удобно делать `model_info * on() group_right ...` чтобы протащить версию модели в другие графики.

### Middleware

```python
@app.middleware("http")
async def prometheus_middleware(request: Request, call_next):
    if request.url.path == "/metrics":
        return await call_next(request)
```

- Исключаем `/metrics` из подсчёта — иначе сам Prometheus, скрейпя сервис каждые 5 сек, накручивал бы RPS и портил latency-гистограмму.

```python
    start = time.perf_counter()
```

- `perf_counter`, а не `time.time()`: монотонные часы, не зависят от перевода времени.

```python
    try:
        response = await call_next(request)
        status_code = response.status_code
        return response
    finally:
        ...
        REQUEST_LATENCY.labels(...).observe(elapsed)
        REQUESTS_TOTAL.labels(..., status=str(status_code)).inc()
```

- Метрики обновляются в `finally`, чтобы они инкрементились даже когда обработчик упал с исключением. `status` приводим к строке: Prometheus лейблы — всегда строки.

### Эндпойнты `/slow` и `/fail`

Это **искусственные** инструменты для проверки алертов, как требует задание (шаг 2: «искусственно увеличьте время отклика»). В реальном проде их бы не было — это эквивалент chaos-инжекторов.

### `/metrics`

```python
return Response(generate_latest(), media_type=CONTENT_TYPE_LATEST)
```

- `generate_latest()` сериализует все зарегистрированные метрики в текстовый формат Prometheus.
- `CONTENT_TYPE_LATEST` = `text/plain; version=0.0.4; charset=utf-8` — без этого заголовка Prometheus иногда отказывается парсить.

---

## Этап 2. Prometheus (`prometheus/prometheus.yml`)

```yaml
global:
  scrape_interval: 5s
  evaluation_interval: 5s
```

- 5 секунд — агрессивно для прода (15s — типично), но для демо удобно: алерт видно почти сразу.
- `scrape_interval` влияет на rate-функции: `rate(...[1m])` усреднит примерно 12 точек.
- `evaluation_interval` определяет, как часто Prometheus считает правила алертов.

```yaml
rule_files:
  - /etc/prometheus/alert_rules.yml
```

- Путь **внутри контейнера**. Маппинг наружу делается в `docker-compose.yml` через `volumes`.

```yaml
scrape_configs:
  - job_name: ml_service
    metrics_path: /metrics
    static_configs:
      - targets: ["ml_service:8000"]
```

- `ml_service:8000` — DNS-имя сервиса внутри docker-сети `monitoring`. Никаких `localhost` или `host.docker.internal` — у каждого контейнера свой `localhost`.
- `static_configs` подходит для демо. В проде используют `kubernetes_sd_configs`, `consul_sd_configs` и т. п. — service discovery.

### `alert_rules.yml`

```yaml
- alert: HighLatencyP95
  expr: |
    histogram_quantile(0.95,
      sum by (le) (rate(request_latency_seconds_bucket{service="ml_service"}[1m]))
    ) > 1
  for: 1m
```

Разбор выражения изнутри наружу:

1. `request_latency_seconds_bucket` — Prometheus автоматически порождает суффикс `_bucket` для гистограмм. Каждый бакет — отдельный временной ряд с лейблом `le="<граница>"`.
2. `rate(...[1m])` — среднее число событий в секунду за последнюю минуту. Это обязательный шаг: `histogram_quantile` хочет получать на вход именно rate, не сырые counter'ы.
3. `sum by (le)` — суммируем по всем измерениям, кроме `le`. Иначе перцентиль считался бы независимо для каждой комбинации `(method, endpoint)`.
4. `histogram_quantile(0.95, ...)` — линейная интерполяция внутри бакета `le`. **Точность ограничена бакетами**: если ближайшие границы `0.5` и `1.0`, реальный p95 = 0.7 даст оценку где-то в этом диапазоне.

- `for: 1m` — алерт «созревает» через минуту: одиночные всплески не разбудят дежурного. Связка `for` + длинное окно `rate(...[1m])` сглаживает шум.

```yaml
- alert: HighErrorRate
  expr: |
    sum(rate(requests_total{status=~"5.."}[5m]))
      /
    sum(rate(requests_total[5m])) > 0.01
```

- `=~"5.."` — regex-матч на статусы 500–599.
- Делим **rate / rate** (а не Counter / Counter): при делении сырых counter'ов сразу после рестарта получили бы 0/0 = NaN.

```yaml
- alert: ServiceDown
  expr: up{job="ml_service"} == 0
```

- `up` — встроенная метрика Prometheus: 1 если последний scrape успешен, 0 если нет. **Самый дешёвый и надёжный** health-check.

---

## Этап 3. Grafana provisioning

Зачем provisioning? Чтобы дашборд и datasource хранились в репозитории как код (GitOps), а не настраивались мышкой и не терялись при пересоздании контейнера.

### `datasources/prometheus.yml`

```yaml
- name: Prometheus
  uid: PBFA97CFB590B2093
  type: prometheus
  url: http://prometheus:9090
```

- **Фиксированный `uid`** — критично! В JSON-дашборде каждая панель ссылается на datasource по uid. Без фиксации Grafana сгенерит случайный uid → дашборд не сможет найти datasource → панели покажут «No data».
- `http://prometheus:9090` — снова внутреннее имя в docker-сети.

### `dashboards/dashboards.yml`

```yaml
providers:
  - name: ml_service_dashboards
    options:
      path: /var/lib/grafana/dashboards
```

- Grafana периодически сканирует указанную папку и подхватывает любой `*.json` как дашборд. Обновление файла на хосте → автоматическая перезагрузка дашборда.

### `ml_service.json`

Краткое описание панелей:

| Panel | Запрос | Что показывает |
|-------|--------|----------------|
| Availability | `up{job="ml_service"}` | UP / DOWN |
| Latency p95 (stat) | `histogram_quantile(0.95, ...)` | текущее значение vs SLO 1s |
| Error rate (stat) | `sum(rate(...5..)) / sum(rate(...))` | доля 5xx |
| RPS (stat) | `sum(rate(requests_total[1m]))` | нагрузка |
| Latency p50/p95/p99 (timeseries) | три перцентиля + threshold-line на 1s | визуализация распределения во времени |
| Requests by status (stacked) | `sum by (status) (rate(...))` | 2xx / 4xx / 5xx |
| Predictions by class | `sum by (predicted_class) (rate(predictions_total[1m]))` | ML — баланс классов |
| Model confidence | `histogram_quantile(0.5/0.05, ...)` | ML — медиана и низкий хвост уверенности |

`clamp_min(..., 1e-9)` в формуле error rate — защита от деления на ноль, когда трафика нет.

---

## Этап 4. docker-compose

```yaml
prometheus:
  command:
    - "--config.file=/etc/prometheus/prometheus.yml"
    - "--web.enable-lifecycle"
```

- `--web.enable-lifecycle` включает эндпойнт `POST /-/reload` → можно перезагружать конфиг без рестарта контейнера: `curl -X POST http://localhost:9090/-/reload`.

```yaml
volumes:
  - ./grafana/dashboards:/var/lib/grafana/dashboards:ro
  - grafana_data:/var/lib/grafana
```

- Первый монт — read-only, чтобы из UI нельзя было «случайно» переписать файл-источник.
- Именованный volume `grafana_data` — для базы Grafana (там хранятся пользователи, alert-state). Без него каждый рестарт сбрасывал бы алерты в `Normal`.

```yaml
networks:
  monitoring:
    driver: bridge
```

- Изолированная сеть. Все сервисы видят друг друга по именам, наружу торчат только проброшенные порты.

---

## Дальше

После прохождения шагов 1–2 (мониторинг работает, алерт срабатывает) переходим к:

- **Шагу 3** — дрифт через EvidentlyAI в `drift/`. Идея: один и тот же датасет берём как `reference` и сильно искажаем как `current` → отчёт показывает feature drift.
- **Шагу 4** — DQOps. Подключаем Postgres из compose, импортируем таблицу, меняем её структуру, ловим инцидент.
- **Шагу 5** — диаграмма архитектуры VPP. Kappa, потому что данные — потоковые видео, а пакетный слой Lambda здесь только удвоит сложность без выигрыша.

Эти разделы добавим по мере реализации.
