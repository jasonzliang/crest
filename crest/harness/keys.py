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

# Both tuples mean "this key specifically failed, try another" -- as opposed to a bad request that
# would fail identically on every key. They are kept separate because they take DIFFERENT actions in
# `call_anthropic`: an INVALID key is permanent for that key and is retired, an EXHAUSTED one is
# transient and is only cooled.
_KEY_INVALID = ("invalid_api_key", "invalid x-api-key", "authentication_error", "authentication",
                "permission_error", "unauthorized", "401", "403")
_KEY_EXHAUSTED = ("usage limits", "regain access", "rate limit", "rate_limit", "429",
                  "credit balance", "insufficient_quota", "quota")

_COOLDOWN_S = 120.0        # how long a tripped key sits out before we try it again

# PROVIDER-WIDE cooldown, distinct from the per-key one above, and the thing that was missing.
# A spend-RATE cap is a property of the ACCOUNT under AGGREGATE load, not of one key or one call, so
# per-call backoff cannot clear it: while one task sleeps 5s, the other N-1 concurrent tasks keep
# hammering the same account, the cap stays tripped, and every task exhausts its retries and dies.
# That is exactly what happened in run 2026-07-31T180746Z -- 3 claude_shallow tasks lost after
# 5s/10s/20s of backoff each, and judge_anthropic dropped from 11 of 31 records -- while _TRANSIENT
# already listed "usage limits" and _retry was working as designed. The retries were fine; nothing
# SHED LOAD. This gate makes every thread wait out one shared window, which is the only thing that
# actually lets a rate cap recover.
# 90s, not the per-key 120s: keys.py's own docstring records that this cap "recovers within minutes
# once load drops", and 90s is long enough to shed a burst without stalling a run that merely
# clipped the limit once. It is a FLOOR on waiting, not a promise -- if the cap is still up, the next
# error re-arms it.
_PROVIDER_COOLDOWN_S = 90.0
_MAX_GATE_WAIT_S = 300.0   # never block a single call longer than this; past it, let the real
                           # provider error surface so the circuit breaker can act on it


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
        self._provider_until = 0.0            # epoch time when ANY Anthropic call may proceed
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

    # ---- provider-wide gate ----
    def trip_provider(self, seconds: float = _PROVIDER_COOLDOWN_S) -> None:
        """Pause ALL Anthropic calls, every thread, for `seconds`. Extends but never shortens an
        existing window, so a second trip during a cooldown cannot accidentally release it early."""
        with self._lock:
            self._provider_until = max(getattr(self, "_provider_until", 0.0), time.time() + seconds)

    def wait_for_provider(self, what: str) -> None:
        """Block until the provider-wide window expires. Called BEFORE spending an attempt, so a
        capped account costs one sleep rather than one failed paid call per task."""
        while True:
            with self._lock:
                until = getattr(self, "_provider_until", 0.0)
            remaining = until - time.time()
            if remaining <= 0.5:      # 0.5 not 0: a sub-second remainder is not worth a log line,
                return                # and printing "waiting 0s" made the gate look broken
            nap = min(remaining, _MAX_GATE_WAIT_S)
            print(f"  [keypool] {what}: Anthropic provider-wide cooldown, waiting {nap:.0f}s "
                  f"(a spend-RATE cap only clears when aggregate load drops)")
            time.sleep(nap)
            if remaining > _MAX_GATE_WAIT_S:
                return          # waited the cap; let the real error surface for the circuit breaker


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
    # Wait out any provider-wide window BEFORE spending an attempt. Checking here rather than after a
    # failure is the point: a capped account then costs one sleep per task instead of one failed --
    # but still billed and still retried -- call per task.
    _POOL.wait_for_provider(what)
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
    # Arm the provider-wide gate ONLY once every key has failed, and only for cap-class errors.
    # Arming it inside the per-key loop was wrong as soon as more than one key exists: keys can sit
    # on DIFFERENT accounts with different limits, so one capped key would repeatedly stall the
    # healthy ones for 90s apiece -- turning a working pool into the single-key case it exists to
    # avoid. Measured on this machine: of 3 keys, 1 was capped until 00:00 UTC and 2 were fine.
    # "Every key is capped" IS the account-level condition worth pausing all threads for; "one key
    # is capped" is what the per-key cooldown in the loop above already handles.
    if last is not None and any(k in str(last).lower() for k in _KEY_EXHAUSTED):
        _POOL.trip_provider()
    raise last if last else RuntimeError("anthropic key pool: no key succeeded")
