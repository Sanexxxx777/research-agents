# Research Agents

<!-- TODO: demo GIF (20-40s) -->

Extension agents for [Hub Research](https://github.com/Sanexxxx777/hub-research) — a set of specialized, constrained runtimes that plug into the main research pipeline via hot-reloadable adapters, each scoped to one narrow job (market metrics, official-source knowledge, scorecard assembly, external data collection) instead of one monolithic agent doing everything.

Written by [Aleksandr Shulgin](https://github.com/Sanexxxx777) (@Aleksandr_NFA) during a DeFi investment-consulting engagement, where these agents supported due-diligence research on crypto/DeFi protocols.

**Stack:** Python, FastAPI/HTTP services, Pydantic v2, CoinGecko/DeFiLlama/Dune APIs, systemd/uvicorn.

Current agents:

- `market_intel_agent` — constrained market-intel runtime with deterministic project-analysis pipeline (CoinGecko + DefiLlama + Dune gap-fill in second pass).
- `project_knowledge_agent` — official knowledge runtime for due diligence (`official docs + official website + official blog`, no third-party analyst retrieval).
- `master_research_agent` — deterministic scorecard, conflict detection, dossier assembly
- `collector_agent` — sync HTTP external collector for ResearchHub (`POST /collect`; CoinGecko + DefiLlama only, no Dune ownership).

Hub Research loads these agents through adapters and hot-reloads `service.py` when files change.

## Market Intel Agent v1 Skeleton

Core modules:
- `target_resolver.py` — resolve query/target_id through Hub capabilities
- `sector_resolver.py` — sector inference from Hub market overview + heuristics
- `profile_selector.py` — choose profile (`generic_token`, `defi_lending`, `dex_spot`)
- `source_planner.py` — constrained source + metric plan per profile
- `hub_writer.py` — write observations/artifacts/snapshot into Hub analysis runs

## License

MIT — see [LICENSE](LICENSE).

---

## На русском (кратко)

Расширяющие агенты для [Hub Research](https://github.com/Sanexxxx777/hub-research) — набора
специализированных runtime-компонентов, подключаемых к основному research-пайплайну через
hot-reload адаптеры, каждый заточен под одну узкую задачу (рыночные метрики, официальные
источники знаний, сборка scorecard, внешний сбор данных) вместо одного монолитного агента.
Написаны во время консалтингового due-diligence проекта по крипто/DeFi протоколам. Стек: Python,
FastAPI/HTTP-сервисы, Pydantic v2, CoinGecko/DeFiLlama/Dune API, systemd/uvicorn.
