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
   - 结合多显示器感知的 GPU 桌面捕获与 GDI 降级机制，支持 **JPEG 与 PNG 双格式智能编码**，截图结果会返回 `capture_method` 便于排障。
   - 默认采用高度优化的 JPEG 编码（文件体积仅为 PNG 的 1/10），不仅彻底杜绝了大语言模型 API 因 Payload 超限引发的 `400 Param Incorrect` 报错，还将视觉理解传输速度提升了 10 倍以上！
5. **🖥️ 系统级桌面全屏控制层**:
   - 新增 `desktop_accessibility` / `desktop_find_elements` / `desktop_wait_for_element` / `desktop_get_element` / `desktop_focus_element` / `desktop_click_element` / `desktop_action`，可从 Windows UIA 桌面根扫描和操作任务栏、开始菜单、托盘弹出层、全局菜单、跨进程窗口和屏幕覆盖层，不必先绑定某个应用 HWND。
   - 新增 `desktop_screenshot` / `desktop_point` / `desktop_pixel` / `desktop_pixel_wait` / `desktop_locate_image` / `desktop_wait_image` / `desktop_click_image` / `desktop_ocr` / `desktop_find_text_ocr` / `desktop_wait_text_ocr` / `desktop_click_text_ocr` / `desktop_click` / `desktop_scroll` / `desktop_drag`，覆盖没有稳定 HWND 或 UIA 很浅的 Windows UI，并支持按全屏图标模板、像素颜色状态或可见文字定位。
6. **🛡️ 暴露动作安全预检 (`check_safety`)**:
   - 原生集成安全分类预检工具，拦截高危动作（数据删除、未知软件安装、交易等）并标准化返回确认信号，保护系统安全。
7. **🧭 UI Automation 结构化控制面**:
   - 新增 `find_elements` / `wait_for_element` / `get_element` / `focus_element`，可按名称、AutomationId、控件类型、Class、Value 和 UIA Pattern 定位控件。
   - 支持 `raw` / `control` / `content` 三种 UIA TreeView 扫描模式；大型 WPF/WinUI/Office/企业软件可用 `control` 或 `content` 降低噪声和扫描量，索引动作会按同一视图重扫，减少“找到 A、点到 B”的问题。
   - UIA index 会保存紧凑身份签名；动态 UI 刷新导致同一控件移动到新 index 时，可按 AutomationId、控件类型、Class、native HWND、名称相似度、Pattern、父容器/祖先路径、兄弟序号和矩形位置保守重定位，同时拒绝明显不同的同类控件，减少 stale index 点错。
   - 修正 UIA Pattern ID，并支持 `Value`、`RangeValue`、`Scroll`、`Text`、`Text2`、`TextChild`、`TextEdit`、`Selection`、`SelectionItem`、`Selection2`、`Grid`、`GridItem`、`Table`、`TableItem`、`Spreadsheet`、`SpreadsheetItem`、`Annotation`、`Styles`、`LegacyIAccessible`、`Transform`、`Transform2`、`Dock`、`Drag`、`DropTarget`、`CustomNavigation`、`SynchronizedInput`、`MultipleView`、`VirtualizedItem`、`Invoke`、`Toggle`、`ExpandCollapse`、`ScrollItem`、`Window` 等原生控件动作，减少纯坐标点击。
8. **🪟 Win32 HWND 原生兜底**:
   - 新增子窗口枚举、点位反查、`HMENU` 菜单树、`WM_COMMAND` 菜单触发、ComboBox/ListBox/Button/ListView/TreeView/TabControl/Toolbar/StatusBar/Trackbar/UpDown/Progress 状态读写、ListView/TreeView 复选框状态图像读写与 `check_state` 归一化、`WM_GETTEXT` / `WM_SETTEXT` / `BM_CLICK` 原生控件操作，覆盖经典安装器、文件对话框、旧式 Win32 软件、资源管理器式列表/树、标签页、工具栏、滑块/微调/进度控件和 UIA 噪声很大的窗口。
9. **⏱️ WinEvent 事件同步**:
   - 新增 `wait_event` / CLI `wait-event`，可全局或按 HWND/PID/标题/Class 等待前台切换、菜单/对话框开始结束、对象创建/销毁/显示/隐藏、焦点、选择、名称、值和位置变化，减少盲目 `sleep`，更稳地捕获弹窗、菜单、动态面板和二级窗口。
10. **👁️ 自绘界面视觉兜底**:
   - 新增像素采样/等待、连续截图视觉稳定等待、OpenCV 模板匹配、Windows 内置 OCR + 可选 Tesseract OCR，以及按可见文字定位/点击，用于微信小程序、Chromium Canvas、游戏、设计软件等无障碍树很浅的应用。

---

## 🛠️ 快速安装与配置

### 1. 自动安装（推荐）
双击运行当前文件夹下的 **`install.bat`**。它会：
* 自动检测 Python 3.12+ 环境并安装 `requirements.txt` 中的核心依赖（`mcp`, `comtypes`, `pillow`, `pyautogui`, `opencv-python`, `numpy`, `pytesseract`, `dxcam`）。
* **动态计算当前绝对路径**，并生成您的 Cursor 或 Claude Desktop 专用的 JSON 配置文件块，完全免去手动复制路径的烦恼。

### 2. 配置 AI 编辑器 (Claude Desktop / Cursor / Windsurf)
在自动安装完成后，将控制台输出的 JSON 块复制到您的 AI 软件配置文件中。例如 `%USERPROFILE%\.claude\settings.local.json` 或 Cursor 的 MCP 页面中：

```json
{
  "mcpServers": {
    "win-automation": {
      "command": "python",
      "args": ["H:/2026年项目/6.电脑控制技能/server.py"]
    }
  }
}
```

---

## ⚙️ 工具与指令接口 (MCP Tools)

本服务器向 AI 暴露了以下全套物理控制工具：

