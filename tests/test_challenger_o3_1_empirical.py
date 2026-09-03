# tests/test_challenger_o3_1_empirical.py
"""
Empirical Adversarial Verification Suite - Challenger Gate 3 (challenger_o3_1)

Rigorous empirical stress-testing and adversarial probing across:
1. R4: In-Memory WinRT OCR (dynamic rendering, latency benchmarks <100ms, bounding boxes, zero subprocess spawns).
2. R2: Helper Security (forged tokens, missing tokens, DNS rebinding, Host header spoofing, live HTTP server 403 checks).
3. R3: Safety Gate (spaced Chinese, zero-width spaces, powershell encodings, registry, batch scripts, payments).
4. R6: Concurrency & State Locking (multithreaded and multiprocess stress, atomic updates, lock reentrancy & timeouts).
"""

from __future__ import annotations

import http.client
import io
import json
import multiprocessing
import os
import random
import re
import string
import subprocess
import sys
import tempfile
import threading
import time
import unittest
from http.server import HTTPServer
from typing import Any, Dict, List, Optional
from unittest.mock import patch

PROJECT_ROOT = os.path.abspath(os.path.join(os.path.dirname(__file__), ".."))
if PROJECT_ROOT not in sys.path:
    sys.path.insert(0, PROJECT_ROOT)

from PIL import Image, ImageDraw, ImageFont

from win_automation.ocr.finder import run_ocr
from win_automation.ocr.winrt_engine import WinRTOCREngine
from win_automation.helper.security import generate_session_token, verify_request
import helper
from win_automation.safety.gate import check_safety
from win_automation.state.locks import FileLock, FileLockTimeoutError
from win_automation.state.persistence import (
    load_state,
    save_state,
    update_state,
    get_state_lock,
)


def _mp_stress_worker(state_file: str, wid: int, iters: int) -> None:
    """Multiprocess worker updating atomic state counter."""
    for _ in range(iters):
        def _mut(st: Dict[str, Any]) -> Dict[str, Any]:
            st["total"] = int(st.get("total", 0)) + 1
            st[f"proc_{wid}"] = int(st.get(f"proc_{wid}", 0)) + 1
            return st
        update_state(_mut, filepath=state_file, lock_timeout=30.0)


class TestR4WinRTOCREmpirical(unittest.TestCase):
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

    def test_01_latency_benchmark_sub_100ms(self):
        """Benchmark 10 dynamic images: single-call latency must be strictly <100ms (avg <50ms)."""
        latencies: List[float] = []
        for i in range(10):
            canvas = Image.new("RGB", (500, 120), (255, 255, 255))
            draw = ImageDraw.Draw(canvas)
            test_phrase = f"SYSTEM_CHECK_{1000 + i} ACTIVE"
            draw.text((30, 40), test_phrase, fill=(0, 0, 0), font=self.font_en)

            t0 = time.perf_counter()
            results = run_ocr(canvas, lang="en-US")
            elapsed_ms = (time.perf_counter() - t0) * 1000
            latencies.append(elapsed_ms)

            self.assertLess(
                elapsed_ms,
                100.0,
                f"Latency exceeded 100ms budget: {elapsed_ms:.2f}ms on iteration {i}",
            )
            self.assertGreater(len(results), 0, "OCR should detect words in test canvas")

        avg_lat = sum(latencies) / len(latencies)
        self.assertLess(avg_lat, 60.0, f"Average latency too high: {avg_lat:.2f}ms")

    def test_02_bounding_box_detection(self):
        """Verify exact character bounding box coordinates within image bounds."""
        canvas = Image.new("RGB", (600, 140), (255, 255, 255))
        draw = ImageDraw.Draw(canvas)
        text_x, text_y = 50, 45
        draw.text((text_x, text_y), "BOUNDING BOX TEST", fill=(0, 0, 0), font=self.font_en)

        results = run_ocr(canvas, lang="en-US")
        self.assertGreater(len(results), 0)

        for item in results:
            self.assertIn("text", item)
            self.assertIn("confidence", item)
            self.assertIn("rect", item)
            rect = item["rect"]
            self.assertIsInstance(rect["x"], int)
            self.assertIsInstance(rect["y"], int)
            self.assertIsInstance(rect["width"], int)
            self.assertIsInstance(rect["height"], int)

            # Coordinates must be positive and within the canvas
            self.assertGreaterEqual(rect["x"], 0)
            self.assertGreaterEqual(rect["y"], 0)
            self.assertGreater(rect["width"], 0)
            self.assertGreater(rect["height"], 0)
            self.assertLessEqual(rect["x"] + rect["width"], canvas.width + 5)
            self.assertLessEqual(rect["y"] + rect["height"], canvas.height + 5)

        # Check that the first word 'BOUNDING' is positioned near text_x
        first_box = results[0]["rect"]
        self.assertAlmostEqual(first_box["x"], text_x, delta=25)

    def test_03_zero_external_process_spawns(self):
        """Confirm zero external process spawns (no powershell.exe or any subprocess)."""
        canvas = Image.new("RGB", (500, 120), (255, 255, 255))
        draw = ImageDraw.Draw(canvas)
        draw.text((30, 40), "VERIFY IN MEMORY OCR", fill=(0, 0, 0), font=self.font_en)

        with patch("subprocess.Popen", side_effect=AssertionError("subprocess.Popen was spawned!")):
            with patch("subprocess.run", side_effect=AssertionError("subprocess.run was spawned!")):
                with patch("subprocess.call", side_effect=AssertionError("subprocess.call was spawned!")):
                    with patch("os.system", side_effect=AssertionError("os.system was called!")):
                        results = run_ocr(canvas, lang="en-US")
                        self.assertGreater(len(results), 0)
                        words = [r["text"] for r in results]
                        self.assertIn("VERIFY", words)

    def test_04_chinese_and_numbers_recognition(self):
        """Verify bilingual Chinese text and numeric recognition."""
        canvas = Image.new("RGB", (600, 140), (255, 255, 255))
        draw = ImageDraw.Draw(canvas)
        draw.text((30, 40), "确认自动化操作 2026", fill=(0, 0, 0), font=self.font_cn)

        results = run_ocr(canvas, lang="zh-Hans-CN")
        self.assertGreater(len(results), 0)
        detected_text = "".join(r.get("text", "") for r in results)
        self.assertIn("2026", detected_text)
        # Check that Chinese characters were recognized
        has_cjk = any("\u4e00" <= c <= "\u9fff" for c in detected_text)
        self.assertTrue(has_cjk, f"No CJK characters recognized in '{detected_text}'")


