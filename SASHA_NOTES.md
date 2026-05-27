# Sasha Notes — research-agents

⚠️ Этот файл — для меня (Саши) и Claude.

## Назначение
Extension agents для **hub-research** — отдельные специализированные runtime'ы,
которые hub-research загружает через адаптеры с hot-reload.

## Что внутри
- **`market_intel_agent/`** — constrained market-intel runtime с deterministic
  project-analysis pipeline (CoinGecko + DefiLlama + Dune gap-fill во втором pass)
- **`project_knowledge_agent/`** — official knowledge runtime для due diligence
  (`official docs + website + blog`, БЕЗ third-party analyst retrieval)
- **`master_research_agent/`** — deterministic scorecard + conflict detection +
  dossier assembly
- **`collector_agent/`** — sync HTTP external collector для ResearchHub
  (`POST /collect`), CoinGecko + DefiLlama. Запущен как systemd unit
  `researchhub-collector-agent.service` :8091 на S#3

## Статус
- **Production:** S#3 [internal-server] `/root/research-agents/`
- **Этот snapshot:** 2026-05-27 (initial commit от 02.04 + локальный
  Pydantic v2 fix)
- **Их remote (не наш):** `[client]/research-agents`

## Связи
- **hub-research** → `Sanexxxx777/hub-research` — main consumer
  (`agent/runner.py` хук, hot-reload через `service.py`)

## Cleanup
- Excluded: venv, __pycache__, data, logs, .env