| 工具名称 | 功能描述 | 核心参数 |
| :--- | :--- | :--- |
| `list_apps` | 列出当前正在运行的所有可见应用程序，并按进程分组 | 无 |
| `list_windows` | 扁平化列出所有打开的窗口句柄、PID 及对应进程信息 | 无 |
| `get_window` | 自动验证、重绑或获取特定句柄（HWND）的详细可见状态 | `hwnd` (可选) |
| `launch_app` | 启动应用，等待可见窗口稳定，并在启动期顶层 HWND 重建时自动重绑 | `path_or_name` |
| `helper_status` | 检查常驻 helper 的 PID、`helper.py` / `tools.py` 源码 SHA-256、是否为当前版本；CLI 可用 `--restart` 主动重载 helper 或 `--elevated --start` 经 UAC 启动高权限 helper，MCP 可用 `restart/elevated/start` 做同样操作 | `restart`, `elevated`, `start` |
| `foreground_window` | 返回当前前台窗口的 HWND、进程、Class、可见状态和真实矩形 | 无 |
| `control_boundary` | 诊断目标 HWND 的完整性级别、管理员/elevated、UIAccess、UIPI 和桌面/安全桌面边界，解释为什么输入/UIA/Win32 消息可能失效 | `hwnd` (可选) |
| `gui_thread_info` | 通过 `GetGUIThreadInfo` 返回 GUI 线程 active/focus/capture/menu-owner/move-size/caret HWND 和 caret 矩形，排查键盘焦点与菜单/拖拽状态 | `hwnd`, `thread_id` |
| `focus_hwnd` | 通过前台锁修复链激活根窗口，并用 `SetActiveWindow`/`SetFocus` 修复顶层窗口或子控件 HWND 的 active/focus 状态，返回 `foreground_repair` 诊断 | `hwnd`, `timeout`, `restore` |
| `focused_input` | 根据 `GetGUIThreadInfo.hwndFocus` 将文本写入真实焦点控件；Edit/RichEdit/Combo 编辑框走 `EM_REPLACESEL`/`WM_SETTEXT`，自绘控件回退 Unicode `SendInput`，并返回验证和焦点诊断 | `text`, `hwnd`, `mode`, `timeout`, `verify` |
| `smart_text_input` | 按稳定选择器设置文本：优先 UIA ValuePattern，再走原生 Win32 文本控件，必要时才启用焦点输入兜底；可用 `control_type`/`class_name` 精准约束输入框 | `text`, `hwnd`, `name`, `automation_id`, `control_type`, `class_name`, `index`, `mode`, `allow_focus_fallback` |
| `smart_wait_text_input` | 轮询等待匹配输入框出现并执行 `smart_text_input` 同一套 UIA/Win32/焦点输入链，适合弹窗、路由切换或懒加载后的输入框；坏 UIA 可用 `skip_uia` 直走 Win32 | `text`, `hwnd`, `name`, `automation_id`, `control_type`, `class_name`, `index`, `mode`, `timeout`, `interval`, `allow_focus_fallback`, `skip_uia` |
| `smart_click` | 按稳定选择器触发控件：UIA 原生动作 → Win32 原生控件动作 → `BM_CLICK`，坐标兜底默认关闭；坏 UIA 可用 `skip_uia` | `hwnd`, `name`, `automation_id`, `control_type`, `class_name`, `index`, `action`, `skip_uia`, `allow_coordinate_fallback` |
| `smart_wait_click` | 轮询等待控件出现并执行 `smart_click` 同一套动作链，适合弹窗、菜单和异步面板 | `hwnd`, `name`, `automation_id`, `control_type`, `class_name`, `index`, `action`, `timeout`, `interval`, `skip_uia` |
| `smart_select` | 按稳定选择器选择下拉框、列表、树、标签页、工具栏、表头或链接项；`mode=check/uncheck/toggle` 会走 UIA Toggle 或 Win32 ListView/TreeView 复选框状态动作，不用 LegacyIAccessible 选择兜底猜测状态 | `hwnd`, `item`, `name`, `automation_id`, `control_type`, `class_name`, `index`, `mode`, `skip_uia` |
| `smart_wait_select` | 轮询等待可选项出现并执行 `smart_select` 同一套 UIA/Win32 选择/勾选链，适合异步下拉、延迟列表、动态树节点、标签页和带复选框的 ListView/TreeView | `hwnd`, `item`, `name`, `automation_id`, `control_type`, `class_name`, `index`, `mode`, `timeout`, `interval`, `skip_uia` |
| `smart_cell` | 按行号/行文本/列号/表头读、选中或设置表格/ListView/Grid 单元格：优先 UIA Grid/Table/Spreadsheet，扫描不到时可用 UIA ItemContainer 查找虚拟化行/单元格，并能在列元数据明确时从虚拟化行派生子单元格，再走原生 Win32 `SysListView32` 单元格读写 | `hwnd`, `row`, `column`, `row_text`, `column_name`, `text`, `action`, `skip_uia` |
| `smart_wait_cell` | 轮询等待表格/ListView/Grid 单元格出现并执行 `smart_cell` 同一套读、选中或设置动作链，适合异步加载表格、延迟行和动态列 | `hwnd`, `row`, `column`, `row_text`, `column_name`, `text`, `action`, `timeout`, `interval`, `skip_uia` |
| `related_windows` | 查找同进程、owner、root-owner 相关窗口，适合弹窗/文件选择器/菜单追踪 | `hwnd`, `include_invisible` |
| `wait_window` | 等待匹配标题或进程的可见顶层窗口出现并达到稳定矩形；超时时返回 `near_windows`、`failure_summary`、观测进程/标题和 `selector_suggestions` 供下一轮放宽或改用 HWND | `title`, `process`, `timeout`, `match` |
| `window_selector_repair_find` | 用 `wait_window` / `auto_window` 的 `failure_summary.selector_suggestions[0]` 清洗出 title/process/pid/HWND 后重新等待稳定顶层窗口；孤立 HWND 默认不盲信，除非建议同时带可验证 title/process/pid 或显式 `allow_suggestion_hwnd` | `suggestion`, `original`, `timeout`, `interval`, `stable_ticks`, `allow_suggestion_hwnd` |
| `wait_event` | 通过 `SetWinEventHook` 等待前台、菜单/对话框、对象显示/隐藏/创建/销毁、焦点、选择、名称、值或位置变化，并返回 direct/root/root-owner HWND 元数据 | `event`, `hwnd`, `pid`, `title`, `class_name`, `timeout`, `limit`, `match` |
| `window_action` | 直接移动、调整大小、Z-order/topmost、读取/恢复 placement、最小化、最大化、恢复、显示或请求关闭顶层 HWND，坐标按 DWM 可见窗口边界补偿阴影偏移 | `action`, `hwnd`, `x`, `y`, `width`, `height`, `timeout` |
| `screen_info` | 返回虚拟桌面、主屏和显示器数量 | 无 |
| `mouse_position` | 返回当前鼠标屏幕坐标 | 无 |
| `desktop_accessibility` | 从 Windows UIA 桌面根读取结构化无障碍树，适合任务栏、开始菜单、托盘弹层、全局菜单、覆盖层和跨进程窗口 | `max_depth`, `max_elements`, `view` |
| `desktop_find_elements` | 从桌面根按名称、AutomationId、控件类型、Class、Value、Pattern 查找 UIA 元素；英文控件类型别名可跨中文/英文系统匹配 UIA ID | `name`, `automation_id`, `control_type`, `class_name`, `value`, `pattern`, `match`, `limit`, `view` |
| `desktop_wait_for_element` | 轮询桌面根 UIA，等待系统 UI/跨窗口元素出现 | `name`, `automation_id`, `control_type`, `class_name`, `value`, `pattern`, `timeout`, `interval`, `view` |
| `desktop_get_element` | 返回桌面根 UIA 扫描中的某个 index 元数据 | `index` |
| `desktop_focus_element` | 将焦点设置到桌面根 UIA 元素，优先使用元素 native HWND 修复前台焦点 | `index` |
| `desktop_click_element` | 点击桌面根 UIA 元素的屏幕中心点 | `index`, `button`, `clicks` |
| `desktop_action` | 对桌面根 UIA 元素执行结构化动作，如 Invoke、Toggle、Select、SetValue、SetRange、Scroll、TextFind/TextSelect、ItemFind、SpreadsheetGetItem、CustomNavigate、Transform/Transform2、Dock、Window 和 LegacyIAccessible 动作 | `index`, `action`, `value`, `horizontal`, `vertical` |
| `desktop_screenshot` | 捕获完整虚拟桌面，适合任务栏、开始菜单、托盘弹出层、全局右键菜单、屏幕遮罩等没有稳定 HWND 的 UI；返回截图 ID 和 MCP 图片 | `max_screenshot_width`, `output_path` |
| `desktop_point` | 将桌面截图坐标映射回真实多显示器物理屏幕坐标 | `x`, `y`, `screenshot_id` |
| `desktop_pixel` | 读取桌面截图坐标处的 RGB/HEX 像素颜色 | `x`, `y`, `screenshot_id` |
| `desktop_pixel_wait` | 轮询完整桌面新截图，等待某个像素等于或不等于目标颜色，适合验证自绘按钮、开关、加载状态和主题色变化 | `x`, `y`, `color`, `tolerance`, `timeout`, `interval`, `mode`, `max_screenshot_width` |
| `desktop_visual_stable_wait` | 轮询完整桌面新截图，等待连续帧变化比例低于阈值，适合动画、加载遮罩、路由跳转和系统弹层稳定后再验证 | `timeout`, `interval`, `stable_ticks`, `difference_threshold`, `pixel_threshold`, `region`, `max_screenshot_width`, `comparison_max_width` |
| `desktop_uia_stable_wait` | 轮询桌面根 UIA 结构签名，等待任务栏、开始菜单、全局弹层或跨窗口 UI 的控件树停止刷新 | `timeout`, `interval`, `stable_ticks`, `max_depth`, `max_elements`, `view`, `include_values`, `rect_bucket` |
| `desktop_locate_image` | 在完整虚拟桌面截图中用 OpenCV 定位图标/按钮模板，返回截图中心点和真实屏幕坐标 | `template_path`, `confidence`, `region`, `scale_min`, `scale_max`, `screenshot_id` |
| `desktop_wait_image` | 轮询完整桌面截图，等待模板图标/按钮出现 | `template_path`, `confidence`, `timeout`, `interval`, `region` |
| `desktop_click_image` | 找到桌面模板匹配后点击中心；可带 `timeout` 等待后点击 | `template_path`, `confidence`, `timeout`, `button`, `clicks`, `region` |
| `desktop_ocr` | 对完整虚拟桌面截图执行 OCR，适合没有 HWND 的系统弹层和覆盖层 | `lang`, `engine`, `max_screenshot_width`, `screenshot_id` |
| `desktop_find_text_ocr` | 用 OCR 在完整桌面里按可见文字定位，返回截图坐标和真实屏幕坐标 | `text`, `lang`, `engine`, `match`, `region`, `screenshot_id` |
| `desktop_wait_text_ocr` | 轮询完整桌面 OCR，等待可见文字出现 | `text`, `lang`, `engine`, `match`, `timeout`, `interval`, `region` |
| `desktop_click_text_ocr` | 用桌面 OCR 找到可见文字后点击中心；可带 `timeout` 等文字出现后再点击 | `text`, `lang`, `engine`, `match`, `index`, `timeout`, `region` |
| `desktop_click` | 在桌面截图坐标处点击，按虚拟桌面边界自动换算多显示器坐标 | `x`, `y`, `button`, `clicks`, `screenshot_id` |
| `desktop_scroll` | 在桌面截图坐标处滚动，适合系统弹层和 HWND-less 面板 | `x`, `y`, `scroll_y`, `screenshot_id` |
| `desktop_drag` | 在两个桌面截图坐标之间拖拽，适合跨窗口/系统级拖放 | `start_x`, `start_y`, `end_x`, `end_y`, `duration`, `screenshot_id` |
| `observe_window` | 一次性返回窗口元数据、截图和 UIA 摘要，适合作为每轮自动化起点；支持 Raw/Control/Content UIA 视图 | `hwnd`, `include_screenshot`, `include_accessibility`, `view` |
| `get_window_state` | 捕获当前窗口的实时截图并生成 Ephemeral（临时级）无障碍树索引；支持 Raw/Control/Content UIA 视图 | `hwnd` (可选), `include_screenshot`, `accessibility_view` |
| `child_windows` | 枚举原生 Win32 子 HWND、Class、ControlId、父/root、客户区原点和可选文本；会优先走已验证 helper/高权限 helper | `hwnd`, `include_text`, `max_count` |
| `window_from_point` | 将屏幕点或窗口截图点反查为 direct/root/owned/native child HWND；会优先按点下 HWND 选择 helper/高权限 helper | `x`, `y`, `hwnd`, `screenshot_width`, `screenshot_height` |
| `element_from_point` | 将屏幕点或窗口截图点反查为 UIA 元素元数据 | `x`, `y`, `hwnd`, `screenshot_width`, `screenshot_height` |
| `msaa_window` | 读取窗口 MSAA/IAccessible 名称、角色、状态、值、默认动作和子级路径；会优先走已验证 helper/高权限 helper | `hwnd`, `max_children` |
| `msaa_from_point` | 将屏幕点或窗口截图点反查为 MSAA/IAccessible 对象；会优先按点下 HWND 选择 helper/高权限 helper | `x`, `y`, `hwnd`, `screenshot_width`, `screenshot_height` |
| `msaa_action` | 调用 MSAA 默认动作、focus/select，或写入 `accValue`；会优先走已验证 helper/高权限 helper | `hwnd`, `action`, `path`, `child_id`, `value` |
| `menu_tree` | 读取经典 Win32 `HMENU` 菜单栏/系统菜单树、路径、CommandId、启用/勾选状态；会优先走已验证 helper/高权限 helper | `hwnd`, `include_system`, `max_depth`, `max_items` |
| `menu_action` | 按路径或 CommandId 直接发送 `WM_COMMAND`/`WM_SYSCOMMAND` 触发菜单项，无需坐标点击；会优先走已验证 helper/高权限 helper | `hwnd`, `path`, `command_id`, `include_system` |
| `win32_text` | 用 `WM_GETTEXT` 读取原生控件文本，带超时防卡死；会优先走已验证 helper/高权限 helper | `hwnd`, `timeout_ms` |
| `win32_set_text` | 用 `WM_SETTEXT` 设置经典 Edit/Combo 等控件文本；会优先走已验证 helper/高权限 helper | `hwnd`, `text`, `timeout_ms` |
| `win32_click` | 用 `BM_CLICK` 触发经典按钮控件，无需坐标点击；会优先走已验证 helper/高权限 helper | `hwnd`, `timeout_ms` |
| `file_dialog_info` | 自动识别前台或指定的标准 Windows 打开/保存 `#32770` 对话框，并定位文件名 ComboBoxEx/Edit、确认和取消控件；会优先走已验证 helper/高权限 helper | `hwnd`, `timeout`, `include_children` |
| `file_dialog_action` | 对标准打开/保存对话框设置完整路径、确认打开/保存/选择，或用 `WM_COMMAND IDCANCEL` 取消关闭；会优先走已验证 helper/高权限 helper | `action`, `hwnd`, `path`, `verify_close` |
| `dialog_command_action` | 等待指定窗口相关的标准 `#32770` 弹窗，并直接发送 OK/Cancel/Yes/No/Retry 等 `WM_COMMAND` 标准按钮 ID；会优先走已验证 helper/高权限 helper | `hwnd`, `action`, `command_id`, `dialog_title`, `verify_close` |
| `dialog_button_action` | 等待相关弹窗后优先用标准 `WM_COMMAND`，再按原生 `Button` 子控件用 `BM_CLICK` 触发按钮，适合消息框、安装器确认框和普通模态弹窗 | `hwnd`, `name`, `action`, `command_id`, `prefer_command`, `verify_close` |
| `win32_control_find` | 在一个窗口下按原生 HWND 元数据查找子控件：可匹配文本/条目文本、ControlId、Class、控件类型别名、当前 value/state，并按稳定 selector 评分排序；找不到时返回跨过滤条件的 `near_matches`、`failure_summary`、观测到的 kind/class 和 `selector_suggestions` 供下一轮修复；会优先走已验证 helper/高权限 helper | `hwnd`, `name`, `automation_id`, `control_type`, `class_name`, `state`, `expected`, `limit` |
| `win32_selector_repair_find` | 用 `win32_control_find` 的 `failure_summary.selector_suggestions[0]` 清洗出 ControlId/Class/type/name 后重新查找原生控件，避免 stale selector 阻塞经典 Win32 控件修复；会优先走已验证 helper/高权限 helper | `hwnd`, `suggestion`, `original`, `limit`, `include_invisible`, `include_self` |
| `win32_control_wait_find` | 轮询 `win32_control_find` 直到匹配的原生控件出现，适合等待延迟创建的 Win32 子控件、ListView/TreeView、按钮和编辑框 | `hwnd`, `name`, `control_type`, `state`, `expected`, `timeout`, `interval` |
| `win32_control_info` | 读取原生 ComboBox/ComboBoxEx/ListBox/Button/Static/SysLink/HotKey/SysListView32/SysHeader32/SysTreeView32/SysTabControl32/ToolbarWindow32/tooltips_class32/StatusBar/Trackbar/ScrollBar/UpDown/Progress/DateTimePicker/MonthCal/IPAddress/Edit/RichEdit 的选项、选中项、链接、快捷键、Header 列头、ListView 多列单元格与 item `checked/check_state/state_image`、TreeView 节点 `checked/check_state/state_image`、ToolTip 工具项、工具栏按钮 tooltip 文本、勾选/展开/按钮/数值/日期/IP/文本选区状态；会优先走已验证 helper/高权限 helper | `hwnd`, `max_items`, `timeout_ms` |
| `win32_control_action` | 用 `CB_*`/`CBEM_*`/`LB_*`/`BM_*`/`STM_*`/`HKM_*`/`LM_*`/`LVM_*`/`HDM_*`/`TVM_*`/`TCM_*`/`TB_*`/`SB_*`/`TBM_*`/`UDM_*`/`PBM_*`/`DTM_*`/`MCM_*`/`IPM_*`/`EM_*` 消息选择下拉框、增强下拉框、列表项、静态文本/链接/快捷键、列头排序/列宽/列顺序、树节点、标签页、工具栏按钮（可按按钮文本或 tooltip 文本）、状态栏文本、滑块/滚动条/微调/进度值、日期/月历/IP 地址、Edit/RichEdit 文本选区/替换、ListView 单元格/列宽、ListView item 和 TreeView node 的 `check/uncheck/toggle/set_check`；未知/自定义 state image 下 `toggle` 会拒绝猜测；会优先走已验证 helper/高权限 helper | `hwnd`, `action`, `index`, `text`, `value`, `checked` |
| `win32_control_wait` | 轮询 `win32_control_info` 直到原生控件或条目的 `checked`/`check_state`/`selected`/`expanded`/`visited`/`selected_index`/`position`/`text`/`value` 等状态匹配目标；可按 `index` 或 `text` 定位 ListView/TreeView/ListBox/Combo/Tab/Toolbar/SysLink 条目；会优先走已验证 helper/高权限 helper | `hwnd`, `state`, `expected`, `index`, `text`, `timeout`, `interval` |
| `pixel` | 读取窗口截图坐标处的 RGB/HEX 像素颜色 | `x`, `y`, `hwnd` |
| `pixel_wait` | 轮询窗口新截图，等待某个像素等于或不等于目标颜色；支持容差和捕获模式 | `hwnd`, `x`, `y`, `color`, `tolerance`, `timeout`, `interval`, `mode`, `capture_mode`, `max_screenshot_width` |
| `visual_stable_wait` | 轮询窗口新截图，等待连续帧变化比例低于阈值，适合动作后等动画、异步渲染、列表滚动或加载状态停止 | `hwnd`, `timeout`, `interval`, `stable_ticks`, `difference_threshold`, `pixel_threshold`, `region`, `capture_mode`, `max_screenshot_width`, `comparison_max_width` |
| `uia_stable_wait` | 轮询窗口 UIA 结构签名，等待控件树、焦点、可见状态、patterns 和矩形桶稳定，适合 WPF/WinUI/Chromium shell/企业软件动态刷新后再操作 | `hwnd`, `timeout`, `interval`, `stable_ticks`, `max_depth`, `max_elements`, `view`, `include_values`, `rect_bucket` |
| `locate_image` | 用 OpenCV 在窗口截图中定位模板图，支持区域限制和多尺度匹配，返回中心坐标和置信度 | `template_path`, `confidence`, `region`, `scale_min`, `scale_max`, `hwnd` |
| `wait_image` | 轮询截图等待模板图标/按钮出现，返回可点击中心点 | `template_path`, `confidence`, `timeout`, `interval`, `region`, `hwnd` |
| `click_image` | 找到模板图标/按钮后点击中心；可带 `timeout` 等待后点击 | `template_path`, `confidence`, `timeout`, `button`, `clicks`, `hwnd` |
| `image_scroll_click` | 对窗口反复模板匹配查找图标/按钮，找不到就滚动列表/面板并重新截图，找到后点击 | `template_path`, `hwnd`, `max_scrolls`, `scroll_amount`, `scroll_x`, `scroll_y`, `pause`, `capture_mode` |
| `ocr` | 对窗口截图执行自动 OCR，优先用 Tesseract，可回退到 Windows 内置 WinRT OCR，返回文本和词级坐标 | `lang`, `engine`, `hwnd` |
| `find_text_ocr` | 用 OCR 在自绘/Canvas/弱无障碍界面里按可见文字定位，返回合并词框和可点击中心点 | `text`, `lang`, `engine`, `match`, `region`, `hwnd` |
| `wait_text_ocr` | 轮询截图和 OCR，等待某个可见文字出现并返回可点击中心点 | `text`, `lang`, `engine`, `match`, `timeout`, `interval`, `region`, `hwnd` |
| `click_text_ocr` | 用 OCR 找到可见文字后直接点击其中心；可带 `timeout` 等文字出现后再点击 | `text`, `lang`, `engine`, `match`, `index`, `timeout`, `region`, `hwnd` |
| `ocr_scroll_click` | 对窗口反复 OCR 查找可见文字，找不到就滚动列表/面板并重新截图，找到后点击；适合没有行号的自绘列表 | `text`, `hwnd`, `max_scrolls`, `scroll_amount`, `scroll_x`, `scroll_y`, `pause`, `capture_mode` |
| `visual_row` | 用 OCR 行号锚点定位自绘/Canvas/弱无障碍编号列表行；可自动推断编号列并插值缺失行号 | `row`, `hwnd`, `lang`, `engine`, `row_region`, `min_row`, `max_row` |
| `visual_row_click` | 定位并点击编号列表/表格第 N 行，适合歌单、搜索结果、数据表等自绘列表 | `row`, `hwnd`, `lang`, `engine`, `row_region`, `click_x`, `x_offset`, `clicks` |
| `visual_row_scroll` | 自动滚动编号列表/表格直到第 N 行可见；每轮强制新截图，按可见行号范围决定滚动方向 | `row`, `hwnd`, `max_scrolls`, `scroll_amount`, `scroll_x`, `scroll_y`, `pause` |
| `visual_row_scroll_click` | 自动滚动到编号列表/表格第 N 行并点击，适合目标行当前不可见的自绘列表 | `row`, `hwnd`, `max_scrolls`, `scroll_amount`, `click_x`, `x_offset`, `clicks` |
| `find_elements` | 按 UIA 名称、AutomationId、控件类型、Class、Value、Pattern 查找元素；`view=control/content` 可减少大型窗口噪声 | `name`, `automation_id`, `control_type`, `pattern`, `view` |
| `wait_for_element` | 轮询等待某个 UIA 元素出现并返回可操作 index；支持 Raw/Control/Content UIA 视图 | `timeout`, `interval`, `view`, 选择器参数 |
| `get_element` | 返回某个无障碍树 index 的完整元数据 | `index`, `hwnd` |
| `focus_element` | 将键盘焦点移动到指定 UIA 元素 | `index`, `hwnd` |
| `click` | 在指定坐标或基于无障碍树 Ephemeral Index 精准点击 UI 元素，**支持双击**（`clicks=2`）| `hwnd` (可选), `x`, `y`, `index`, `clicks` |
| `type_text` | 将文本内容高效、无阻碍地键入至当前激活的输入框（中文/Unicode 100% 支持）；需要剪贴板粘贴时使用 | `text`, `hwnd` (可选) |
| `press_key` | 执行单键或组合键快捷键动作（如 `Control_L+v`, `Alt_L+F4`） | `keys`, `hwnd` (可选) |
| `scroll` | 在指定的窗口物理坐标上模拟鼠标滚轮滚动 | `x`, `y`, `scroll_y`, `hwnd` (可选) |
| `drag` | 在指定的两点物理坐标间执行平滑拖拽 | `start_x`, `start_y`, `end_x`, `end_y` |
| `set_value` | 用 UIA ValuePattern 直接设置输入控件文本 | `index`, `value`, `hwnd` |
| `find_item_in_container` | 通过 UIA `ItemContainer.FindItemByProperty` 在虚拟化/大型列表或网格中按 `name`、`automation_id`、`control_type` 等属性查找项，并注册为后续可操作 index；可带 `include_children` 查看 provider 返回行下面的直接子单元格 | `index`, `property_name`, `property_value`, `limit`, `hwnd`, `include_children`, `max_children` |
| `perform_secondary_action` | 调用 UIA 原生动作，如 Invoke、Toggle、Select、AddToSelection、RemoveFromSelection、Expand、Collapse、ScrollItem、SetRange、Scroll、SetScrollPercent、TextFind、TextSelect、TextScrollIntoView、TextSelectRange、ItemFind、SpreadsheetGetItem、CustomNavigate、SyncStart、SyncCancel、LegacyDefault、LegacySetValue、LegacySelect、Move、Resize、Rotate、Zoom、ZoomByUnit、SetDockPosition、SetCurrentView、Realize | `index`, `action`, `value`, `text`, `horizontal`, `vertical`, `hwnd` |
| `activate_window` | 通过 `AttachThreadInput`、`AllowSetForegroundWindow`、Alt 脉冲、`SwitchToThisWindow` 和 `SetForegroundWindow` 兜底激活窗口 | `hwnd` |
| `doctor` | 自检窗口枚举、窗口动作、截图/捕获方式、像素、UIA RangeValue/Scroll/Text/Selection/LegacyIAccessible/Transform、UIA Raw/Control/Content 视图、WinEvent、Win32、focused-input、HMENU、MSAA、Header/通用控件等原生探针、OpenCV、dxcam、Tesseract、Windows OCR 和聚合 OCR 可用性 | `hwnd` (可选) |
| `selftest` (CLI) | 回归测试；覆盖 Notepad UIA、UIA RangeValue/Scroll/Text/Selection/LegacyIAccessible/Transform、UIA Raw/Control/Content 视图、窗口移动/缩放/最小化/最大化/关闭、WinEvent、前台/子控件焦点、focused-input、标准文件对话框、Win32 Edit/Button、ComboBox/ComboBoxEx/ListBox/Button、SysListView32/SysTreeView32 复选框状态图像与 `check_state`、SysHeader32/SysTabControl32/ToolbarWindow32/tooltips_class32、ToolTip-backed Toolbar、StatusBar/Trackbar/UpDown/Progress、DateTimePicker/MonthCal/IPAddress、RichEdit、Static/SysLink/HotKey、Windows OCR fallback、OpenCV 图像匹配、连续视觉稳定等待、HMENU `WM_COMMAND`、MSAA 值/默认动作 | `notepad`, `uia`, `text`, `winevent`, `view`, `window`, `focus`, `focused_input`, `file_dialog`, `win32`, `msaa`, `menu`, `controls`, `common`, `header`, `bars`, `numeric`, `date_ip`, `richedit`, `light`, `ocr`, `image`, `batch`, `selector`, `server-contracts`, `all`, `timeout` |
| `check_safety` | 在动作前预先验证操作是否具有系统级潜在威胁 | `action` |

