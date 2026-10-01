# -*- coding: utf-8 -*-
"""Win32 底层封装（纯 ctypes，无第三方依赖）。

提供：DPI 感知、鼠标坐标读写、SendInput 点击、按键状态查询、
屏幕区域抓取与取色（BitBlt + GetDIBits）。
"""
from __future__ import annotations

import ctypes
from ctypes import wintypes

user32 = ctypes.WinDLL("user32", use_last_error=True)
gdi32 = ctypes.WinDLL("gdi32", use_last_error=True)
try:
    winmm = ctypes.WinDLL("winmm")
except OSError:  # pragma: no cover
    winmm = None

ULONG_PTR = wintypes.WPARAM


def begin_timer_period(ms: int = 1) -> None:
    """临时提升系统定时器精度，让毫秒级连点间隔更准。"""
    if winmm:
        try:
            winmm.timeBeginPeriod(int(ms))
        except Exception:
            pass


def end_timer_period(ms: int = 1) -> None:
    if winmm:
        try:
            winmm.timeEndPeriod(int(ms))
        except Exception:
            pass

# ---------------------------------------------------------------- DPI


def enable_dpi_awareness() -> None:
    """开启 DPI 感知，保证 GetCursorPos / 截屏 / 界面坐标三者一致。"""
    try:
        ctypes.windll.shcore.SetProcessDpiAwareness(1)  # SYSTEM_DPI_AWARE
        return
    except Exception:
        pass
    try:
        user32.SetProcessDPIAware()
    except Exception:
        pass


def get_system_dpi() -> int:
    try:
        hdc = user32.GetDC(0)
        dpi = gdi32.GetDeviceCaps(hdc, 88)  # LOGPIXELSX
        user32.ReleaseDC(0, hdc)
        return int(dpi) or 96
    except Exception:
        return 96


# ---------------------------------------------------------------- 坐标


class POINT(ctypes.Structure):
    _fields_ = [("x", wintypes.LONG), ("y", wintypes.LONG)]


user32.GetCursorPos.argtypes = [ctypes.POINTER(POINT)]
user32.GetCursorPos.restype = wintypes.BOOL
user32.SetCursorPos.argtypes = [ctypes.c_int, ctypes.c_int]
user32.SetCursorPos.restype = wintypes.BOOL
user32.GetSystemMetrics.argtypes = [ctypes.c_int]
user32.GetSystemMetrics.restype = ctypes.c_int


def get_cursor_pos() -> tuple[int, int]:
    pt = POINT()
    user32.GetCursorPos(ctypes.byref(pt))
    return int(pt.x), int(pt.y)


def set_cursor_pos(x: int, y: int) -> None:
    user32.SetCursorPos(int(x), int(y))


def virtual_screen() -> tuple[int, int, int, int]:
    """整个虚拟桌面（含多显示器）的 (left, top, width, height)。"""
    left = user32.GetSystemMetrics(76)   # SM_XVIRTUALSCREEN
    top = user32.GetSystemMetrics(77)    # SM_YVIRTUALSCREEN
    width = user32.GetSystemMetrics(78)  # SM_CXVIRTUALSCREEN
    height = user32.GetSystemMetrics(79)  # SM_CYVIRTUALSCREEN
    return int(left), int(top), int(width or 1920), int(height or 1080)


# ---------------------------------------------------------------- 鼠标输入

INPUT_MOUSE = 0
MOUSEEVENTF_MOVE = 0x0001
MOUSEEVENTF_LEFTDOWN = 0x0002
MOUSEEVENTF_LEFTUP = 0x0004
MOUSEEVENTF_RIGHTDOWN = 0x0008
MOUSEEVENTF_RIGHTUP = 0x0010
MOUSEEVENTF_MIDDLEDOWN = 0x0020
MOUSEEVENTF_MIDDLEUP = 0x0040
MOUSEEVENTF_ABSOLUTE = 0x8000

BUTTON_FLAGS = {
    "left": (MOUSEEVENTF_LEFTDOWN, MOUSEEVENTF_LEFTUP),
    "right": (MOUSEEVENTF_RIGHTDOWN, MOUSEEVENTF_RIGHTUP),
    "middle": (MOUSEEVENTF_MIDDLEDOWN, MOUSEEVENTF_MIDDLEUP),
}


