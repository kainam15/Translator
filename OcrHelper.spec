# -*- mode: python ; coding: utf-8 -*-

from pathlib import Path
from PyInstaller.utils.hooks import collect_dynamic_libs

project_root = Path(SPECPATH)

a = Analysis(
    [str(project_root / "scripts" / "ocr_helper.py")],
    pathex=[str(project_root)],
    binaries=collect_dynamic_libs("onnxruntime"),
    datas=[],
    hiddenimports=["matplotlib.backends.backend_agg"],
    hookspath=[],
    hooksconfig={"matplotlib": {"backends": ["Agg"]}},
    runtime_hooks=[],
    excludes=[
        "torch", "torchvision", "transformers", "optimum", "cv2",
        "scipy", "pandas", "IPython", "tkinter", "PyQt5", "PyQt6",
        "PySide2", "PySide6", "wx",
    ],
    noarchive=False,
    optimize=0,
)
pyz = PYZ(a.pure)

exe = EXE(
    pyz,
    a.scripts,
    [],
    exclude_binaries=True,
    name="TranslatorOCR",
    debug=False,
    bootloader_ignore_signals=False,
    strip=False,
    upx=False,
    console=True,
    disable_windowed_traceback=False,
)

coll = COLLECT(
    exe,
    a.binaries,
    a.datas,
    strip=False,
    upx=False,
    name="TranslatorOCR",
)
