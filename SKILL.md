---
name: win-automation
description: Control Windows applications - screenshots, UI automation, keyboard/mouse input
---

# Windows Automation

Use this skill to automate Windows applications via Python scripts.

## Quick Start

The automation scripts are located at:
```
C:/Users/19901/Desktop/win-automation-mcp/
```

**Helper server auto-starts** when you use input commands (click/type/key/scroll/drag).
No manual setup needed — just run commands directly.

## Commands

### 1. List Windows
```bash
python "C:/Users/19901/Desktop/win-automation-mcp/tools.py" list_windows
```
Returns: `[{hwnd, title, pid, process_name, process_path, rect}]`

### 2. List Apps (grouped by process)
```bash
python "C:/Users/19901/Desktop/win-automation-mcp/tools.py" list_apps
```
Returns:
```json
[{
  "app_name": "cloudmusic.exe",
  "app_path": "C:\\Program Files\\NetEase\\CloudMusic\\cloudmusic.exe",
  "is_running": true,
  "windows": [{"hwnd": 131472, "title": "...", "pid": 21000, "rect": {...}}]
}]
```

### 3. Screenshot
```bash
python "C:/Users/19901/Desktop/win-automation-mcp/tools.py" screenshot <hwnd> [output.png]
```
Returns: `{id, path, width, height, dpi_scale, window_hwnd}`

### 4. Screenshot (base64)
```bash
python "C:/Users/19901/Desktop/win-automation-mcp/tools.py" screenshot_b64 <hwnd>
```
Returns: `{base64, width, height, dpi_scale}` — PNG encoded as base64 string.

### 5. Accessibility Tree
```bash
python "C:/Users/19901/Desktop/win-automation-mcp/tools.py" accessibility <hwnd>
```
Returns: element tree with indexes + focused_element + selected_text

### 6. Click
```bash
python "C:/Users/19901/Desktop/win-automation-mcp/tools.py" click <hwnd> <x> <y> [button] [screenshot_id]
```
- Coordinates are in screenshot space, auto-scaled to window
- Uses helper server for cross-process input (works with Chromium/NW.js apps)

### 7. Type Text (Unicode/Chinese supported)
```bash
python "C:/Users/19901/Desktop/win-automation-mcp/tools.py" type <hwnd> "text"
```
Uses clipboard paste via helper server — works in all app types.

### 8. Press Key
```bash
python "C:/Users/19901/Desktop/win-automation-mcp/tools.py" key <hwnd> "Control_L+c"
```
Keys: Return, Escape, space, Tab, BackSpace, Delete, Up, Down, Left, Right, F1-F12, KP_0-KP_9, Menu, etc.

### 9. Scroll
```bash
python "C:/Users/19901/Desktop/win-automation-mcp/tools.py" scroll <hwnd> <x> <y> <dy> [screenshot_id]
```
dy>0 scrolls up, dy<0 scrolls down. Cursor moves to position first.

### 10. Drag
```bash
python "C:/Users/19901/Desktop/win-automation-mcp/tools.py" drag <hwnd> <x1> <y1> <x2> <y2> [duration]
```

### 11. Activate Window
```bash
python "C:/Users/19901/Desktop/win-automation-mcp/tools.py" activate <hwnd>
```
Uses AttachThreadInput trick for reliable activation.

### 12. Get Window Info
```bash
python "C:/Users/19901/Desktop/win-automation-mcp/tools.py" get_window <hwnd>
```
Returns window title, position, size, process info, and DPI scale.

### 13. Batch Operations
Execute multiple commands in a single call:
```bash
python "C:/Users/19901/Desktop/win-automation-mcp/tools.py" batch '[{"command":"activate","args":{"hwnd":131472}},{"command":"key","args":{"hwnd":131472,"keys":"space"}}]'
```
Each item is `{"command": "<name>", "args": {...}}`. Supported commands: `activate`, `click`, `type`, `key`, `scroll`, `screenshot`.