class MOUSEINPUT(ctypes.Structure):
    _fields_ = [
        ("dx", wintypes.LONG),
        ("dy", wintypes.LONG),
        ("mouseData", wintypes.DWORD),
        ("dwFlags", wintypes.DWORD),
        ("time", wintypes.DWORD),
        ("dwExtraInfo", ULONG_PTR),
    ]


class _INPUTUNION(ctypes.Union):
    _fields_ = [("mi", MOUSEINPUT)]


class INPUT(ctypes.Structure):
    _anonymous_ = ("u",)
    _fields_ = [("type", wintypes.DWORD), ("u", _INPUTUNION)]


user32.SendInput.argtypes = [wintypes.UINT, ctypes.POINTER(INPUT), ctypes.c_int]
user32.SendInput.restype = wintypes.UINT


def _send_mouse(flags: int) -> None:
    inp = INPUT(type=INPUT_MOUSE)
    inp.mi = MOUSEINPUT(0, 0, 0, flags, 0, 0)
    user32.SendInput(1, ctypes.byref(inp), ctypes.sizeof(INPUT))


def mouse_down(button: str = "left") -> None:
    _send_mouse(BUTTON_FLAGS.get(button, BUTTON_FLAGS["left"])[0])


def mouse_up(button: str = "left") -> None:
    _send_mouse(BUTTON_FLAGS.get(button, BUTTON_FLAGS["left"])[1])


# ---------------------------------------------------------------- 按键状态

VK_SHIFT = 0x10
VK_CONTROL = 0x11
VK_MENU = 0x12

user32.GetAsyncKeyState.argtypes = [ctypes.c_int]
user32.GetAsyncKeyState.restype = ctypes.c_short


def is_key_down(vk: int) -> bool:
    return bool(user32.GetAsyncKeyState(int(vk)) & 0x8000)


# ---------------------------------------------------------------- 屏幕取色

SRCCOPY = 0x00CC0020
CAPTUREBLT = 0x40000000
DIB_RGB_COLORS = 0
BI_RGB = 0


class BITMAPINFOHEADER(ctypes.Structure):
    _fields_ = [
        ("biSize", wintypes.DWORD),
        ("biWidth", wintypes.LONG),
        ("biHeight", wintypes.LONG),
        ("biPlanes", wintypes.WORD),
        ("biBitCount", wintypes.WORD),
        ("biCompression", wintypes.DWORD),
        ("biSizeImage", wintypes.DWORD),
        ("biXPelsPerMeter", wintypes.LONG),
        ("biYPelsPerMeter", wintypes.LONG),
        ("biClrUsed", wintypes.DWORD),
        ("biClrImportant", wintypes.DWORD),
    ]


class BITMAPINFO(ctypes.Structure):
    _fields_ = [("bmiHeader", BITMAPINFOHEADER), ("bmiColors", wintypes.DWORD * 3)]


gdi32.CreateCompatibleDC.argtypes = [wintypes.HDC]
gdi32.CreateCompatibleDC.restype = wintypes.HDC
gdi32.CreateCompatibleBitmap.argtypes = [wintypes.HDC, ctypes.c_int, ctypes.c_int]
gdi32.CreateCompatibleBitmap.restype = wintypes.HBITMAP
gdi32.SelectObject.argtypes = [wintypes.HDC, wintypes.HGDIOBJ]
gdi32.SelectObject.restype = wintypes.HGDIOBJ
gdi32.DeleteObject.argtypes = [wintypes.HGDIOBJ]
gdi32.DeleteDC.argtypes = [wintypes.HDC]
gdi32.BitBlt.argtypes = [
    wintypes.HDC, ctypes.c_int, ctypes.c_int, ctypes.c_int, ctypes.c_int,
    wintypes.HDC, ctypes.c_int, ctypes.c_int, wintypes.DWORD,
]
gdi32.BitBlt.restype = wintypes.BOOL
gdi32.GetDIBits.argtypes = [
    wintypes.HDC, wintypes.HBITMAP, wintypes.UINT, wintypes.UINT,
    ctypes.c_void_p, ctypes.POINTER(BITMAPINFO), wintypes.UINT,
]
gdi32.GetDIBits.restype = ctypes.c_int
gdi32.GetPixel.argtypes = [wintypes.HDC, ctypes.c_int, ctypes.c_int]
gdi32.GetPixel.restype = wintypes.DWORD
user32.GetDC.argtypes = [wintypes.HWND]
user32.GetDC.restype = wintypes.HDC
user32.ReleaseDC.argtypes = [wintypes.HWND, wintypes.HDC]


