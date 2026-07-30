"""API-key pooling for providers with tight spend-rate caps.

Why: this project's Anthropic account enforces a spend-RATE cap, not just a balance. Under sustained
benchmark load it returns

    400 invalid_request_error: "You have reached your specified API usage limits.
                                You will regain access on <date> at 00:00 UTC."

Despite naming a future date it recovers within minutes once load drops. Because `judge_anthropic`
is called for 4 of 5 entrants (leave-one-family-out only excludes it for the Anthropic entrant),
Anthropic is by far the hottest path in a run -- and when it trips, every affected record silently
loses a judge and lands as `judge_degraded`. Lowering concurrency helps but wastes wall-clock and
still trips under a long run.

This module lets several independently-funded keys share the load. On a cap/rate error a key is put
in cooldown and the call is retried on the next available key, so a run only degrades if EVERY key
is capped at once.

Configuration (most specific wins):
    ANTHROPIC_API_KEYS   comma/whitespace-separated list  <- preferred for pooling
    ANTHROPIC_API_KEY    single key (always included)

A single key is the degenerate case and behaves exactly as before, so nothing needs configuring for
the common path.
"""
from __future__ import annotations
import os, re, threading, time

# Errors meaning "this key is temporarily unusable, try another" (as opposed to a bad request that
# would fail identically on every key).
_KEY_EXHAUSTED = ("usage limits", "regain access", "rate limit", "rate_limit", "429",
                  "credit balance", "insufficient_quota", "quota")

_COOLDOWN_S = 120.0        # how long a tripped key sits out before we try it again


def _split(v: str) -> list[str]:
    return [p for p in re.split(r"[,\s]+", v.strip()) if p]


def anthropic_keys() -> list[str]:
    """All configured Anthropic keys, de-duplicated, order-stable (pooled list first)."""
    keys = _split(os.environ.get("ANTHROPIC_API_KEYS", ""))
    single = os.environ.get("ANTHROPIC_API_KEY", "").strip()
    if single:
        keys.append(single)
    seen, out = set(), []
    for k in keys:
        if k and k not in seen:
            seen.add(k); out.append(k)
    return out


class _Pool:
    """Round-robin key selection with per-key cooldown after a cap/rate error."""
    def __init__(self):
        self._lock = threading.Lock()
        self._cool: dict[str, float] = {}     # key -> epoch time when usable again
        self._i = 0

    def order(self, keys: list[str]) -> list[str]:
        """Keys to try, in preference order: not-cooling first (round-robin), then cooling ones
        soonest-available-first as a last resort (better to try than to drop the judge)."""
        now = time.time()
        with self._lock:
            self._i = (self._i + 1) % max(1, len(keys))
            rot = keys[self._i:] + keys[:self._i]
            ready = [k for k in rot if self._cool.get(k, 0.0) <= now]
            cooling = sorted((k for k in rot if self._cool.get(k, 0.0) > now),
                             key=lambda k: self._cool.get(k, 0.0))
        return ready + cooling

    def trip(self, key: str, seconds: float = _COOLDOWN_S) -> None:
        with self._lock:
            self._cool[key] = time.time() + seconds


_POOL = _Pool()


def call_anthropic(fn, what: str = "anthropic"):
    """Run `fn(api_key)` against the key pool.

    Tries each key once. A cap/rate/quota error puts that key in cooldown and moves to the next; any
    other error (bad request, auth, model-not-found) raises immediately, since retrying it on
    another key would just burn time. Raises the last cap error if every key is exhausted, which
    lets the caller's existing retry/backoff or judge-drop logic take over."""
    keys = anthropic_keys()
    if not keys:
        raise RuntimeError("no ANTHROPIC_API_KEY / ANTHROPIC_API_KEYS configured")
    last: Exception | None = None
    for key in _POOL.order(keys):
        try:
            return fn(key)
        except Exception as e:
            msg = str(e).lower()
            if not any(k in msg for k in _KEY_EXHAUSTED):
                raise                       # genuine error -- same on every key
            _POOL.trip(key)
            last = e
            if len(keys) > 1:
                print(f"  [keypool] {what}: key ...{key[-4:]} exhausted, trying next "
                      f"({len(keys)} configured)")
    raise last if last else RuntimeError("anthropic key pool: no key succeeded")
