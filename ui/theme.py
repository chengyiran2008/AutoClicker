# -*- coding: utf-8 -*-
"""白色主题与 DPI 缩放。"""
from __future__ import annotations

import tkinter as tk
from tkinter import font as tkfont
from tkinter import ttk

from core.winapi import get_system_dpi

# 配色：以白为主，蓝色作强调
BG = "#FFFFFF"
PANEL = "#F7F8FA"
CHIP = "#F2F3F5"
BORDER = "#E5E6EB"
BORDER_STRONG = "#C9CDD4"
TEXT = "#1D2129"
SUB = "#86909C"
ACCENT = "#165DFF"
ACCENT_HOVER = "#4080FF"
ACCENT_PRESS = "#0E42D2"
SUCCESS = "#00B42A"
DANGER = "#F53F3F"
DANGER_HOVER = "#F76965"
WARN = "#FF7D00"

FONT_CANDIDATES = ("Microsoft YaHei UI", "Microsoft YaHei", "Segoe UI", "TkDefaultFont")


class Theme:
    def __init__(self, root: tk.Misc) -> None:
        self.root = root
        dpi = get_system_dpi()
        self.scale = max(1.0, dpi / 96.0)
        try:
            root.tk.call("tk", "scaling", dpi / 72.0)
        except Exception:
            pass
        families = set(tkfont.families(root))
        self.family = next((f for f in FONT_CANDIDATES if f in families), "TkDefaultFont")

    # ---------------- 尺寸与字体
    def px(self, value: float) -> int:
        return max(1, int(round(value * self.scale)))

    def font(self, size: int = 10, bold: bool = False, mono: bool = False):
        family = "Consolas" if mono else self.family
        return (family, size, "bold") if bold else (family, size)

    # ---------------- ttk 样式
    def apply(self) -> ttk.Style:
        style = ttk.Style(self.root)
        try:
            style.theme_use("clam")
        except tk.TclError:
            pass

        base = self.font(10)
        style.configure(".", background=BG, foreground=TEXT, font=base,
                        borderwidth=0, focuscolor=BG)
        style.configure("TFrame", background=BG)
        style.configure("Panel.TFrame", background=PANEL)
        style.configure("Card.TFrame", background=BG)

        style.configure("TLabel", background=BG, foreground=TEXT, font=base)
        style.configure("Panel.TLabel", background=PANEL, foreground=TEXT)
        style.configure("Sub.TLabel", background=BG, foreground=SUB, font=self.font(9))
        style.configure("PanelSub.TLabel", background=PANEL, foreground=SUB, font=self.font(9))
        style.configure("Title.TLabel", background=BG, foreground=TEXT, font=self.font(11, True))
        style.configure("H1.TLabel", background=BG, foreground=TEXT, font=self.font(14, True))
        style.configure("Value.TLabel", background=BG, foreground=TEXT, font=self.font(13, True, mono=True))
        style.configure("Accent.TLabel", background=BG, foreground=ACCENT, font=self.font(10, True))

        style.configure("TSeparator", background=BORDER)

        style.configure("TNotebook", background=BG, borderwidth=0, tabmargins=(0, 0, 0, 0))
        style.configure("TNotebook.Tab", background=CHIP, foreground=SUB,
                        padding=(self.px(18), self.px(8)), font=self.font(10, True),
                        borderwidth=0)
        style.map("TNotebook.Tab",
                  background=[("selected", BG), ("active", "#E8F0FF")],
                  foreground=[("selected", ACCENT), ("active", TEXT)])

        style.configure("TLabelframe", background=BG, bordercolor=BORDER,
                        borderwidth=1, relief="solid",
                        padding=(self.px(12), self.px(10)))
        style.configure("TLabelframe.Label", background=BG, foreground=TEXT,
                        font=self.font(10, True))

        for name in ("TEntry", "TSpinbox", "TCombobox"):
            style.configure(name, fieldbackground=BG, background=BG, foreground=TEXT,
                            bordercolor=BORDER, lightcolor=BG, darkcolor=BG,
                            insertcolor=TEXT, arrowcolor=SUB, arrowsize=self.px(12),
                            padding=(self.px(6), self.px(4)), relief="solid", borderwidth=1)
            style.map(name,
                      bordercolor=[("focus", ACCENT), ("hover", BORDER_STRONG)],
                      fieldbackground=[("disabled", PANEL)],
                      foreground=[("disabled", SUB)])
        style.configure("TCombobox", selectbackground=BG, selectforeground=TEXT)
        self.root.option_add("*TCombobox*Listbox.background", BG)
        self.root.option_add("*TCombobox*Listbox.foreground", TEXT)
        self.root.option_add("*TCombobox*Listbox.selectBackground", ACCENT)
        self.root.option_add("*TCombobox*Listbox.selectForeground", "#FFFFFF")
        self.root.option_add("*TCombobox*Listbox.font", base)

        style.configure("TCheckbutton", background=BG, foreground=TEXT, font=base,
                        indicatorcolor=BG, indicatorbackground=BG, bordercolor=BORDER_STRONG,
                        padding=(0, self.px(2)))
        style.map("TCheckbutton",
                  indicatorcolor=[("selected", ACCENT), ("active", "#E8F0FF")],
                  foreground=[("disabled", SUB)])
        style.configure("TRadiobutton", background=BG, foreground=TEXT, font=base,
                        indicatorcolor=BG, bordercolor=BORDER_STRONG,
                        padding=(0, self.px(2)))
        style.map("TRadiobutton",
                  indicatorcolor=[("selected", ACCENT), ("active", "#E8F0FF")],
                  foreground=[("disabled", SUB)])

        style.configure("TScale", background=BG, troughcolor=CHIP,
                        bordercolor=BORDER, lightcolor=ACCENT, darkcolor=ACCENT)

        style.configure("Link.TButton", background=BG, foreground=ACCENT,
                        font=self.font(9), relief="flat", borderwidth=0,
                        padding=(self.px(6), self.px(3)))
        style.map("Link.TButton", background=[("active", "#E8F0FF")],
                  foreground=[("active", ACCENT_PRESS)])

        style.configure("Mini.TButton", background=CHIP, foreground=TEXT,
                        font=self.font(9), relief="flat", borderwidth=0,
                        padding=(self.px(10), self.px(4)))
        style.map("Mini.TButton",
                  background=[("active", "#E8F0FF"), ("pressed", "#DCE7FF")],
                  foreground=[("active", ACCENT)])

        style.configure("Vertical.TScrollbar", background=CHIP, troughcolor=BG,
                        bordercolor=BG, arrowcolor=SUB, gripcount=0)
        return style
