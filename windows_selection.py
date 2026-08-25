"""Read the focused Windows text selection through UI Automation.

The implementation mirrors pot-desktop's preferred Windows selection path but
uses only ctypes, keeping the application dependency-free.
"""

from __future__ import annotations

import ctypes
import uuid


HRESULT = ctypes.c_long
ULONG = ctypes.c_ulong
WINFUNCTYPE = getattr(ctypes, "WINFUNCTYPE", ctypes.CFUNCTYPE)

COINIT_APARTMENTTHREADED = 0x2
CLSCTX_INPROC_SERVER = 0x1
RPC_E_CHANGED_MODE = 0x80010106
UIA_TEXT_PATTERN_ID = 10014


class GUID(ctypes.Structure):
    _fields_ = [
        ("Data1", ctypes.c_ulong),
        ("Data2", ctypes.c_ushort),
        ("Data3", ctypes.c_ushort),
        ("Data4", ctypes.c_ubyte * 8),
    ]

    @classmethod
    def from_text(cls, value: str) -> "GUID":
        return cls.from_buffer_copy(uuid.UUID(value).bytes_le)


CLSID_CUI_AUTOMATION = GUID.from_text("ff48dba4-60ef-4201-aa87-54103eef594e")
IID_IUI_AUTOMATION = GUID.from_text("30cbe57d-d9d0-452a-ab13-7ac5ac4825ee")
IID_IUI_AUTOMATION_TEXT_PATTERN = GUID.from_text(
    "32eba289-3583-42c9-9c59-3b6d9a1e9b6a"
)


def _com_method(
    pointer: ctypes.c_void_p,
    index: int,
    result_type: type[ctypes._SimpleCData],
    *argument_types: type[ctypes._SimpleCData],
):
    if not pointer:
        raise OSError("COM interface pointer is null")
    vtable = ctypes.cast(
        pointer, ctypes.POINTER(ctypes.POINTER(ctypes.c_void_p))
    ).contents
    prototype = WINFUNCTYPE(result_type, ctypes.c_void_p, *argument_types)
    return prototype(vtable[index])


def _check_hresult(result: int, operation: str) -> None:
    signed = ctypes.c_long(result).value
    if signed < 0:
        raise OSError(f"{operation} failed (HRESULT 0x{signed & 0xFFFFFFFF:08X})")


def _release(pointer: ctypes.c_void_p) -> None:
    if pointer:
        _com_method(pointer, 2, ULONG)(pointer)


