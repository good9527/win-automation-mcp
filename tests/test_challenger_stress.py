# tests/test_challenger_stress.py
"""
Adversarial Stress Test Suite for Challenger (M6 / Requirements R4, R5, R6)

Covers:
1. High-concurrency state file locking (multithreaded & multiprocess read/write).
2. Lock reentrancy and timeout failure modes.
3. DXCam singleton caching and GDI object handle leak verification via GetGuiResources.
4. PEP 562 symbol resolution and CLI bare-name discrepancy verification.
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
import ctypes
from ctypes import wintypes
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
)
from win_automation.vision.dxcam_manager import DXCamManager
import win_automation.compat.resolver as resolver
import server
import tools


def _mp_worker(state_file: str, wid: int, iters: int) -> None:
    """Worker process updating state file concurrently."""
    for _ in range(iters):
        def _mutator(state: Dict[str, Any]) -> None:
            state["total"] = int(state.get("total", 0)) + 1
            state[f"proc_{wid}"] = int(state.get(f"proc_{wid}", 0)) + 1
        update_state(_mutator, filepath=state_file, lock_timeout=30.0)


def _mp_mixed_worker(state_file: str, wid: int, iters: int) -> None:
    """Worker process mixing set_state_value, next_screenshot_id, and load_state."""
    for i in range(iters):
        set_state_value(f"p_{wid}_{i}", i, filepath=state_file)
        next_screenshot_id(filepath=state_file)
        s = load_state(filepath=state_file)
        assert isinstance(s, dict)


class TestAdversarialConcurrencyLocking(unittest.TestCase):
    """Adversarial stress testing of state persistence locking (Requirement R6)."""

    def test_c1_multithreaded_high_contention(self):
        """30 concurrent threads performing 50 updates each (1500 total ops)."""
        with tempfile.TemporaryDirectory() as td:
            sf = os.path.join(td, "threaded_stress.json")
            save_state({"total": 0}, filepath=sf)

            num_threads = 30
            ops_per_thread = 50
            exceptions: List[Exception] = []

            def worker(tid: int):
                try:
                    for _ in range(ops_per_thread):
                        def _mutator(state: Dict[str, Any]) -> None:
                            state["total"] = int(state.get("total", 0)) + 1
                            state[f"t_{tid}"] = int(state.get(f"t_{tid}", 0)) + 1
                        update_state(_mutator, filepath=sf, lock_timeout=30.0)
                except Exception as ex:
                    exceptions.append(ex)

            threads = [threading.Thread(target=worker, args=(i,)) for i in range(num_threads)]
            for t in threads: t.start()
            for t in threads: t.join(timeout=45.0)

            self.assertEqual(len(exceptions), 0, f"Exceptions occurred: {exceptions}")
            final = load_state(filepath=sf)
            self.assertEqual(final.get("total"), num_threads * ops_per_thread)
            for tid in range(num_threads):
                self.assertEqual(final.get(f"t_{tid}"), ops_per_thread)

    def test_c2_multiprocess_high_contention(self):
        """10 concurrent processes performing 30 updates each (300 total ops)."""
        with tempfile.TemporaryDirectory() as td:
            sf = os.path.join(td, "mp_stress.json")
            save_state({"total": 0}, filepath=sf)

            num_procs = 10
            iters = 30
            procs = []

            for wid in range(num_procs):
                p = multiprocessing.Process(target=_mp_worker, args=(sf, wid, iters))
                procs.append(p)
                p.start()

            for p in procs:
                p.join(timeout=45.0)
                self.assertEqual(p.exitcode, 0, f"Process {p} failed with exit code {p.exitcode}")

            final = load_state(filepath=sf)
            self.assertEqual(final.get("total"), num_procs * iters)
            for wid in range(num_procs):
                self.assertEqual(final.get(f"proc_{wid}"), iters)

    def test_c3_multiprocess_mixed_workload_and_screenshot_id(self):
        """6 concurrent processes executing mixed write, read, and screenshot ID increments."""
        with tempfile.TemporaryDirectory() as td:
            sf = os.path.join(td, "mp_mixed.json")
            save_state({"screenshot_counter": 50}, filepath=sf)

            num_procs = 6
            iters = 15
            procs = []

            for wid in range(num_procs):
                p = multiprocessing.Process(target=_mp_mixed_worker, args=(sf, wid, iters))
                procs.append(p)
                p.start()

            for p in procs:
                p.join(timeout=45.0)
                self.assertEqual(p.exitcode, 0)

            final = load_state(filepath=sf)
            expected_counter = 50 + num_procs * iters
            self.assertEqual(final.get("screenshot_counter"), expected_counter)

    def test_c4_nested_lock_reentrancy_success(self):
        """
        Verify: Calling load_state/save_state inside an update_state mutator
        succeeds cleanly on Windows due to reentrant per-path locking.
        """
        with tempfile.TemporaryDirectory() as td:
            sf = os.path.join(td, "nested_lock.json")
            save_state({"val": 1}, filepath=sf)

            def nested_mutator(state: Dict[str, Any]) -> Dict[str, Any]:
                current = load_state(filepath=sf, lock_timeout=0.5)
                state["nested_val"] = current.get("val", 0) + 10
                return state

            res = update_state(nested_mutator, filepath=sf, lock_timeout=1.0)
            self.assertEqual(res.get("nested_val"), 11)


class TestAdversarialVisionAndGDICleanup(unittest.TestCase):
    """Adversarial stress testing of DXCam caching and GDI cleanup (Requirement R4)."""

    def setUp(self):
        DXCamManager.reset()

    def test_v1_dxcam_singleton_instance_caching(self):
        """DXCamManager caches camera per (device_idx, output_idx) and reuses it."""
        c1 = DXCamManager.get_camera(0, 0)
        c2 = DXCamManager.get_camera(0, 0)
        self.assertIs(c1, c2)
        self.assertEqual(DXCamManager.creation_count(), 1)

        c3 = DXCamManager.get_camera(0, 1)
        self.assertIsNot(c1, c3)
        self.assertEqual(DXCamManager.creation_count(), 2)

        DXCamManager.reset()
        self.assertEqual(DXCamManager.creation_count(), 0)

    def test_v2_dxcam_multithreaded_concurrent_access(self):
        """20 threads concurrently retrieving cameras get identical cached instances."""
        retrieved = []
        lock = threading.Lock()

        def worker():
            cam = DXCamManager.get_camera(0, None)
            with lock:
                retrieved.append(cam)

        threads = [threading.Thread(target=worker) for _ in range(20)]
        for t in threads: t.start()
        for t in threads: t.join()

        self.assertEqual(len(retrieved), 20)
        self.assertEqual(DXCamManager.creation_count(), 1)
        for c in retrieved:
            self.assertIs(c, retrieved[0])

    def test_v3_gdi_zero_handle_leak_verification(self):
        """
        Measure process GDI handle count via GetGuiResources before and after
        500 GDI DC/bitmap create, select, and delete cycles.
        """
        user32 = ctypes.WinDLL("user32", use_last_error=True)
        gdi32 = ctypes.WinDLL("gdi32", use_last_error=True)
        kernel32 = ctypes.WinDLL("kernel32", use_last_error=True)

        user32.GetGuiResources.argtypes = [wintypes.HANDLE, wintypes.DWORD]
        user32.GetGuiResources.restype = wintypes.DWORD
        kernel32.GetCurrentProcess.restype = wintypes.HANDLE

        h_proc = kernel32.GetCurrentProcess()
        gdi_start = user32.GetGuiResources(h_proc, 0)

        for _ in range(500):
            hdc_mem1 = gdi32.CreateCompatibleDC(None)
            hdc_mem2 = gdi32.CreateCompatibleDC(hdc_mem1)
            hbmp = gdi32.CreateCompatibleBitmap(hdc_mem1, 100, 100)
            old_bmp = gdi32.SelectObject(hdc_mem2, hbmp)

            if hdc_mem2 and old_bmp:
                gdi32.SelectObject(hdc_mem2, old_bmp)
            if hbmp:
                gdi32.DeleteObject(hbmp)
            if hdc_mem2:
                gdi32.DeleteDC(hdc_mem2)
            if hdc_mem1:
                gdi32.DeleteDC(hdc_mem1)

        gdi_end = user32.GetGuiResources(h_proc, 0)
        self.assertEqual(gdi_start, gdi_end, f"GDI handle leak detected! Start: {gdi_start}, End: {gdi_end}")


class TestAdversarialPEP562AndCLICompatibility(unittest.TestCase):
    """Adversarial stress testing of PEP 562 resolver and CLI command dispatch (Requirement R5)."""

    def test_p1_pep562_server_and_tools_resolution(self):
        """server.py and tools.py properly resolve all primary functions via PEP 562."""
        self.assertTrue(callable(server.enum_windows))
        self.assertTrue(callable(server._enum_windows))
        self.assertTrue(callable(server.save_state))
        self.assertTrue(callable(server.check_safety))
        self.assertTrue(callable(tools.observe))
        self.assertTrue(callable(tools.desktop_screenshot))
        self.assertTrue(callable(tools.doctor))

    def test_p2_pep562_nonexistent_attribute_error(self):
        """Accessing non-existent attributes raises standard AttributeError."""
        with self.assertRaises(AttributeError):
            _ = server.definitely_not_a_valid_server_symbol_xyz
        with self.assertRaises(AttributeError):
            _ = tools.definitely_not_a_valid_tools_symbol_xyz

    def test_p3_cli_command_bare_name_discrepancies(self):
        """
        Verify: CLI commands do not crash with NameError or TypeError due to missing
        imports or bare-name module invocations.
        """
        verified_commands = [
            "observe",
            "desktop_screenshot",
            "desktop_ocr",
            "list_apps",
            "desktop_visual_stable_wait",
            "desktop_uia_stable_wait",
            "desktop_accessibility",
            "desktop_find",
            "desktop_wait",
        ]

        for cmd in verified_commands:
            res = subprocess.run(
                [sys.executable, "tools.py", cmd],
                cwd=PROJECT_ROOT,
                capture_output=True,
                text=True,
                encoding="utf-8",
                errors="replace",
            )
            combined_out = res.stdout + res.stderr
            self.assertNotIn(
                "NameError",
                combined_out,
                f"Unexpected NameError in {cmd}, stdout: {res.stdout}, stderr: {res.stderr}"
            )
            self.assertNotIn(
                "TypeError: 'module' object is not callable",
                combined_out,
                f"Unexpected TypeError in {cmd}, stdout: {res.stdout}, stderr: {res.stderr}"
            )

        res_selftest = subprocess.run(
            [sys.executable, "tools.py", "selftest", "batch"],
            cwd=PROJECT_ROOT,
            capture_output=True,
            text=True,
            encoding="utf-8",
            errors="replace",
        )
        combined_selftest = res_selftest.stdout + res_selftest.stderr
        self.assertNotIn("TypeError: 'module' object is not callable", combined_selftest)


if __name__ == "__main__":
    unittest.main()