---

## CLI 推荐流程

```bash
python tools.py helper-status
python tools.py helper-status --restart
python tools.py observe <hwnd>
python tools.py control-boundary <hwnd>
python tools.py helper-status --elevated --start
python tools.py wait-event object-show --hwnd <hwnd> --timeout 5
python tools.py wait-event system-dialog-start --title "Save" --timeout 10
python tools.py gui-thread-info <hwnd>
python tools.py focus-hwnd <control_hwnd>
python tools.py focused-input <hwnd> "Hello"
python tools.py focused-input <hwnd> "replacement" --mode replace-selection
python tools.py focused-input <hwnd> "full value" --mode set-text
python tools.py smart-text <hwnd> "C:\Path\file.txt" --name "File name" --type edit --class Edit
python tools.py smart-wait-text <hwnd> "C:\Path\file.txt" --name "File name" --type custom --class SearchBox --timeout 10 --no-uia
python tools.py smart-click <hwnd> --name "Save" --type button
python tools.py smart-wait-click <hwnd> --name "OK" --type button --timeout 10
python tools.py smart-click <hwnd> --name "I agree" --type checkbox --action check --no-uia
python tools.py smart-select <hwnd> "Beta" --type listbox
python tools.py smart-select <hwnd> "Gamma" --type listview --mode check
python tools.py smart-select <hwnd> --type combobox --index 1 --no-uia
python tools.py smart-wait-select <hwnd> "Beta" --type listbox --timeout 10
python tools.py smart-cell <hwnd> --row-text "Beta" --column-name "State"
python tools.py smart-cell <hwnd> --row-text "Beta" --column-name "State" --action set --text "Done" --no-uia
python tools.py smart-wait-cell <hwnd> --row-text "Beta" --column-name "State" --timeout 10 --no-uia
python tools.py file-dialog info
python tools.py file-dialog set "C:\Path\To\file.txt"
python tools.py file-dialog open "C:\Path\To\file.txt" --verify-close
python tools.py file-dialog cancel --verify-close
python tools.py desktop-accessibility --view control --max-depth 3
python tools.py desktop-find --type window --limit 3 --view control
python tools.py desktop-find --name "任务栏" --type pane --view control
python tools.py desktop-wait --type window --timeout 5 --view control
python tools.py desktop-element <index> --view control
python tools.py desktop-focus <index> --view control
python tools.py desktop-click-index <index> left 1 --view control
python tools.py desktop-action <index> Invoke --view control
python tools.py desktop-screenshot "%TEMP%\desktop-control.jpg" --max-width 1600
python tools.py desktop-point <x> <y> <screenshot_id>
python tools.py desktop-pixel <x> <y> <screenshot_id>
python tools.py desktop-pixel-wait <x> <y> "#22c55e" --timeout 5 --tolerance 8
python tools.py desktop-pixel-wait <x> <y> "#777777" --not --timeout 5
python tools.py desktop-visual-stable-wait --timeout 5 --stable-ticks 2 --region 0,0,1200,800
python tools.py desktop-visual-stable-wait --timeout 5 --stable-ticks 2 --region 0,0,1600,900
python tools.py desktop-uia-stable-wait --timeout 5 --stable-ticks 2 --view control
python tools.py desktop-locate-image icon.png 0.85 --screenshot-id <screenshot_id>
python tools.py desktop-image-wait icon.png 0.85 --timeout 10
python tools.py desktop-image-click icon.png 0.85 --timeout 10
python tools.py desktop-ocr eng --engine windows --screenshot-id <screenshot_id>
python tools.py desktop-ocr-find "Settings" eng --engine windows
python tools.py desktop-ocr-wait "Settings" eng --engine windows --timeout 10
python tools.py desktop-ocr-click "Settings" eng --engine windows --timeout 10
python tools.py desktop-click <x> <y> left 1 <screenshot_id>
python tools.py desktop-scroll <x> <y> 3 <screenshot_id>
python tools.py desktop-drag <x1> <y1> <x2> <y2> <screenshot_id>
python tools.py window-action <hwnd> set-rect --x 80 --y 80 --width 1200 --height 800
python tools.py window-action <hwnd> topmost
python tools.py window-action <hwnd> not-topmost
python tools.py window-action <hwnd> placement
python tools.py window-action <hwnd> restore
python tools.py observe <hwnd> --view control
python tools.py accessibility <hwnd> --view control
python tools.py child-windows <hwnd> --include-text
python tools.py window-from-point <x> <y> <hwnd> <screenshot_id>
python tools.py msaa-window <hwnd>
python tools.py msaa-from-point <x> <y> <hwnd> <screenshot_id>
python tools.py menu-tree <hwnd>
python tools.py menu-action <hwnd> '["File","Open"]'
python tools.py find <hwnd> --name "Save" --pattern Invoke --view control
python tools.py find <hwnd> --pattern Text --view content
python tools.py find <hwnd> --pattern RangeValue
python tools.py action <hwnd> <slider_index> set-range 42
python tools.py action <hwnd> <button_index> Invoke --view control
python tools.py find <hwnd> --pattern Scroll
python tools.py action <hwnd> <scroll_index> set-scroll-percent -1 75
python tools.py action <hwnd> <scroll_index> scroll no-amount small-increment
python tools.py find <hwnd> --pattern Text
python tools.py action <hwnd> <text_index> text-find "target"
python tools.py action <hwnd> <text_index> text-select "target"
python tools.py action <hwnd> <text_index> text-scroll-into-view "target"
python tools.py find <hwnd> --pattern SelectionItem
python tools.py action <hwnd> <item_index> select
python tools.py action <hwnd> <item_index> add-to-selection
python tools.py action <hwnd> <item_index> remove-from-selection
python tools.py find <hwnd> --pattern Grid
python tools.py element <hwnd> <grid_index>
python tools.py action <hwnd> <view_index> set-view 2
python tools.py action <hwnd> <virtualized_item_index> realize
python tools.py find <hwnd> --pattern ItemContainer
python tools.py item-container-find <hwnd> <container_index> name "Customer 42"
python tools.py item-container-find <hwnd> <container_index> name "Customer 42" --include-children --max-children 96
python tools.py find <hwnd> --pattern Spreadsheet
python tools.py action <hwnd> <sheet_index> spreadsheet-get-item A1
python tools.py find <hwnd> --pattern Annotation
python tools.py find <hwnd> --pattern Styles
python tools.py action <hwnd> <nav_index> custom-navigate next-sibling
python tools.py action <hwnd> <sync_index> sync-start key-down
python tools.py action <hwnd> <sync_index> sync-cancel
python tools.py find <hwnd> --pattern LegacyIAccessible
python tools.py action <hwnd> <legacy_index> legacy-default
python tools.py action <hwnd> <legacy_index> legacy-set-value "new value"
python tools.py find <hwnd> --pattern Transform
python tools.py action <hwnd> <window_index> move 96 96
python tools.py action <hwnd> <window_index> resize 560 380
python tools.py action <hwnd> <dock_index> set-dock-position left
python tools.py win32-control-info <control_hwnd>
python tools.py win32-control-action <control_hwnd> select "Option"
python tools.py win32-control-action <comboboxex_hwnd> set-item-text --index 1 --text "Beta Prime"
python tools.py win32-control-action <comboboxex_hwnd> set-edit-text --text "typed value"
python tools.py win32-control-action <listview_hwnd> check "Item"
python tools.py win32-control-action <listview_hwnd> set-cell --index 1 --value 2 --text "Done"
python tools.py win32-control-action <listview_hwnd> set-column-width --index 2 --value 160
python tools.py win32-control-action <header_hwnd> click --index 2
python tools.py win32-control-action <header_hwnd> set-width --index 2 --value 160
python tools.py win32-control-action <header_hwnd> set-order --text "[2,0,1]"
python tools.py win32-control-action <treeview_hwnd> expand "Node"
python tools.py win32-control-action <treeview_hwnd> check "Node"
python tools.py win32-control-action <tab_hwnd> select "Advanced"
python tools.py win32-control-action <toolbar_hwnd> press "Save"
python tools.py win32-control-action <toolbar_hwnd> press "Export Report"
python tools.py win32-control-action <trackbar_hwnd> set --value 70
python tools.py win32-control-action <scrollbar_hwnd> page-down
python tools.py win32-control-action <statusbar_hwnd> set-text --index 1 --text "Busy"
python tools.py win32-control-action <datetime_hwnd> set "2026-06-07T09:30:15"
python tools.py win32-control-action <monthcal_hwnd> set "2026-12-25"
python tools.py win32-control-action <ipaddress_hwnd> set "192.168.1.77"
python tools.py win32-control-action <edit_hwnd> select-range --index 0 --value 4
python tools.py win32-control-action <edit_hwnd> replace-selection --text "new"
python tools.py win32-control-action <edit_hwnd> append --text " more"
python tools.py win32-control-action <richedit_hwnd> select-range --index 6 --value 10
python tools.py win32-control-action <richedit_hwnd> replace-selection --text "replacement"
python tools.py win32-control-action <richedit_hwnd> append --text "`r`nmore text"
python tools.py win32-control-action <static_hwnd> set-text --text "Ready"
python tools.py win32-control-action <hotkey_hwnd> set --text "ctrl+shift+S"
python tools.py win32-control-action <syslink_hwnd> set-visited --index 0 --checked true
python tools.py locate-image <hwnd> icon.png 0.85 --region 0,0,800,500 --scale-min 0.8 --scale-max 1.25 --scale-step 0.05
python tools.py visual-stable-wait <hwnd> --timeout 5 --stable-ticks 2 --region 0,0,1200,800 --capture-mode visible
python tools.py uia-stable-wait <hwnd> --timeout 5 --stable-ticks 2 --view control
python tools.py desktop-visual-stable-wait --timeout 5 --stable-ticks 2 --region 0,0,1600,900
python tools.py desktop-uia-stable-wait --timeout 5 --stable-ticks 2 --view control
python tools.py image-wait <hwnd> icon.png 0.85 --timeout 10
python tools.py image-click <hwnd> icon.png 0.85 --timeout 10
python tools.py ocr <hwnd> eng+chi_sim --engine auto
python tools.py ocr <hwnd> eng --engine windows
python tools.py ocr-find <hwnd> "确定" eng+chi_sim --engine windows
python tools.py ocr-wait <hwnd> "确定" eng+chi_sim --engine windows --timeout 10
python tools.py ocr-click <hwnd> "确定" eng+chi_sim --engine windows
python tools.py ocr-click <hwnd> "保存" eng+chi_sim --engine windows --match exact --region 0,0,800,500 --timeout 10
python tools.py observe <hwnd> --ocr --ocr-engine windows
python tools.py batch-file commands.json
python tools.py doctor
python tools.py selftest notepad
python tools.py selftest uia
python tools.py selftest text
python tools.py selftest winevent
python tools.py selftest view
python tools.py selftest window
python tools.py selftest focus
python tools.py selftest focused_input
python tools.py selftest file_dialog
python tools.py selftest win32
python tools.py selftest msaa
python tools.py selftest menu
python tools.py selftest controls
python tools.py selftest common
python tools.py selftest header
python tools.py selftest bars
python tools.py selftest numeric
python tools.py selftest date_ip
python tools.py selftest richedit
python tools.py selftest light
python tools.py selftest ocr
python tools.py selftest image
python tools.py selftest batch
python tools.py selftest selector
python tools.py selftest server-contracts
python tools.py selftest clipboard
python tools.py selftest all
```

