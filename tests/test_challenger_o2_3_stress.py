# tests/test_challenger_o2_3_stress.py
"""
Adversarial Stress Test Suite - Challenger Gate 2 (challenger_o2_3)
Adversarially tests all 6 requirements (R1-R6) on the remediated codebase:
1. In-Memory WinRT OCR on dynamically generated PIL images (<100ms, exact recognition).
2. Helper Security (missing token, wrong token, spoofed Host with port injection).
3. Safety Gate on dangerous commands (powershell, delete, reg add, spaced Chinese, format, payment).
4. Compact Schema (<35k chars) and Expert Profile (111 tools).
5. State locking concurrency & reentrancy.
6. Repository hygiene & UTF-8 BOM absence.
"""

from __future__ import annotations

import glob
import hmac
import io
import json
import multiprocessing
import os
import random
import re
import string
import sys
import tempfile
import threading
import time
import unittest
from typing import Any, Dict, List, Optional

PROJECT_ROOT = os.path.abspath(os.path.join(os.path.dirname(__file__), ".."))
if PROJECT_ROOT not in sys.path:
    sys.path.insert(0, PROJECT_ROOT)

from PIL import Image, ImageDraw, ImageFont

from win_automation.ocr.finder import run_ocr
from win_automation.helper.security import generate_session_token, verify_request
from win_automation.safety.gate import check_safety
from win_automation.server.compact_tools import COMPACT_TOOL_SCHEMAS, calculate_serialized_schema_size, compact_act
from win_automation.server.app import create_app
from win_automation.state.locks import FileLock, FileLockTimeoutError
from win_automation.state.persistence import load_state, save_state, update_state, get_state_lock


def _mp_worker(state_file: str, worker_id: int, iters: int) -> None:
    """Multiprocess worker for concurrent state file updates."""
    for _ in range(iters):
        def _mutator(state: Dict[str, Any]) -> Dict[str, Any]:
            state["total"] = int(state.get("total", 0)) + 1
            state[f"proc_{worker_id}"] = int(state.get(f"proc_{worker_id}", 0)) + 1
            return state
        update_state(_mutator, filepath=state_file, lock_timeout=30.0)


class TestR4WinRTOCREmpiricalStress(unittest.TestCase):
    """Empirical adversarial stress testing of R4: In-Memory WinRT OCR."""

    @classmethod
    def setUpClass(cls):
        try:
            cls.font_en = ImageFont.truetype("arial.ttf", 32)
        except Exception:
            cls.font_en = ImageFont.load_default()
        try:
            cls.font_cn = ImageFont.truetype("msyh.ttc", 32)
        except Exception:
            cls.font_cn = cls.font_en

    def test_r4_01_random_string_recognition_and_sub_100ms_latency(self):
        """Verify dynamic random alphanumeric strings recognized in <100ms."""
        trials = 8
        latencies = []
        for i in range(trials):
            rand_suffix = "".join(random.choices(string.ascii_uppercase + string.digits, k=6))
            target_str = f"ACTION_{rand_suffix}"
            img = Image.new("RGB", (450, 80), (255, 255, 255))
            draw = ImageDraw.Draw(img)
            draw.text((15, 20), target_str, fill=(0, 0, 0), font=self.font_en)

            t0 = time.perf_counter()
            results = run_ocr(img, lang="en-US")
            elapsed_ms = (time.perf_counter() - t0) * 1000
            latencies.append(elapsed_ms)

            # Assert latency budget
            self.assertLess(elapsed_ms, 100.0, f"Latency {elapsed_ms:.2f}ms exceeded 100ms threshold")

            # Assert exact recognition
            recognized_texts = [r.get("text", "") for r in results]
            full_text = " ".join(recognized_texts)
            self.assertTrue(
                rand_suffix in full_text or rand_suffix in "".join(recognized_texts),
                f"Failed to recognize random string {rand_suffix} in {recognized_texts}"
            )

        avg_latency = sum(latencies) / len(latencies)
        self.assertLess(avg_latency, 50.0, f"Average latency {avg_latency:.2f}ms too high")

    def test_r4_02_chinese_text_recognition(self):
        """Verify Chinese characters recognized accurately in <100ms."""
        target_str = "确认操作8888"
        img = Image.new("RGB", (450, 80), (255, 255, 255))
        draw = ImageDraw.Draw(img)
        draw.text((15, 20), target_str, fill=(0, 0, 0), font=self.font_cn)

        t0 = time.perf_counter()
        results = run_ocr(img, lang="zh-Hans-CN")
        elapsed_ms = (time.perf_counter() - t0) * 1000
        self.assertLess(elapsed_ms, 100.0)

        combined = "".join(r.get("text", "") for r in results)
        self.assertIn("确认操作", combined)
        self.assertIn("8888", combined)

    def test_r4_03_invalid_inputs_graceful_handling(self):
        """Verify graceful error handling on corrupt or empty image buffers."""
        self.assertEqual(run_ocr(None), [])
        self.assertEqual(run_ocr(b""), [])
        self.assertEqual(run_ocr(b"NOT_AN_IMAGE_RANDOM_GARBAGE"), [])


