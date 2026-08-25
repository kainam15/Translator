# Google Translate 网页请求模拟

这个项目重放 Google Translate 网页前端当前使用的内部 `MkEWBc` RPC。它只依赖 Python 标准库，不读取 Cookie，也不需要登录或 API key。

## 轻量桌面应用

双击 `Translator.pyw`，或运行：

```powershell
pythonw .\Translator.pyw
```

桌面版使用 Windows 自带的 `Tkinter` UI，不需要 Electron、WebView 或第三方包。窗口默认并始终置顶；左上角图钉用于固定弹窗位置：未固定时，划词窗口跟随鼠标出现；固定后，每次都在记录的位置出现，拖动窗口还会自动更新该位置。图钉状态和坐标会与热键一起持久化。应用还支持粘贴翻译、语言交换、`Ctrl+Enter` 翻译和结果复制。

默认划词热键为 `Alt+W`：

1. 在任意应用中划词选中文本。
2. 按 `Alt+W`。
3. Translator 会优先通过 Windows UI Automation 读取选区；不支持时再模拟 `Ctrl+C`，随后在鼠标附近弹出并自动翻译。

如果 `Alt+W` 已被其他程序占用，应用会自动尝试 `Alt+Shift+W`，再尝试 `Ctrl+Alt+T`；当前生效组合会显示在窗口底部。

点击窗口右上角“设置”可以录制新快捷键。设置保存在 `%APPDATA%\TranslatorLite\settings.json`。`Esc`、标题栏 `×` 和系统关闭按钮都只隐藏窗口，程序会继续驻留在 Windows 系统托盘并等待热键。左键单击托盘图标可恢复窗口；只有在托盘图标上右键选择“退出”，程序才会真正结束。

划词实现参考 [pot-desktop](https://github.com/pot-app/pot-desktop) 的 Windows 两级策略：先尝试 UI Automation，再使用剪贴板回退。回退路径会把选中文本复制到剪贴板；无论通过哪种方式读取，文本都会发送给 Google Translate。请勿对密码、token 或其他敏感文本使用该快捷键。

## 本地测试 UI

```powershell
python -X utf8 .\app.py
```

然后打开 <http://127.0.0.1:8000>。UI 会向本机 `POST /api/translate`，本地 Python backend 再调用 `MkEWBc` RPC。

本地 JSON API 请求格式：

```json
{
  "text": "Hello from API",
  "source": "auto",
  "target": "zh-TW"
}
```

## 已捕获的请求

Google Translate 页面在文字翻译时发送：

```http
POST https://translate.google.com.tw/_/TranslateWebserverUi/data/batchexecute?rpcids=MkEWBc
Content-Type: application/x-www-form-urlencoded;charset=UTF-8
```

解码后的最小 form body：

```text
f.req=[[["MkEWBc","[[\"Hello\",\"auto\",\"zh-TW\",true],[null]]",null,"generic"]]]
```

网页还会附带 `f.sid`、`bl`、`_reqid` 等动态 query 参数；实测主翻译 RPC 不依赖这些参数，因此 client 没有把它们写死。

## 使用

```powershell
python -X utf8 .\google_translate_client.py "Hello from API" --from auto --to zh-TW
python -X utf8 .\google_translate_client.py "今天天气很好" --to en --json
```

Windows 下的 `-X utf8` 用来保证重定向或管道中的中文输出不乱码；调用逻辑本身不依赖该选项。

作为 Python 模块：

```python
from google_translate_client import translate

result = translate("Hello from API", source="auto", target="zh-TW")
print(result.text)
print(result.detected_source_language)
```

运行测试：

```powershell
python -m unittest -v
```

## 注意

这是 Google Translate 网站的未公开内部接口，不是有稳定性承诺的正式 API。Google 可能随时修改 RPC ID、请求格式、返回结构、限流或访问策略；不要把它作为高可靠生产依赖，也不要用它绕过配额或访问限制。

正式生产服务应使用 [Google Cloud Translation API](https://cloud.google.com/translate/docs/translate-text)，其 REST endpoint 为 `POST https://translation.googleapis.com/v3/projects/PROJECT_ID/locations/LOCATION:translateText`，需要 Google Cloud 项目和认证。
