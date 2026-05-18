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

## Этап 5. Telegram-уведомления через Alertmanager (`alertmanager/` + `.env`)

Prometheus сам ничего никому не шлёт — это делает **Alertmanager**. Цепочка:

```
Prometheus  ──active alerts──▶  Alertmanager  ──HTTPS─▶  api.telegram.org/bot<TOKEN>/sendMessage
```

### Что добавляли

1. В `prometheus.yml`:
   ```yaml
   alerting:
     alertmanagers:
       - static_configs:
           - targets: ["alertmanager:9093"]
   ```
   Без этой секции Prometheus считает алерты, но никуда не пушит. Запоминать имя `alertmanager` — DNS внутри docker-сети `monitoring`.

2. **Шаблон конфига `alertmanager.yml.template`** — с плейсхолдерами `${TELEGRAM_BOT_TOKEN}` и `${TELEGRAM_CHAT_ID}`. Сам Alertmanager **не поддерживает** переменные окружения в конфиге, поэтому подставляем их снаружи через `envsubst`.

3. **init-контейнер `alertmanager-init`** на базе `alpine`:
   ```yaml
   envsubst '$$TELEGRAM_BOT_TOKEN $$TELEGRAM_CHAT_ID' < /template/alertmanager.yml.template > /config/alertmanager.yml
   ```
   - Аргумент `'$$VAR1 $$VAR2'` явно ограничивает список подставляемых переменных — без этого `envsubst` сожрёт и Go-template `{{ ... }}` внутри `message`, превратив их в пустоту.
   - Двойные `$$` в `docker-compose.yml` — экранирование от самого compose, который тоже умеет подставлять `${VAR}`.
   - Результат пишется в **именованный volume** `alertmanager_config`, который потом монтируется в основной контейнер только на чтение.
4. **Основной `alertmanager`** ждёт init через `depends_on.condition: service_completed_successfully` — это гарантирует, что конфиг готов до старта.

5. **`.env` с секретами**:
   ```env
   TELEGRAM_BOT_TOKEN=...
   TELEGRAM_CHAT_ID=...
   ```
   - Лежит в `.gitignore`, права `chmod 600`, в репозитории только `.env.example`.

### Подводные камни, на которые наступили

- **bind-mount + редактор = старый файл внутри контейнера.** Когда `Write`/IDE сохраняет файл через temp+rename, у файла меняется inode. Docker bind-mount при создании контейнера резолвит **inode**, а не «следит за путём» — поэтому в работающем контейнере остаётся видна старая версия. Лечится `docker compose up -d --force-recreate <service>`.
- **`/-/reload` Prometheus** — отрабатывает только если новый конфиг **уже** виден внутри контейнера. Если bind-mount устарел (см. выше), reload пройдёт без ошибки, но конфиг останется старый.
- **Telegram bot не пишет первым.** Перед тем как ждать уведомление, нужно один раз нажать **Start** боту — иначе Telegram блокирует исходящие.

### Шаблон сообщения

В `telegram_configs.message` — Go-template Alertmanager'а:
```
{{ if eq .Status "firing" }} FIRING{{ else }} RESOLVED{{ end }} — {{ .CommonLabels.alertname }}
severity: {{ .CommonLabels.severity }}
slo: {{ .CommonLabels.slo }}
{{ range .Alerts }}
• {{ .Annotations.summary }}
  {{ .Annotations.description }}
  started: {{ .StartsAt.Format "15:04:05" }}
{{ end }}
```

- `.Status` — единый статус группы (firing/resolved). Парные RESOLVED-сообщения приходят благодаря `send_resolved: true`.
- `.CommonLabels` — лейблы, общие для всех алертов в группе.
- `range .Alerts` — список конкретных алертов внутри группы (если их несколько).

### Маршрутизация и group_*

```yaml
route:
  group_by: ["alertname"]
  group_wait: 10s
  group_interval: 30s
  repeat_interval: 1h
```

