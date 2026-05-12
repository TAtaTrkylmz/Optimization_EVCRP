"""
PlannerLogger — Timestamped console logger for optimization analytics.

Provides structured, timestamped output for all pipeline stages.
Tracks operation durations with automatic start/finish pairing.

Usage:
    from planner.setup.logger import log

    log.section("GEOCODING")
    log.info("Looking up coordinates...")
    log.step("Izmir, Turkey -> (38.4, 27.1)")
    log.metric("Stations loaded", 1482)
    log.warn("Low battery handoff!")

    with log.timed("Building matrices"):
        ...  # logs start & finish with duration
"""
from __future__ import annotations

import time
from contextlib import contextmanager
from datetime import datetime


class PlannerLogger:
    """Timestamped console logger for optimization analytics.

    All output goes to stdout — nothing is written to disk.
    """

    def __init__(self) -> None:
        self._journey_start: float | None = None

    # ── Core formatters ──

    def _ts(self) -> str:
        """Wall-clock timestamp [HH:MM:SS]."""
        return datetime.now().strftime("[%H:%M:%S]")

    def _elapsed(self) -> str:
        """Elapsed time since journey start, if available."""
        if self._journey_start is None:
            return ""
        dt = time.perf_counter() - self._journey_start
        m, s = divmod(int(dt), 60)
        return f" (dt {m:02d}:{s:02d})"

    # ── Public API ──

    def mark_journey_start(self) -> None:
        """Call once at the beginning of plan_journey()."""
        self._journey_start = time.perf_counter()

    def section(self, title: str) -> None:
        """Print a prominent section header with timestamp."""
        line = f"{'=' * 60}"
        print(f"\n{self._ts()}{self._elapsed()} {line}")
        print(f"{self._ts()}{self._elapsed()}   {title}")
        print(f"{self._ts()}{self._elapsed()} {line}")

    def info(self, msg: str) -> None:
        """General information line."""
        print(f"{self._ts()}{self._elapsed()} {msg}")

    def step(self, msg: str) -> None:
        """Indented sub-step."""
        print(f"{self._ts()}{self._elapsed()}    -> {msg}")

    def metric(self, key: str, value) -> None:
        """Key-value metric line."""
        print(f"{self._ts()}{self._elapsed()}    {key}: {value}")

    def warn(self, msg: str) -> None:
        """Warning line."""
        print(f"{self._ts()}{self._elapsed()}  [!] {msg}")

    def banner(self, lines: list[str], char: str = "=", width: int = 60) -> None:
        """Print a multi-line banner block."""
        border = char * width
        print(f"\n{self._ts()}{self._elapsed()} {border}")
        for line in lines:
            print(f"{self._ts()}{self._elapsed()}   {line}")
        print(f"{self._ts()}{self._elapsed()} {border}")

    @contextmanager
    def timed(self, label: str):
        """Context manager that logs start and finish with duration.

        Usage:
            with log.timed("Building matrices"):
                ...  # heavy computation
        Prints:
            [HH:MM:SS] > Building matrices...
            [HH:MM:SS] OK Building matrices [1.23s]
        """
        print(f"{self._ts()}{self._elapsed()} > {label}...")
        t0 = time.perf_counter()
        try:
            yield
        finally:
            dt = time.perf_counter() - t0
            print(f"{self._ts()}{self._elapsed()} OK {label} [{dt:.2f}s]")


# ── Module-level singleton ──
log = PlannerLogger()
