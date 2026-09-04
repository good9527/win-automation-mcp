# 💻 Windows Desktop Automation MCP (win-automation-mcp)

<p align="center">
  <strong>极速、像素级精准、完全离线的 Windows 桌面物理控制 MCP 服务器</strong><br>
  为 Claude 3.5 / 3.7、Cursor、Windsurf、Trae 等大模型赋予物理级 Windows 桌面自动化操控技能
</p>

<p align="center">
  <img src="https://img.shields.io/badge/Platform-Windows%2010%20%7C%2011-0078D6?logo=windows&logoColor=white" alt="Windows 10/11" />
  <img src="https://img.shields.io/badge/Python-3.12%2B-blue?logo=python&logoColor=white" alt="Python 3.12+" />
  <img src="https://img.shields.io/badge/MCP-FastMCP%20Ready-success" alt="MCP Ready" />
  <img src="https://img.shields.io/badge/Token%20Saved-96%25-brightgreen" alt="Token Saved 96%" />
  <img src="https://img.shields.io/badge/Network-100%25%20Offline-orange" alt="100% Offline" />
  <img src="https://img.shields.io/badge/License-MIT-green" alt="License MIT" />
</p>

---

## 📑 目录 (Table of Contents)

- [🌟 核心突破与亮点](#-核心突破与亮点)
- [⚡ 双 Profile 工具架构 (Compact vs Expert)](#-双-profile-工具架构)
- [🚀 3 分钟极速上手](#-3-分钟极速上手)
  - [1. 安装与依赖环境](#1-安装与依赖环境)
  - [2. 配置 AI 编辑器 (Claude / Cursor / Windsurf)](#2-配置-ai-编辑器)
- [🧰 核心工具概览 (Compact Profile)](#-核心工具概览-compact-profile)
- [🛡️ 安全与权限保护](#️-安全与权限保护)
- [💻 CLI 命令行使用指南](#-cli-命令行使用指南)
- [📚 全量 111 个原子工具参考 (Expert Profile)](#-全量-111-个原子工具参考)
- [📝 许可证与隐私说明](#-许可证与隐私说明)

---

## 🌟 核心突破与亮点

> [!TIP]
> 本项目专为大语言模型桌面自动化（Agent Desktop Automation）量身定制，解决原生 Windows 自动化中“漂移、乱码、卡顿、垃圾文件多、Token 爆炸”五大痛点。

* **🎯 像素级精准定位 (Pixel-Perfect Clicks)**
  * 调用 Windows DWM API `DwmGetWindowAttribute`（`DWMWA_EXTENDED_FRAME_BOUNDS`），精准剔除 Win10/11 窗口自带的 **7~8 像素隐形阴影边框**，点击彻底告别偏位。
* **⚡ 极致轻量与 Token 暴降 96%**
  * 引入 **Compact 高意图架构**，将原 113,000 字符的巨型 Schema 精简至 **4,471 字符**（Token 消耗从 ~30,000 降至 ~1,100），极大减少模型上下文浪费与工具幻觉。
* **🏎️ 毫秒级内存 WinRT OCR + 智能视觉管道**
  * 原生绑定 Windows COM 内存级 WinRT OCR 引擎，无需冷启动 PowerShell 子进程，OCR 识别延迟实测 **< 10ms**。
  * 结合 DirectX **DXCam 实例单例复用** 与 GDI 句柄严密释放，截图采用高效 JPEG 压缩（体积仅 PNG 的 1/10），杜绝 Payload 超限报错。
* **🛡️ 双向防线：中英高危安全拦截 + Helper 隔离**
  * 内置 **中英双语高危分类引擎**，自动拦截“删除文件/格式化/支付/关机/修改注册表”等高危动作并标定风险级别。
  * 常驻提权服务采用 **256 位动态随机令牌 (`X-Helper-Token`) + 严格 `Host: 127.0.0.1` 校验**，根除本地提权漏洞与 DNS 重绑定攻击。
* **💾 原子状态持久化与 100% 向后兼容**
  * `~/.win-auto-state.json` 采用 `tempfile` + `os.replace` 原子覆写与跨进程文件锁，杜绝并发损坏。
  * 根目录 `server.py` 与 `tools.py` 封装为透明薄包装，**现有任何项目与 IDE 配置零修改直接可用**。
* **🧹 零垃圾文件策略 (Zero Trash Policy)**
  * 运行时截图统一重定向至系统临时目录，MCP 启动时自动清理历史残留碎片，保持工作区绝对洁净。

---

## ⚡ 双 Profile 工具架构

针对大模型认知负荷与深度桌面控制需求，设计了双模式热切换：

```text
┌────────────────────────────────────────────────────────┐
│               win-automation-mcp Server                │
└──────────────────────────┬─────────────────────────────┘
                           │
             ┌─────────────┴─────────────┐
             ▼                           ▼
  【Compact Profile】(默认推荐)   【Expert Profile】
   • 仅暴露 9 个高聚合意图工具     • 暴露全量 111 个原子工具
   • Schema 体积: ~4.4K 字符       • 适合复杂极客脚本编排
   • Token 消耗: ~1,100 Tokens     • 通过环境变量灵活开启
   • 自动降级: UIA → Win32 → OCR   • WIN_AUTO_PROFILE=expert
```

---

## 🚀 3 分钟极速上手

### 1. 安装与依赖环境

本项目支持 **Windows 10 / 11**，需安装 **Python 3.12+**。

在项目根目录下运行 **`install.bat`**，或在终端执行：

```powershell
pip install -r requirements.txt
```

> [!NOTE]
> `install.bat` 会自动检测依赖，并动态计算你当前的绝对路径，生成适合你电脑的 JSON 配置段，直接复制即可。

---

### 2. 配置 AI 编辑器

将以下配置加入到你的 AI 工具 MCP 配置文件中（将 `<项目所在绝对路径>` 替换为你本地克隆该项目的实际路径，如 `C:/path/to/win-automation-mcp`）：

#### 选项 A：默认推荐（Compact 模式，极省 Token，响应极速）

```json
{
  "mcpServers": {
    "win-automation": {
      "command": "python",
      "args": ["<项目所在绝对路径>/server.py"]
    }
  }
}
```

#### 选项 B：Expert 全量模式（111 个原子工具全暴露）

```json
{
  "mcpServers": {
    "win-automation": {
      "command": "python",
      "args": ["<项目所在绝对路径>/server.py"],
      "env": {
        "WIN_AUTO_PROFILE": "expert"
      }
    }
  }
}
```

* **Claude Desktop**: 粘贴至 `%APPDATA%\Claude\claude_desktop_config.json`
* **Cursor**: 在 Settings -> MCP -> Add New MCP Server，选择 `stdio`，写入命令与参数
* **Windsurf / Trae**: 粘贴至各自的 `mcp_config.json` 中

---

## 🧰 核心工具概览 (Compact Profile)

在默认的 Compact 模式下，AI 将使用以下 9 个高意图工具完成绝大多数复杂交互：

| 工具名称 | 功能说明 | 核心输入参数 |
| :--- | :--- | :--- |
| `observe_window` | 状态观察：一站式获取窗口元数据、实时截图与 UIA 结构摘要 | `hwnd` (可选), `view` (raw/control/content) |
| `act` | 智能动作：按意图触发控件，自动在 UIA → Win32 → OCR → 坐标间智能降级 | `intent` (click/select/invoke), `selector`, `hwnd` |
| `type_input` | 智能文本输入：优先通过 UIA Value 设置，自绘控件自动降级焦点输入 | `text`, `hwnd` (可选), `selector` |
| `key_press` | 按键与快捷键模拟：精确执行系统级组合键（如 `ctrl+s`、`alt+f4`） | `keys`, `hwnd` (可选) |
| `wait_state` | 状态守候：等待特定窗口、控件、文本或视觉帧达到稳定状态 | `target_type`, `condition`, `timeout` |
| `execute_batch` | 批处理工作流：原子执行多步骤复合图状任务，支持局部失败自愈 | `steps`, `stop_on_error` |
| `check_safety` | 安全前置门禁：在执行前验证当前操作是否具有破坏性或系统风险 | `action` (中英文操作描述) |
| `launch_app` | 应用启动与附着：启动指定应用并自动等待主窗口稳定绑定 | `path_or_name`, `timeout` |
| `doctor` | 全局自检诊断：一键巡检 Win32、UIA、DXCam、WinRT OCR 与 Helper 运行健康度 | 无 |

---

## 🛡️ 安全与权限保护

### 1. 中英双语敏感操作预检 (`check_safety`)
大模型在执行可能产生破坏后果的操作前，可调用 `check_safety` 进行验证：

```python
# 示例拦截场景
check_safety("删除系统文件")    # -> needs_confirmation: True, risk_level: "critical"
check_safety("支付订单 50 元")   # -> needs_confirmation: True, risk_level: "critical"
check_safety("format c:")       # -> needs_confirmation: True, risk_level: "critical"
check_safety("查看当前窗口状态") # -> needs_confirmation: False, risk_level: "none"
```

### 2. 高权限 Helper 守卫 (`helper.py`)
针对管理员窗口或特殊 UAC 界面，项目提供常驻安全守护进程：
- **安全握手**：每次启动生成 256-bit 随机密码，客户端请求必须携带 `X-Helper-Token` 请求头。
- **Host 防御**：严格拒绝非 `127.0.0.1` / `localhost` 请求，全面免疫恶意网页发起的跨站攻击。

---

## 💻 CLI 命令行使用指南

所有底层控制功能均可通过 `python tools.py <command>` 独立运行，便于调试与脚本自动化：

<details>
<summary><strong>🔍 窗口探测与观察命令</strong> (点击展开)</summary>

```bash
# 列出当前所有运行的应用与窗口
python tools.py list_apps
python tools.py list_windows

# 观察目标窗口 (截图 + 控件树)
python tools.py observe <hwnd>
python tools.py observe <hwnd> --view control

# 捕获屏幕截图
python tools.py screenshot <hwnd> output.jpg
python tools.py desktop-screenshot "%TEMP%\desktop.jpg"
```
</details>

<details>
<summary><strong>🖱️ 智能点击与输入命令</strong> (点击展开)</summary>

```bash
# 智能点击控件 (优先语义，带降级)
python tools.py smart-click <hwnd> --name "保存" --type button
python tools.py smart-wait-click <hwnd> --name "确定" --timeout 10

# 智能输入文本
python tools.py smart-text <hwnd> "C:\file.txt" --name "文件名" --type edit
python tools.py focused-input <hwnd> "hello world"

# 快捷键发送
python tools.py key-press "ctrl+s"
```
</details>

<details>
<summary><strong>👁️ 视觉与 OCR 识别命令</strong> (点击展开)</summary>

```bash
# 原生超快 WinRT OCR 文字识别
python tools.py ocr <hwnd> eng+chi_sim --engine windows
python tools.py ocr-find <hwnd> "提交" --engine windows
python tools.py ocr-click <hwnd> "提交" --timeout 10

# OpenCV 图标/按钮模板匹配
python tools.py locate-image <hwnd> icon.png 0.85
python tools.py image-click <hwnd> icon.png 0.85 --timeout 10
```
</details>

<details>
<summary><strong>🩺 诊断与自动化测试</strong> (点击展开)</summary>

```bash
# 环境自检诊断
python tools.py doctor

# 执行 142 项全量工业级测试
python tests/runner.py
```
</details>

---

## 📚 全量 111 个原子工具参考 (Expert Profile)

当启用 `WIN_AUTO_PROFILE=expert` 时，服务器将解锁全部 111 个原子控制接口。

<details>
<summary><strong>📋 点击展开查看 111 个完整工具清单</strong></summary>

### 1. 窗口与进程管理 (14 个)
- `list_apps`：按进程分组列出可见应用
- `list_windows`：平铺列出所有窗口句柄、PID 与类名
- `get_window`：查询特定句柄详情与物理位置
- `launch_app`：启动应用并等待窗口绑定
- `foreground_window`：获取当前前台激活窗口
- `activate_window`：多重策略强制激活窗口到前台
- `focus_hwnd`：修复窗口与子控件焦点链
- `related_windows`：查找同进程/Owner 相关弹出窗口
- `wait_window`：等待目标窗口创建并达到稳定尺寸
- `window_action`：直接移动、缩放、置顶、最小化/最大化窗口
- `window_from_point`：从屏幕坐标反查宿主窗口与子控件 HWND
- `control_boundary`：检测目标完整性级别、UAC 与 UIPI 边界
- `gui_thread_info`：分析 GUI 线程焦点与拖拽状态
- `window_selector_repair_find`：根据失败建议自愈窗口选择器

### 2. UI Automation (UIA) 结构化操控 (17 个)
- `find_elements`：按名称/AutomationId/类型/Pattern 检索元素
- `wait_for_element`：轮询等待 UIA 元素出现
- `get_element`：获取 UIA 元素完整元数据
- `focus_element`：将焦点移至目标 UIA 元素
- `set_value`：直接修改可编辑元素内容
- `perform_secondary_action`：调用 Toggle/Select/Expand 等原生动作
- `find_item_in_container`：在大列表/表格中快速检索项
- `uia_stable_wait`：等待 UIA 控件树变动稳定
- `desktop_accessibility`：获取系统桌面级 UIA 根节点树
- `desktop_find_elements`：桌面全局查找 UIA 元素
- `desktop_wait_for_element`：桌面全局等待 UIA 元素
- `desktop_get_element`：获取桌面元素元数据
- `desktop_focus_element`：聚焦桌面全局元素
- `desktop_click_element`：点击桌面全局元素
- `desktop_action`：对桌面元素执行结构化动作
- `desktop_uia_stable_wait`：等待全局桌面 UIA 树停止刷新
- `uia_selector_repair_find`：针对过期索引进行自愈重定位

### 3. 高级智能语义操作 (8 个)
- `smart_click`：UIA → Win32 → 坐标点击动作链
- `smart_wait_click`：轮询等待并执行智能点击
- `smart_text_input`：UIA → Win32 文本写入链
- `smart_wait_text_input`：轮询等待并智能输入文本
- `smart_select`：智能单选/多选/勾选树与列表项
- `smart_wait_select`：轮询等待并智能选择
- `smart_cell`：智能读取/修改表格与网格单元格
- `smart_wait_cell`：轮询等待并操作网格单元格

### 4. 屏幕捕获与视觉定位 (17 个)
- `observe_window`：一键综合采集窗口截图与语义信息
- `get_window_state`：获取窗口截图并构建临时索引
- `locate_image`：OpenCV 模板图匹配定位
- `wait_image`：等待模板图出现
- `click_image`：匹配并点击模板图中心
- `image_scroll_click`：边滚动边搜索模板图并点击
- `pixel`：读取指定坐标的 RGB/HEX 颜色值
- `pixel_wait`：等待指定像素变成目标颜色
- `visual_stable_wait`：等待屏幕画面帧间停止变动
- `desktop_screenshot`：捕获完整虚拟桌面
- `desktop_point`：多显示器物理坐标转换
- `desktop_pixel`：读取桌面像素色彩
- `desktop_pixel_wait`：等待桌面像素变化
- `desktop_visual_stable_wait`：等待桌面视觉画面稳定
- `desktop_locate_image`：桌面全屏模板匹配
- `desktop_wait_image`：桌面等待模板图
- `desktop_click_image`：桌面模板匹配后点击

### 5. 极速 OCR 与文字识别 (11 个)
- `ocr`：自动调度 WinRT / Tesseract OCR
- `find_text_ocr`：按可见文字定位其屏幕坐标
- `wait_text_ocr`：等待指定文字出现
- `click_text_ocr`：找到文字后直接点击
- `ocr_scroll_click`：边滚动列表边 OCR 查找并点击
- `visual_row`：利用行号锚点定位自绘表格行
- `visual_row_click`：点击自绘表格指定行
- `visual_row_scroll`：滚动表格至指定行可见
- `visual_row_scroll_click`：滚动至指定行并点击
- `desktop_ocr`：全桌面文本识别
- `desktop_find_text_ocr` / `desktop_wait_text_ocr` / `desktop_click_text_ocr`：桌面级文字定位与交互

### 6. Win32 原生控件与经典消息 (13 个)
- `child_windows`：枚举原生 Win32 子控件
- `win32_text` / `win32_set_text`：WM_GETTEXT / WM_SETTEXT 快速读写
- `win32_click`：BM_CLICK 物理级无损点击
- `menu_tree` / `menu_action`：经典 HMENU 树提取与触发
- `file_dialog_info` / `file_dialog_action`：经典打开/保存弹窗自动化
- `dialog_command_action` / `dialog_button_action`：直接派发标准对话框按钮指令
- `win32_control_find` / `win32_control_info` / `win32_control_action` / `win32_control_wait`：深层 Win32 控件读写

### 7. 物理键盘/鼠标模拟与事件流 (17 个)
- `click` / `desktop_click`：精确坐标点击（支持左右键与双击）
- `type_text`：模拟打字或高兼容剪贴板粘贴
- `press_key`：发送物理按键与快捷键
- `scroll` / `desktop_scroll`：精确鼠标滚轮滚动
- `drag` / `desktop_drag`：平滑鼠标拖拽
- `focused_input`：向当前焦点控件直接写入
- `mouse_position` / `screen_info`：获取鼠标坐标与屏幕分辨率
- `wait_event`：系统级 WinEvent 钩子监听等待
- `msaa_window` / `msaa_from_point` / `msaa_action`：旧式 MSAA 接口无障碍兼容

### 8. 系统安全、诊断与批处理 (4 个)
- `check_safety`：执行前中英安全拦截与风险定级
- `helper_status`：管理并重载常驻安全提权服务
- `doctor`：环境运行能力综合体检
- `execute_batch`：执行多任务复合工作流

</details>

---

## 📝 许可证与隐私说明

- **许可证**：[MIT License](LICENSE)
- **隐私保护**：**100% 离线运行**。所有屏幕捕获、OCR 识别与输入模拟均在您的本地计算设备完成，没有任何数据会回传至任何第三方云端。
- **开源协作**：欢迎提交 Issue 与 Pull Request 共同改进 Windows AI 控制生态！
