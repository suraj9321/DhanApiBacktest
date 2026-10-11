"""HTTP client for the Dhan API: rate limiting, retries, and raw-response caching.

Design notes:
- Every successful response is written to disk as JSON *before* any parsing.
  The cache key is the request's semantic identity (endpoint + params), so
  re-running any pull skips completed calls — the pipeline is resumable and
  idempotent by construction.
- Rate limiting is a simple minimum-interval throttle (Data APIs allow 5 rps;
  we run at RATE_LIMIT_RPS). 429s and 5xxs retry with exponential backoff.
- Auth errors (401) abort immediately with a clear message — retrying is useless.
"""
from __future__ import annotations

import json
import time
from pathlib import Path
from typing import Any

import requests

from . import config


class DhanAPIError(RuntimeError):
    pass


class DhanClient:
    def __init__(self) -> None:
        self._session = requests.Session()
        self._session.headers.update(
            {
                "access-token": config.ACCESS_TOKEN,
                "client-id": config.CLIENT_ID,
                "Content-Type": "application/json",
                "Accept": "application/json",
            }
        )
        self._min_interval = 1.0 / config.RATE_LIMIT_RPS
        self._last_call = 0.0

    def _throttle(self) -> None:
        wait = self._min_interval - (time.monotonic() - self._last_call)
        if wait > 0:
            time.sleep(wait)
        self._last_call = time.monotonic()

    def post(self, endpoint: str, payload: dict[str, Any]) -> dict[str, Any]:
        """POST with throttle + retry. Returns parsed JSON body."""
        url = f"{config.API_BASE}{endpoint}"
        backoff = 2.0
        for attempt in range(1, config.MAX_RETRIES + 1):
            self._throttle()
            try:
                resp = self._session.post(
                    url, json=payload, timeout=config.REQUEST_TIMEOUT_S
                )
            except requests.RequestException as exc:
                if attempt == config.MAX_RETRIES:
                    raise DhanAPIError(f"network error on {endpoint}: {exc}") from exc
                time.sleep(backoff)
                backoff *= 2
                continue

            if resp.status_code == 200:
                return resp.json()
            if resp.status_code == 401:
                raise DhanAPIError(
                    "401 Unauthorized — access token invalid/expired, or the Data "
                    "APIs subscription is inactive for this endpoint."
                )
            if resp.status_code == 429 or resp.status_code >= 500:
                if attempt == config.MAX_RETRIES:
                    raise DhanAPIError(
                        f"{resp.status_code} from {endpoint} after "
                        f"{config.MAX_RETRIES} attempts: {resp.text[:300]}"
                    )
                time.sleep(backoff)
                backoff *= 2
                continue
            # Other 4xx: a bad request won't get better by retrying.
            raise DhanAPIError(
                f"{resp.status_code} from {endpoint}: {resp.text[:300]} "
                f"(payload: {json.dumps(payload)[:300]})"
            )
        raise DhanAPIError(f"unreachable retry exit for {endpoint}")

    def cached_post(
        self, cache_path: Path, endpoint: str, payload: dict[str, Any]
    ) -> tuple[dict[str, Any], bool]:
        """POST with disk cache. Returns (body, was_cached).

        The response is cached only if it parses as JSON and is not an error
        body, so failed calls are retried on the next run rather than poisoning
        the cache.
        """
        if cache_path.exists():
            with cache_path.open() as f:
                return json.load(f), True

        body = self.post(endpoint, payload)
        if isinstance(body, dict) and body.get("errorCode"):
            raise DhanAPIError(f"API error from {endpoint}: {body}")

        cache_path.parent.mkdir(parents=True, exist_ok=True)
        tmp = cache_path.with_suffix(".tmp")
        with tmp.open("w") as f:
            json.dump(body, f)
        tmp.rename(cache_path)  # atomic: a crash never leaves a half-written cache
        return body, False