Clipboard paste input snapshots memory-backed clipboard formats plus duplicable `CF_BITMAP` / `CF_ENHMETAFILE` handles before replacing the clipboard with the requested text, restores all captured formats afterward, and restores an originally empty clipboard back to empty. Helper diagnostics report saved/skipped/restored format counts so failed paste cleanup can be detected without inspecting the user's real clipboard.

Batch JSON accepts command-style and path-style aliases such as `smart-click`, `/smart-text-input`, `smart-wait-text-input`, `/smart-control-action`, `smart-select-item`, `smart-grid-cell`, `type-text`, `/press-key`, `find_elements`, `get_element`, `click_element`, `perform_secondary_action`, `uia-repair-find`, `uia-cell-repair-find`, `win32-selector-repair-find`, `window-selector-repair-find`, `desktop_get_element`, `/desktop-click`, `/click-text-ocr`, `/wait-image`, `win32-control-find`, `win32-control-wait-find`, `pixel-wait`, `/pixel-wait`, `desktop-wait-pixel`, `/desktop-pixel-wait`, `batch-auto`, `auto_action`, `app_action`, `app_sequence`, `batch_sleep`, `ensure-window`, and `/auto-window`. Helper-routable UIA/input/native aliases are normalized to canonical helper endpoints before posting so scan indexes, native HWND discovery, and follow-up actions stay in the same helper process; local-only path aliases run locally instead of being rejected as unknown paths. Batch items also accept either `args` or `data` for parameters, so command-style and path-style snippets can be reused safely. Failed batch entries include `failure_category` plus `recommendations`; summaries and failed `batch_try` results also aggregate `failure_categories` so callers can distinguish selector/configuration, timeout, focus, elevation, semantic provider, native, MSAA, visual, and input failures without scraping messages. Top-level batch summaries and `batch_try` / `batch_auto` results also preserve compact `diagnostic_summary` data such as `relocated`, `uia_relocation_count`, `last_uia_relocation`, `uia_find`, `uia_selector_suggestions`, `native_control_find`, `native_selector_suggestions`, `window_find`, and `window_selector_suggestions` when a smart/UIA step repaired a stale index or a UIA/Win32/window probe found diagnosable selector drift. Any step can add `recover_on_failure` / `failure_recovery` as a list or category map such as `{focus:[...], selector:[...], default:[...]}`; after normal retries are exhausted, the matching recovery steps run locally and the original step is retried once, with the recovery report attached to `results[].recovery`. Use `batch_sleep`/`sleep` with `delay` or `seconds` for an explicit in-engine pause that respects batch timeout budgets. Use `batch_auto`/`auto_action` with `kind: click|text|select|cell|dialog|key|scroll|drag|menu|window|window_action|window_sequence` to expand one intent into semantic smart helper, Win32, MSAA, OCR/image, keyboard/mouse, and coordinate/input fallback branches; `kind: select` with `mode=check/uncheck/toggle` generates state-aware `smart_select` plus native `win32_control_action check/uncheck/toggle`, and by default does not fall back to MSAA select or visual click unless `allow-unverified-check-fallback` is explicitly true; add `verify-checked: true`, `verify-selected`, `verify-expanded`, or `verify-win32-state` to append a native `win32_control_wait` state check after each generated branch. `kind: key` sends shortcuts through `key` and can append post verification, `kind: scroll` emits HWND-bound wheel `scroll` plus keyboard fallback while desktop coordinate scroll uses `desktop_scroll` and only adds keyboard fallback when `keyboard-scroll`/`keyboard-fallback` is true, `kind: drag` emits HWND-bound `drag` or desktop `desktop_drag` from `start-x`/`start-y` to `end-x`/`end-y`, and `kind: menu` invokes classic Win32 `HMENU`/system-menu commands with `menu-path` or `command-id`, plus `include-system`, `async-post`, and `timeout-ms`. `kind: dialog` first adds a native `dialog_command_action` branch for standard dialogs, waiting for the related owner/PID/root-owner dialog and sending standard `WM_COMMAND` IDs such as OK/Cancel/Yes/No; it then adds a `dialog_button_action` branch with `prefer_command=false` to target a matching Win32 `Button` child via `BM_CLICK` before falling back to smart UIA, desktop-root UIA, desktop-root selector repair, OCR/image, and coordinate paths for custom or system-level popups. Use `kind: window` or direct `auto_window` to acquire, launch, foreground/focus, boundary-check, and optionally observe a stable target window from `hwnd`, `title`/`name`, `process`, or `app`/`path-or-name`; failed window acquisition returns `near_windows`, `failure_summary`, observed processes/titles, and selector suggestions. Set `plan-only: true` to return generated branches plus a compact `plan_summary` without touching the desktop, including branch ids, layer coverage, command coverage, previews, recovery/retry/focus/fallback flags, `risk_flags`, `risk_count`, and recommendations for launch, elevation, weak selector, visual, coordinate, and sensitive/destructive-action preflight review. Use `kind: window_action` or `app_action` to acquire/repair a target window first, then inject its resolved HWND into an inner `action-kind: click|text|select|cell|dialog|key|scroll|drag|menu`; use `kind: window_sequence` or `app_sequence` when the same resolved window should run multiple ordered actions from `steps`/`actions`/`workflow`, mixing auto-action specs and raw batch commands. Auto sequence steps can specify `kind: key|scroll|drag|menu`, and the generated branches inject the resolved HWND before sending keys, wheel scrolls, drags, or menu commands. Window-phase keys include `window-title`, `process-name`, `path-or-name`, `window-timeout`, and `window-layers`, while control-phase keys include `name`, `automation-id`, `control-type`, `text`, `item`, `template-path`, `x`/`y`, `keys`, `dy`/`delta`, `start-x`/`start-y`, `end-x`/`end-y`, `menu-path`, `command-id`, `include-system`, `async-post`, `action-timeout`, and `action-layers`; sequence keys include `sequence-focus`/`focus-each-step` to insert `focus_hwnd` before each step, `step-delay`/`sequence-delay` to insert `batch_sleep` between steps, and `sequence-recovery`/`on-step-failure` plus optional `recovery-delay`/`sequence-recovery-focus` to refocus, run recovery actions such as dialog dismissal, then retry only the failed sequence step. It normalizes common MCP/CLI key spellings such as `automation-id`, `control-type`, `template-path`, `timeout-ms`, `action-timeout`, `dialog-title`, `process-name`, `path-or-name`, `row-text`, and `column-name`. Explicit `branches`/`alternatives` override generated branches when you need full control.