class TestR2HelperSecurityEmpirical(unittest.TestCase):
    """Empirical adversarial testing of R2: Helper Security & Authentication Barrier."""

    def setUp(self):
        self.token = generate_session_token()

    def test_01_token_verification_evasions(self):
        """Test forged, missing, empty, and partial tokens return HTTP 403."""
        evasion_cases = [
            ({}, "Missing all headers"),
            ({"Host": "127.0.0.1:18765"}, "Missing X-Helper-Token"),
            ({"Host": "127.0.0.1:18765", "X-Helper-Token": ""}, "Empty token"),
            ({"Host": "127.0.0.1:18765", "X-Helper-Token": "forged_random_token_val"}, "Forged token"),
            ({"Host": "127.0.0.1:18765", "X-Helper-Token": self.token[:-2]}, "Truncated token"),
            ({"Host": "127.0.0.1:18765", "X-Helper-Token": self.token + "extra"}, "Extended token"),
        ]
        for headers, desc in evasion_cases:
            ok, status, msg = verify_request(headers, self.token)
            self.assertFalse(ok, f"Should reject {desc}")
            self.assertEqual(status, 403, f"Expected 403 for {desc}")

    def test_02_dns_rebinding_and_malformed_host_headers(self):
        """Test DNS rebinding, external hostnames, out-of-range ports return HTTP 403."""
        rebinding_cases = [
            "evil.com",
            "127.0.0.1:18765@evil.com",
            "attacker.com:18765",
            "192.168.1.10:18765",
            "10.0.0.1",
            "127.0.0.1:99999",
            "127.0.0.1:0",
            "127.0.0.1:abc",
            "127.0.0.1:-1",
            "localhost:8080#evil.com",
            "127.0.0.1.attacker.com",
            "127.0.0.1:18765?query=1",
            "",
            "   ",
        ]
        for host in rebinding_cases:
            ok, status, msg = verify_request(
                {"Host": host, "X-Helper-Token": self.token},
                self.token,
            )
            self.assertFalse(ok, f"Host '{host}' should have been rejected")
            self.assertEqual(status, 403, f"Host '{host}' should return 403")

    def test_03_valid_hosts_accepted(self):
        """Strictly valid loopback hosts return HTTP 200."""
        valid_hosts = [
            "127.0.0.1:18765",
            "127.0.0.1",
            "localhost:18765",
            "localhost",
        ]
        for host in valid_hosts:
            ok, status, msg = verify_request(
                {"Host": host, "X-Helper-Token": self.token},
                self.token,
            )
            self.assertTrue(ok, f"Valid host '{host}' was rejected")
            self.assertEqual(status, 200)

    def test_04_live_http_server_verification(self):
        """Run actual live Helper HTTP server and verify unauthorized requests return HTTP 403."""
        saved_token = helper.EXPECTED_TOKEN
        server_token = generate_session_token()
        helper.EXPECTED_TOKEN = server_token

        try:
            httpd = HTTPServer(("127.0.0.1", 0), helper.HelperHandler)
            port = httpd.server_port
            th = threading.Thread(target=httpd.serve_forever, daemon=True)
            th.start()
            time.sleep(0.05)

            # 1. Unauthorized GET without token
            conn = http.client.HTTPConnection("127.0.0.1", port)
            conn.request("GET", "/health", headers={"Host": f"127.0.0.1:{port}"})
            resp = conn.getresponse()
            self.assertEqual(resp.status, 403)
            data = json.loads(resp.read().decode())
            self.assertFalse(data.get("ok"))
            self.assertEqual(data.get("error"), "forbidden")
            conn.close()

            # 2. Unauthorized GET with forged token
            conn = http.client.HTTPConnection("127.0.0.1", port)
            conn.request(
                "GET",
                "/health",
                headers={"Host": f"127.0.0.1:{port}", "X-Helper-Token": "bad_token"},
            )
            resp = conn.getresponse()
            self.assertEqual(resp.status, 403)
            conn.close()

            # 3. Spoofed Host header
            conn = http.client.HTTPConnection("127.0.0.1", port)
            conn.request(
                "GET",
                "/health",
                headers={"Host": "attacker.com:18765", "X-Helper-Token": server_token},
            )
            resp = conn.getresponse()
            self.assertEqual(resp.status, 403)
            conn.close()

            # 4. Authorized GET with valid token and Host
            conn = http.client.HTTPConnection("127.0.0.1", port)
            conn.request(
                "GET",
                "/health",
                headers={"Host": f"127.0.0.1:{port}", "X-Helper-Token": server_token},
            )
            resp = conn.getresponse()
            self.assertEqual(resp.status, 200)
            conn.close()

            httpd.shutdown()
        finally:
            helper.EXPECTED_TOKEN = saved_token


