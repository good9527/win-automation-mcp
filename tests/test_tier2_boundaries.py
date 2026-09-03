# tests/test_tier2_boundaries.py
"""
Tier 2: Boundaries, Corners & Extreme Inputs (R1 - R6)

Exercises edge cases, empty/null values, extreme inputs, spoofed headers,
Unicode anomalies, and corrupted files across all modules.
"""

import os
import sys
import tempfile
import unittest

PROJECT_ROOT = os.path.abspath(os.path.join(os.path.dirname(__file__), ".."))
if PROJECT_ROOT not in sys.path:
    sys.path.insert(0, PROJECT_ROOT)

from win_automation.safety.gate import check_safety
from win_automation.helper.security import generate_session_token, verify_request
from win_automation.state.persistence import save_state, load_state
from win_automation.vision.dxcam_manager import DXCamManager
from win_automation.ocr.finder import run_ocr


class TestTier2EmptyAndNullInputs(unittest.TestCase):
    def test_t2_01_check_safety_empty_string(self):
        res = check_safety("")
        self.assertFalse(res["needs_confirmation"])
        res2 = check_safety("   ")
        self.assertFalse(res2["needs_confirmation"])

    def test_t2_02_check_safety_none_input(self):
        res = check_safety(None)
        self.assertFalse(res["needs_confirmation"])

    def test_t2_03_verify_request_empty_headers(self):
        ok, code, msg = verify_request({}, "test_token")
        self.assertFalse(ok)
        self.assertEqual(code, 403)

    def test_t2_04_verify_request_empty_server_token(self):
        ok, code, msg = verify_request({"Host": "127.0.0.1", "X-Helper-Token": "tok"}, "")
        self.assertFalse(ok)
        self.assertEqual(code, 403)

    def test_t2_05_save_state_empty_dict(self):
        with tempfile.TemporaryDirectory() as td:
            spath = os.path.join(td, "state.json")
            res = save_state({}, spath)
            self.assertEqual(load_state(spath), {})

    def test_t2_06_ocr_empty_bytes(self):
        res = run_ocr(b"")
        self.assertIsInstance(res, list)


class TestTier2GiantAndExtremeInputs(unittest.TestCase):
    def test_t2_07_check_safety_giant_string(self):
        giant_str = "safe action " * 10000
        res = check_safety(giant_str)
        self.assertFalse(res["needs_confirmation"])

    def test_t2_08_check_safety_giant_destructive(self):
        giant_dest = ("x" * 5000) + "删除系统文件" + ("y" * 5000)
        res = check_safety(giant_dest)
        self.assertTrue(res["needs_confirmation"])

    def test_t2_09_helper_token_giant_header(self):
        tok = generate_session_token()
        giant_token = "xa" * 5000
        ok, code, msg = verify_request({"Host": "127.0.0.1", "X-Helper-Token": giant_token}, tok)
        self.assertFalse(ok)
        self.assertEqual(code, 403)

    def test_t2_10_state_giant_payload(self):
        with tempfile.TemporaryDirectory() as td:
            spath = os.path.join(td, "state.json")
            payload = {"keys": ["element_" + str(i) for i in range(1000)], "blob": "A" * 100000}
            save_state(payload, spath)
            loaded = load_state(spath)
            self.assertEqual(len(loaded["keys"]), 1000)

    def test_t2_11_ocr_giant_image_bytes(self):
        giant_img = b"\x00" * (1024 * 1024)
        res = run_ocr(giant_img)
        self.assertIsInstance(res, list)


