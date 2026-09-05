# Translator Lite

Translator Lite 是一个面向 Windows 的轻量划词与 OCR 翻译应用。它使用 Python 标准库和 Tkinter，支持全局热键、Windows UI Automation、Windows OCR、窗口置顶与定位、系统托盘以及本地 Web 测试页。

当前翻译实现重放 Google Translate 网页前端的内部 `MkEWBc` RPC，不读取 Cookie，也不需要登录或 API key。该接口并非 Google 官方公开接口，可能随时变化。

## 功能

- 在任意应用中选中文本后按全局热键翻译，默认是 `Alt+W`。
- 按 `Alt+Q` 后拖动框选屏幕文字，使用本机 `Windows.Media.Ocr` 识别并翻译；两个快捷键都可在设置中修改。
- OCR 使用界面选择的原文语言，需要本机安装对应的 Windows OCR 语言包。自动模式会按行选择英文识别结果，同时保留中英混合内容；英文扫描页也可直接选择 `English`。不会对 `O`、`o` 或 `0` 做统一替换。
- 安装可选本地公式组件后，先检测并识别公式，再识别正文，支持混排公式的上标、下标和分式。输入框与译文显示公式排版，点击 `LaTeX` 可切换到源码并编辑，点击 `公式` 更新预览。
- 原文的 `复制`、`复制译文` 及选区复制保留公式 LaTeX。桌面翻译仅发送公式周围的正文，公式保持原样；不支持排版的 LaTeX 会以源码显示。
- 优先使用 Windows UI Automation 获取选区，不支持时模拟 `Ctrl+C`。
- 弹窗默认置顶，可用图钉固定出现位置。
- 窗口移动与八方向缩放使用 Win32 快速路径，尺寸会自动保存。
- 点击窗口外、按 `Esc` 或关闭窗口时隐藏到系统托盘。
- 只有在托盘菜单选择“退出”才会结束进程。
- 提供命令行客户端和本地 Web tester。
- 主程序只依赖 Python 标准库；可选公式组件使用独立进程和模型文件。

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

需要保留当前 `dist\Translator.exe` 时，可构建隔离测试版本：

```powershell
.\scripts\build_exe.ps1 -Isolated
```

隔离输出位于 `.artifacts\dist\Translator.exe`。

需要公式 OCR 和公式预览时，用 Python 3.11 构建独立组件，再连同主程序打包：

```powershell
.\scripts\build_ocr.ps1
.\scripts\build_exe.ps1 -WithOcr
```

第一次构建会在项目 `.artifacts` 中创建隔离环境并下载约 200 MB 的模型。之后可使用
`.\scripts\build_ocr.ps1 -SkipInstall -SkipModelDownload` 重建组件。两种主程序构建均可添加 `-Isolated`。
携带公式功能时须一起保留 `dist\Translator.exe` 和 `dist\ocr\`，不能只复制 EXE。
源码启动也会自动发现项目内已构建的组件。模型来源、校验值和许可说明见 [docs/ocr-models.md](docs/ocr-models.md)。

识别在 CPU 本地运行，首次使用需要加载模型；扫描质量、复杂版式或模型误识别仍可能影响结果，建议核对关键公式。测试覆盖识别、翻译保护和 LaTeX 复制；实际缩放与窗口布局请在运行的 EXE 中确认。

## 项目结构

```text
translator_lite/
├── client.py              # Translation Client
├── desktop/               # Tkinter App、Settings、Placement、OCR overlay
├── windows/               # Hotkey、Selection、OCR、Mouse、Tray adapters
├── ocr/                   # 独立公式组件、文档混排与 stdlib 进程客户端
├── math_translation.py    # 公式保留与正文翻译
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

选中或 OCR 识别出的正文会发送给 Google Translate；桌面中用 `\(...\)` 或 `\[...\]` 包围的完整公式会保留在本机。剪贴板回退也可能暂时改变剪贴板内容。OCR 截图与公式模型推理均在本机处理；临时截图在识别成功或失败后删除。OCR 组件不保存识别历史。

本项目目前处于 Alpha 阶段，仅针对 Windows。内部网页 RPC 没有稳定性承诺，不应作为高可靠生产依赖。正式开源发布前还需要由维护者选择并添加明确的 `LICENSE`。

划词策略参考 [pot-desktop](https://github.com/pot-app/pot-desktop) 的 Windows 实现思路。
