# Session Handoff — 2026-04-04

## 1) Контекст и архитектурная рамка

- Работаем **только** в `market_intel_agent` (не в Hub, не в collector для метрик-агрегации).
- Принцип ownership:
  - `CoinGecko` — market/token базовые метрики.
  - `DefiLlama` — протокольные/DeFi-метрики, unlocks, sector metrics.
  - `Dune` сейчас **не используем** (gap-fill выключен по умолчанию).
- Пайплайн детерминированный, двухпроходный:
  1. entity resolution + sector routing
  2. first-pass через 3 DefiLlama skills
  3. normalized state
  4. second-pass только по missing fields
  5. local ratios
  6. peer comparison
  7. final structured object + markdown report

## 2) Что уже реализовано (факт)

- В `market_intel_agent/project_analysis/*` реализован production-oriented pipeline.
- Поддерживаемые first-class сектора: `lending`, `spot_dex`, `perp_dex`.
- DefiLlama skill aliases нормализуются:
  - `defillama-openapi-skill -> protocol-deep-dive`
  - `defillama-api -> market-analysis`
- Реальный first-pass adapter:
  - `scripts/execute_first_pass_skill.py`
  - Может запускать skill-runner и fallback на прямые DefiLlama endpoint'ы.
- Source ownership enforced: wrong-owner поля не перезаписывают state.
- Добавлена observability:
  - `fetch_audit`
  - `source_cost`
  - `missing_fields.reason` с максимально конкретными причинами.
- Добавлен reusable matrix-runner:
  - `scripts/run_project_analysis_matrix.py`

## 3) Ключевые свежие улучшения этой сессии

1. CoinGecko retry/backoff
- Добавлен retry/backoff для `coingecko` на `429/5xx` + transport errors.
- Новые env:
  - `MARKET_INTEL_PA_COINGECKO_RETRY_MAX`
  - `MARKET_INTEL_PA_COINGECKO_RETRY_BACKOFF_MS`

2. Fail-open + negative memoization при флапах API
- В source layer добавлен short TTL для фейловых запросов (чтобы не дергать одинаковые упавшие URL многократно).
- Новый env:
  - `MARKET_INTEL_PA_ERROR_CACHE_TTL_SEC` (default 30)
- Это снижает лишние вызовы на DefiLlama/CoinGecko при временной недоступности.

3. Улучшение missing reasons
- Для required defillama metrics, которые остались null, source layer теперь пишет `metric_unavailable` с причиной.
- First-pass runner добавляет synthetic `metric_unavailable` для covered metrics, которые skill не вернул:
  - reason: `first_pass_skills output missing metric`

4. Graceful degradation
- Сетевые ошибки в resolver path (`/protocol/<slug>`) больше не валят весь pipeline.
- При проблемах с источниками pipeline стремится возвращать structured analysis с `missing_fields`, а не `None`.

## 4) Live E2E статус (последний прогон)

Прогон через:
- `scripts/run_project_analysis_matrix.py --assets "AAVE,UNI,DYDX"`

Итог:
- `AAVE`: `final_report_ready`, missing `5`
  - `token_unlocks_12m`, `unlock_recipients`, `bad_debt`, `collateral_mix`, `borrow_mix`
- `UNI`: `final_report_ready`, missing `3`
  - `token_unlocks_12m`, `unlock_recipients`, `retention`
- `DYDX`: `final_report_ready`, missing `7`
  - `token_unlocks_12m`, `unlock_recipients`, `main_demand_kpi`, `volume`, `open_interest`, `retention`, `markets_count`
- `dune_estimated_calls = 0`

Live artifacts:
- `/tmp/mi_live_matrix_v4/summary.json`
- `/tmp/mi_live_matrix_v4/aave.json`
- `/tmp/mi_live_matrix_v4/uni.json`
- `/tmp/mi_live_matrix_v4/dydx.json`

## 5) Почему часть полей всё ещё missing

- На free DefiLlama часть данных реально отсутствует/нестабильна для конкретных slug/summary групп.
- Для AAVE проверено напрямую: `badDebt/collateral/borrowTokens` в payload часто `null`.
- Для DYDX perp-метрики (`volume/open_interest/markets_count`) на текущих free endpoint'ах DefiLlama `summary/derivatives/*` фактически недоступны/похоже paywalled (часто 402), поэтому поле остается missing.

## 6) Что протестировано

- Тесты project analysis + first-pass adapter зелёные:
  - `34 passed`
- Покрыты:
  - source ownership
  - first-pass normalization/aliases
  - retry/backoff logic
  - duplicate-call prevention via negative memoization
  - graceful fallback поведения

## 7) Где основные файлы

- Core pipeline:
  - `market_intel_agent/project_analysis/pipeline.py`
  - `market_intel_agent/project_analysis/sources.py`
  - `market_intel_agent/project_analysis/first_pass.py`
  - `market_intel_agent/project_analysis/registry.py`
  - `market_intel_agent/project_analysis/models.py`
- Scripts:
  - `scripts/execute_first_pass_skill.py`
  - `scripts/run_project_analysis.py`
  - `scripts/run_project_analysis_matrix.py`
- Docs:
  - `README.md`
  - `docs/migration-changelog.md`

## 8) Текущий приоритет next step

Сфокусироваться на `perp_dex` без Dune:

1. Targeted fallback по secondary slugs для `dexs/derivatives` уже добавлен в source-layer.
2. Явные причины confirmed-unavailable для perp skill-covered метрик уже добавлены (с `attempted_slugs`).
3. Следующий шаг: принять продуктовое решение по источнику для perp gaps (оставляем explicit missing на free DefiLlama или включаем отдельный расширенный источник позже).

## 9) Готовый промпт для продолжения завтра

Вставь в новый чат:

---
Продолжаем с checkpoint `market_intel_agent` (handoff: `docs/session-handoff-2026-04-04.md`).

Контекст:
- Работаем только в `market_intel_agent`.
- Dune сейчас не включаем.
- DefiLlama-first pipeline уже реализован, matrix runner есть.
- Последний live статус:
  - AAVE missing=5
  - UNI missing=3
  - DYDX missing=7
  - все `final_report_ready`, dune calls = 0
- Важные последние изменения:
  - CoinGecko retry/backoff
  - negative memoization failed fetches (`MARKET_INTEL_PA_ERROR_CACHE_TTL_SEC`)
  - улучшенные missing reasons (source + first-pass synthetic metric_unavailable)

Задача на этот шаг:
1) Дожать `perp_dex` coverage (DYDX) через DefiLlama-only targeted fallback по derivatives slugs, без Dune.
2) Сохранить strict ownership, без дублирующих запросов.
3) Обновить тесты и прогнать matrix (`AAVE,UNI,DYDX`) через `scripts/run_project_analysis_matrix.py`.
4) Дать short diff-summary: что изменено, какие missing закрылись, какие остались и почему.
---
