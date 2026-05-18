# Шаг 3. Data drift и деградация модели — EvidentlyAI

## Что показываем

На датасете **Wine** (sklearn, 13 числовых фич, 3 класса) симулируется ситуация «прод пошёл вразнос»:
- датчики начали мерить `alcohol`, `color_intensity`, `proline`, `magnesium`, `malic_acid` по-другому → covariate shift;
- метки классов не меняются → это именно **data drift**, не concept drift;
- модель, обученная на оригинальных данных, теряет качество — это **деградация модели**, вызванная дрифтом.

## Файлы

| Файл                       | Что внутри |
|----------------------------|------------|
| `drift_demo.ipynb`         | Учебный ноутбук: обучает модель, считает метрики, генерирует HTML-отчёты и `metrics_summary.json` |
| `requirements.txt`         | `evidently>=0.4.30,<0.5`, sklearn, pandas, numpy |
| `data_drift_report.html`   | Отчёт `DataDriftPreset + DataQualityPreset` (создаётся при запуске) |
| `model_performance_report.html` | Отчёт `ClassificationPreset` — деградация по классам |
| `metrics_summary.json`     | accuracy/F1 на reference и current, число drifted фич |

## Запуск

```bash
cd hw8/drift
python -m venv .venv
.venv/bin/pip install -r requirements.txt
.venv/bin/jupyter lab drift_demo.ipynb
```

Затем последовательно выполнить все ячейки (Cell → Run All). После прогона в текущей папке появятся `data_drift_report.html`, `model_performance_report.html` и `metrics_summary.json`.

## Ожидаемый результат

```
Reference: 89 rows, Current(drifted): 89 rows

=== Metrics summary ===
  accuracy_reference: 0.99
  accuracy_current_drifted: ~0.40–0.60
  f1_macro_reference: ~0.99
  f1_macro_current_drifted: ~0.40–0.60
  drifted_columns: 5+ (из 13)
  share_of_drifted_columns: > 0.3
  dataset_drift: True
```

В HTML-отчёте видно:
- KS-test по каждой фиче → подсвечивает «сдвинутые» (alcohol, color_intensity, proline, magnesium, malic_acid);
- сравнение распределений в виде гистограмм reference vs current;
- агрегат `dataset_drift = True` если доля дрифтнувших колонок > порога (по умолчанию 0.5; для 5/13 — на грани, можно уменьшить порог в `DataDriftPreset(drift_share=0.3)`).

## Скриншоты для отчётности

Положить в `hw8/screenshots/`:
1. `05_drift_overview.png` — верх HTML-отчёта `data_drift_report.html` со сводкой по dataset drift.
2. `06_drift_columns.png` — таблица с per-column drift (KS-test, p-value).
3. `07_model_performance.png` — раздел Classification Report с reference vs current accuracy.

## Куда это пристраивается в проде

В реальном проде такой отчёт:
1. Запускается на расписании (Airflow / cron / Argo Workflows) — раз в сутки или после каждого batch-инференса.
2. Метрики **публикуются в Prometheus** (либо через Pushgateway, либо через ad-hoc HTTP-сервис).
3. На метрику `share_of_drifted_columns > 0.3` ставится алерт — точно так же, как мы делали для latency в Шаге 2.
4. HTML-отчёт сохраняется в S3 и линкуется из Slack/Telegram-уведомления.