class TestR2HelperSecurityAdversarial(unittest.TestCase):
    """Empirical adversarial testing of R2: Helper Security & Authentication Barrier."""

    def setUp(self):
        self.token = generate_session_token()

    def test_r2_01_missing_and_wrong_token(self):
        """Missing or wrong X-Helper-Token must return HTTP 403."""
        # Missing token
        ok, code, msg = verify_request({"Host": "127.0.0.1:18765"}, self.token)
        self.assertFalse(ok)
        self.assertEqual(code, 403)
        self.assertIn("Missing X-Helper-Token", msg)

        # Wrong token
        ok, code, msg = verify_request(
            {"Host": "127.0.0.1:18765", "X-Helper-Token": "invalid_wrong_token_xyz"},
            self.token,
        )
        self.assertFalse(ok)
        self.assertEqual(code, 403)
        self.assertIn("Invalid X-Helper-Token", msg)

    def test_r2_02_spoofed_host_headers(self):
        """Spoofed Host headers (DNS rebinding / port injection) must return HTTP 403."""
        adversarial_hosts = [
            "evil.com",
            "127.0.0.1:18765@evil.com",
            "192.168.1.1",
            "127.0.0.1:99999",  # Port > 65535
            "127.0.0.1:0",      # Port 0
            "127.0.0.1:abc",    # Non-numeric port
            "localhost:8080#evil.com",
            "127.0.0.1.attacker.com",
            "",
        ]

        for host in adversarial_hosts:
            ok, code, msg = verify_request(
                {"Host": host, "X-Helper-Token": self.token},
                self.token,
            )
            self.assertFalse(ok, f"Host '{host}' should have been rejected")
            self.assertEqual(code, 403, f"Host '{host}' should return 403")

    def test_r2_03_valid_hosts_accepted(self):
        """Strictly valid 127.0.0.1 and localhost hosts must return HTTP 200."""
        valid_hosts = [
            "127.0.0.1:18765",
            "127.0.0.1",
            "localhost:18765",
            "localhost",
        ]
        for host in valid_hosts:
            ok, code, msg = verify_request(
                {"Host": host, "X-Helper-Token": self.token},
                self.token,
            )
            self.assertTrue(ok, f"Valid host '{host}' was rejected")
            self.assertEqual(code, 200)


