"""Concurrency tests for the /brief guards — the locking only matters under threads.

FastAPI runs sync routes on a threadpool, so RateLimiter.allow() and
ConcurrencyLimiter.slot() race in production; test_api.py only ever drives them
single-threaded. These tests hammer them from real threads and assert the
invariants the guards exist to hold (never over-admit), which a dropped lock or
non-atomic check-then-append would break.
"""

import threading
from concurrent.futures import ThreadPoolExecutor
from contextlib import ExitStack, suppress
from types import SimpleNamespace
from typing import Any

import pytest

from argus.api.limits import ConcurrencyLimiter, RateLimiter, SlotUnavailable


def _request(host: str) -> Any:
    return SimpleNamespace(headers={}, client=SimpleNamespace(host=host))


def test_rate_limiter_never_over_admits_under_threads() -> None:
    limiter = RateLimiter(max_requests=10, window_seconds=60.0, trust_forwarded=False)
    request = _request("10.0.0.1")
    with ThreadPoolExecutor(max_workers=16) as pool:
        results = list(pool.map(lambda _: limiter.allow(request), range(200)))
    assert sum(results) == 10  # exactly the budget, no lost-update over-admission


def test_rate_limiter_keys_clients_independently_under_threads() -> None:
    limiter = RateLimiter(max_requests=5, window_seconds=60.0, trust_forwarded=False)
    hosts = [f"10.0.0.{i}" for i in range(8)]
    with ThreadPoolExecutor(max_workers=16) as pool:
        results = list(pool.map(lambda i: limiter.allow(_request(hosts[i % 8])), range(160)))
    assert sum(results) == 5 * 8  # each client gets its own full budget


def test_concurrency_limiter_rejects_only_while_full() -> None:
    limiter = ConcurrencyLimiter(limit=3, acquire_timeout=0.05)
    with ExitStack() as stack:
        for _ in range(3):
            stack.enter_context(limiter.slot())
        with pytest.raises(SlotUnavailable), limiter.slot():  # full → 503 path, not a hang
            pass
    with limiter.slot():  # all slots released → admits again
        pass


def test_concurrency_limiter_caps_simultaneous_slots_under_threads() -> None:
    limiter = ConcurrencyLimiter(limit=3, acquire_timeout=1.0)
    active = 0
    peak = 0
    lock = threading.Lock()
    full = threading.Barrier(3, timeout=5)  # holds each cohort inside until 3 coincide

    def work(_: int) -> None:
        nonlocal active, peak
        # SlotUnavailable = timed out behind a straggler cohort; BrokenBarrierError = a
        # final cohort of <3 timed out waiting for peers. Neither affects the invariant.
        with suppress(SlotUnavailable), limiter.slot():
            with lock:
                active += 1
                peak = max(peak, active)
            with suppress(threading.BrokenBarrierError):
                full.wait()
            with lock:
                active -= 1

    with ThreadPoolExecutor(max_workers=12) as pool:
        list(pool.map(work, range(12)))

    assert peak == 3  # 3 provably ran at once, and the cap was never exceeded