def get_pixel(x: int, y: int) -> tuple[int, int, int]:
    """读取屏幕单点颜色，返回 (r, g, b)。"""
    hdc = user32.GetDC(0)
    if not hdc:
        return (0, 0, 0)
    try:
        color = gdi32.GetPixel(hdc, int(x), int(y))
        if color == 0xFFFFFFFF:  # CLR_INVALID
            return (0, 0, 0)
        return (color & 0xFF, (color >> 8) & 0xFF, (color >> 16) & 0xFF)
    finally:
        user32.ReleaseDC(0, hdc)


class ScreenGrabber:
    """复用 GDI 资源的区域抓屏器，适合高频轮询。返回 BGRA 原始字节。"""

    def __init__(self) -> None:
        self._screen_dc = None
        self._mem_dc = None
        self._bitmap = None
        self._size = (0, 0)
        self._buffer = None
        self._info = None

    def _ensure(self, width: int, height: int) -> bool:
        if self._screen_dc is None:
            self._screen_dc = user32.GetDC(0)
            if not self._screen_dc:
                self._screen_dc = None
                return False
            self._mem_dc = gdi32.CreateCompatibleDC(self._screen_dc)
        if self._size != (width, height) or self._bitmap is None:
            if self._bitmap:
                gdi32.DeleteObject(self._bitmap)
            self._bitmap = gdi32.CreateCompatibleBitmap(self._screen_dc, width, height)
            if not self._bitmap:
                return False
            self._size = (width, height)
            self._buffer = ctypes.create_string_buffer(width * height * 4)
            info = BITMAPINFO()
            info.bmiHeader.biSize = ctypes.sizeof(BITMAPINFOHEADER)
            info.bmiHeader.biWidth = width
            info.bmiHeader.biHeight = -height  # 自上而下
            info.bmiHeader.biPlanes = 1
            info.bmiHeader.biBitCount = 32
            info.bmiHeader.biCompression = BI_RGB
            self._info = info
        return True

    def grab(self, x: int, y: int, width: int, height: int):
        """抓取屏幕区域，返回 (bytes, width, height)；失败返回 (None, 0, 0)。"""
        width = max(1, int(width))
        height = max(1, int(height))
        if not self._ensure(width, height):
            return None, 0, 0
        gdi32.SelectObject(self._mem_dc, self._bitmap)
        ok = gdi32.BitBlt(self._mem_dc, 0, 0, width, height,
                          self._screen_dc, int(x), int(y), SRCCOPY | CAPTUREBLT)
        if not ok:
            ok = gdi32.BitBlt(self._mem_dc, 0, 0, width, height,
                              self._screen_dc, int(x), int(y), SRCCOPY)
        if not ok:
            return None, 0, 0
        got = gdi32.GetDIBits(self._mem_dc, self._bitmap, 0, height,
                              self._buffer, ctypes.byref(self._info), DIB_RGB_COLORS)
        if got == 0:
            return None, 0, 0
        return self._buffer.raw, width, height

    def close(self) -> None:
        if self._bitmap:
            gdi32.DeleteObject(self._bitmap)
            self._bitmap = None
        if self._mem_dc:
            gdi32.DeleteDC(self._mem_dc)
            self._mem_dc = None
        if self._screen_dc:
            user32.ReleaseDC(0, self._screen_dc)
            self._screen_dc = None

    def __del__(self):  # pragma: no cover
        try:
            self.close()
        except Exception:
            pass


# ---------------------------------------------------------------- 工具


def rgb_to_hex(rgb) -> str:
    r, g, b = (max(0, min(255, int(v))) for v in rgb)
    return "#%02X%02X%02X" % (r, g, b)


def hex_to_rgb(text: str):
    """解析 #RRGGBB / RRGGBB / r,g,b，失败返回 None。"""
    if not text:
        return None
    s = str(text).strip().lstrip("#")
    if "," in s:
        parts = [p.strip() for p in s.split(",")]
        if len(parts) != 3:
            return None
        try:
            vals = [max(0, min(255, int(p))) for p in parts]
        except ValueError:
            return None
        return tuple(vals)
    if len(s) == 3:
        s = "".join(c * 2 for c in s)
    if len(s) != 6:
        return None
    try:
        return (int(s[0:2], 16), int(s[2:4], 16), int(s[4:6], 16))
    except ValueError:
        return None
