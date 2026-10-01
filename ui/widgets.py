# -*- coding: utf-8 -*-
"""通用界面组件：卡片、实心按钮、色块、热键选择器、全屏框选。"""
from __future__ import annotations

import tkinter as tk

from core.hotkey import Hotkey, vk_name
from core.winapi import VK_CONTROL, VK_MENU, VK_SHIFT, is_key_down, virtual_screen

from .theme import (ACCENT, ACCENT_HOVER, ACCENT_PRESS, BG, BORDER, BORDER_STRONG,
                    CHIP, DANGER, DANGER_HOVER, SUB, TEXT)

BUTTON_KINDS = {
    "primary": (ACCENT, "#FFFFFF", ACCENT_HOVER, ACCENT_PRESS),
    "danger": (DANGER, "#FFFFFF", DANGER_HOVER, "#CB272D"),
    "ghost": (CHIP, TEXT, "#E8F0FF", "#DCE7FF"),
}


class Card(tk.Frame):
    """白底描边卡片，可带标题。内容请放到 self.body。tint 可指定浅色背景。"""

    def __init__(self, master, theme, title: str = "", subtitle: str = "", pad: int = 12,
                 tint: str | None = None):
        tint = tint or BG
        super().__init__(master, bg=tint, highlightbackground=BORDER,
                         highlightcolor=BORDER, highlightthickness=1, bd=0)
        self.theme = theme
        p = theme.px(pad)
        if title:
            header = tk.Frame(self, bg=tint)
            header.pack(fill="x", padx=p, pady=(p, 0))
            tk.Label(header, text=title, bg=tint, fg=TEXT,
                     font=theme.font(11, True)).pack(side="left")
            if subtitle:
                tk.Label(header, text=subtitle, bg=tint, fg=SUB,
                         font=theme.font(9)).pack(side="left", padx=(theme.px(8), 0))
        self.body = tk.Frame(self, bg=tint)
        self.body.pack(fill="both", expand=True, padx=p, pady=p)


class SolidButton(tk.Button):
    """扁平实心按钮，带悬停反馈。"""

    def __init__(self, master, theme, text: str, command=None, kind: str = "primary",
                 width: int | None = None, big: bool = False):
        self.theme = theme
        self._kind = kind
        bg, fg, hover, press = BUTTON_KINDS[kind]
        super().__init__(master, text=text, command=command, bg=bg, fg=fg,
                         activebackground=press, activeforeground=fg,
                         relief="flat", bd=0, highlightthickness=0,
                         cursor="hand2", font=theme.font(11 if big else 10, True),
                         padx=theme.px(20 if big else 12),
                         pady=theme.px(9 if big else 5))
        if width:
            self.configure(width=width)
        self._hover = hover
        self._bg = bg
        self.bind("<Enter>", self._on_enter, add="+")
        self.bind("<Leave>", self._on_leave, add="+")

    def _on_enter(self, _=None):
        if str(self["state"]) != "disabled":
            self.configure(bg=self._hover)

    def _on_leave(self, _=None):
        self.configure(bg=self._bg)

    def set_kind(self, kind: str, text: str | None = None) -> None:
        bg, fg, hover, press = BUTTON_KINDS[kind]
        self._kind, self._bg, self._hover = kind, bg, hover
        self.configure(bg=bg, fg=fg, activebackground=press, activeforeground=fg)
        if text is not None:
            self.configure(text=text)


class ColorSwatch(tk.Frame):
    """颜色预览块。"""

    def __init__(self, master, theme, color: str = "#FFFFFF", width: int = 34, height: int = 22):
        super().__init__(master, bg=color, highlightbackground=BORDER_STRONG,
                         highlightthickness=1, bd=0,
                         width=theme.px(width), height=theme.px(height))
        self.pack_propagate(False)

    def set_color(self, color: str) -> None:
        try:
            self.configure(bg=color)
        except tk.TclError:
            pass


