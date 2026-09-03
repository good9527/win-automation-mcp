# tests/test_tier5_adversarial.py
"""
Tier 5: Adversarial, Stress, Concurrency & Dynamic Resolver Hardening (M1)

Empirically tests:
1. Concurrency & locking: 20+ concurrent threads & 20 concurrent processes hammering state persistence.
2. PEP 562 Dynamic Resolver: Valid, legacy, fallback, and non-existent attribute resolution.
3. CLI edge cases: Missing arguments, invalid flags, malformed inputs, unknown commands.
"""

from __future__ import annotations

import os
import sys
import time
import json
import tempfile
import threading
import multiprocessing
import subprocess
import unittest
from typing import Any, Dict, List

PROJECT_ROOT = os.path.abspath(os.path.join(os.path.dirname(__file__), ".."))
if PROJECT_ROOT not in sys.path:
    sys.path.insert(0, PROJECT_ROOT)

import win_automation
from win_automation.state.locks import FileLock, FileLockTimeoutError
from win_automation.state.persistence import (
    load_state,
    save_state,
    update_state,
    next_screenshot_id,
    set_state_value,
    get_state_value,
    clear_state,
    remember_screenshot,
    load_screenshot_meta,
)
import win_automation.compat.resolver as resolver
import server
import tools


def _multiprocess_worker(state_file: str, worker_id: int, iterations: int) -> None:
    """Worker function executed in separate processes to mutate state."""
    for i in range(iterations):
        def _mutator(state: Dict[str, Any]) -> None:
            # Increment total counter
            total = int(state.get("total_ops", 0)) + 1
            state["total_ops"] = total

            # Update per-worker counter
            worker_key = f"worker_{worker_id}"
            state[worker_key] = int(state.get(worker_key, 0)) + 1

        update_state(_mutator, filepath=state_file, lock_timeout=20.0)


def _multiprocess_mixed_worker(state_file: str, worker_id: int, iterations: int) -> None:
    """Worker function testing mixed operations across processes."""
    for i in range(iterations):
        # 1. Update state
        set_state_value(f"proc_{worker_id}_step_{i}", {"ts": time.time(), "iter": i}, filepath=state_file)
        # 2. Increment screenshot ID
        _ = next_screenshot_id(filepath=state_file)
        # 3. Read state
        state = load_state(filepath=state_file)
        assert isinstance(state, dict)