Window-phase auto plans add a `window_selector_repair` branch after the normal wait branch and before launch. It probes with `wait_window`, reuses the matched HWND if the original selector still resolves, otherwise reads `failure_summary.selector_suggestions[0]`, calls `window_selector_repair_find` to clean and verify the suggested `hwnd`/title/process/pid/match, then runs the same focus, boundary, helper, and observe steps before returning a repaired HWND. MCP/server exposes the same `window_selector_repair_find` tool, so callers can feed a failed `wait_window` or `auto_window` suggestion directly into the next acquisition attempt. `plan-only: true` marks this with `has_window_selector_repair`; use `window-selector-repair: false` or `selector-repair: false` to disable it.

Window helper handling is conditional by design. If `helper-status: true` / `helper: true` is set, generated window acquisition keeps `control_boundary` enabled even when `boundary: false` was supplied, and the wait/repair/launch branches only run `helper_status(elevated=true,start=true)` when `needs_elevation` is true. For generated `window_action` / `app_action` and `window_sequence` / `app_sequence`, set `pre-boundary: true` to run a fresh `control_boundary` after the target HWND is resolved and before the first control step; add `pre-helper: true` to conditionally start the elevated helper from that preflight result. `plan-only: true` marks these with `has_boundary_preflight` and `has_conditional_helper`, so elevated-control plans can be audited before touching the desktop.

