# Translator Lite

Translator Lite 是一个面向 Windows 的轻量划词翻译应用。它使用 Python 标准库和 Tkinter，支持全局热键、Windows UI Automation、剪贴板回退、窗口置顶与定位、系统托盘以及本地 Web 测试页。

当前翻译实现重放 Google Translate 网页前端的内部 `MkEWBc` RPC，不读取 Cookie，也不需要登录或 API key。该接口并非 Google 官方公开接口，可能随时变化。

## 功能

- 在任意应用中选中文本后按全局热键翻译，默认是 `Alt+W`。
- 优先使用 Windows UI Automation 获取选区，不支持时模拟 `Ctrl+C`。
- 弹窗默认置顶，可用图钉固定出现位置。
- 可从四条边或四个角拖拽调整窗口大小，尺寸会自动保存。
- 点击窗口外、按 `Esc` 或关闭窗口时隐藏到系统托盘。
- 只有在托盘菜单选择“退出”才会结束进程。
- 提供命令行客户端和本地 Web tester。
- 运行时没有第三方 Python 依赖。

## 快速开始

桌面版可双击 `Translator.pyw`，或运行：

```powershell
python -m translator_lite
```

本地 Web tester：

```powershell
python -X utf8 -m translator_lite.web.server
```

然后打开 <http://127.0.0.1:8000>。兼容入口 `python -X utf8 .\app.py` 仍然可用。

命令行翻译：

```powershell
python -X utf8 -m translator_lite.client "Hello" --from auto --to zh-TW
python -X utf8 -m translator_lite.client "今天天气很好" --to en --json
```

作为 Python Module：

```python
from translator_lite import translate

result = translate("Hello", source="auto", target="zh-TW")
print(result.text)
```

## 开发与构建

开发安装会注册 `translator-lite`、`translator-lite-cli` 和 `translator-lite-web` 三个命令：

```powershell
python -m pip install -e .
python -B -m unittest discover -s tests -v
```

构建单文件 EXE：

```powershell
python -m pip install -e ".[build]"
.\scripts\build_exe.ps1
```

输出位于 `dist\Translator.exe`。如果 PowerShell 禁止执行脚本，可运行：

```powershell
powershell -ExecutionPolicy Bypass -File .\scripts\build_exe.ps1
```

## 项目结构

```text
translator_lite/
├── client.py              # Translation Client
├── desktop/               # Tkinter App、Settings、Placement
├── windows/               # Hotkey、Selection、Mouse、Tray adapters
├── web/                   # 本地 HTTP tester 与静态页面
└── assets/                # 图标资源
tests/                     # unittest 测试
scripts/                   # 构建脚本
Translator.pyw             # 源码双击入口
Translator.spec            # PyInstaller 配置
pyproject.toml             # Package 与命令入口元数据
```

更完整的 Module 职责见 `CONTEXT.md`；贡献规则见 `AGENTS.md`。

## 本地 JSON 接口

Web tester 向本机 `POST /api/translate`：

```json
{
  "text": "Hello from API",
  "source": "auto",
  "target": "zh-TW"
}
```

Translation Client 随后请求：

```http
POST https://translate.google.com.tw/_/TranslateWebserverUi/data/batchexecute?rpcids=MkEWBc
Content-Type: application/x-www-form-urlencoded;charset=UTF-8
```

## 隐私与稳定性

选中的文本会发送给 Google Translate。不要对密码、token 或其他敏感文本使用划词热键；剪贴板回退也可能暂时改变剪贴板内容。

本项目目前处于 Alpha 阶段，仅针对 Windows。内部网页 RPC 没有稳定性承诺，不应作为高可靠生产依赖。正式开源发布前还需要由维护者选择并添加明确的 `LICENSE`。

划词策略参考 [pot-desktop](https://github.com/pot-app/pot-desktop) 的 Windows 实现思路。