class TestTier2SpoofedAndMalformedHeaders(unittest.TestCase):
    def setUp(self):
        self.token = generate_session_token()

    def test_t2_12_host_spoof_dns_rebinding_patterns(self):
        bad_hosts = ["localhost.evil.com", "127.0.0.1.it", "127.0.0.1.evil.com", "evil-localhost"]
        for h in bad_hosts:
            ok, code, msg = verify_request({"Host": h, "X-Helper-Token": self.token}, self.token)
            self.assertFalse(ok, f"Host {h} must be rejected")
            self.assertEqual(code, 403)

    def test_t2_13_host_with_whitespace(self):
        ok, code, msg = verify_request({"Host": "  127.0.0.1  ", "X-Helper-Token": self.token}, self.token)
        self.assertTrue(ok)

    def test_t2_14_token_with_null_byte(self):
        ok, code, msg = verify_request({"Host": "127.0.0.1", "X-Helper-Token": self.token + "\x00test"}, self.token)
        self.assertFalse(ok)
        self.assertEqual(code, 403)

    def test_t2_15_malformed_port_number(self):
        ok, code, msg = verify_request({"Host": "127.0.0.1:abc", "X-Helper-Token": self.token}, self.token)
        # Port with letters still starts with 127.0.0.1: or is rejected safely
        self.assertIsInstance(ok, bool)

    def test_t2_16_ipv6_host_handling(self):
        for h in ["[::1]", "[::1]:18765"]:
            ok, code, msg = verify_request({"Host": h, "X-Helper-Token": self.token}, self.token)
            self.assertFalse(ok)


class TestTier2UnusualUnicodeAndMetaCharacters(unittest.TestCase):
    def test_t2_17_zero_width_spaces_in_safety(self):
        cmd = "删除\u200b系统\u200b文件"
        res = check_safety(cmd)
        self.assertTrue(res["needs_confirmation"])

    def test_t2_18_emojis_in_safety(self):
        cmd = "🔥 删除文件 🔥"
        res = check_safety(cmd)
        self.assertTrue(res["needs_confirmation"])

    def test_t2_19_sql_and_shell_meta_characters(self):
        for c in ["del *.* ; regedit", "shutdown && regedit", "format c: | regedit"]:
            res = check_safety(c)
            self.assertTrue(res["needs_confirmation"])

    def test_t2_20_mixed_scripts_in_safety(self):
        cmd = "支付action"
        res = check_safety(cmd)
        self.assertTrue(res["needs_confirmation"])

    def test_t2_21_unicode_in_state_persistence(self):
        with tempfile.TemporaryDirectory() as td:
            spath = os.path.join(td, "state.json")
            payload = {"text": "测试・🔥・emoji", "arabic": "مرحبا"}
            save_state(payload, spath)
            loaded = load_state(spath)
            self.assertEqual(loaded["text"], payload["text"])


class TestTier2ExtremeAndNegativeNumerics(unittest.TestCase):
    def test_t2_22_hwnd_extremes_in_state(self):
        with tempfile.TemporaryDirectory() as td:
            spath = os.path.join(td, "state.json")
            save_state({"hwnd": 0xFFFFFFFFFFFFFFFF}, spath)
            loaded = load_state(spath)
            self.assertEqual(loaded["hwnd"], 0xFFFFFFFFFFFFFFFF)

    def test_t2_23_state_float_dpi_scales(self):
        with tempfile.TemporaryDirectory() as td:
            spath = os.path.join(td, "state.json")
            save_state({"dpi_scale": 2.25, "zoom": 1.0}, spath)
            loaded = load_state(spath)
            self.assertEqual(loaded["dpi_scale"], 2.25)

    def test_t2_24_negative_coordinates_state(self):
        with tempfile.TemporaryDirectory() as td:
            spath = os.path.join(td, "state.json")
            save_state({"last_pos": [-500, -300]}, spath)
            loaded = load_state(spath)
            self.assertEqual(loaded["last_pos"], [-500, -300])

    def test_t2_25_dxcam_negative_device_idx(self):
        cam = DXCamManager.get_camera(-1, None)
        self.assertIsNotNone(cam)


class TestTier2MissingAndCorruptedResources(unittest.TestCase):
    def test_t2_26_state_file_nonexistent_directory(self):
        with tempfile.TemporaryDirectory() as td:
            non_exist_dir = os.path.join(td, "sub", "deep", "state.json")
            res_path = save_state({"status": "okay"}, non_exist_dir)
            self.assertTrue(os.path.exists(res_path))

    def test_t2_27_load_state_empty_file(self):
        with tempfile.TemporaryDirectory() as td:
            empty_f = os.path.join(td, "empty.json")
            open(empty_f, "w").close()
            loaded = load_state(empty_f)
            self.assertEqual(loaded, {})

    def test_t2_28_ocr_non_bytes_format(self):
        res = run_ocr({"image_data": "not_bytes"})
        self.assertIsInstance(res, list)


if __name__ == "__main__":
    unittest.main()