class HotkeyPicker(tk.Frame):
    """点击后进入捕获状态，按下任意组合键完成设置。"""

    def __init__(self, master, theme, label: str, hotkey: Hotkey,
                 on_change=None, on_capture=None):
        super().__init__(master, bg=BG)
        self.theme = theme
        self.hotkey = hotkey
        self._on_change = on_change
        self._on_capture = on_capture
        self._capturing = False

        tk.Label(self, text=label, bg=BG, fg=SUB,
                 font=theme.font(9)).pack(anchor="w")
        self.button = tk.Button(self, text=hotkey.label, command=self._begin,
                                bg=CHIP, fg=TEXT, activebackground="#DCE7FF",
                                relief="flat", bd=0, highlightthickness=1,
                                highlightbackground=BORDER, cursor="hand2",
                                font=theme.font(10, True),
                                padx=theme.px(10), pady=theme.px(4), width=11)
        self.button.pack(anchor="w", pady=(theme.px(3), 0))

    def _begin(self) -> None:
        if self._capturing:
            return
        self._capturing = True
        self.button.configure(text="按下按键…", bg="#E8F0FF", fg=ACCENT,
                              highlightbackground=ACCENT)
        if self._on_capture:
            self._on_capture(True)
        self.button.focus_set()
        self.button.bind("<KeyPress>", self._on_key)
        self.button.bind("<FocusOut>", lambda e: self._end())

    def _end(self) -> None:
        if not self._capturing:
            return
        self._capturing = False
        self.button.unbind("<KeyPress>")
        self.button.unbind("<FocusOut>")
        self.button.configure(text=self.hotkey.label, bg=CHIP, fg=TEXT,
                              highlightbackground=BORDER)
        if self._on_capture:
            self._on_capture(False)

    def _on_key(self, event) -> str:
        vk = int(event.keycode)
        if vk == 0x1B:  # Esc 取消
            self._end()
            return "break"
        if vk in (VK_SHIFT, VK_CONTROL, VK_MENU):
            return "break"
        if vk not in range(1, 256):
            return "break"
        hotkey = Hotkey(vk, ctrl=is_key_down(VK_CONTROL),
                        alt=is_key_down(VK_MENU), shift=is_key_down(VK_SHIFT))
        if not vk_name(vk):
            return "break"
        self.hotkey = hotkey
        self._end()
        if self._on_change:
            self._on_change(hotkey)
        return "break"

    def set_hotkey(self, hotkey: Hotkey) -> None:
        self.hotkey = hotkey
        self.button.configure(text=hotkey.label)


class RegionPicker:
    """全屏半透明遮罩 + 拖拽选择屏幕区域。"""

    def __init__(self, root: tk.Misc, theme, on_done, on_cancel=None):
        self.on_done = on_done
        self.on_cancel = on_cancel
        vx, vy, vw, vh = virtual_screen()
        self.origin = (vx, vy)
        self.start = None
        self.rect = None
        self.size_text = None

        top = tk.Toplevel(root)
        self.top = top
        top.overrideredirect(True)
        top.geometry("%dx%d+%d+%d" % (vw, vh, vx, vy))
        top.attributes("-topmost", True)
        try:
            top.attributes("-alpha", 0.35)
        except tk.TclError:
            pass
        top.configure(bg="#000000", cursor="crosshair")

        self.canvas = tk.Canvas(top, bg="#000000", highlightthickness=0, cursor="crosshair")
        self.canvas.pack(fill="both", expand=True)
        self.canvas.create_text(
            vw // 2, theme.px(48),
            text="拖拽鼠标框选需要监测的屏幕区域    ·    按 Esc 取消",
            fill="#FFFFFF", font=theme.font(15, True))

        self.canvas.bind("<Button-1>", self._on_press)
        self.canvas.bind("<B1-Motion>", self._on_drag)
        self.canvas.bind("<ButtonRelease-1>", self._on_release)
        top.bind("<Escape>", lambda e: self._cancel())
        top.focus_force()
        self.canvas.focus_set()

    def _on_press(self, event) -> None:
        self.start = (event.x, event.y)
        if self.rect:
            self.canvas.delete(self.rect)
        self.rect = self.canvas.create_rectangle(event.x, event.y, event.x, event.y,
                                                 outline="#FFFFFF", width=2)
        self.size_text = self.canvas.create_text(event.x, event.y - 12, text="",
                                                 fill="#FFFFFF", anchor="w")

    def _on_drag(self, event) -> None:
        if not self.start or not self.rect:
            return
        x0, y0 = self.start
        self.canvas.coords(self.rect, x0, y0, event.x, event.y)
        self.canvas.coords(self.size_text, min(x0, event.x), min(y0, event.y) - 12)
        self.canvas.itemconfig(self.size_text,
                               text="%d × %d" % (abs(event.x - x0), abs(event.y - y0)))

    def _on_release(self, event) -> None:
        if not self.start:
            self._cancel()
            return
        x0, y0 = self.start
        vx, vy = self.origin
        region = (x0 + vx, y0 + vy, event.x + vx, event.y + vy)
        self.top.destroy()
        if abs(region[2] - region[0]) < 2 or abs(region[3] - region[1]) < 2:
            if self.on_cancel:
                self.on_cancel()
            return
        self.on_done(region)

    def _cancel(self) -> None:
        self.top.destroy()
        if self.on_cancel:
            self.on_cancel()


# ---------------------------------------------------------------- 输入解析


def to_int(value, default: int, lo: int | None = None, hi: int | None = None) -> int:
    try:
        result = int(float(str(value).strip()))
    except (TypeError, ValueError):
        return default
    if lo is not None:
        result = max(lo, result)
    if hi is not None:
        result = min(hi, result)
    return result


def to_float(value, default: float, lo: float | None = None, hi: float | None = None) -> float:
    try:
        result = float(str(value).strip())
    except (TypeError, ValueError):
        return default
    if lo is not None:
        result = max(lo, result)
    if hi is not None:
        result = min(hi, result)
    return result