`batch_auto` / `auto_action` also supports `kind: file_dialog` for standard Windows Open/Save dialogs. It emits native `file_dialog_info` when `file-dialog-action: info` is requested, or `file_dialog_action` for `open`, `save`, `select`, `choose`, `ok`, `accept`, `set`, `set-filename`, and `cancel` style actions. Use `file-dialog-path` / `filename` / `file` for the target path, `verify-close` to wait for close after confirm/cancel, `include-children` for deeper info output, `timeout-ms` for native control probing, and `layers: native` when you want only this deterministic path. `app_action` accepts `action-kind: file_dialog`, and `app_sequence` steps can use `kind: file_dialog`; both first resolve the target app window and then inject that HWND so the file-dialog resolver can match owned/root-owner `#32770` dialogs instead of relying only on the foreground window.

Batch alias coverage also includes `visual-stable-wait`, `/visual-stable-wait`, `wait-visual-stable`, `desktop-wait-visual-stable`, `wait-desktop-visual-stable`, `/desktop-visual-stable-wait`, `uia-stable-wait`, `/uia-stable-wait`, `wait-uia-stable`, `desktop-wait-uia-stable`, and `/desktop-uia-stable-wait`. Use these inside mixed batches after clicks, scrolls, route changes, loading overlays, animations, or UIA tree refreshes before OCR/image/pixel/selector assertions.

MCP `execute_batch` accepts the same object-form batch options as the CLI batch-file path. Boolean options such as `stop-on-error` are parsed with the engine's normal coercion rules, so JSON strings like `"false"`, `"0"`, or `"off"` do not accidentally enable stop-on-error and truncate fallback or cleanup steps.

For generated `window_action` / `app_action` and `window_sequence` / `app_sequence` plans, set `auto-recover: true` or a non-disabled `recovery-policy` to opt into automatic category-aware recovery. The generated control steps receive `recover_on_failure` maps for focus, selector, semantic provider, native control, visual, input, clipboard-restore, timeout, and elevation/blocking failures, so a failed action can refocus, wait for UIA/visual stability, check `control_boundary`, start the helper only when needed, then retry through the same local recovery engine. Tune generated stability waits with `recovery-timeout`, `recovery-interval`, `recovery-stable-ticks`, `recovery-uia-stable`, and `recovery-visual-stable`.

Generated `click`, `text`, `select`, `cell`, `dialog`, `window_action` / `app_action`, and `window_sequence` / `app_sequence` plans can append post-action verification and observation steps. Add `post-delay` to wait for UI settling, `verify-name` / `verify-control-type` / `verify-selector` to emit UIA `uia_wait` or `desktop_wait`, `verify-text` to emit `ocr_wait` / `desktop_ocr_wait`, `verify-image` to emit `image_wait` / `desktop_image_wait`, `verify-pixel` / `verify-pixel-color` with `verify-pixel-x` and `verify-pixel-y` to emit `pixel_wait` / `desktop_pixel_wait`, `post-event` to wait for a WinEvent, `post-observe: true` to capture a final `observe` or desktop UIA/screenshot snapshot, and `post-steps` for custom checks. Add `post-uia-stable`, `verify-uia-stable`, or `post-structure-stable` to insert `uia_stable_wait` / `desktop_uia_stable_wait` before selector/OCR/image/pixel checks; tune it with `post-uia-stable-ticks`, `post-uia-stable-max-depth`, `post-uia-stable-max-elements`, `post-uia-stable-view`, `post-uia-stable-include-values`, and `post-uia-stable-rect-bucket`. Use `verify-absent-name` / `verify-absent-selector`, `verify-absent-text`, `verify-absent-image`, and `verify-absent-pixel` when the expected result is that a popup, loading mask, stale label, spinner, old icon color, or other stale UI disappears; generated plans poll `uia_find` / `desktop_find`, `ocr_find` / `desktop_ocr_find`, `locate_image` / `desktop_locate_image`, or `pixel_wait` / `desktop_pixel_wait` in `not_equals` mode with `batch_repeat` until the target is absent. `post-timeout` and `post-interval` control generated verification waits; `verify-pixel-tolerance` and `verify-pixel-mode` tune color matching. The compact `plan_summary` marks these plans with `has_post_verification`, and negative checks also set `has_negative_post_verification`, so `plan-only: true` can distinguish a verified action plan from a fire-and-forget click before touching the desktop.

For visual-only transitions, add `post-stable`, `post-visual-stable`, `verify-stable`, or `verify-visual-stable`. Generated plans emit `visual_stable_wait` for HWND-bound actions or `desktop_visual_stable_wait` for desktop-level actions before selector/OCR/image/pixel checks. Tune it with `post-stable-region`, `post-stable-ticks`, `post-difference-threshold`, `post-pixel-threshold`, and `post-stable-max-width`.

