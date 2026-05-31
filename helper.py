"""
Windows Automation Helper Server
Runs as a persistent background process in the desktop session.
Accepts HTTP commands from tools.py and executes them via SendInput.

Usage: python helper.py [--port 18765]
"""

import ctypes
import ctypes.wintypes
import json
import os
import sys
import time
import io
import base64
import threading
import atexit
from http.server import HTTPServer, BaseHTTPRequestHandler
from urllib.parse import urlparse, parse_qs

# Shared constants, structs, utilities
from common import (
    user32, kernel32, gdi32,
    INPUT, INPUT_UNION, KEYBDINPUT, MOUSEINPUT,
    BITMAPINFOHEADER, BITMAPINFO,
    GWL_STYLE, GWL_EXSTYLE, WS_EX_TOOLWINDOW, WS_EX_APPWINDOW,
    SW_RESTORE, PROCESS_QUERY_LIMITED_INFORMATION, MAX_PATH,
    CF_UNICODETEXT, GMEM_MOVEABLE, SRCCOPY,
    INPUT_KEYBOARD, KEYEVENTF_KEYUP, KEYEVENTF_UNICODE, KEYEVENTF_SCANCODE,
    MOUSEEVENTF_LEFTDOWN, MOUSEEVENTF_LEFTUP,
    MOUSEEVENTF_RIGHTDOWN, MOUSEEVENTF_RIGHTUP,
    MOUSEEVENTF_MIDDLEDOWN, MOUSEEVENTF_MIDDLEUP,
    MOUSEEVENTF_WHEEL,
    KEYMAP,
    _load_state, _save_state, _get_window_rect, _get_dpi_scale,
    _get_process_name, _set_clipboard_text, _clipboard_save, _clipboard_restore,
)

# Auto-cleanup temporary screenshot file on daemon termination
def _cleanup():
    try:
        import tempfile
        output_dir = os.path.join(tempfile.gettempdir(), "win-automation-mcp")
        path = os.path.join(output_dir, "screenshot.png")
        if os.path.exists(path):
            os.remove(path)
        desktop_dir = os.path.join(os.path.expanduser("~"), "Desktop", "win-automation-mcp")
        desktop_path = os.path.join(desktop_dir, "screenshot.png")
        if os.path.exists(desktop_path):
            os.remove(desktop_path)
    except Exception:
        pass

atexit.register(_cleanup)


# ---------------------------------------------------------------------------
# Input helpers (SendInput-based, helper.py specific)
# ---------------------------------------------------------------------------
def _send_key(scancode: int, up: bool = False) -> None:
    inp = INPUT()
    inp.type = INPUT_KEYBOARD
    inp.union.ki.wVk = 0
    inp.union.ki.wScan = scancode & 0xFF
    inp.union.ki.dwFlags = KEYEVENTF_SCANCODE
    if scancode & 0xE000:
        inp.union.ki.dwFlags |= 0x0001  # EXTENDEDKEY
    if up:
        inp.union.ki.dwFlags |= KEYEVENTF_KEYUP
    user32.SendInput(1, ctypes.byref(inp), ctypes.sizeof(inp))


def _send_char(ch: str) -> None:
    for code in ch:
        cp = ord(code)
        inp = INPUT()
        inp.type = INPUT_KEYBOARD
        inp.union.ki.wVk = 0
        inp.union.ki.wScan = cp
        inp.union.ki.dwFlags = KEYEVENTF_UNICODE
        user32.SendInput(1, ctypes.byref(inp), ctypes.sizeof(inp))
        time.sleep(0.01)
        inp.union.ki.dwFlags = KEYEVENTF_UNICODE | KEYEVENTF_KEYUP
        user32.SendInput(1, ctypes.byref(inp), ctypes.sizeof(inp))
        time.sleep(0.01)


