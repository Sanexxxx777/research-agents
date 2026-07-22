# Security Policy

## Scope

These agents call third-party market-data APIs (CoinGecko, DeFiLlama, Dune)
and an internal Hub Research service over HTTP. Credentials (Dune API key,
Hub service token, etc.) are read from environment variables — see each
agent's config module for the exact variable names. Do not commit populated
`.env` files or hardcode credentials in source.

## Reporting a vulnerability

If you find a security issue, please open a GitHub issue or contact
[@Aleksandr_NFA](https://github.com/Sanexxxx777).

## Supported versions

Latest `main` only.
