# 💻 电脑控制技能 (win-automation-mcp)

极速、像素级精准、零垃圾文件的 Windows 桌面自动化 MCP 服务器，为大语言模型（如 Claude 3.5 Sonnet、Cursor、Windsurf 等）赋予完美的物理级 Windows 电脑控制技能。

---

## 🌟 核心突破与亮点 (Core Features)

1. **🎯 像素级精准点击 (Pixel-Perfect Clicks)**:
   - 彻底解决了 Windows 10/11 窗口中 **7~8 像素隐形阴影边框 (Invisible Shadow Border)** 导致的点击偏移问题。
   - 引入 Desktop Window Manager (DWM) API `DwmGetWindowAttribute` 获取 **DWMWA_EXTENDED_FRAME_BOUNDS** 真实物理边界，完美对齐屏幕。
2. **🧹 零垃圾文件策略 (Zero Trash File Policy)**:
   - **后台感知零残留**：所有的临时运行截图均自动保存在系统临时文件夹（`tempfile.gettempdir()/win-automation-mcp`）中，绝不污染您的桌面。
   - **工作区自动清扫**：MCP 服务器每次启动时，会自动清扫工作区内所有由 AI 视觉推理产生的临时 cropped `.png` 图片碎片，随时保持开发目录的整洁。
3. **💾 磁盘级状态持久化 (Persistent HWND Sync)**:
   - 全局共享 `~/.win-auto-state.json` 状态。`hwnd` 在所有交互接口中为 **完全可选参数**，一旦激活目标应用，后续命令自动继承，会话重置也能完美秒级恢复。
4. **🚀 极速与高兼容性截图管道 (dxCam + PrintWindow + BitBlt + JPEG 极速引擎)**:
   - 结合 GPU 加速与 GDI 降级机制，支持 **JPEG 与 PNG 双格式智能编码**。
   - 默认采用高度优化的 JPEG 编码（文件体积仅为 PNG 的 1/10），不仅彻底杜绝了大语言模型 API 因 Payload 超限引发的 `400 Param Incorrect` 报错，还将视觉理解传输速度提升了 10 倍以上！
5. **🛡️ 暴露动作安全预检 (`check_safety`)**:
   - 原生集成安全分类预检工具，拦截高危动作（数据删除、未知软件安装、交易等）并标准化返回确认信号，保护系统安全。

---

## 🛠️ 快速安装与配置

### 1. 自动安装（推荐）
双击运行当前文件夹下的 **`install.bat`**。它会：
* 自动检测 Python 3.12+ 环境并安装核心依赖（`mcp`, `comtypes`, `pillow`, `pyautogui`）。
* **动态计算当前绝对路径**，并生成您的 Cursor 或 Claude Desktop 专用的 JSON 配置文件块，完全免去手动复制路径的烦恼。

### 2. 配置 AI 编辑器 (Claude Desktop / Cursor / Windsurf)
在自动安装完成后，将控制台输出的 JSON 块复制到您的 AI 软件配置文件中。例如 `%USERPROFILE%\.claude\settings.local.json` 或 Cursor 的 MCP 页面中：

```json
{
  "mcpServers": {
    "win-automation": {
      "command": "python",
      "args": ["<项目绝对路径>/server.py"]
    }
  }
}
```

> 将 `<项目绝对路径>` 替换为您本机的实际路径。`install.bat` 会自动生成正确的配置。

---

## ⚙️ 工具与指令接口 (MCP Tools)

本服务器向 AI 暴露了以下全套物理控制工具：

| 工具名称 | 功能描述 | 核心参数 |
| :--- | :--- | :--- |
| `list_apps` | 列出当前正在运行的所有可见应用程序，并按进程分组 | 无 |
| `list_windows` | 扁平化列出所有打开的窗口句柄、PID 及对应进程信息 | 无 |
| `get_window` | 自动验证、重绑或获取特定句柄（HWND）的详细可见状态 | `hwnd` (可选) |
| `get_window_state` | 捕获当前窗口的实时截图并生成 Ephemeral（临时级）无障碍树索引 | `hwnd` (可选), `include_screenshot` |
| `click` | 在指定坐标或基于无障碍树 Ephemeral Index 精准点击 UI 元素，**支持双击**（`clicks=2`）| `hwnd` (可选), `x`, `y`, `index`, `clicks` |
| `type_text` | 将文本内容高效、无阻碍地键入至当前激活的输入框（中文/Unicode 100% 支持）| `text`, `hwnd` (可选) |
| `press_key` | 执行单键或组合键快捷键动作（如 `Control_L+v`, `Alt_L+F4`） | `keys`, `hwnd` (可选) |
| `scroll` | 在指定的窗口物理坐标上模拟鼠标滚轮滚动 | `x`, `y`, `scroll_y`, `hwnd` (可选) |
| `drag` | 在指定的两点物理坐标间执行平滑拖拽 | `start_x`, `start_y`, `end_x`, `end_y` |
| `activate_window` | 通过 AttachThreadInput 强行激活并将窗口置顶 | `hwnd` |
| `check_safety` | 在动作前预先验证操作是否具有系统级潜在威胁 | `action` |

---

## 📝 许可证 (License)

MIT License. 100% 离线、本地化运行，零云端 API 依赖，完全保护隐私。