def _mouse_click(x: int, y: int, button: str = "left", clicks: int = 1) -> None:
    user32.SetCursorPos(x, y)
    time.sleep(0.05)
    down_map = {
        "left": MOUSEEVENTF_LEFTDOWN, "right": MOUSEEVENTF_RIGHTDOWN,
        "middle": MOUSEEVENTF_MIDDLEDOWN,
    }
    up_map = {
        "left": MOUSEEVENTF_LEFTUP, "right": MOUSEEVENTF_RIGHTUP,
        "middle": MOUSEEVENTF_MIDDLEUP,
    }
    for _ in range(clicks):
        user32.mouse_event(down_map[button], 0, 0, 0, 0)
        time.sleep(0.02)
        user32.mouse_event(up_map[button], 0, 0, 0, 0)
        time.sleep(0.05)


def _mouse_scroll(x: int, y: int, delta: int) -> None:
    user32.SetCursorPos(x, y)
    time.sleep(0.05)
    user32.mouse_event(MOUSEEVENTF_WHEEL, 0, 0, delta, 0)


def _activate_window(hwnd: int) -> bool:
    """Bring window to foreground using AttachThreadInput for robustness."""
    try:
        fg = user32.GetForegroundWindow()
        fg_tid = user32.GetWindowThreadProcessId(fg, None)
        my_tid = kernel32.GetCurrentThreadId()
        user32.AttachThreadInput(my_tid, fg_tid, True)
        user32.BringWindowToTop(hwnd)
        user32.ShowWindow(hwnd, SW_RESTORE)
        user32.SetForegroundWindow(hwnd)
        user32.AttachThreadInput(my_tid, fg_tid, False)
        return user32.GetForegroundWindow() == hwnd
    except Exception:
        return False




def _capture_screenshot(hwnd: int, max_width: int = 1280) -> dict:
    """Capture window screenshot. Returns dict with path, width, height, dpi_scale."""
    from PIL import Image as PILImage

    rect = _get_window_rect(hwnd)
    win_w = rect.right - rect.left
    win_h = rect.bottom - rect.top
    if win_w <= 0 or win_h <= 0:
        return {"error": f"Invalid dimensions: {win_w}x{win_h}"}

    logical_rect = ctypes.wintypes.RECT()
    user32.GetWindowRect(hwnd, ctypes.byref(logical_rect))
    log_w = logical_rect.right - logical_rect.left
    log_h = logical_rect.bottom - logical_rect.top

    dpi_scale = _get_dpi_scale(hwnd)
    img = None

    # --- Capture method 1: dxcam (fastest, GPU-accelerated) ---
    try:
        import dxcam
        camera = dxcam.create(output_color="BGR")
        if camera:
            region = (rect.left, rect.top, rect.right, rect.bottom)
            dxcam_img = camera.grab(region=region)
            camera.stop()
            if dxcam_img is not None:
                import numpy as np
                rgb = np.flip(dxcam_img[:, :, ::-1], axis=2)
                img = PILImage.fromarray(rgb)
                width = win_w
                height = win_h
    except ImportError:
        pass
    except Exception:
        pass

    # --- Capture method 2: PrintWindow ---
    if img is None:
        hdc = user32.GetDC(hwnd)
        hdc_mem = gdi32.CreateCompatibleDC(hdc)
        hbitmap = gdi32.CreateCompatibleBitmap(hdc, log_w, log_h)
        old_bmp = gdi32.SelectObject(hdc_mem, hbitmap)

        captured = user32.PrintWindow(hwnd, hdc_mem, 0x00000002)
        if not captured:
            captured = user32.PrintWindow(hwnd, hdc_mem, 0)

        if captured:
            width = log_w
            height = log_h
        else:
            # --- Capture method 3: BitBlt ---
            gdi32.SelectObject(hdc_mem, old_bmp)
            gdi32.DeleteObject(hbitmap)
            gdi32.DeleteDC(hdc_mem)
            user32.ReleaseDC(hwnd, hdc)

            hdc_screen = user32.GetDC(0)
            hdc_mem = gdi32.CreateCompatibleDC(hdc_screen)
            hbitmap = gdi32.CreateCompatibleBitmap(hdc_screen, win_w, win_h)
            old_bmp = gdi32.SelectObject(hdc_mem, hbitmap)
            gdi32.BitBlt(hdc_mem, 0, 0, win_w, win_h,
                         hdc_screen, rect.left, rect.top, SRCCOPY)
            user32.ReleaseDC(0, hdc_screen)
            width = win_w
            height = win_h

        bmi = BITMAPINFO()
        bmi.bmiHeader.biSize = ctypes.sizeof(BITMAPINFOHEADER)
        bmi.bmiHeader.biWidth = width
        bmi.bmiHeader.biHeight = -height
        bmi.bmiHeader.biPlanes = 1
        bmi.bmiHeader.biBitCount = 32
        bmi.bmiHeader.biCompression = 0

        buf_size = width * height * 4
        buf = ctypes.create_string_buffer(buf_size)
        gdi32.GetDIBits(hdc_mem, hbitmap, 0, height, buf, ctypes.byref(bmi), 0)

        img = PILImage.frombuffer("RGBA", (width, height), buf, "raw", "BGRA", 0, 1)

        gdi32.SelectObject(hdc_mem, old_bmp)
        gdi32.DeleteObject(hbitmap)
        gdi32.DeleteDC(hdc_mem)
        user32.ReleaseDC(hwnd, hdc)

    img = img.convert("RGB")

    if max_width and width > max_width:
        ratio = max_width / width
        new_height = int(height * ratio)
        img = img.resize((max_width, new_height), PILImage.LANCZOS)

    import tempfile
    output_dir = os.path.join(tempfile.gettempdir(), "win-automation-mcp")
    os.makedirs(output_dir, exist_ok=True)
    path = os.path.join(output_dir, "screenshot.png")
    img.save(path, "PNG")

    return {
        "path": path,
        "width": img.width,
        "height": img.height,
        "dpi_scale": dpi_scale,
        "window_hwnd": hwnd,
    }


