# Metrics Agent Migration Plan

## Goal

Consolidate metrics collection into `market_intel_agent` and remove duplicate/competing implementations from Hub and `collector_agent`.

## Ownership Decision

- `market_intel_agent` owns:
  - CoinGecko collection
  - DefiLlama collection
  - Dune gap-fill (second pass)
  - deterministic normalized analysis pipeline
- `collector_agent` must not execute Dune collection.
- Hub keeps only boundary/integration code, not duplicated metrics orchestration.

## File-Level Migration

1. Move deterministic pipeline modules to market intel:
   - `market_intel_agent/project_analysis/*`
2. Add reusable runtime entrypoints:
   - `scripts/bootstrap_market_intel_stack.sh`
   - `scripts/run_project_analysis.py`
3. Wire agent service:
   - `market_intel_agent/service.py` adds `run_project_analysis()`
4. Add tests in market intel:
   - `tests/test_project_analysis_*.py`

## Cleanup

1. Remove duplicated Hub package and endpoints:
   - `services/project_analysis/*`
   - `api` / `bootstrap` entries for `/internal/capabilities/project-analysis/*`
   - docs/scripts/tests tied only to hub-local project-analysis runtime
2. Remove Dune from `collector_agent` contract path:
   - no `dune` in accepted `sources`
   - docs updated to point Dune ownership to `market_intel_agent`

## Verification

1. `pytest` for new `market_intel_agent/tests/test_project_analysis_*.py`
2. CLI smoke:
   - `python3 scripts/run_project_analysis.py AAVE`
3. Skill bootstrap check:
   - `./scripts/bootstrap_market_intel_stack.sh --check-only`