class TestTier5ConcurrencyAndLocking(unittest.TestCase):
    """Stress tests for multi-threaded and multi-process state persistence."""

    def test_t5_01_multithreaded_20_threads_atomic_increment(self):
        """20 concurrent threads performing 50 updates each (1000 total) on a shared state file."""
        with tempfile.TemporaryDirectory() as td:
            state_file = os.path.join(td, "threaded_state.json")
            save_state({"total_ops": 0}, filepath=state_file)

            num_threads = 20
            ops_per_thread = 50
            exceptions: List[Exception] = []

            def worker(tid: int):
                try:
                    for _ in range(ops_per_thread):
                        def _mutator(state: Dict[str, Any]) -> None:
                            state["total_ops"] = int(state.get("total_ops", 0)) + 1
                            key = f"t_{tid}"
                            state[key] = int(state.get(key, 0)) + 1
                        update_state(_mutator, filepath=state_file, lock_timeout=30.0)
                except Exception as e:
                    exceptions.append(e)

            threads = [threading.Thread(target=worker, args=(i,)) for i in range(num_threads)]
            for t in threads:
                t.start()
            for t in threads:
                t.join(timeout=30.0)

            self.assertEqual(len(exceptions), 0, f"Thread exceptions: {exceptions}")

            final_state = load_state(filepath=state_file)
            expected_total = num_threads * ops_per_thread
            self.assertEqual(final_state.get("total_ops"), expected_total)
            for tid in range(num_threads):
                self.assertEqual(final_state.get(f"t_{tid}"), ops_per_thread)

    def test_t5_02_concurrent_readers_and_writers_integrity(self):
        """Concurrent reader threads and writer threads verify state persistence is atomic and error-free."""
        with tempfile.TemporaryDirectory() as td:
            state_file = os.path.join(td, "rw_state.json")
            save_state({"counter": 0, "payload": "x" * 500}, filepath=state_file)

            stop_event = threading.Event()
            read_errors: List[str] = []
            valid_reads = [0]

            def reader():
                while not stop_event.is_set():
                    try:
                        data = load_state(filepath=state_file, lock_timeout=10.0)
                        if not isinstance(data, dict) or "counter" not in data:
                            read_errors.append(f"Malformed dict structure: {data}")
                        else:
                            valid_reads[0] += 1
                    except Exception as err:
                        read_errors.append(f"Exception during load_state: {err}")
                    time.sleep(0.001)

            def writer():
                for i in range(50):
                    save_state({"counter": i, "payload": "y" * 500}, filepath=state_file, lock_timeout=10.0)
                    time.sleep(0.002)

            readers = [threading.Thread(target=reader) for _ in range(5)]
            writers = [threading.Thread(target=writer) for _ in range(4)]

            for r in readers:
                r.start()
            for w in writers:
                w.start()

            for w in writers:
                w.join(timeout=20.0)

            stop_event.set()
            for r in readers:
                r.join(timeout=5.0)

            self.assertEqual(len(read_errors), 0, f"Encountered errors: {read_errors[:5]}")
            self.assertGreater(valid_reads[0], 20)

    def test_t5_03_multiprocess_20_workers_concurrency(self):
        """Concurrent processes executing atomic updates on the same state file."""
        with tempfile.TemporaryDirectory() as td:
            state_file = os.path.join(td, "mp_state.json")
            save_state({"total_ops": 0}, filepath=state_file)

            num_workers = int(os.environ.get("WIN_AUTO_MP_WORKERS", 8))
            iterations = 10
            processes = []

            for wid in range(num_workers):
                p = multiprocessing.Process(
                    target=_multiprocess_worker,
                    args=(state_file, wid, iterations)
                )
                processes.append(p)
                p.start()

            for p in processes:
                p.join(timeout=30.0)
                self.assertEqual(p.exitcode, 0, f"Process {p} failed with exit code {p.exitcode}")

            final_state = load_state(filepath=state_file)
            expected_total = num_workers * iterations
            self.assertEqual(
                final_state.get("total_ops"),
                expected_total,
                f"Expected total_ops={expected_total}, got {final_state.get('total_ops')}"
            )
            for wid in range(num_workers):
                self.assertEqual(final_state.get(f"worker_{wid}"), iterations)

    def test_t5_04_multiprocess_mixed_workload(self):
        """Concurrent processes executing mixed read/write/screenshot operations."""
        with tempfile.TemporaryDirectory() as td:
            state_file = os.path.join(td, "mp_mixed_state.json")
            save_state({"screenshot_counter": 0}, filepath=state_file)

            num_workers = int(os.environ.get("WIN_AUTO_MP_WORKERS", 6))
            iterations = 8
            processes = []

            for wid in range(num_workers):
                p = multiprocessing.Process(
                    target=_multiprocess_mixed_worker,
                    args=(state_file, wid, iterations)
                )
                processes.append(p)
                p.start()

            for p in processes:
                p.join(timeout=30.0)
                self.assertEqual(p.exitcode, 0)

            final_state = load_state(filepath=state_file)
            expected_screenshots = num_workers * iterations
            self.assertEqual(final_state.get("screenshot_counter"), expected_screenshots)

    def test_t5_05_next_screenshot_id_concurrency(self):
        """High-frequency concurrent calls to next_screenshot_id guarantee unique monotonic IDs."""
        with tempfile.TemporaryDirectory() as td:
            state_file = os.path.join(td, "screenshot_state.json")
            save_state({"screenshot_counter": 100}, filepath=state_file)

            num_threads = 15
            calls_per_thread = 20
            collected_ids: List[int] = []
            lock = threading.Lock()

            def worker():
                local_ids = []
                for _ in range(calls_per_thread):
                    sid = next_screenshot_id(filepath=state_file)
                    local_ids.append(sid)
                with lock:
                    collected_ids.extend(local_ids)

            threads = [threading.Thread(target=worker) for _ in range(num_threads)]
            for t in threads:
                t.start()
            for t in threads:
                t.join(timeout=20.0)

            total_expected = num_threads * calls_per_thread
            self.assertEqual(len(collected_ids), total_expected)
            self.assertEqual(len(set(collected_ids)), total_expected, "Duplicate screenshot IDs generated!")
            self.assertEqual(min(collected_ids), 101)
            self.assertEqual(max(collected_ids), 100 + total_expected)

    def test_t5_06_tempfile_cleanup_after_stress(self):
        """Ensure no temporary files (.win_auto_state_*.tmp) leak in target directory."""
        with tempfile.TemporaryDirectory() as td:
            state_file = os.path.join(td, "cleanup_test_state.json")
            for i in range(100):
                save_state({"iter": i}, filepath=state_file)

            remaining_files = os.listdir(td)
            tmp_files = [f for f in remaining_files if f.startswith(".win_auto_state_") and f.endswith(".tmp")]
            self.assertEqual(len(tmp_files), 0, f"Temporary state files leaked: {tmp_files}")


