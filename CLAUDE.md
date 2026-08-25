# CLAUDE.md

This file provides guidance to Claude Code (claude.ai/code) when working with code in this repository.

Translator Lite 是 Windows 平台的轻量划词翻译应用：Python 标准库 + Tkinter + ctypes 调用 Win32，运行期零第三方依赖。

## 常用命令

在仓库根目录执行（PowerShell 或 bash 均可）：

```powershell
python -m pip install -e .                      # 开发安装，注册三个入口命令
python -m translator_lite                       # 启动桌面应用（无边框）
python -m translator_lite --decorated           # 保留系统标题栏，便于 UI Automation 调试
python -X utf8 -m translator_lite.web.server    # 本地 Web tester，http://127.0.0.1:8000
python -X utf8 -m translator_lite.client "Hello" --to zh-TW --json
```

测试：

```powershell
python -B -m unittest discover -s tests -v                    # 全部（当前 45 个）
python -B -m unittest tests.test_desktop_window -v            # 单个模块
python -B -m unittest tests.test_desktop_window.DesktopWindowMotionTests.test_drag_uses_native_positioning_without_tk_geometry -v
```

构建单文件 EXE：

```powershell
python -m pip install -e ".[build]"
.\scripts\build_exe.ps1     # 若 PowerShell 禁止脚本：powershell -ExecutionPolicy Bypass -File .\scripts\build_exe.ps1
```

注意事项：

- `-X utf8` 在 CLI 与 web 入口是必需的，否则 Windows 默认编码会破坏中文输出。
- `build_exe.ps1` 会先探测 `dist\Translator.exe` 是否被占用；应用常驻托盘，重新构建前必须从托盘菜单「退出」。
- 没有配置 lint/format 工具链；风格约定见 `AGENTS.md`。

## 架构要点

### 线程 + 队列是整个应用的骨架

`TranslatorApp`（[translator_lite/desktop/app.py](translator_lite/desktop/app.py)）跑在 Tk 主线程。所有原生子系统各自持有一条 daemon 线程和独立的 Win32 消息循环，**只能通过 `queue.Queue` 回传事件，绝不直接触碰 Tk 组件**：

| 线程 | 模块 | 队列 | 主线程轮询间隔 |
| --- | --- | --- | --- |
| `TranslatorGlobalHotkey` | `windows/hotkey.py` | `_hotkey_events` | 60 ms |
| `TranslatorGlobalMouseClick` | `windows/mouse.py` | `_mouse_events` | 20 ms |
| `TranslatorSystemTray` | `windows/tray.py` | `_tray_events` | 80 ms |
| 翻译请求 worker（每次请求一条） | `client.translate` | `_results` | 80 ms |

轮询靠 `root.after(...)` 自我调度，`_closed` 为 True 时链条终止。翻译结果带单调递增的 `_request_id`，主线程丢弃过期响应。新增任何原生能力都必须沿用这个模式。

线程生命周期统一为：`start()` 返回 `(success, error_message)`，通过 `threading.Event` 等待就绪（默认 2 秒超时）；`stop()` 用 `PostThreadMessageW(WM_QUIT)`（hotkey/mouse）或 `PostMessageW(WM_CLOSE)`（tray）唤醒消息循环后 join。

### 划词捕获是两段式的

`_begin_selection_capture` 先试 UI Automation（`windows/selection.py`，纯 ctypes 走 COM vtable，不碰剪贴板）。失败则回退：记录 `GetClipboardSequenceNumber()` → `SendInput` 模拟 Ctrl+C → 每 35 ms 轮询序号变化，1 秒截止。序号没变即判定「没有选中文本」，避免读到剪贴板里的旧内容。`_capture_pending` 防止热键连按导致重入。

`send_copy_shortcut()` 会先显式抬起 Ctrl/Alt/Shift——WM_HOTKEY 到达时用户往往还按着修饰键。

### 无边框窗口：所有窗口行为都要自己实现

默认 `overrideredirect(True)`，因此没有系统标题栏、没有系统缩放边框：