# ---------------------------------------------------------------------------
# HTTP Handler
# ---------------------------------------------------------------------------
class HelperHandler(BaseHTTPRequestHandler):
    def log_message(self, format, *args):
        pass

    def _send_json(self, data: dict, status: int = 200) -> None:
        body = json.dumps(data, ensure_ascii=False).encode("utf-8")
        self.send_response(status)
        self.send_header("Content-Type", "application/json")
        self.send_header("Content-Length", len(body))
        self.end_headers()
        self.wfile.write(body)

    def do_GET(self):
        parsed = urlparse(self.path)
        path = parsed.path
        params = parse_qs(parsed.query)

        if path == "/health":
            self._send_json({"status": "ok"})
        elif path == "/list_windows":
            self._handle_list_windows()
        elif path == "/list_apps":
            self._handle_list_apps()
        elif path == "/get_window":
            hwnd = int(params.get("hwnd", [0])[0])
            self._handle_get_window(hwnd)
        elif path == "/screenshot":
            hwnd = int(params.get("hwnd", [0])[0])
            max_w = int(params.get("max_width", [1280])[0])
            self._handle_screenshot(hwnd, max_w)
        elif path == "/screenshot_b64":
            hwnd = int(params.get("hwnd", [0])[0])
            max_w = int(params.get("max_width", [1280])[0])
            self._handle_screenshot_b64(hwnd, max_w)
        elif path == "/get_state":
            self._handle_get_state(params)
        else:
            self._send_json({"error": f"Unknown path: {path}"}, 404)

    def do_POST(self):
        parsed = urlparse(self.path)
        path = parsed.path

        content_length = int(self.headers.get("Content-Length", 0))
        body = self.rfile.read(content_length) if content_length > 0 else b"{}"
        try:
            data = json.loads(body)
        except json.JSONDecodeError:
            data = {}

        if path in ("/click", "/type_text", "/press_key", "/scroll"):
            if "hwnd" not in data or data["hwnd"] is None:
                target = _load_state().get("target_hwnd")
                if target:
                    data["hwnd"] = target

        if path == "/click":
            self._handle_click(data)
        elif path == "/type_text":
            self._handle_type_text(data)
        elif path == "/press_key":
            self._handle_press_key(data)
        elif path == "/scroll":
            self._handle_scroll(data)
        elif path == "/activate":
            self._handle_activate(data)
        elif path == "/clipboard":
            self._handle_clipboard(data)
        elif path == "/set_clipboard":
            self._handle_set_clipboard(data)
        elif path == "/set_state":
            self._handle_set_state(data)
        elif path == "/batch":
            self._handle_batch(data)
        else:
            self._send_json({"error": f"Unknown path: {path}"}, 404)

    # ----- Handlers -----

    def _handle_list_windows(self):
        from common import _enum_windows
        windows = _enum_windows()
        self._send_json({"windows": windows})

    def _handle_get_window(self, hwnd: int):
        if not user32.IsWindow(hwnd):
            self._send_json({"error": f"Window {hwnd} no longer exists"})
            return
        buf = ctypes.create_unicode_buffer(512)
        user32.GetWindowTextW(hwnd, buf, 512)
        rect = _get_window_rect(hwnd)
        pid = ctypes.c_ulong()
        user32.GetWindowThreadProcessId(hwnd, ctypes.byref(pid))
        proc_path = _get_process_name(pid.value)
        self._send_json({
            "hwnd": hwnd, "title": buf.value,
            "pid": pid.value,
            "process_name": os.path.basename(proc_path) if proc_path else "",
            "process_path": proc_path,
            "dpi_scale": _get_dpi_scale(hwnd),
            "rect": {"left": rect.left, "top": rect.top, "right": rect.right, "bottom": rect.bottom},
            "width": rect.right - rect.left, "height": rect.bottom - rect.top,
        })

    def _handle_screenshot(self, hwnd: int, max_width: int):
        if not user32.IsWindow(hwnd):
            self._send_json({"error": f"Window {hwnd} no longer exists"})
            return
        result = _capture_screenshot(hwnd, max_width)
        self._send_json(result)

    def _handle_click(self, data: dict):
        hwnd = data.get("hwnd")
        x = data.get("x", 0)
        y = data.get("y", 0)
        button = data.get("button", "left")
        clicks = data.get("clicks", 1)

        if hwnd:
            rect = _get_window_rect(hwnd)
            logical_rect = ctypes.wintypes.RECT()
            user32.GetWindowRect(hwnd, ctypes.byref(logical_rect))
            log_w = logical_rect.right - logical_rect.left
            log_h = logical_rect.bottom - logical_rect.top

            ss_w = data.get("screenshot_width") or (1280 if log_w > 1280 else log_w)
            ss_h = data.get("screenshot_height") or (int(log_h * 1280 / log_w) if log_w > 1280 else log_h)

            real_x = int(x * log_w / ss_w) + rect.left
            real_y = int(y * log_h / ss_h) + rect.top

            if data.get("activate", True):
                _activate_window(hwnd)
                time.sleep(0.1)

            _mouse_click(real_x, real_y, button, clicks)
            self._send_json({"ok": True, "screen_x": real_x, "screen_y": real_y})
        else:
            _mouse_click(x, y, button, clicks)
            self._send_json({"ok": True})

    def _handle_type_text(self, data: dict):
        hwnd = data.get("hwnd")
        text = data.get("text", "")

        if not text:
            self._send_json({"error": "No text provided"})
            return

        if hwnd and data.get("activate", True):
            _activate_window(hwnd)
            time.sleep(0.1)

        saved = _clipboard_save()
        _set_clipboard_text(text)
        time.sleep(0.05)

        ctrl_sc = KEYMAP.get("control_l", 0x1D)
        v_sc = KEYMAP.get("v", 0x2F)
        _send_key(ctrl_sc)
        _send_key(v_sc)
        time.sleep(0.05)
        _send_key(v_sc, up=True)
        _send_key(ctrl_sc, up=True)
        time.sleep(0.1)

        _clipboard_restore(saved)
        self._send_json({"ok": True, "length": len(text)})

    def _handle_press_key(self, data: dict):
        hwnd = data.get("hwnd")
        keys = data.get("keys", "")

        if not keys:
            self._send_json({"error": "No keys provided"})
            return

        if hwnd and data.get("activate", True):
            _activate_window(hwnd)
            time.sleep(0.1)

        parts = keys.replace(" ", "").split("+")
        scancodes = []
        for part in parts:
            sc = KEYMAP.get(part.lower(), KEYMAP.get(part))
            if sc is None:
                if len(part) == 1:
                    sc = KEYMAP.get(part.lower())
                if sc is None:
                    self._send_json({"error": f"Unknown key: {part}"})
                    return
            scancodes.append(sc)

        for sc in scancodes:
            _send_key(sc)
            time.sleep(0.02)
        for sc in reversed(scancodes):
            _send_key(sc, up=True)
            time.sleep(0.02)

        self._send_json({"ok": True, "keys": keys})

    def _handle_scroll(self, data: dict):
        hwnd = data.get("hwnd")
        x = data.get("x", 0)
        y = data.get("y", 0)
        delta = data.get("delta", 120)
        clicks = data.get("clicks", 3)

        if hwnd:
            rect = _get_window_rect(hwnd)
            logical_rect = ctypes.wintypes.RECT()
            user32.GetWindowRect(hwnd, ctypes.byref(logical_rect))
            log_w = logical_rect.right - logical_rect.left
            log_h = logical_rect.bottom - logical_rect.top

            ss_w = data.get("screenshot_width") or (1280 if log_w > 1280 else log_w)
            ss_h = data.get("screenshot_height") or (int(log_h * 1280 / log_w) if log_w > 1280 else log_h)

            real_x = int(x * log_w / ss_w) + rect.left
            real_y = int(y * log_h / ss_h) + rect.top

            if data.get("activate", True):
                _activate_window(hwnd)
                time.sleep(0.1)

            user32.SetCursorPos(real_x, real_y)
            time.sleep(0.05)
            for _ in range(abs(clicks)):
                _mouse_scroll(real_x, real_y, delta if clicks > 0 else -delta)
                time.sleep(0.05)
            self._send_json({"ok": True, "screen_x": real_x, "screen_y": real_y})
        else:
            user32.SetCursorPos(x, y)
            time.sleep(0.05)
            for _ in range(abs(clicks)):
                _mouse_scroll(x, y, delta if clicks > 0 else -delta)
                time.sleep(0.05)
            self._send_json({"ok": True})

    def _handle_activate(self, data: dict):
        hwnd = data.get("hwnd")
        if not hwnd:
            self._send_json({"error": "No hwnd provided"})
            return
        if not user32.IsWindow(hwnd):
            self._send_json({"error": f"Window {hwnd} no longer exists"})
            return
        result = _activate_window(hwnd)
        buf = ctypes.create_unicode_buffer(512)
        user32.GetWindowTextW(hwnd, buf, 512)
        self._send_json({"ok": result, "title": buf.value})

    def _handle_clipboard(self, data: dict):
        action = data.get("action", "get")
        if action == "get":
            saved = _clipboard_save()
            if saved:
                try:
                    text = saved.decode("utf-16-le").rstrip("\x00")
                except Exception:
                    text = ""
                self._send_json({"text": text})
            else:
                self._send_json({"text": ""})
        elif action == "save":
            saved = _clipboard_save()
            save_path = os.path.join(os.path.expanduser("~"), ".win-auto-clipboard")
            with open(save_path, "wb") as f:
                f.write(saved if saved else b"")
            self._send_json({"ok": True})
        elif action == "restore":
            save_path = os.path.join(os.path.expanduser("~"), ".win-auto-clipboard")
            if os.path.exists(save_path):
                with open(save_path, "rb") as f:
                    saved_data = f.read()
                _clipboard_restore(saved_data if saved_data else None)
                os.remove(save_path)
                self._send_json({"ok": True})
            else:
                self._send_json({"error": "No saved clipboard"})

    def _handle_set_clipboard(self, data: dict):
        text = data.get("text", "")
        _set_clipboard_text(text)
        self._send_json({"ok": True, "length": len(text)})

    def _handle_list_apps(self):
        from common import _enum_windows
        windows = _enum_windows()
        by_pid = {}
        for w in windows:
            pid = w["pid"]
            if pid not in by_pid:
                by_pid[pid] = {
                    "app_name": w.get("process_name", ""),
                    "app_path": w.get("process_path", ""),
                    "is_running": True,
                    "windows": [],
                }
            by_pid[pid]["windows"].append({
                "hwnd": w["hwnd"], "title": w["title"], "pid": pid,
                "rect": w.get("rect", {}),
            })
        self._send_json(list(by_pid.values()))

    def _handle_screenshot_b64(self, hwnd: int, max_width: int):
        if not user32.IsWindow(hwnd):
            self._send_json({"error": f"Window {hwnd} no longer exists"})
            return
        result = _capture_screenshot(hwnd, max_width)
        if "error" in result:
            self._send_json(result)
            return
        try:
            with open(result["path"], "rb") as f:
                png_data = f.read()
            self._send_json({
                "text": "Captured window screenshot.",
                "base64": base64.b64encode(png_data).decode("ascii"),
                "width": result["width"],
                "height": result["height"],
                "dpi_scale": result.get("dpi_scale", 1.0),
            })
        except Exception as e:
            self._send_json({"error": str(e)})

    def _handle_get_state(self, params: dict):
        state = _load_state()
        key = params.get("key", [None])[0]
        if key:
            if key in state:
                self._send_json({key: state[key]})
            else:
                self._send_json({"error": f"Key '{key}' not found"})
        else:
            self._send_json({"state": state})

    def _handle_set_state(self, data: dict):
        state = _load_state()
        state.update(data)
        _save_state(state)
        self._send_json({"ok": True, "state": state})

    def _handle_batch(self, data: dict):
        commands = data.get("commands", [])
        results = []
        for cmd in commands:
            cmd_path = cmd.get("path", "")
            cmd_data = cmd.get("data", {})
            result = self._dispatch_command(cmd_path, cmd_data)
            results.append({"path": cmd_path, "result": result})
        self._send_json({"results": results})

    def _dispatch_command(self, path: str, data: dict) -> dict:
        dispatch = {
            "/activate": self._handle_activate,
            "/click": self._handle_click,
            "/type_text": self._handle_type_text,
            "/press_key": self._handle_press_key,
            "/scroll": self._handle_scroll,
            "/clipboard": self._handle_clipboard,
            "/set_clipboard": self._handle_set_clipboard,
        }
        handler = dispatch.get(path)
        if not handler:
            return {"error": f"Unknown command path: {path}"}

        captured = {}

        def capturing_send(data_arg, status=200):
            captured["response"] = data_arg

        original_send = self._send_json
        self._send_json = capturing_send
        try:
            handler(data)
        except Exception as e:
            captured["response"] = {"error": str(e)}
        finally:
            self._send_json = original_send

        return captured.get("response", {"error": "No response"})


# ---------------------------------------------------------------------------
# Main
# ---------------------------------------------------------------------------
def main():
    port = 18765
    if "--port" in sys.argv:
        idx = sys.argv.index("--port")
        if idx + 1 < len(sys.argv):
            port = int(sys.argv[idx + 1])

    server = HTTPServer(("127.0.0.1", port), HelperHandler)
    print(f"Helper server running on http://127.0.0.1:{port}")

    try:
        server.serve_forever()
    except KeyboardInterrupt:
        pass
    finally:
        server.server_close()
        _cleanup()


if __name__ == "__main__":
    main()
