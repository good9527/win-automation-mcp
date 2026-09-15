<div align="center">

# 💻 win-automation-mcp

### Windows 桌面自动化 MCP 服务器

极速、高精度、完全离线的 Windows 桌面自动化 MCP (Model Context Protocol) 服务器。
让 Claude Desktop、Cursor、Antigravity 等 AI 助手直接控制你的 Windows 电脑。

[![License](https://img.shields.io/badge/License-MIT-a855f7?style=flat-square)](LICENSE)
[![Platform](https://img.shields.io/badge/Platform-Windows-0078D4?style=flat-square)]()
[![Python](https://img.shields.io/badge/Python-3.10+-3776AB?style=flat-square&logo=python&logoColor=white)]()

</div>

---

## ✨ 功能特性

| 工具 | 功能 | 说明 |
|:---|:---|:---|
| `list_apps` | 📋 列出运行中的应用 | 获取所有应用及其窗口句柄 |
| `list_windows` | 🪟 列出所有可见窗口 | 包含窗口标题、类名、位置 |
| `get_window_state` | 📸 截图 + 无障碍树 | 带元素索引的完整窗口状态 |
| `click` | 🖱️ 点击操作 | 支持坐标点击和元素索引点击 |
| `type_text` | ⌨️ 文本输入 | 完全支持中文和 Unicode |
| `press_key` | 🎹 快捷键 | X11 keysym 风格，如 `Control_L+c` |
| `scroll` | 📜 滚动 | 支持垂直和水平滚动 |
| `drag` | ↔️ 拖拽 | 从起点到终点的拖拽操作 |
| `launch_app` | 🚀 启动应用 | 启动任意 Windows 程序 |
| `activate_window` | 🔝 窗口置前 | 将指定窗口带到最前 |
| `set_value` | ✏️ 设置值 | 设置可编辑元素的内容 |
| `perform_secondary_action` | ⚡ 辅助操作 | 执行元素的次要动作 |

## 🚀 快速开始

### 安装依赖

```bash
pip install mcp comtypes pillow pyautogui
```

### 配置 Claude Desktop

编辑 `%APPDATA%\Claude\claude_desktop_config.json`：

```json
{
  "mcpServers": {
    "win-automation": {
      "command": "python",
      "args": ["C:/path/to/win-automation-mcp/server.py"]
    }
  }
}
```

### 配置 Cursor

在 Cursor Settings → MCP Servers 中添加：

```json
{
  "win-automation": {
    "command": "python",
    "args": ["C:/path/to/win-automation-mcp/server.py"]
  }
}
```

### 配置 Antigravity

在 `.antigravity/settings.json` 中添加：

```json
{
  "mcpServers": {
    "win-automation": {
      "command": "python",
      "args": ["C:/path/to/win-automation-mcp/server.py"]
    }
  }
}
```

## 📖 使用示例

### 1. 发现应用
```
list_apps() → 获取所有运行中的应用和窗口句柄
```

### 2. 获取窗口状态（截图 + 无障碍树）
```
get_window_state(hwnd=12345, include_screenshot=True, include_accessibility=True)
```

### 3. 交互操作
```python
click(hwnd=12345, x=100, y=200)           # 坐标点击
click(hwnd=12345, index=5)                  # 元素索引点击
type_text(hwnd=12345, text="你好世界")       # 输入中文
press_key(hwnd=12345, keys="Control_L+c")   # 复制
scroll(hwnd=12345, x=500, y=300, scroll_y=-3)  # 向上滚动
```

## 🔧 技术细节

- **截图引擎**：使用 Windows PrintWindow API，支持截取被遮挡窗口
- **坐标系统**：所有坐标相对于窗口客户区（不含标题栏和边框）
- **中文输入**：通过剪贴板粘贴方式输入，完全支持 Unicode
- **元素索引**：基于无障碍树深度优先遍历，每次 `get_window_state` 刷新
- **默认截图宽度**：最大 1280 像素，可通过 `max_screenshot_width` 参数调整

## 🔗 相关项目

| 项目 | 简介 |
|:---|:---|
| [Antigravity-Chinese-Patch](https://github.com/good9527/Antigravity-Chinese-Patch) | Google Antigravity 深度汉化补丁 |
| [Claude-Desktop-Chinese](https://github.com/good9527/Claude-Desktop-Chinese) | Claude Desktop 全量汉化包 |

## 📄 许可证

MIT License © 2026 good9527