Generated `click`, `text`, `select`, and `cell` auto plans also add semantic selector-repair branches before Win32/MSAA/visual/input fallbacks when useful. A full smart selector is tried first, followed by bounded variants such as `automation_id+control_type+class_name`, `name+control_type+class_name`, `name+control_type`, or `item+class_name`; this helps apps whose UIA names, classes, or automation IDs change between renders without falling straight to OCR or coordinates. UIA diagnostic repair branches then probe with `uia_find`, read `failure_summary.selector_suggestions[0]`, clean missing optional fields, retry the suggested selector with `uia_selector_repair_find`, and execute the repaired UIA index with `uia_action` or `uia_set_value` in the same view. MCP/server exposes the same `uia_selector_repair_find` tool so callers can feed a failed `find_elements` suggestion directly into the next action. Cell plans use `uia_cell_selector_repair_find` instead: they require `row`/`row_text` plus `column`/`column_name`, scan GridItem/TableItem/SpreadsheetItem candidates, and only act after the repaired cell is proven by row/column metadata; MCP/server exposes this as `uia_cell_selector_repair_find` too. Native Win32 `click`, `text`, `select`, and `cell` plans can also add a diagnostic repair branch: it probes with `win32_control_find`, acts directly on the matched child HWND if the original selector still resolves, otherwise reads `failure_summary.selector_suggestions[0]`, runs `win32_selector_repair_find` with the cleaned suggested `automation_id`/class/type/name, and executes the requested action on the repaired child HWND. MCP/server exposes `win32_selector_repair_find` too, so native selector drift in classic dialogs, installers, and common controls can be repaired without building a full `batch_auto` plan. `plan-only: true` marks these with `has_selector_repair`, `has_uia_selector_repair`, and `has_native_selector_repair`. Use `selector-repair: false` to disable all generated selector repair branches, `uia-selector-repair: false` to disable only UIA diagnostic repair, `native-selector-repair: false` / `win32-selector-repair: false` to disable only the native diagnostic repair branch, `selector-variant-limit` to cap semantic variants, and `allow-weak-selector-fallback: true` only when a broad `name`/`item` fallback is acceptable.
Generated click auto plans with visible `text`/`name` also add `ocr_scroll_click` after the first OCR click probe and before coordinate fallback. This lets weak or custom-rendered scrollable lists find a text item that is not currently visible by repeatedly taking fresh OCR screenshots and scrolling at `scroll-x`/`scroll-y` for up to `max-scrolls`.
Generated click auto plans with `template`/`template-path`/`image` also add `image_scroll_click` after the first image click probe and before coordinate fallback. This gives icon-only custom lists and toolbars the same scroll-search behavior as OCR text, preserving `confidence`, `region`, scale options, `max-scrolls`, `scroll-amount`, `scroll-x`, `scroll-y`, `pause`, and `capture-mode`.
Generated text auto plans with `placeholder`/`label`/`field-label`/`target-text`/`visual-text`/`name` can add OCR focus-then-input branches, and plans with `template`/`template-path`/`image` can add image focus-then-input branches. Each branch first clicks the visible input label, placeholder, or icon, then writes the requested `text`/`value` through `focused_input`; desktop-level visual text plans without an HWND use `type_foreground` after the visual click so HWND-less overlays and global search boxes can still receive text. The visual locator keeps OCR, template, region, scale, scroll, pause, and `capture-mode` arguments separate from the actual text being typed.
Generated visual fallback branches for click, text, select, cell, and dialog intents can set `pre-visual-stable: true` to insert `visual_stable_wait` or `desktop_visual_stable_wait` before OCR, image matching, or numbered-row fallback runs. Tune it with `pre-stable-timeout`, `pre-stable-interval`, `pre-stable-ticks`, `pre-stable-region`, `pre-difference-threshold`, `pre-pixel-threshold`, and `pre-stable-max-width`; use it when animation, lazy rendering, loading masks, or freshly scrolled lists make the first visual screenshot unreliable.
Generated semantic/UIA branches for click, text, select, cell, and dialog intents can set `pre-uia-stable: true` to insert `uia_stable_wait` or `desktop_uia_stable_wait` before smart UIA, selector-repair, Grid/Table, or desktop-root UIA steps run. Tune it with `pre-uia-stable-timeout`, `pre-uia-stable-interval`, `pre-uia-stable-ticks`, `pre-uia-stable-max-depth`, `pre-uia-stable-max-elements`, `pre-uia-stable-view`, `pre-uia-stable-include-values`, and `pre-uia-stable-rect-bucket`; use it after route changes, modal creation, virtualized list refreshes, and WPF/WinUI/Chromium shell redraws.
When `auto-recover: true` is enabled, generated window action/sequence steps include a default `clipboard_restore` recovery category. Text actions refocus the target HWND and retry the original `text`/`value` through `focused_input` rather than repeating clipboard paste; non-text actions keep the category as a focus-only recovery so clipboard warnings are still classified and handled consistently. Selector, semantic-provider, native-control, visual, and timeout recovery categories now also add optional UIA and/or visual stability waits before retrying, which helps animated, lazy-loaded, and freshly re-rendered Windows controls settle before the next layered attempt.
Generated select auto plans with `item`/`text`/`value`/`name` can add OCR visual select and OCR scroll select branches, and plans with `template`/`template-path`/`image` can add image visual select and image scroll select branches. This helps custom-rendered dropdowns, option lists, and picker panels keep selecting items when UIA/Win32/MSAA providers are missing or stale, while preserving OCR, template, region, scale, scroll, pause, and `capture-mode` arguments.
Generated `click`, `select`, and click-style `cell` auto plans can also use OCR numbered-row fallback before raw coordinates when `row`, `visual-row`, or `row-number` is supplied with an `hwnd`. This emits `visual_row_scroll_click`, preserving options such as `row-region`, `click-x`, `x-offset`, `clicks`, `min-row`, `max-row`, `max-scrolls`, `scroll-amount`, `scroll-x`, `scroll-y`, `pause`, and `capture-mode`; set `visual-row-fallback: false` to disable it for a plan.

Window screenshot capture modes are available on `screenshot`, `observe`, `screenshot_b64`, `locate-image`, `image-wait`, `image-click`, `ocr`, `ocr-find`, `ocr-wait`, `ocr-click`, and `visual-row*` window commands:

```bash
python tools.py screenshot <hwnd> out.jpg --capture-mode auto
python tools.py locate-image <hwnd> icon.png 0.85 --capture-mode window
python tools.py ocr-click <hwnd> "OK" eng --engine windows --capture-mode printwindow
python tools.py visual-row-scroll <hwnd> --row 40 --engine windows --capture-mode visible
```

Use `auto` for compatibility, `visible` for the current on-screen desktop crop, `window` to prefer the target window's own rendered pixels and then fall back to visible BitBlt, `printwindow` to require PrintWindow-only capture for occluded/background windows, and `bitblt` to force a visible BitBlt crop. Full-desktop commands keep their existing visible virtual-desktop semantics.

Helper health verifies both the resident `helper.py` hash and the `tools.py` hash loaded by that helper. If either file changed after the helper started, `tools.py` treats the helper as stale and reloads it before helper-backed actions.

Helper-backed CLI/MCP input, desktop input, UIA, smart-action, Win32/MSAA/HMENU, file-dialog, and native-control calls now fail explicitly with `error: "elevated_helper_required"`, `failure_category: "blocked_or_elevation"`, and a compact `boundary` object when the target crosses a Windows integrity/UIPI boundary and the elevated helper is not already running. Run `control_boundary(hwnd)` first, then `helper_status(elevated=true, start=true)` only when the boundary report says elevation is needed.

MCP 模式下先用 `helper_status()` 检查普通 helper；当 `control_boundary(hwnd)` 报告 `uipi_risk` 或 `needs_elevation` 时，再显式调用 `helper_status(elevated=true, start=true)` 触发 UAC。随后 MCP `activate_window`、坐标 `click`、UIA `find_elements`/`wait_for_element`/`get_element`/`focus_element`/index `click`/`set_value`/`perform_secondary_action`、`smart_click`、`smart_wait_click`、`smart_select`、`smart_wait_select`、`smart_cell`、`smart_wait_cell`、`smart_text_input`、`smart_wait_text_input`、桌面 UIA 工具、`type_text`、`press_key`、`scroll`、`drag`、`file_dialog_info`、`file_dialog_action`、`child_windows`、`window_from_point`、`msaa_window`、`msaa_from_point`、`msaa_action`、`menu_tree`、`menu_action`、`win32_text`、`win32_set_text`、`win32_click`、`win32_control_info`、`win32_control_action`、桌面级 `desktop_click`/`desktop_scroll`/`desktop_drag` 和窗口截图会优先选择已验证的高权限 helper。桌面级输入会先从屏幕点反查目标 HWND，再用绝对屏幕坐标发送给 helper，避免旧 `target_hwnd` 导致坐标被错误缩放。`smart_click` / `smart_wait_click` / `smart_select` / `smart_wait_select` / `smart_cell` / `smart_wait_cell` / `smart_text_input` / `smart_wait_text_input` 在 helper 可用时会作为一个 helper-worker 事务执行，让 UIA provider 返回元素或虚拟化项在查找、Realize/ScrollIntoView 和动作/读写之间保持可操作。`smart_click(skip_uia=true)` / `smart_wait_click(skip_uia=true)` / `smart_select(skip_uia=true)` / `smart_wait_select(skip_uia=true)` / `smart_cell(skip_uia=true)` / `smart_wait_cell(skip_uia=true)` 等同 CLI `--no-uia`，适合绕开会卡死或返回错误结构的 UIA provider；坐标兜底只有在显式开启时才会使用。
This elevated-helper routing also covers `dialog_command_action`, `dialog_button_action`, `win32_control_find`, `win32_selector_repair_find`, `win32_control_wait_find`, and `win32_control_wait`.

MCP also exposes `visual_stable_wait(...)`, `desktop_visual_stable_wait(...)`, `uia_stable_wait(...)`, and `desktop_uia_stable_wait(...)`; use visual stability after pixel-level transitions and UIA stability after semantic tree refreshes before calling UIA/OCR/image/pixel verification tools.

Indexed UIA commands keep a compact identity signature across scans, including parent container, recent ancestor path, and sibling ordinal hints. When a dynamic refresh moves the same element to a different index, `get_element` / `focus_element` / `click(index)` / `set_value` / `perform_secondary_action` / `find_item_in_container` and desktop-root UIA actions can conservatively relocate it; AutomationId/name/control-type/parent mismatches are treated as stale rather than guessed. When relocation happens, JSON/MCP results include `relocated: true` plus a `relocation` diagnostic with `from_index`, `to_index`, `score`, and match `reasons`.
Smart UIA actions and `smart_wait_*` poll summaries preserve the same relocation diagnostics, and compact `failure_summary` output records UIA relocation counts so a successful or failed high-level action still explains when stale index repair was involved. Failed high-level smart actions also promote UIA find `selector_suggestions` into the smart `failure_summary`; smart-wait poll summaries and batch diagnostics surface them as `uia_selector_repair_available` / `uia_selector_suggestions` so the next retry can use `uia_selector_repair_find` without scraping nested attempts.