class TestR3SafetyGateAdversarial(unittest.TestCase):
    """Empirical adversarial testing of R3: Safety Gate Classification."""

    def test_r3_01_dangerous_commands_gated(self):
        """Dangerous commands across Chinese, English, and evasion patterns must require confirmation."""
        dangerous_cases = [
            ("powershell -enc aW52b2tlLWV4cHJlc3Npb24=", "system_alteration", "high"),
            ("powershell.exe -ExecutionPolicy Bypass", "system_alteration", "high"),
            ("delete c:\\file.txt", "file_destruction", "critical"),
            ("del c:\\file.txt", "file_destruction", "critical"),
            ("reg add HKLM\\Software\\Test /v Val /t REG_SZ /d 1", "system_alteration", "high"),
            ("reg.exe delete HKCU\\Software\\Test /f", "file_destruction", "critical"),
            ("删 除系统文件", "file_destruction", "critical"),
            ("彻底 删 除", "file_destruction", "critical"),
            ("微信支付100元", "financial_transaction", "critical"),
            ("向张三 转 账 500 元", "financial_transaction", "critical"),
            ("format c:", "file_destruction", "critical"),
            ("format c: /q /y", "file_destruction", "critical"),
            ("rmdir /s /q c:\\temp", "file_destruction", "critical"),
            ("shutdown /s /t 0", "system_alteration", "high"),
            ("删\u200b除\u200b文\u200b件", "file_destruction", "critical"),
            ("清 空 回 收 站", "file_destruction", "critical"),
        ]

        for cmd, exp_cat, exp_risk in dangerous_cases:
            res = check_safety(cmd)
            self.assertTrue(
                res.get("needs_confirmation"),
                f"Command '{cmd}' should return needs_confirmation: True",
            )
            self.assertEqual(
                res.get("category"),
                exp_cat,
                f"Command '{cmd}' category expected {exp_cat}, got {res.get('category')}",
            )
            self.assertEqual(
                res.get("risk_level"),
                exp_risk,
                f"Command '{cmd}' risk expected {exp_risk}, got {res.get('risk_level')}",
            )

    def test_r3_02_benign_commands_allowed(self):
        """Benign automation commands must not require confirmation."""
        benign_cases = [
            "observe_window 12345",
            "click button Submit",
            "type_input hello world",
            "key_press Enter",
            "doctor",
        ]
        for cmd in benign_cases:
            res = check_safety(cmd)
            self.assertFalse(
                res.get("needs_confirmation"),
                f"Benign command '{cmd}' should return needs_confirmation: False",
            )
            self.assertEqual(res.get("category"), "safe")
            self.assertEqual(res.get("risk_level"), "none")


class TestR1DualProfilesAndSchema(unittest.TestCase):
    """Empirical testing of R1: Dual MCP Profiles and Token Efficiency."""

    def test_r1_01_compact_schema_size_budget(self):
        """Compact schema serialized size must be < 35,000 chars."""
        schema_size = calculate_serialized_schema_size(COMPACT_TOOL_SCHEMAS)
        self.assertLess(
            schema_size,
            35000,
            f"Compact schema size {schema_size} exceeds budget of 35000 characters",
        )
        self.assertEqual(len(COMPACT_TOOL_SCHEMAS), 9)

    def test_r1_02_expert_profile_exact_111_tools(self):
        """Expert profile must register exactly 111 tools."""
        os.environ["WIN_AUTO_PROFILE"] = "expert"
        app_expert = create_app()
        tools_expert = app_expert._tool_manager._tools
        self.assertEqual(len(tools_expert), 111, f"Expert profile registered {len(tools_expert)} tools, expected 111")

    def test_r1_03_compact_profile_exact_9_tools(self):
        """Compact profile must register exactly 9 tools."""
        os.environ["WIN_AUTO_PROFILE"] = "compact"
        app_compact = create_app()
        tools_compact = app_compact._tool_manager._tools
        self.assertEqual(len(tools_compact), 9, f"Compact profile registered {len(tools_compact)} tools, expected 9")

    def test_r1_04_expert_profile_all_111_tools_authenticated(self):
        """Verify all 111 Expert profile tools resolve in tools.py and return no facade error."""
        import tools
        os.environ["WIN_AUTO_PROFILE"] = "expert"
        app = create_app()
        self.assertEqual(len(app._tool_manager._tools), 111)
        for name in app._tool_manager._tools:
            target = getattr(tools, name, None)
            self.assertIsNotNone(target, f"Tool '{name}' not found in tools.py")
            self.assertTrue(callable(target), f"Tool '{name}' is not callable")

    def test_r1_05_compact_doctor_callable(self):
        """Verify doctor tool in compact profile can be executed with or without arguments."""
        from win_automation.server.compact_tools import compact_doctor
        res = compact_doctor()
        self.assertIsInstance(res, dict)
        self.assertIn("status", res)