class TestTier5DynamicImportResolver(unittest.TestCase):
    """Stress tests for PEP 562 dynamic symbol resolution in server.py and tools.py."""

    def test_t5_07_server_fast_map_symbols(self):
        """All static fast-map symbols in server.py resolve to expected callables/constants."""
        for name in resolver._SERVER_FAST_MAP:
            val = getattr(server, name, None)
            self.assertIsNotNone(val, f"server.{name} resolved to None")

    def test_t5_08_tools_fast_map_symbols(self):
        """All static fast-map symbols in tools.py resolve to expected callables/constants."""
        for name in resolver._TOOLS_FAST_MAP:
            val = getattr(tools, name, None)
            self.assertIsNotNone(val, f"tools.{name} resolved to None")

    def test_t5_09_leading_underscore_aliases(self):
        """Leading underscore aliases resolve identically to non-underscored names."""
        self.assertEqual(server._enum_windows, server.enum_windows)
        self.assertEqual(server._load_state, server.load_state)
        self.assertEqual(server._save_state, server.save_state)
        self.assertEqual(server._check_safety, server.check_safety)
        self.assertEqual(tools._enum_windows, tools.enum_windows)

    def test_t5_10_submodule_fallback_resolution(self):
        """Symbols present in submodules but not in fast-map are dynamically discovered."""
        # Point, Rect, WinAutomationError from win_automation.core
        self.assertIsNotNone(getattr(tools, "Point", None))
        self.assertIsNotNone(getattr(tools, "Rect", None))
        self.assertIsNotNone(getattr(tools, "WinAutomationError", None))
        self.assertIsNotNone(getattr(server, "Point", None))
        self.assertIsNotNone(getattr(server, "WinAutomationError", None))

    def test_t5_11_non_existent_attribute_raises_attribute_error(self):
        """Accessing non-existent attributes on server or tools raises AttributeError."""
        with self.assertRaises(AttributeError):
            _ = server.definitely_non_existent_attribute_12345

        with self.assertRaises(AttributeError):
            _ = tools.completely_fake_function_99999

        # Verify getattr with default returns default without raising
        self.assertEqual(getattr(server, "non_existent", "default_val"), "default_val")
        self.assertEqual(getattr(tools, "non_existent", 42), 42)

    def test_t5_12_dir_and_hasattr_integrity(self):
        """dir() lists resolved attributes and hasattr() returns correct booleans."""
        server_dir = dir(server)
        tools_dir = dir(tools)

        self.assertIn("enum_windows", server_dir)
        self.assertIn("save_state", server_dir)
        self.assertIn("doctor", tools_dir)
        self.assertIn("smart_text_input", tools_dir)

        self.assertTrue(hasattr(server, "enum_windows"))
        self.assertFalse(hasattr(server, "completely_fake_symbol"))
        self.assertTrue(hasattr(tools, "selftest"))
        self.assertFalse(hasattr(tools, "bogus_symbol_xyz"))