def get_selected_text_by_automation(max_length: int = 5_000) -> str:
    """Return the focused control's selected text, or an empty string.

    UI Automation works without touching the clipboard in browsers and many
    native/UWP editors. Unsupported controls simply fall back to Ctrl+C in the
    caller.
    """

    if not hasattr(ctypes, "WinDLL"):
        return ""

    ole32 = ctypes.WinDLL("ole32", use_last_error=True)
    oleaut32 = ctypes.WinDLL("oleaut32", use_last_error=True)
    ole32.CoInitializeEx.argtypes = (ctypes.c_void_p, ctypes.c_ulong)
    ole32.CoInitializeEx.restype = HRESULT
    ole32.CoUninitialize.argtypes = ()
    ole32.CoCreateInstance.argtypes = (
        ctypes.POINTER(GUID),
        ctypes.c_void_p,
        ctypes.c_ulong,
        ctypes.POINTER(GUID),
        ctypes.POINTER(ctypes.c_void_p),
    )
    ole32.CoCreateInstance.restype = HRESULT
    oleaut32.SysStringLen.argtypes = (ctypes.c_void_p,)
    oleaut32.SysStringLen.restype = ctypes.c_uint
    oleaut32.SysFreeString.argtypes = (ctypes.c_void_p,)

    initialized_here = False
    automation = ctypes.c_void_p()
    element = ctypes.c_void_p()
    text_pattern = ctypes.c_void_p()
    ranges = ctypes.c_void_p()
    try:
        initialize_result = int(
            ole32.CoInitializeEx(None, COINIT_APARTMENTTHREADED)
        )
        initialize_code = initialize_result & 0xFFFFFFFF
        if initialize_result in (0, 1):
            initialized_here = True
        elif initialize_code != RPC_E_CHANGED_MODE:
            _check_hresult(initialize_result, "CoInitializeEx")

        _check_hresult(
            ole32.CoCreateInstance(
                ctypes.byref(CLSID_CUI_AUTOMATION),
                None,
                CLSCTX_INPROC_SERVER,
                ctypes.byref(IID_IUI_AUTOMATION),
                ctypes.byref(automation),
            ),
            "CoCreateInstance(CUIAutomation)",
        )

        # IUIAutomation: IUnknown (0-2), GetFocusedElement is method 8.
        get_focused_element = _com_method(
            automation, 8, HRESULT, ctypes.POINTER(ctypes.c_void_p)
        )
        _check_hresult(
            get_focused_element(automation, ctypes.byref(element)),
            "IUIAutomation.GetFocusedElement",
        )

        # IUIAutomationElement.GetCurrentPatternAs is method 14.
        get_current_pattern_as = _com_method(
            element,
            14,
            HRESULT,
            ctypes.c_int,
            ctypes.POINTER(GUID),
            ctypes.POINTER(ctypes.c_void_p),
        )
        _check_hresult(
            get_current_pattern_as(
                element,
                UIA_TEXT_PATTERN_ID,
                ctypes.byref(IID_IUI_AUTOMATION_TEXT_PATTERN),
                ctypes.byref(text_pattern),
            ),
            "IUIAutomationElement.GetCurrentPatternAs(TextPattern)",
        )

        # IUIAutomationTextPattern.GetSelection is method 5.
        get_selection = _com_method(
            text_pattern, 5, HRESULT, ctypes.POINTER(ctypes.c_void_p)
        )
        _check_hresult(
            get_selection(text_pattern, ctypes.byref(ranges)),
            "IUIAutomationTextPattern.GetSelection",
        )

        get_length = _com_method(ranges, 3, HRESULT, ctypes.POINTER(ctypes.c_int))
        length = ctypes.c_int()
        _check_hresult(
            get_length(ranges, ctypes.byref(length)),
            "IUIAutomationTextRangeArray.Length",
        )

        get_element = _com_method(
            ranges,
            4,
            HRESULT,
            ctypes.c_int,
            ctypes.POINTER(ctypes.c_void_p),
        )
        selected_parts: list[str] = []
        remaining = max(0, max_length)
        for index in range(max(0, length.value)):
            if remaining == 0:
                break
            text_range = ctypes.c_void_p()
            bstr = ctypes.c_void_p()
            try:
                _check_hresult(
                    get_element(ranges, index, ctypes.byref(text_range)),
                    "IUIAutomationTextRangeArray.GetElement",
                )
                # IUIAutomationTextRange.GetText is method 12.
                get_text = _com_method(
                    text_range,
                    12,
                    HRESULT,
                    ctypes.c_int,
                    ctypes.POINTER(ctypes.c_void_p),
                )
                _check_hresult(
                    get_text(text_range, remaining, ctypes.byref(bstr)),
                    "IUIAutomationTextRange.GetText",
                )
                if bstr:
                    part_length = min(int(oleaut32.SysStringLen(bstr)), remaining)
                    part = ctypes.wstring_at(bstr, part_length)
                    selected_parts.append(part)
                    remaining -= len(part)
            finally:
                if bstr:
                    oleaut32.SysFreeString(bstr)
                _release(text_range)

        return "".join(selected_parts).strip()
    except (OSError, ValueError):
        return ""
    finally:
        _release(ranges)
        _release(text_pattern)
        _release(element)
        _release(automation)
        if initialized_here:
            ole32.CoUninitialize()
