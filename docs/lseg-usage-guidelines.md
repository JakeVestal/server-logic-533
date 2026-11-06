# LSEG Data Library for Python — Usage Guidelines for Robin

Distilled from the official Reference Guide and Maximum Usage Reference Guide.  
These limits apply to a single Workspace / Platform session and are aggregated across all applications sharing that session.

Last reviewed: 2026-11-06.

## Hard limits we must respect

| Limit | Value | Notes |
|-------|-------|-------|
| Requests per second | 5 | Aggregate across the session. Stay at ≤ 3–4 req/s. |
| Response volume per minute | 50 MB | Aggregate. |
| Requests per day | 10,000 | Resets at midnight local time. |
| Response volume per day | 5 GB | Resets at midnight local time. |
| Concurrent open requests | Platform-dependent | High load from others can cause 400/timeouts. |

## Per-request datapoint / row caps

A datapoint = one instrument × one field × one timestamp.

| Function | Approx. cap | Practical implication |
|----------|-------------|-----------------------|
| `get_data` (v1.1+) | No hard datapoint cap; ~300 s server timeout | Still chunk large universes or field sets. |
| `get_history` (interday: daily and above) | ~3,000 rows | ~11–12 years of daily bars per request. |
| `get_history` (intraday) | ~50,000 rows | ~120 trading days of 1-minute bars. |
| `news.get_headlines` | 15 months of history | — |
| `news.get_story` | 1 story per request | Must loop. |

If a request is too large the response is truncated (no error). Always verify you received what you asked for.

## Error handling

- **429 Too Many Requests** — pacing or daily limit hit. Use the retry-after metadata if present; otherwise back off.
- **503 Service Unavailable** — temporary. Retry with backoff.
- **400 Backend error** — platform overload (not necessarily our fault).
- **403** — entitlement / API proxy not allowed for the account.
- Daily limit exhaustion requires waiting until the next midnight.

Never silently swallow exceptions. Incomplete data is worse than a visible failure.

## Best practices for Robin

1. **Pace deliberately.** Target 3 requests per second maximum. A simple sleep or token-bucket is enough; do not rely on the library to throttle for us.
2. **Chunk everything.**  
   - Daily history: request ≤ 10 years (or fewer instruments) at a time.  
   - Option chains / large universes: break into batches of a few hundred instruments.  
   - Verify row counts against the requested window; if truncated, split and re-request.
3. **Cache aggressively.** Once a bar or fundamental is in Robin, do not re-fetch it. The whole point of the database is to take the load off LSEG so students are not hitting the API.
4. **Prefer Platform Session** for headless / server use. Desktop Session requires a running Workspace instance and is not appropriate for a long-lived container.
5. **Stay inside entitlements.** Only request fields and instruments the account is licensed for. Extra content needs an add-on.
6. **Monitor daily usage.** Check remaining request and volume quotas (see the linked “Check Usage Limits Remaining” article) before large seeds. Stop or defer when approaching 80 % of the daily cap.
7. **Schedule heavy work off-peak** when possible, but do not assume the platform is quieter; other users can still cause 400s.
8. **For true bulk / multi-million-row extracts** the Data Library is not the right tool. Use Tick History or another LSEG product designed for large-scale extraction and talk to the account team.

## What this means for the redesign

- Option-chain and multi-year equity seeds must be chunked and paced; a single giant request will be truncated or timed out.
- The daily 10 k request / 5 GB ceiling is the real constraint once we track more than a handful of underlyings plus their options. Local caching and incremental updates are mandatory.
- IBKR remains useful for live trading and contract identity, but the heavy historical load should move to LSEG under these rules.

Sources:  
- https://developers.lseg.com/en/api-catalog/lseg-data-platform/lseg-data-library-for-python/documentation/manuals-and-guides/ReferenceGuide  
- https://developers.lseg.com/en/article-catalog/article/the-data-library-for-python-maximum-usage-reference-guide
