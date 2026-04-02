# Collector Agent v1

Minimal external collector service for ResearchHub.

Location:
- `/root/research-agents/collector_agent`

Scope:
- lives outside ResearchHub
- sync HTTP pull only
- no direct writes into RH DB
- no queue/event bus
- no browser automation framework in v1
- `dune` works as read-only gap filler (after CoinGecko/DefiLlama diagnostics)

## Run

From `/root/research-agents/collector_agent`:

```bash
PYTHONPATH=/root/research-agents/collector_agent uvicorn collector_agent.http_app:app --host 127.0.0.1 --port 8091
```

Env vars:
- `COLLECTOR_SERVICE_TOKEN` — optional shared token for `X-Service-Token`
- `COLLECTOR_HTTP_TIMEOUT_SECONDS` — per-upstream request cap, default `10`
- `COINGECKO_BASE_URL` — default `https://api.coingecko.com/api/v3`
- `DEFILLAMA_BASE_URL` — default `https://api.llama.fi`
- `COLLECTOR_DUNE_API_KEY` — Dune API key for query execution
- `COLLECTOR_DUNE_BASE_URL` — default `https://api.dune.com/api/v1`
- `COLLECTOR_DUNE_QUERY_IDS` — JSON map of profile→query_id, e.g. `{"perp_dex":123,"lending":456,"blockchain":789,"rwa":1011,"default":111}`
- `COLLECTOR_DUNE_QUERY_TIMEOUT_SECONDS` — execution polling cap, default `25`
- `COLLECTOR_DUNE_POLL_INTERVAL_SECONDS` — status poll interval, default `2`

Auth behavior:
- if `COLLECTOR_SERVICE_TOKEN` is set, inbound `X-Service-Token` must match
- if `COLLECTOR_SERVICE_TOKEN` is empty, auth is disabled for local/dev and this is intentional for v1

## Endpoint

`POST /collect`

Request body:
- `target: { name, ticker?, coingecko_id? }`
- `sources: ["coingecko", "defillama", "dune"]`
- `criteria: { need_metrics, need_protocol, need_yields?, need_competitors? }`
- `strategy: "api_first_browser_second"`
- `deadline_sec: number`
- optional `period_days`

Response body:
- `status: ok | partial | error`
- `target`
- `collected_at`
- `source_results[]`
- optional `errors[]`

Notes:
- `items[]` are RH-compatible normalized items
- `partial` is returned when at least one source is usable and at least one source fails or times out
- `browser-second` stays in the contract, but browser fallback is not implemented in v1
- when `dune` is requested, service executes in order: non-dune sources first, then `dune` only for unresolved metric gaps