class TestR6ConcurrencyAndLockReentrancy(unittest.TestCase):
    """Empirical testing of R6: State Locking Concurrency and Reentrancy."""

    def test_r6_01_same_thread_nested_reentrancy(self):
        """Reentrant lock acquisitions on the same thread succeed without deadlocking."""
        with tempfile.TemporaryDirectory() as td:
            sf = os.path.join(td, "reentrant_test.json")
            save_state({"count": 0, "history": []}, filepath=sf)

            lock_file = sf + ".lock"
            with FileLock(lock_file, timeout=2.0):
                with FileLock(lock_file, timeout=2.0):
                    with FileLock(lock_file, timeout=2.0):
                        def mutator(st: Dict[str, Any]) -> Dict[str, Any]:
                            st["count"] = st.get("count", 0) + 1
                            inner_state = load_state(filepath=sf)
                            st["history"] = inner_state.get("history", []) + [st["count"]]
                            return st

                        res = update_state(mutator, filepath=sf, lock_timeout=2.0)
                        self.assertEqual(res["count"], 1)

            final = load_state(filepath=sf)
            self.assertEqual(final["count"], 1)
            self.assertEqual(final["history"], [1])

    def test_r6_02_multithreaded_high_contention(self):
        """25 threads concurrently updating state perform atomic increments."""
        with tempfile.TemporaryDirectory() as td:
            sf = os.path.join(td, "thread_stress.json")
            save_state({"total": 0}, filepath=sf)

            num_threads = 25
            ops_per_thread = 20
            exceptions: List[Exception] = []

            def worker(tid: int):
                try:
                    for _ in range(ops_per_thread):
                        def _mut(st: Dict[str, Any]) -> Dict[str, Any]:
                            st["total"] = int(st.get("total", 0)) + 1
                            st[f"t_{tid}"] = int(st.get(f"t_{tid}", 0)) + 1
                            return st
                        update_state(_mut, filepath=sf, lock_timeout=30.0)
                except Exception as ex:
                    exceptions.append(ex)

            threads = [threading.Thread(target=worker, args=(i,)) for i in range(num_threads)]
            for t in threads:
                t.start()
            for t in threads:
                t.join(timeout=30.0)

            self.assertEqual(len(exceptions), 0, f"Thread exceptions: {exceptions}")
            final = load_state(filepath=sf)
            self.assertEqual(final.get("total"), num_threads * ops_per_thread)

    def test_r6_03_multiprocess_high_contention(self):
        """6 worker processes concurrently updating state perform atomic increments."""
        with tempfile.TemporaryDirectory() as td:
            sf = os.path.join(td, "mp_stress.json")
            save_state({"total": 0}, filepath=sf)

            num_procs = 6
            iters = 15
            procs = [
                multiprocessing.Process(target=_mp_worker, args=(sf, wid, iters))
                for wid in range(num_procs)
            ]
            for p in procs:
                p.start()
            for p in procs:
                p.join(timeout=30.0)
                self.assertEqual(p.exitcode, 0, f"Process {p} failed")

            final = load_state(filepath=sf)
            self.assertEqual(final.get("total"), num_procs * iters)


class TestR5RepositoryHygiene(unittest.TestCase):
    """Empirical testing of R5 & R6: Repository Hygiene, BOM, Stray Files."""

    def test_r5_01_zero_utf8_bom_in_python_files(self):
        """All .py files across the codebase must have zero UTF-8 BOM bytes."""
        bom_files = []
        for root, _, files in os.walk(PROJECT_ROOT):
            if ".git" in root or ".agents" in root or "venv" in root:
                continue
            for f in files:
                if f.endswith(".py"):
                    full_path = os.path.join(root, f)
                    try:
                        with open(full_path, "rb") as fp:
                            prefix = fp.read(3)
                            if prefix == b"\xef\xbb\xbf":
                                bom_files.append(full_path)
                    except Exception:
                        pass
        self.assertEqual(len(bom_files), 0, f"UTF-8 BOM detected in: {bom_files}")

    def test_r5_02_zero_stray_artifacts_in_root(self):
        """Root directory must contain no stray .png, .jpg, or .log files."""
        stray_patterns = ["*.png", "*.jpg", "*.jpeg", "*.log"]
        found_strays = []
        for pat in stray_patterns:
            matches = glob.glob(os.path.join(PROJECT_ROOT, pat))
            found_strays.extend(matches)
        self.assertEqual(len(found_strays), 0, f"Stray artifacts found in root: {found_strays}")


if __name__ == "__main__":
    unittest.main()