### 14. State Management
Persistent state that survives between tool calls:
```bash
# Set target window (click/type/key/scroll auto-use this when no hwnd given)
python "C:/Users/19901/Desktop/win-automation-mcp/tools.py" state target <hwnd>

# Get state
python "C:/Users/19901/Desktop/win-automation-mcp/tools.py" state get
python "C:/Users/19901/Desktop/win-automation-mcp/tools.py" state get target_hwnd

# Set arbitrary key/value
python "C:/Users/19901/Desktop/win-automation-mcp/tools.py" state set last_screenshot '{"id":1,"path":"..."}'
```

### 15. Safety Check
Check if an action requires user confirmation:
```bash
python "C:/Users/19901/Desktop/win-automation-mcp/tools.py" confirm "delete file.txt"
```
Returns `{needs_confirmation: true/false, category, description}`.

## Workflow Example

```bash
# Step 1: Find target window
python "C:/Users/19901/Desktop/win-automation-mcp/tools.py" list_windows

# Step 2: Set target window for auto-resolution
python "C:/Users/19901/Desktop/win-automation-mcp/tools.py" state target <hwnd>

# Step 3: Screenshot (helper auto-starts if needed)
python "C:/Users/19901/Desktop/win-automation-mcp/tools.py" screenshot <hwnd>

# Step 4: Interact (hwnd now auto-resolved from state)
python "C:/Users/19901/Desktop/win-automation-mcp/tools.py" click <hwnd> 100 200
python "C:/Users/19901/Desktop/win-automation-mcp/tools.py" type <hwnd> "Hello World"
python "C:/Users/19901/Desktop/win-automation-mcp/tools.py" key <hwnd> "Return"

# Or use batch for multiple actions at once:
python "C:/Users/19901/Desktop/win-automation-mcp/tools.py" batch '[
  {"command":"activate","args":{"hwnd":131472}},
  {"command":"type","args":{"hwnd":131472,"text":"Hello"}},
  {"command":"key","args":{"hwnd":131472,"keys":"Return"}}
]'
```

## Architecture

```
tools.py (CLI) ──HTTP──▶ helper.py (常驻后台) ──SendInput──▶ 目标应用
                         (端口 18765)
```

- **helper.py**: 在桌面会话中持续运行，处理所有输入操作
- **tools.py**: 每次 Bash 调用时，自动检测并连接 helper
- 如果 helper 未运行，输入命令会自动启动它
- **State**: 持久化状态存储在 `~/.win-auto-state.json`

## Key Format

X11 keysym-style names with `+` separator:
- `Control_L+c` → Ctrl+C
- `Control_L+Shift_L+s` → Ctrl+Shift+S
- `Alt_L+F4` → Alt+F4
- `Return` → Enter
- `Escape` → ESC
- `space` → Space
- `KP_0` through `KP_9` → Numpad keys
- `Menu` → Context menu key

## Safety Confirmations

The following actions require explicit user confirmation before execution:
- **Delete data**: Any action that deletes files, messages, or data
- **Install software**: Running newly downloaded executables
- **Financial**: Any monetary transactions or subscriptions
- **Account creation**: Creating new accounts or API keys
- **Send messages**: Posting comments, sending messages to others
- **System settings**: Changing security/privacy settings

Use `python tools.py confirm "<action>"` to check if an action needs confirmation.
The tool returns `{needs_confirmation: true, category, description}` when confirmation is required.
The LLM should ask the user before proceeding with any confirmed-dangerous action.

## Technical Details

- **Input**: Via persistent helper process (SendInput in same desktop session)
- **Screenshots**: dxcam (fastest) → PrintWindow → BitBlt fallback
- **Activation**: AttachThreadInput trick for reliable foreground switching
- **DPI**: Per-monitor DPI aware, scale factor returned with screenshots
- **Clipboard**: Saved and restored after paste operations
- **Unicode**: Full support via KEYEVENTF_UNICODE input
- **State**: Persistent JSON state at `~/.win-auto-state.json` for target hwnd and more
- **Batch**: Execute multiple commands in one call via helper server or local fallback

## Error Handling

- Helper not running → auto-started on first input command
- Window closed → error message with recovery guidance
- Element stale → "Call accessibility to refresh"
- Screenshot failed → dxcam → PrintWindow → BitBlt fallback attempted automatically
- No hwnd given → falls back to stored target_hwnd from state
