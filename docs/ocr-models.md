# 本地公式 OCR 助手与模型来源

Translator 的 Tkinter 主程序仍使用 Python standard library。可选的
`TranslatorOCR.exe` 在独立进程中运行公式检测、LaTeX 识别及 MathText 渲染，
通过 stdin/stdout JSON 与主程序通信；主程序使用 `CREATE_NO_WINDOW` 启动助手。
数学图片不会上传到 OCR 服务，正文 OCR 仍由 Windows OCR 在本机执行。

## 项目隔离构建

已验证环境为 Windows x64、Python 3.11.9。所有额外依赖仅安装到
仓库的 `.artifacts/ocr-env`，不安装到全局 Python，也不将模型塞入主 EXE。

```powershell
# 自动创建项目 venv、安装固定核心依赖、下载并校验模型、构建助手。
.\scripts\build_ocr.ps1

# 已有依赖和模型时，只校验模型并重新构建。
.\scripts\build_ocr.ps1 -SkipInstall -SkipModelDownload

# 仅校验模型，无下载、无文件修改。
.\.artifacts\ocr-env\Scripts\python.exe -X utf8 scripts\setup_ocr.py --verify-only
```

没有 Python Launcher 时，可向构建脚本传入 `-Python C:\path\to\python.exe`，
该解释器仅用于创建 venv。固定核心版本在
[`scripts/ocr-requirements.txt`](../scripts/ocr-requirements.txt)：

| 包 | 版本 | 用途 |
| --- | --- | --- |
| onnxruntime | 1.24.3 | CPU 模型推理 |
| numpy | 2.4.6 | 图像数组和模型张量 |
| Pillow | 12.3.0 | 截图读取、裁剪和 PNG 输出 |
| tokenizers | 0.22.2 | MFR 原始 LaTeX token 解码 |
| matplotlib | 3.11.1 | Agg MathText 公式排版 |
| pyinstaller | 6.22.2 | 独立助手打包 |

核心包已固定；其传递依赖由 pip 解析，因此不声称不同日期构建的二进制逐字节相同。
本项目不依赖 Torch、Transformers、Optimum 或 Ultralytics Python 包。
PyInstaller spec 显式排除这些包及 GUI plotting backends，只使用 Agg。

构建产物为 `.artifacts/ocr-dist/TranslatorOCR/TranslatorOCR.exe`，必须保留
同目录的 `_internal` 文件夹；这是 `console=True` 的 stdio 助手，并非给用户
交互启动的控制台程序。模型位于 `.artifacts/ocr-models/{mfd,mfr}`，保持外置。
构建脚本不部署、不覆盖 `dist/Translator.exe`。

部署约定：将 `TranslatorOCR` 目录内全部内容复制到 `dist/ocr`，
将 `ocr-models` 内全部内容复制到 `dist/ocr/models`。

## 固定模型

| 组件 | 官方来源 | 固定 revision | 权重字节数 |
| --- | --- | --- | --- |
| MFD 1.5 | [breezedeus/pix2text-mfd-1.5](https://huggingface.co/breezedeus/pix2text-mfd-1.5) | `f470a885e0fca1d3d2bfa2a54991db7ae01f1861` | 80,311,115 |
| MFR 1.5 | [breezedeus/pix2text-mfr-1.5](https://huggingface.co/breezedeus/pix2text-mfr-1.5) | `1cef9f0bdcd6a4c63df7de1311fb0894593340cc` | encoder 87,510,770；decoder 32,026,253 |

[`scripts/setup_ocr.py`](../scripts/setup_ocr.py) 固定每个文件的下载 URL、
大小和 SHA-256。ONNX 哈希与官方仓库 Git LFS 元数据一致；小配置及模型卡的
原始字节同时核对过官方 Git blob ID。下载先写同目录临时文件，大小和哈希均
通过后才 atomic replace；下载失败会清理临时文件并保留原文件。

| 权重 | SHA-256 |
| --- | --- |
| `mfd/pix2text-mfd-1.5.onnx` | `40d4fc852d99bcbf25a9478897d2f49fbbb8f7fdd6569c088cd1c31386293bd7` |
| `mfr/encoder_model.onnx` | `080a3f660f08bc9ebcacdd96e34be6b6400f8c7e62d7cd0dd8251badc37f610b` |
| `mfr/decoder_model.onnx` | `917deb98e91a0453c5f234f58a0f32f9fb037de8527c7eb4ed394daf9e692f2a` |

## 来源许可标记与本轮使用范围

[Pix2Text 项目](https://github.com/breezedeus/Pix2Text) 的 LICENSE 为 MIT；
上述两个模型仓库的模型卡也都标注 `license: mit`。
但实际 MFD ONNX 的 `custom_metadata_map` 还包含导出工具写入的
`license: AGPL-3.0 License (https://ultralytics.com/license)`，
以及 `Ultralytics YOLO11m`、导出版本 `8.3.123`。
**MFD 模型卡与文件内许可标记存在冲突；目前没有得到作者澄清。**
不能将模型文件内标记当作已不存在，也不能据模型卡断言整套权重已确定可按 MIT 分发。

本轮仅在用户本机安装和验证，不制作公开 release。后续公开分发前，维护者需确认
模型许可及第三方声明，并遵守仓库原有的显式选择项目 LICENSE 要求。
模型下载保留官方 README；本文记录来源和观察到的冲突，不替代许可证原文。

## 能力与验证边界

检测器区分行内和独立公式；识别器输出原始 LaTeX，保留 `o`、`O`、`0` 等符号区别，
不会用字符串替换猜测缺失上标。CPU intra-op 线程上限为 4、inter-op 为 1；
单公式最多生成 256 tokens，循环时间上限 30 秒，超限报错而不返回静默截断的公式。
所有临时截图由主程序在成功、失败和超时路径清理。

Windows 本地实测的合成多项式 `P(x)=2x^4+3x^3-3x^2+5x-1` 结构正确；
混排中的 `x=1/2` 可能额外识别出粗体样式。复杂字体、低分辨率或更复杂的公式
仍可能出错；未通过把所有 `\\mathbf` 等样式宏删除来伪造准确率。
Agg MathText 不支持完整 LaTeX，无法排版的公式应保留原始 LaTeX 显示和复制。
用户要求视觉检查由其自行完成，因此本轮自动验证限于非 GUI 模型、图像及程序协议。