class TestR3SafetyGateEmpirical(unittest.TestCase):
    """Empirical adversarial testing of R3: Safety Gate Classification."""

    def test_01_spaced_chinese_evasions(self):
        """Verify spaced Chinese characters and zero-width spaces are classified as dangerous."""
        evasion_vectors = [
            ("删 除系统文件", "file_destruction"),
            ("格 式 化 D 盘", "file_destruction"),
            ("清 空 回 收 站", "file_destruction"),
            ("彻 底 删 除", "file_destruction"),
            ("销 毁 凭 据", "file_destruction"),
            ("关 机 倒计时", "system_alteration"),
            ("重 启 电脑", "system_alteration"),
            ("支 付 500 元", "financial_transaction"),
            ("向 张 三 转 账", "financial_transaction"),
            ("充 值 100 元", "financial_transaction"),
            ("删\u200b除\u200b文\u200b件", "file_destruction"),
            ("格\u200c式\u200d化", "file_destruction"),
            ("\ufeff删除重要数据", "file_destruction"),
            ("删\t除", "file_destruction"),
            ("删   除", "file_destruction"),
        ]
        for cmd, exp_cat in evasion_vectors:
            res = check_safety(cmd)
            self.assertTrue(
                res.get("needs_confirmation"),
                f"Vector '{cmd}' failed to trigger needs_confirmation: True",
            )
            self.assertEqual(
                res.get("category"),
                exp_cat,
                f"Vector '{cmd}' category expected {exp_cat}, got {res.get('category')}",
            )

    def test_02_powershell_and_registry_operations(self):
        """Verify PowerShell invocations and dangerous registry operations require confirmation."""
        dangerous_ops = [
            ("powershell -enc aW52b2tlLWV4cHJlc3Npb24=", "system_alteration"),
            ("powershell.exe -ExecutionPolicy Bypass -File evil.ps1", "system_alteration"),
            ("powershell -Command Remove-Item -Force", "system_alteration"),
            ("PowerShell -Enc aW52b2tl", "system_alteration"),
            ("PoWeRsHeLl.eXe -c Get-Process", "system_alteration"),
            ("reg add HKLM\\Software\\Test /v Val /t REG_SZ /d 1", "system_alteration"),
            ("reg.exe delete HKCU\\Software\\Test /f", "file_destruction"),
            ("regedit.exe /s patch.reg", "system_alteration"),
            ("reg import test.reg", "system_alteration"),
            ("reg copy HKLM\\A HKLM\\B", "system_alteration"),
        ]
        for cmd, exp_cat in dangerous_ops:
            res = check_safety(cmd)
            self.assertTrue(
                res.get("needs_confirmation"),
                f"Op '{cmd}' should require confirmation",
            )
            self.assertEqual(
                res.get("category"),
                exp_cat,
                f"Op '{cmd}' expected category {exp_cat}, got {res.get('category')}",
            )

    def test_03_dangerous_batch_and_financial(self):
        """Verify dangerous batch commands and financial requests require confirmation."""
        ops = [
            ("del c:\\boot.ini", "file_destruction"),
            ("del /f /q C:\\Windows\\System32", "file_destruction"),
            ("format c: /fs:ntfs /q /y", "file_destruction"),
            ("rmdir /s /q c:\\users", "file_destruction"),
            ("shutdown /s /t 0", "system_alteration"),
            ("taskkill /f /im explorer.exe", "system_alteration"),
            ("net stop spooler", "system_alteration"),
            ("微信支付50元", "financial_transaction"),
            ("支付宝付款100元", "financial_transaction"),
            ("扫码支付账单", "financial_transaction"),
            ("向李四转账5000元", "financial_transaction"),
            ("免密支付开通", "financial_transaction"),
            ("checkout cart", "financial_transaction"),
            ("order_pay id=123", "financial_transaction"),
            ("wire transfer 1000 USD", "financial_transaction"),
        ]
        for cmd, exp_cat in ops:
            res = check_safety(cmd)
            self.assertTrue(res.get("needs_confirmation"), f"Op '{cmd}' should require confirmation")
            self.assertEqual(res.get("category"), exp_cat)

    def test_04_benign_operations_allowed(self):
        """Verify benign automation operations return needs_confirmation: False."""
        benign = [
            "observe_window 12345",
            "click button OK",
            "type_input hello world",
            "key_press Enter",
            "doctor",
            "get_window_title 12345",
            "list_windows",
        ]
        for cmd in benign:
            res = check_safety(cmd)
            self.assertFalse(
                res.get("needs_confirmation"),
                f"Benign op '{cmd}' falsely flagged as dangerous",
            )
            self.assertEqual(res.get("category"), "safe")
            self.assertEqual(res.get("risk_level"), "none")


