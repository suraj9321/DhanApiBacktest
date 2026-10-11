---
tags: [reference, api]
---

# Dhan API — project notes

Project-specific notes on the [DhanHQ v2 API](https://dhanhq.co/docs/v2/). The full
vendor documentation is **not** vendored here — read it at the official site. This file
records only what matters for *this* pipeline: which endpoints we use and the quirks we
had to resolve empirically.

> A full local export of the vendor docs used to live here; it was removed from the public
> repo (vendor copyright + ~10k lines of noise). Regenerate your own copy from the source
> if you need offline reference.

## Endpoints this project uses (Data APIs only)

| Purpose | Endpoint |
|---------|----------|
| Expired weekly/monthly option chains, 1-min bars | **Historical Rolling Options Data** |
| Nifty / India VIX daily since inception | **Get Daily Historical Data** |
| Nifty / India VIX 1-min intraday (5y) | **Get Intraday Historical Data** |
| Expiry calendar | **Get Expiry List** |

Requires an active DhanHQ **Data APIs** subscription. Auth is via `DHAN_ACCESS_TOKEN`
and `DHAN_CLIENT_ID` (env only — see [`.env.example`](../.env.example); never commit the
token or put it in notes). Client, retry, and disk-cache behavior live in
`src/pipeline/dhan_client.py`.

## Ambiguities resolved by `scripts/pull_all.py --probe`

The probe makes ~4 tiny live calls before any full pull to pin down two things the docs
left unclear — both determine the shape of the full request grid:

1. **CE+PE in one call vs. two** — whether a single rolling-options request returns both
   option types or must be issued per `option_type`.
2. **Strike-offset semantics** — how the `ATM±N` offset grid maps to actual strikes
   (we pull **ATM±10**; far wings may hit quote gaps — see [[data-pipeline]]).

Run `--probe` first on any fresh setup and read its output before the full pull.

## Rate limits & resilience

- Calls are throttled in `dhan_client.py`; responses are cached to `data/raw/` keyed by
  request identity **before** parsing, so pulls are resumable and idempotent (interrupted
  runs continue; completed calls are never repeated).
- On throttling/transient errors the client retries with backoff.

See [[data-pipeline]] for the end-to-end ingestion design and partitioning rationale.