`observe` 会一次性返回窗口信息、持久截图 ID 和 UIA 摘要；`observe/accessibility/find/wait` 支持 `--view raw|control|content`，默认 `raw` 覆盖最全，`control` 适合大型软件里优先扫描可操作控件，`content` 适合文档/列表/正文区域并常能减少扫描量；如果某次 `find/wait` 用了 `--view control` 或 `--view content`，后续 `element`、`focus`、`click-index`、`set-value`、`item-container-find`、`action` 也可以显式带同一 `--view`，并支持同组 `--max-depth` / `--max-elements`，批处理 JSON 里也可传 `view`、`max_depth`、`max_elements`；`desktop-accessibility` / MCP `desktop_accessibility` 从 Windows UIA 桌面根扫描任务栏、开始菜单、托盘弹层、全局菜单、覆盖层和跨进程窗口，`desktop-find` / MCP `desktop_find_elements`、`desktop-wait` / MCP `desktop_wait_for_element`、`desktop-element` / MCP `desktop_get_element`、`desktop-focus` / MCP `desktop_focus_element`、`desktop-click-index` / MCP `desktop_click_element`、`desktop-action` / MCP `desktop_action` 可在不选择 app HWND 的情况下按 UIA 名称、控件类型、Pattern 或 index 做结构化定位与动作；`desktop-action` 支持和普通 UIA action 同级的 TextPattern、ItemContainer、Spreadsheet、CustomNavigation、SynchronizedInput、LegacyIAccessible、Transform/Transform2、Dock、Window、MultipleView 和 VirtualizedItem 动作，provider 返回元素会注册成后续可操作 index；英文 `--type window|pane|button|menu item` 会按 UIA ControlTypeId 匹配，因此可跨中文/英文 Windows 使用；`desktop-screenshot` / MCP `desktop_screenshot` 用于任务栏、开始菜单、托盘弹出层、全局右键菜单、屏幕遮罩和其他没有稳定 HWND 的系统级 UI，返回的桌面截图 ID 可交给 `desktop-point`、`desktop-pixel`、`desktop-locate-image` / MCP `desktop_locate_image`、`desktop-image-wait` / MCP `desktop_wait_image`、`desktop-image-click` / MCP `desktop_click_image`、`desktop-ocr` / MCP `desktop_ocr`、`desktop-ocr-find` / MCP `desktop_find_text_ocr`、`desktop-ocr-wait` / MCP `desktop_wait_text_ocr`、`desktop-ocr-click` / MCP `desktop_click_text_ocr`、`desktop-click`、`desktop-scroll`、`desktop-drag` 做全屏图标/文字定位和多显示器虚拟桌面坐标换算；`file-dialog` / MCP `file_dialog_info`、`file_dialog_action` 优先处理标准 Windows 打开/保存对话框，可自动找 `#32770`、文件名 ComboBoxEx/Edit 和确认/取消按钮，设置完整路径并用 `WM_COMMAND IDOK/IDCANCEL` 确认或取消；`wait-event` / MCP `wait_event` 用 `SetWinEventHook` 等待前台、菜单/对话框、对象显示/隐藏/创建/销毁、焦点、选择、名称、值或位置变化，适合在点击、快捷键、菜单动作后等待弹窗、菜单、动态面板和焦点切换，优先替代盲目 `sleep`；`gui-thread-info` / MCP `gui_thread_info` 读取 GUI 线程 active/focus/capture/menu/caret HWND 与 caret 矩形，用来排查键盘焦点、菜单拥有者和拖拽/缩放状态；`focus-hwnd` / MCP `focus_hwnd` 通过前台锁修复链激活根窗口，并用 `SetActiveWindow`/`SetFocus` 修复顶层窗口或子控件 HWND 的 active/focus，适合放在 `type`、`key` 和剪贴板粘贴前；`focused-input` / MCP `focused_input` 会读取真实 `hwndFocus`，对 Edit/RichEdit/Combo 编辑框用 `EM_REPLACESEL`、`WM_SETTEXT`、append 或 `WM_CHAR`，对自绘输入框回退 Unicode `SendInput`，比盲粘贴更适合需要验证焦点和文本结果的场景；`window-action` / MCP `window_action` 可用 DWM 可见边界坐标直接移动、缩放，控制 `top`/`bottom`/`topmost`/`not-topmost` Z-order，读取 `placement`，并最小化、最大化、恢复、显示或请求关闭顶层 HWND；`find --pattern RangeValue` / `action set-range` 用于 WPF/WinUI/UWP/Win32 暴露给 UIA 的滑块、进度式数值控件和缩放条；`find --pattern Scroll` / `action set-scroll-percent` / `action scroll` 用于 UIA 可滚动容器，布局变化后应重新 `find` 刷新 index；`find --pattern Text` / `action text-find` / `action text-select` / `action text-scroll-into-view` 用于 Notepad、浏览器/PDF 阅读器、日志视图、文档面板和只读文本面板暴露的 UIA TextPattern，可读取全文/可见范围、返回文字矩形、定位并选择目标文字；`Text2`、`TextChild`、`TextEdit` 可读取 caret、文本子对象、输入法 composition/conversion target；`find --pattern Selection` / `find --pattern SelectionItem` / `find --pattern Selection2` 可读取列表、树、网格和数据行的选中项，并用 `select`、`add-to-selection`、`remove-from-selection` 做结构化选择；`Grid`、`GridItem`、`Table`、`TableItem`、`Spreadsheet`、`SpreadsheetItem` 元数据会返回行列数、单元格样例、行列坐标、公式、批注类型和表头，适合 WPF/WinUI/Office/企业软件数据网格；`Annotation`、`Styles`、`Drag`、`DropTarget`、`CustomNavigation`、`SynchronizedInput`、`ObjectModel` 会暴露 Office/文档/富文本/拖放和自定义导航控件的结构化元数据，并支持 `spreadsheet-get-item`、`custom-navigate`、`sync-start`、`sync-cancel`；`ItemContainer` 可用 CLI `item-container-find` 或 MCP `find_item_in_container` 按 `name`、`automation_id`、`control_type`、`class_name`、`framework_id`、`item_status`、`item_type`、`value` 等属性搜索虚拟化/大型列表和网格，MCP 返回项会注册成后续可操作 index；`LegacyIAccessible` 会把 MSAA 名称、值、角色、状态、默认动作和选区挂到 UIA 元素上，并支持 `legacy-default`、`legacy-set-value`、`legacy-select`；`Transform`/`Transform2`/`Dock` 支持结构化移动、缩放、旋转、缩放级别和停靠位置，优先于鼠标拖拽；`MultipleView` 和 `VirtualizedItem` 可用 `set-view`、`realize` 处理多视图和虚拟化列表；`child-windows` / `window-from-point` 用于经典 Win32 控件和点位反查；`menu-tree` / `menu-action` 用于经典菜单栏和系统菜单的结构化读取与无坐标触发；`win32-control-info` / `win32-control-action` 用于下拉框、ComboBoxEx 增强下拉框、列表框、复选框、单选按钮、Static 文本/通知、SysLink 链接、HotKey 快捷键框、SysListView32 列表和多列表格、SysHeader32 列头排序/列宽/列顺序、SysTreeView32 树、SysTabControl32 标签页、ToolbarWindow32 工具栏、StatusBar 状态栏、Trackbar 滑块、ScrollBar 滚动条、UpDown 微调框、Progress 进度条、DateTimePicker 日期时间选择器、MonthCal 月历、IPAddress 输入框、Edit 和 RichEdit 文本控件；`locate-image` / MCP `locate_image` 支持区域限制和多尺度 OpenCV 模板匹配，`image-wait` / MCP `wait_image` 可等待图标或无文字按钮出现，`image-click --timeout` / MCP `click_image(timeout=...)` 可等待后点击模板中心；`ocr --engine auto` 会优先使用 Tesseract，缺失时回退到 Windows 内置 WinRT OCR，`eng+chi_sim` 会映射到 `en-US` / `zh-Hans-CN` 等已安装识别语言，`observe --ocr --ocr-engine windows` 可强制用 Windows OCR，`ocr-find` / MCP `find_text_ocr` 会把可见文字合并成可点击矩形，`ocr-wait` / MCP `wait_text_ocr` 会轮询等待可见文字出现，`ocr-click --timeout` / MCP `click_text_ocr(timeout=...)` 可等待后直接点击文字中心，支持 `--match exact|regex`、`--region left,top,right,bottom` 和重复文字 `--index`；`msaa-window` / `msaa-from-point` 用于旧式 MSAA/IAccessible 控件、owner-drawn 菜单和兼容模式软件；`batch-file` 适合 Windows 下执行包含 UIA、Win32、HMENU、MSAA、视觉、事件等待和输入命令的混合 JSON 批处理，避免命令行引号问题；`doctor` 用来安装后快速确认各控制层是否可用；`selftest clipboard` 使用假 Win32 剪贴板验证内存格式、`CF_BITMAP`、`CF_ENHMETAFILE` 快照/恢复、空剪贴板恢复和不支持句柄格式跳过；`selftest notepad` 验证真实应用 UIA 链路，`selftest uia` 验证 UIA RangeValue/Scroll/Selection/LegacyIAccessible/Transform 读写与刷新索引链路，`selftest text` 验证 UIA TextPattern 全文读取、文本定位、文本选择和选区刷新链路，`selftest winevent` 验证 `SetWinEventHook` 事件等待链路，`selftest view` 验证 UIA RawView/ControlView/ContentView 扫描和索引重扫链路，`selftest window` 验证原生 HWND 移动、缩放、Z-order/topmost、placement、最小化、最大化、恢复和关闭链路，`selftest focus` 验证原生前台修复和子控件 HWND 焦点链路，`selftest focused_input` 验证真实焦点控件输入、选区替换、append、`WM_SETTEXT` 和 `WM_CHAR` 链路，`selftest file_dialog` 验证标准文件对话框识别、文件名设置和取消关闭链路，`selftest win32` 验证 `WM_GETTEXT` / `WM_SETTEXT` / Edit 选区替换追加清空 / `BM_CLICK` 原生控件链路，`selftest controls` 验证 ComboBox/ComboBoxEx/ListBox/Button 状态链路，`selftest common` 验证 SysListView32 多列读取/单元格编辑/列宽与 SysTreeView32 远程缓冲读取和选择链路，`selftest header` 验证 SysHeader32 列头读取、改名、列宽、列顺序和点击通知链路，`selftest bars` 验证 SysTabControl32/ToolbarWindow32 读取与动作链路，`selftest numeric` 验证 StatusBar/Trackbar/ScrollBar/UpDown/Progress 读取与动作链路，`selftest date_ip` 验证 DateTimePicker/MonthCal/IPAddress 读取与动作链路，`selftest richedit` 验证 RichEdit 文本、选区、替换、追加与清空链路，`selftest light` 验证 Static/SysLink/HotKey 读取和动作链路，`selftest ocr` 验证 Windows OCR fallback 与 OCR 文本定位/等待链路，`selftest image` 验证 OpenCV 精确/区域/多尺度/等待/超时图像匹配链路，`selftest menu` 验证 `HMENU` 枚举与 `WM_COMMAND` 投递链路，`selftest msaa` 验证 IAccessible 值/动作链路。

## 📝 许可证 (License)

MIT License. 100% 离线、本地化运行，零云端 API 依赖，完全保护隐私。
