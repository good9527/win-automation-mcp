# 协作通信板

## 协作流程
1. 开发端修改代码并 commit + push
2. 测试端自动检测新提交，cherry-pick 并运行测试
3. 测试结果写入本文件
4. 如有问题反馈给开发端继续修复

## 状态记录

### 轮次 1：基线测试
- 测试端对原始代码进行全面审查
- 发现 50+ 个问题，按优先级分为 P0/P1/P2
- 反馈写入本文件

### 轮次 2：重构 + 修复
- 开发端创建 common.py 共享模块，精简代码 937 行
- 修复：原子写入、GDI 泄漏、扩展键扫描码、MAX_PATH、剪贴板异常安全
- 测试端验证通过，创建 PR #2

### 轮次 3：P0 Bug 修复 ✅
- 开发端修复全部 3 个 P0 问题：
  - P0-1: _paste_text 剪贴板保存/恢复
  - P0-2: _set_clipboard_text NULL 检查
  - P0-3: 数字键盘 E0 扩展扫描码 + NumLock 映射
- 测试端验证：所有测试通过 ✅
- PR 已更新推送

## 测试结果（轮次 3）

| 测试项 | 状态 | 详情 |
|--------|------|------|
| test_server.py | ✅ | 11 个窗口，截图 957 bytes，无障碍树 7 元素 |
| list_windows | ✅ | 正确返回 JSON（11 个窗口） |
| screenshot | ✅ | 1280x845, dpi_scale=1.5 |
| P0-1 剪贴板保存/恢复 | ✅ | common.py 实现正确，server.py 已集成 |
| P0-2 NULL 检查 | ✅ | GlobalAlloc/GlobalLock 失败时正确处理 |
| P0-3 数字键盘 | ✅ | KP_7=0xE047 等使用 E0 扩展码 |

## 剩余 P1 问题（非阻塞）
1. ~~click/hover 坐标系不一致（DWM vs GetWindowRect）~~ ✅ 已修复
2. ~~坐标缩放除零风险~~ ✅ 已修复
3. ~~_check_safety 子串匹配过于宽泛~~ ✅ 已修复
4. _scale_coords DPI scale 未使用

## 测试结果（轮次 4）
- 状态：等待测试
- 开发端修复：
  - P1-1: 统一 click/scroll 使用 _get_window_rect (DWM) 做偏移和缩放
  - P1-2: click/scroll/drag/hover 坐标缩放前增加除零保护
  - P1-3: _check_safety 改为单词边界正则匹配，防止 "install" 误匹配 "reinstalls" 等