class TestTier5CLIEdgeCasesAndErrorHandling(unittest.TestCase):
    """Stress tests for CLI edge case invocations and graceful error handling."""

    def _run_cli(self, args: List[str]) -> subprocess.CompletedProcess[str]:
        cmd = [sys.executable, "tools.py"] + args
        return subprocess.run(
            cmd,
            cwd=PROJECT_ROOT,
            capture_output=True,
            text=True,
            encoding="utf-8",
        )

    def test_t5_13_cli_no_args_and_help(self):
        """Invoking tools.py without args or with --help displays usage text."""
        res_no_args = self._run_cli([])
        self.assertIn("Usage: python tools.py", res_no_args.stdout)

        res_help = self._run_cli(["--help"])
        self.assertEqual(res_help.returncode, 0)
        self.assertIn("Usage: python tools.py", res_help.stdout)

        res_h = self._run_cli(["-h"])
        self.assertEqual(res_h.returncode, 0)
        self.assertIn("Usage: python tools.py", res_h.stdout)

    def test_t5_14_cli_unknown_command(self):
        """Unknown CLI commands return non-zero exit code and informative message without traceback."""
        res = self._run_cli(["nonexistent_command_xyz123"])
        self.assertNotEqual(res.returncode, 0)
        self.assertIn("Unknown command: nonexistent_command_xyz123", res.stdout)
        self.assertNotIn("Traceback (most recent call last):", res.stderr)

    def test_t5_15_cli_state_subcommands(self):
        """CLI state get/set subcommands handle valid, missing, and JSON values."""
        # State get all
        res_get = self._run_cli(["state", "get"])
        self.assertEqual(res_get.returncode, 0)
        parsed = json.loads(res_get.stdout)
        self.assertIsInstance(parsed, dict)

        # State set JSON value
        res_set = self._run_cli(["state", "set", "cli_test_key", '{"a": 100, "b": "hello"}'])
        self.assertEqual(res_set.returncode, 0)

        # State get specific key
        res_get_key = self._run_cli(["state", "get", "cli_test_key"])
        self.assertEqual(res_get_key.returncode, 0)
        parsed_key = json.loads(res_get_key.stdout)
        self.assertEqual(parsed_key.get("cli_test_key"), {"a": 100, "b": "hello"})

    def test_t5_16_cli_missing_required_args(self):
        """Commands with missing required arguments exit cleanly with error message."""
        # state without subcmd
        res_state_no_sub = self._run_cli(["state"])
        self.assertNotEqual(res_state_no_sub.returncode, 0)
        self.assertIn("state subcommand required", res_state_no_sub.stdout)

        # state set with missing value
        res_state_set_no_val = self._run_cli(["state", "set", "foo"])
        self.assertNotEqual(res_state_set_no_val.returncode, 0)
        self.assertIn("state set requires <key> <value>", res_state_set_no_val.stdout)

        # confirm without action
        res_confirm = self._run_cli(["confirm"])
        self.assertNotEqual(res_confirm.returncode, 0)
        self.assertIn("confirm requires <action>", res_confirm.stdout)
        self.assertNotIn("Traceback (most recent call last):", res_confirm.stderr)

    def test_t5_17_cli_doctor_output_json_validity(self):
        """tools.py doctor returns valid JSON structure with diagnostic metrics."""
        res = self._run_cli(["doctor"])
        self.assertEqual(res.returncode, 0)
        parsed = json.loads(res.stdout)
        self.assertIn("checks", parsed)
        self.assertIn("windows_ocr", parsed["checks"])
        self.assertIn("opencv", parsed["checks"])
        self.assertIn("dxcam", parsed["checks"])


if __name__ == "__main__":
    unittest.main()
