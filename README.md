# Research Agents

Shared external workspace for Research Hub specialized agents.

Current agents:

- `market_intel_agent` — constrained v1 market intel (profiles: generic_token/defi_lending/dex_spot; sources: Hub capabilities + CoinGecko + DefiLlama; lending block supports TVL/borrows/supplied/competitors/gaps)
- `master_research_agent` — deterministic scorecard, conflict detection, dossier assembly
- `collector_agent` — sync HTTP external collector for ResearchHub (`POST /collect`; sources: CoinGecko + DefiLlama; `dune` reserved as extension point)

Hub Research loads these agents through adapters and hot-reloads `service.py` when files change.

## Market Intel Agent v1 Skeleton

Core modules:
- `target_resolver.py` — resolve query/target_id through Hub capabilities
- `sector_resolver.py` — sector inference from Hub market overview + heuristics
- `profile_selector.py` — choose profile (`generic_token`, `defi_lending`, `dex_spot`)
- `source_planner.py` — constrained source + metric plan per profile
- `hub_writer.py` — write observations/artifacts/snapshot into Hub analysis runs
