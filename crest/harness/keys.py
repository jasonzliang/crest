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
# Per-KEY auth failures. Distinct from _KEY_EXHAUSTED because they are permanent for that key
# rather than transient, but identical in the action they require: drop this key, try the next.
_KEY_INVALID = ("invalid_api_key", "invalid x-api-key", "authentication_error", "authentication",
                "permission_error", "unauthorized", "401", "403")
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
        self._dead: set[str] = set()          # keys retired permanently (auth failures)
        self._i = 0

    def order(self, keys: list[str]) -> list[str]:
        """Keys to try, in preference order: not-cooling first (round-robin), then cooling ones
        soonest-available-first as a last resort (better to try than to drop the judge)."""
        now = time.time()
        with self._lock:
            self._i = (self._i + 1) % max(1, len(keys))
            rot = keys[self._i:] + keys[:self._i]
            rot = [k for k in rot if k not in self._dead] or rot   # never return an empty pool:
                            # if every key is retired, hand them all back so the caller sees the
                            # real provider error instead of an empty-list IndexError
            ready = [k for k in rot if self._cool.get(k, 0.0) <= now]
            cooling = sorted((k for k in rot if self._cool.get(k, 0.0) > now),
                             key=lambda k: self._cool.get(k, 0.0))
        return ready + cooling

    def retire(self, key: str) -> None:
        """Permanently remove a key for the rest of the process. Used for auth failures, which -- unlike
        rate limits and spend caps -- do not heal on their own, so cooling them just re-spends an
        attempt every cooldown."""
        with self._lock:
            self._dead.add(key)

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
            # A per-KEY auth failure (revoked, wrong project, disabled) is not "the same on every
            # key" -- it is the one case where failover is exactly right. Without these terms a
            # single revoked key raised immediately, was never tripped out of the pool, and its
            # message matched run_crest's _TERMINAL_ERR, so three rotations circuit-broke a
            # perfectly healthy entrant. Measured with 1 bad key of 3: 20 of 60 hard failures.
            invalid = any(k in msg for k in _KEY_INVALID)
            if not (invalid or any(k in msg for k in _KEY_EXHAUSTED)):
                raise                       # genuine error -- same on every key
            # An INVALID key is permanent for that key; an EXHAUSTED one is transient. Cooling both
            # for _COOLDOWN_S meant a revoked key re-entered the ready rotation every two minutes and
            # burned one attempt per call for the whole run, while the operator was told it was
            # "exhausted" and sent to check billing rather than key validity.
            _POOL.retire(key) if invalid else _POOL.trip(key)
            last = e
            if len(keys) > 1:
                print(f"  [keypool] {what}: key ...{key[-4:]} "
                      f"{'INVALID (retired for this run)' if invalid else 'exhausted'}, trying next "
                      f"({len(keys)} configured)")
    raise last if last else RuntimeError("anthropic key pool: no key succeeded")