- 拖动 = 标题栏 Frame 上的 `<ButtonPress-1>`/`<B1-Motion>` 绑定。
- 缩放 = `_build_resize_handles()` 用 `place()` 铺 8 个透明 `tk.Frame`（n/ne/e/se/s/sw/w/nw）。`--decorated` 模式下不创建它们，交给系统边框。
- 实际移动/缩放走 `windows/window.py` 的 `SetWindowPos` 快速路径，失败才回落到 `root.geometry(...)`。理由：拖拽期间让 Tk 重新布局会卡顿闪烁；缩放结束时用 `redraw_window(immediate=True)` 强制一次完整重绘。
- **纯几何计算全部放在 [translator_lite/desktop/placement.py](translator_lite/desktop/placement.py)**（`clamp_window_position`、`resize_window_geometry`），与 Tk 和 Win32 解耦，因此可以无显示环境测试。新增窗口几何逻辑应继续放这里。

### 托盘常驻的生命周期

关闭按钮、`Esc`、点击窗口外（低级鼠标钩子 + `WindowFromPoint` 比对进程 ID）都只调用 `hide_window()` → `withdraw()`。**只有托盘菜单的「退出」会走 `exit_app()` 结束进程**。设置对话框打开时会临时停用点击外部隐藏。

### 翻译客户端

[translator_lite/client.py](translator_lite/client.py) 重放 Google Translate 网页前端的内部 `MkEWBc` batchexecute RPC，无 Cookie / 无 API key。解析要点：从 `[["wrb.fr"` 标记处 `raw_decode` 跳过 XSSI 前缀，再解内层 JSON 字符串，译文分段位于 `payload[1][0][0][5]`。这是未公开接口，结构随时可能变；改动解析逻辑必须同步更新 `tests/test_google_translate_client.py` 中的响应样本。

### 设置持久化

`%APPDATA%\TranslatorLite\settings.json`。`settings_from_payload` 是防御式解析——任何字段非法都降级为默认值而不抛异常，并兼容只有 hotkey 的旧文件。写入用 `.tmp` + `replace()` 保证原子性。调用方对 `save_settings` 的 `OSError` 逐处捕获，把失败降级成状态栏提示而不是崩溃。

热键注册失败时按 `preferred → Alt+Shift+W → Ctrl+Alt+T` 依次回退（`HOTKEY_FALLBACKS`）。

## ctypes 约定

- 所有平台函数在非 Windows（`ctypes.WinDLL` 不存在）时静默降级返回 `False` / `None` / `""`，这正是测试可以在任意环境跑通的原因；新增 Win32 封装必须保持这个性质。
- 显式声明 `argtypes` / `restype`。结构体字段顺序与联合体成员影响 ABI 尺寸——`hotkey.py` 里的 `INPUT_UNION` 必须包含 `MOUSEINPUT`，否则 64 位下 `INPUT` 是 32 而非 40 字节，`SendInput` 直接失败（代码中有注释说明）。
- COM 调用（`selection.py`）通过 `_com_method(pointer, vtable_index, ...)` 手取 vtable 槽位，索引带注释标明对应接口方法；每条路径都要在 `finally` 里 `_release`。

## 测试约定

两种风格并存：

1. **纯逻辑**：`Mock` + `patch` 打掉 `translator_lite.desktop.app` 里导入的原生函数（注意 patch 的是导入位置，不是定义位置）。
2. **真实 Tk**：用 `TranslatorApp.__new__(TranslatorApp)` 绕过 `__init__`（否则会真的注册全局热键、托盘和鼠标钩子），只手工赋值待测属性；窗口用 `attributes("-alpha", 0.0)` 隐藏，高 DPI 用 `root.tk.call("tk", "scaling", 2.65)` 模拟；**每个用例必须在 `finally` 中 `root.destroy()`**。

## 其他文档

- [AGENTS.md](AGENTS.md)：编码风格、命名、提交与 PR 规范（提交信息用简短的中文特性描述）。
- [CONTEXT.md](CONTEXT.md)：领域术语表与项目约束。
- [README.md](README.md)：面向用户的功能与快速开始。

根目录的 `Translator.pyw`、`app.py`、`google_translate_client.py` 是兼容入口，保持薄封装即可。