- `group_by` — алерты с одинаковым `alertname` объединяются в один тред (не зальёт чат).
- `group_wait` — после первого алерта ждём ещё 10 секунд: вдруг по соседним инстансам прилетят такие же, отправим одним сообщением.
- `repeat_interval: 1h` — если алерт всё ещё firing, повторное напоминание раз в час (а не каждые 30 секунд).

---

## Этап 6. Drift и деградация модели (`drift/`)

Шаг 3 задания закрывается ноутбуком `drift/drift_demo.ipynb`. Внутри — все шаги эксперимента (подготовка данных, обучение, отчёты Evidently) + финальная ячейка, которая сохраняет `metrics_summary.json` для отчётности.

### Идея демонстрации

Берём **один и тот же датасет** (Wine, 13 числовых фич, 3 класса), делим 50/50 и **искусственно искажаем половину `current`**. Сценарий — covariate shift («производство откалибровало датчики»): метки не трогаем, меняем только распределение фич.

```python
current_drift['alcohol']         *= 1.5    # сдвиг масштаба
current_drift['color_intensity'] *= 2.0
current_drift['proline']         *= 0.4
current_drift['magnesium']       += rng.normal(20, 15, ...)   # +Гауссов шум
current_drift['malic_acid']      += rng.normal(1.0, 0.6, ...)
```

5 из 13 фич сильно ломаем; в итоге Evidently'ев KS-test находит **6 дрифтнувших колонок** (parsy/coloraffect ловит соседние через корреляцию).

### Почему именно covariate shift, а не concept drift

- **Concept drift** — изменилась зависимость target от фич (например, изменились предпочтения пользователей). Для демо требуется поменять *метки* при тех же фичах — этого мы не делаем.
- **Data drift (covariate shift)** — изменилось распределение фич, но зависимость `P(y|x)` та же. Это самый частый сценарий в проде: сенсоры стареют, в логи попадает новый сегмент пользователей, A/B-эксперимент изменил входной трафик.

### Почему `drift_share=0.3`, а не дефолтное 0.5

`DataDriftPreset` по умолчанию считает датасет дрифтнувшим, если **больше половины** фич сместились. Это слишком терпимо для нашего демо: уже 6/13 = 46 % фич ломают модель в 2.5 раза. Снижаем порог до 30 % и получаем явный `dataset_drift = True`.

### Что есть «деградация модели» в эксперименте

Обучаем `LogisticRegression` на reference, считаем accuracy/F1 на двух выборках:

| Метрика     | Reference | Current (drifted) |
|-------------|-----------|-------------------|
| accuracy    | 1.0       | ~0.40             |
| f1_macro    | 1.0       | ~0.37             |

Та же модель, **те же метки**, но «увидевшая» сдвинутые фичи — теряет качество в 2.5 раза. Это и есть деградация, *вызванная* data drift. В отчёте `model_performance_report.html` Evidently разложит F1 по классам и подсветит, какой именно класс просел сильнее (у нас — класс 2).

### Что бы делали в проде

1. Тот же эксперимент в виде CLI-скрипта (легко выделить из ноутбука) запускается по расписанию (cron / Airflow / Argo) на свежем батче inference-логов vs «золотая» reference-выборка.
2. Метрики из `metrics_summary.json` push'ятся в **Pushgateway** Prometheus (`drift_score`, `share_of_drifted_columns`).
3. Алерт в `alert_rules.yml`:
   ```yaml
   - alert: DataDriftHigh
     expr: drift_share_of_drifted_columns > 0.3
     for: 30m
     ...
   ```
   Уходит в тот же Telegram через тот же Alertmanager.
4. HTML-отчёты сохраняются в S3, ссылку прокидываем в аннотацию алерта — DS получает уведомление с прямым линком на отчёт.

---

## Дальше

- **Шагу 4** — DQOps. Подключаем Postgres из compose, импортируем таблицу, меняем её структуру, ловим инцидент.
- **Шагу 5** — диаграмма архитектуры VPP. Kappa, потому что данные — потоковые видео, а пакетный слой Lambda здесь только удвоит сложность без выигрыша.

Эти разделы добавим по мере реализации.
