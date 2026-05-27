# Migration Changelog

## 2026-04-04

### Added in `market_intel_agent`
- Deterministic two-pass pipeline package:
  - `market_intel_agent/project_analysis/*`
- Local TTL cache:
  - `market_intel_agent/project_analysis/cache.py`
- Dune gap-fill support in second pass:
  - `project_analysis/sources.py`
  - `project_analysis/pipeline.py`
- Service integration:
  - `market_intel_agent/service.py` now exposes `run_project_analysis()`
  - `run()` includes `project_analysis` payload
- Bootstrap and run scripts:
  - `scripts/bootstrap_market_intel_stack.sh`
  - `scripts/run_project_analysis.py`
  - `scripts/run_project_analysis_matrix.py`
- Test suite:
  - `tests/test_project_analysis_*.py`
  - `pytest.ini`
- Docs:
  - `README.md`
  - `docs/metrics-agent-migration-plan.md`
  - free DefiLlama limit controls and retries:
    - `MARKET_INTEL_PA_DEFILLAMA_MAX_CALLS_PER_RUN`
    - `MARKET_INTEL_PA_DEFILLAMA_RETRY_MAX`
    - `MARKET_INTEL_PA_DEFILLAMA_RETRY_BACKOFF_MS`
  - source runtime updates:
    - per-run DefiLlama call budget guard
    - retry/backoff on `429/5xx`
    - CoinGecko retry/backoff on transient `429/5xx` and transport errors:
      - `MARKET_INTEL_PA_COINGECKO_RETRY_MAX`
      - `MARKET_INTEL_PA_COINGECKO_RETRY_BACKOFF_MS`
    - negative memoization for failed DefiLlama/CoinGecko fetches to prevent duplicate calls during short failure windows:
      - `MARKET_INTEL_PA_ERROR_CACHE_TTL_SEC`
    - budget exhaustion audit event (`defillama_budget_exhausted`)
    - first-pass skill alias normalization:
      - `defillama-openapi-skill` -> `protocol-deep-dive`
      - `defillama-api` -> `market-analysis`
    - real first-pass skills-command adapter:
      - `scripts/execute_first_pass_skill.py`
      - deterministic per-skill JSON output
      - local file cache to avoid duplicate DefiLlama calls across 3 skills
      - protocol resolution fallback via `/protocols` + `parentProtocol` matching
      - summary fallback attempts across related slugs with attempted-slugs audit trail
    - missing-field observability upgrades:
      - first-pass `_audit` is propagated into pipeline `fetch_audit`
      - `missing_fields.reason` now uses metric-specific unavailability reasons when available
      - source adapter emits metric-specific `metric_unavailable` audit events for required DefiLlama fields that remain null
      - first-pass runner emits synthetic `metric_unavailable` audit for covered metrics absent from skill output (`first_pass_skills output missing metric`)
    - source resolver robustness:
      - DefiLlama `/protocol/<slug>` HTTP `400` now treated as non-fatal missing candidate (continue fallback resolution)
      - DefiLlama `/protocol/<slug>` transport errors are now non-fatal in resolver path (graceful degradation instead of pipeline crash)
    - targeted perp fallback improvements:
      - `market-analysis` first-pass now emits explicit `metric_unavailable` reasons for missing perp fields (`volume`, `open_interest`, `markets_count`, `main_demand_kpi`, `retention`) with attempted slugs
      - DefiLlama source adapter now uses candidate-based slug attempts for `summary/dexs/*` and `summary/derivatives/*` (not single-slug only)
  - tests:
    - `tests/test_project_analysis_defillama_limits.py`

### Changed in `collector_agent`
- Removed Dune from accepted request contract:
  - `collector_agent/contracts.py`
- Removed Dune path from service orchestration:
  - `collector_agent/service.py`
- Removed Dune adapter from default adapters:
  - `collector_agent/sources.py`
- Removed Dune runtime settings:
  - `collector_agent/config.py`
- Updated docs/tests to match no-Dune collector scope:
  - `collector_agent/README.md`
  - `collector_agent/tests/test_collector_agent.py`

### Cleaned in Hub (`hub-research`)
- Removed hub-local `project_analysis` runtime wiring and endpoint references.
- Kept Hub as boundary/integration layer.
