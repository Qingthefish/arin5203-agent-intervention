"""Public API for the Agent Memory Crash Test research toolkit."""

from platform_agent_eval.memory_crash_test import (
    CONDITIONS,
    MEMORY_CRASH_TEST_VERSION,
    PROOF_SOURCES,
    CrashCase,
    CrashEvent,
    CrashSuite,
    StrategySpec,
    load_crash_suite,
    run_crash_suite,
    select_event_ids,
    visible_event_ids,
    write_json_report,
)

__version__ = "0.1.0"

__all__ = [
    "CONDITIONS",
    "MEMORY_CRASH_TEST_VERSION",
    "PROOF_SOURCES",
    "CrashCase",
    "CrashEvent",
    "CrashSuite",
    "StrategySpec",
    "load_crash_suite",
    "run_crash_suite",
    "select_event_ids",
    "visible_event_ids",
    "write_json_report",
]