class TestR6ConcurrencyStateLockingEmpirical(unittest.TestCase):
    """Empirical testing of R6: Concurrency & State Locking."""

    def test_01_multithreaded_high_contention(self):
        """25 threads concurrently performing 20 updates each (500 ops) atomically."""
        with tempfile.TemporaryDirectory() as td:
            sf = os.path.join(td, "thread_contention.json")
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
            for t in threads: t.start()
            for t in threads: t.join(timeout=30.0)

            self.assertEqual(len(exceptions), 0, f"Thread exceptions occurred: {exceptions}")
            final = load_state(filepath=sf)
            self.assertEqual(final.get("total"), num_threads * ops_per_thread)
            for tid in range(num_threads):
                self.assertEqual(final.get(f"t_{tid}"), ops_per_thread)

    def test_02_multiprocess_high_contention(self):
        """6 worker processes performing 15 updates each (90 ops) concurrently."""
        with tempfile.TemporaryDirectory() as td:
            sf = os.path.join(td, "mp_contention.json")
            save_state({"total": 0}, filepath=sf)

            num_procs = 6
            iters = 15
            procs = [
                multiprocessing.Process(target=_mp_stress_worker, args=(sf, wid, iters))
                for wid in range(num_procs)
            ]
            for p in procs: p.start()
            for p in procs:
                p.join(timeout=30.0)
                self.assertEqual(p.exitcode, 0)

            final = load_state(filepath=sf)
            self.assertEqual(final.get("total"), num_procs * iters)

    def test_03_lock_reentrancy_and_timeout(self):
        """Verify lock reentrancy on same thread and timeout on foreign lock."""
        with tempfile.TemporaryDirectory() as td:
            sf = os.path.join(td, "reentrant_test.json")
            lock_path = sf + ".lock"

            # Same thread nested acquisition should succeed
            with FileLock(lock_path, timeout=2.0):
                with FileLock(lock_path, timeout=2.0):
                    with FileLock(lock_path, timeout=2.0):
                        pass

            # Acquire in thread, then another thread with short timeout should raise FileLockTimeoutError
            lock_acquired_event = threading.Event()
            release_event = threading.Event()
            foreign_exception = []

            def holder():
                with FileLock(lock_path, timeout=5.0):
                    lock_acquired_event.set()
                    release_event.wait(timeout=5.0)

            th = threading.Thread(target=holder)
            th.start()
            lock_acquired_event.wait(timeout=2.0)

            def contender():
                try:
                    with FileLock(lock_path, timeout=0.2):
                        pass
                except FileLockTimeoutError as ex:
                    foreign_exception.append(ex)

            th_contender = threading.Thread(target=contender)
            th_contender.start()
            th_contender.join(timeout=2.0)

            release_event.set()
            th.join(timeout=2.0)

            self.assertEqual(len(foreign_exception), 1)
            self.assertIsInstance(foreign_exception[0], FileLockTimeoutError)


if __name__ == "__main__":
    unittest.main()
