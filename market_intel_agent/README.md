# Market Intel Agent

External metrics and market-intel agent for Research Hub.

## Ownership (single source of truth)

- `market_intel_agent` owns metric collection from:
  - CoinGecko
  - DefiLlama
  - Dune (gap-fill in second pass)
- `collector_agent` is no longer a Dune path.

## Deterministic analysis pipeline

Implemented in:
- `market_intel_agent/project_analysis/`

Flow:
1. Entity resolution
2. Sector routing (`lending`, `spot_dex`, `perp_dex`)
3. DefiLlama first-pass skills (`protocol-deep-dive`, `market-analysis`, `risk-assessment`)
4. Normalized internal state object
5. Second-pass enrichment for missing fields that are outside first-pass skill coverage
6. Local ratio computation
7. Compact peer comparison
8. Structured output + human report

Current rollout policy:
- Dune gap-fill is disabled by default (`MARKET_INTEL_PA_DUNE_GAP_FILL_ENABLED=0`)
- First complete DefiLlama-first pipeline, then enable Dune later if required
- DefiLlama free API rate limits are handled with a request interval (`MARKET_INTEL_PA_DEFILLAMA_MIN_INTERVAL_MS`, default `250`)
- DefiLlama per-run call budget and retries are configurable (`MARKET_INTEL_PA_DEFILLAMA_MAX_CALLS_PER_RUN`, `MARKET_INTEL_PA_DEFILLAMA_RETRY_MAX`, `MARKET_INTEL_PA_DEFILLAMA_RETRY_BACKOFF_MS`)
- CoinGecko retries for transient `429/5xx` and transport failures are configurable (`MARKET_INTEL_PA_COINGECKO_RETRY_MAX`, `MARKET_INTEL_PA_COINGECKO_RETRY_BACKOFF_MS`)
- Failed fetches are negatively memoized for a short TTL to avoid duplicate calls during API flaps (`MARKET_INTEL_PA_ERROR_CACHE_TTL_SEC`)
- For some perp protocols, DefiLlama `summary/derivatives/*` can be unavailable/paywalled on free plan; pipeline records explicit missing reasons with attempted slugs.

## Bootstrap skills

```bash
cd /root/research-agents/market_intel_agent
./scripts/bootstrap_market_intel_stack.sh
```

By default bootstrap targets OpenClaw agent `market-intel-agent`.
You can override with:

```bash
MARKET_INTEL_OPENCLAW_AGENT_ID=market-intel-agent ./scripts/bootstrap_market_intel_stack.sh
```

If you need temporary default-agent switch during install and automatic restore:

```bash
MARKET_INTEL_SWITCH_DEFAULT_AGENT=1 MARKET_INTEL_RESTORE_DEFAULT_AGENT=1 ./scripts/bootstrap_market_intel_stack.sh
```

Bootstrap tries exact requested skill slugs first:
- `protocol-deep-dive`
- `market-analysis`
- `risk-assessment`

If a slug is unavailable in ClawHub, it falls back to nearest available alternatives.
Current practical mapping:
- `protocol-deep-dive` -> `defillama-openapi-skill`
- `market-analysis` -> `defillama-api`
- `risk-assessment` -> `risk-assessment`

Note: `defillama-api` requires `uv` binary in runtime.

Check-only:

```bash
./scripts/bootstrap_market_intel_stack.sh --check-only
```

## Run pipeline

```bash
cd /root/research-agents/market_intel_agent
python3 scripts/run_project_analysis.py AAVE
```

Matrix smoke check (writes per-asset JSON + `summary.json`):

```bash
cd /root/research-agents/market_intel_agent
python3 scripts/run_project_analysis_matrix.py --assets "AAVE,UNI,DYDX" --out-dir /tmp/mi_live_matrix
```

## Enable real first-pass skill command mode

```bash
export MARKET_INTEL_DEFILLAMA_SKILLS="defillama-openapi-skill,defillama-api,risk-assessment"
export MARKET_INTEL_SKILLS_COMMAND_TEMPLATE='python3 /root/research-agents/market_intel_agent/scripts/execute_first_pass_skill.py --skill "{skill}" --canonical-skill "{canonical_skill}" --asset "{asset_input}" --sector "{sector}" --defillama-slug "{defillama_slug}" --coingecko-id "{coingecko_id}" --symbol "{symbol}"'
```

Notes:
- `execute_first_pass_skill.py` is deterministic and returns structured JSON per skill.
- It prefers installed `defillama-api` skill runner (`uv run .../defillama-api/src/run.py`) and falls back to `api.llama.fi` endpoints.
- It caches first-pass fetches in `/tmp/market-intel-first-pass` to avoid duplicate calls across the 3 skill invocations.
- It resolves related protocol slugs via `/protocols` + `parentProtocol` and tries summary endpoints across related candidates before marking metric unavailable.

## Env (key ones)

- `MARKET_INTEL_DEFILLAMA_SKILLS`
- Supports canonical names (`protocol-deep-dive,market-analysis,risk-assessment`)
- Also supports installed aliases (`defillama-openapi-skill,defillama-api,risk-assessment`)
- `MARKET_INTEL_SKILLS_COMMAND_TEMPLATE`
- Command template placeholders include `{skill}` (configured slug) and `{canonical_skill}` (normalized internal skill id)
- `MARKET_INTEL_PA_DEFILLAMA_MIN_INTERVAL_MS`
- `MARKET_INTEL_PA_DEFILLAMA_MAX_CALLS_PER_RUN`
- `MARKET_INTEL_PA_DEFILLAMA_RETRY_MAX`
- `MARKET_INTEL_PA_DEFILLAMA_RETRY_BACKOFF_MS`
- `MARKET_INTEL_PA_COINGECKO_RETRY_MAX`
- `MARKET_INTEL_PA_COINGECKO_RETRY_BACKOFF_MS`
- `MARKET_INTEL_PA_ERROR_CACHE_TTL_SEC`
- `MARKET_INTEL_PA_DEFILLAMA_SUMMARY_MAX_CANDIDATES`
- `MARKET_INTEL_PA_DEFILLAMA_PROTOCOL_ALIASES` (JSON map for deterministic token->protocol mapping)
- `MARKET_INTEL_PA_DUNE_GAP_FILL_ENABLED` (keep `0` for current phase)
- `MARKET_INTEL_DUNE_API_KEY`
- `MARKET_INTEL_DUNE_QUERY_IDS` (JSON map, e.g. `{"lending":123,"spot_dex":456,"perp_dex":789,"default":111}`)
