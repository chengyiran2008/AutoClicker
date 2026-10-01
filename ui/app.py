# -*- coding: utf-8 -*-
"""主窗口：实时坐标/取色、手动连点、智能颜色触发连点、全局快捷键。"""
from __future__ import annotations

import json
import os
import queue
import sys
import time
import tkinter as tk
from tkinter import ttk

from core.engine import (ClickerEngine, ManualConfig, SmartConfig, normalize_region,
                         sample_region)
from core.hotkey import Hotkey, HotkeyListener
from core.winapi import (ScreenGrabber, get_cursor_pos, get_pixel, hex_to_rgb,
                         rgb_to_hex)

from .theme import (ACCENT, BG, BORDER, CHIP, DANGER, PANEL, SUB, SUCCESS, TEXT,
                    WARN, Theme)
from .widgets import (Card, ColorSwatch, HotkeyPicker, RegionPicker, SolidButton,
                      to_float, to_int)

def _app_dir() -> str:
    """程序目录：打包成 exe 后取 exe 所在目录，否则取源码包根目录。"""
    if getattr(sys, "frozen", False):
        return os.path.dirname(sys.executable)
    return os.path.dirname(os.path.dirname(os.path.abspath(__file__)))


CONFIG_PATH = os.path.join(_app_dir(), "config.json")

DEFAULT_HOTKEYS = {
    "toggle": "F6",
    "stop": "F12",
    "pick_point": "F7",
    "pick_color": "F8",
}


class Choice:
    """中文选项 <-> 内部值 的双向映射。"""

    def __init__(self, pairs):
        self.labels = [p[0] for p in pairs]
        self._l2v = {p[0]: p[1] for p in pairs}
        self._v2l = {p[1]: p[0] for p in pairs}

    def value(self, label, default=None):
        return self._l2v.get(label, default if default is not None else self.labels and self._l2v[self.labels[0]])

    def label(self, value):
        return self._v2l.get(value, self.labels[0])


BUTTONS = Choice([("鼠标左键", "left"), ("鼠标右键", "right"), ("鼠标中键", "middle")])
CLICK_TYPES = Choice([("单击", "single"), ("双击", "double")])
TRIGGERS = Choice([("匹配目标颜色时触发", "match"),
                   ("偏离目标颜色时触发", "mismatch"),
                   ("颜色发生变化时触发", "change")])
SAMPLES = Choice([("区域平均色", "average"), ("区域内像素占比", "ratio")])
POSITIONS = Choice([("监测区域中心", "region_center"),
                    ("鼠标当前位置", "cursor"),
                    ("指定坐标", "fixed")])


class ClickerApp:
    def __init__(self, root: tk.Tk) -> None:
        self.root = root
        self.theme = Theme(root)
        self.theme.apply()
        self.px = self.theme.px

        root.title("轻点 · 鼠标连点器")
        root.configure(bg=BG)
        root.minsize(self.px(880), self.px(700))

        self.events: queue.Queue = queue.Queue()
        self.engine = ClickerEngine(on_event=self.events.put)
        self.grabber = ScreenGrabber()
        self.region = None            # (x1, y1, x2, y2) 或 None
        self._last_region_probe = 0.0
        self._capturing_hotkey = False

        self._init_vars()
        self._build()
        self._load_config()

        self.listener = HotkeyListener()
        self._rebind_hotkeys()
        self.listener.start()

        root.protocol("WM_DELETE_WINDOW", self._on_close)
        self._tick()
        self._drain()
        self._log("就绪。默认 %s 启动/停止连点，%s 紧急停止。"
                  % (self.hotkeys["toggle"].label, self.hotkeys["stop"].label))

    # ================================================== 变量
    def _init_vars(self) -> None:
        v = tk.StringVar
        # 手动
        self.m_button = v(value=BUTTONS.label("left"))
        self.m_type = v(value=CLICK_TYPES.label("single"))
        self.m_interval = v(value="100")
        self.m_jitter = v(value="0")
        self.m_hold = v(value="10")
        self.m_count_mode = v(value="infinite")   # infinite / fixed
        self.m_count = v(value="100")
        self.m_pos_mode = v(value="cursor")       # cursor / fixed
        self.m_x = v(value="0")
        self.m_y = v(value="0")
        self.m_delay = v(value="0")
        # 智能
        self.s_trigger = v(value=TRIGGERS.label("match"))
        self.s_sample = v(value=SAMPLES.label("average"))
        self.s_color = v(value="#FFFFFF")
        self.s_tolerance = v(value="20")
        self.s_ratio = v(value="30")
        self.s_check = v(value="100")
        self.s_action = v(value="burst")          # burst / hold
        self.s_burst = v(value="1")
        self.s_cooldown = v(value="300")
        self.s_max_trig = v(value="0")
        self.s_pos = v(value=POSITIONS.label("region_center"))
        self.s_x = v(value="0")
        self.s_y = v(value="0")
        # 热键
        self.hotkeys = {name: (Hotkey.parse(label) or Hotkey(0x75))
                        for name, label in DEFAULT_HOTKEYS.items()}

    # ================================================== 布局
    def _build(self) -> None:
        pad = self.px(14)
        # 顶部装饰条：横贯窗口的强调色细线
        topbar = tk.Frame(self.root, bg=ACCENT, height=self.px(3))
        topbar.pack(side="top", fill="x")
        topbar.pack_propagate(False)
        outer = tk.Frame(self.root, bg=BG)
        outer.pack(fill="both", expand=True, padx=pad, pady=pad)

        self._build_header(outer)
        self._build_tiles(outer)
        self._build_tabs(outer)
        self._build_hotkeys(outer)
        self._build_controls(outer)
        self._build_log(outer)

    # -------------------------------------------------- 顶部
    def _build_header(self, parent) -> None:
        bar = tk.Frame(parent, bg=BG)
        bar.pack(fill="x", pady=(0, self.px(12)))

        left = tk.Frame(bar, bg=BG)
        left.pack(side="left")
        tk.Label(left, text="轻点 · 鼠标连点器", bg=BG, fg=TEXT,
                 font=self.theme.font(16, True)).pack(anchor="w")
        tk.Label(left, text="手动连点 · 屏幕颜色智能触发 · 全局快捷键控制",
                 bg=BG, fg=SUB, font=self.theme.font(9)).pack(anchor="w",
                                                              pady=(self.px(2), 0))

        self.badge = tk.Label(bar, text="  ● 就绪  ", bg=CHIP, fg=SUB,
                              font=self.theme.font(10, True),
                              padx=self.px(8), pady=self.px(5))
        self.badge.pack(side="right")

    # -------------------------------------------------- 信息卡
    def _build_tiles(self, parent) -> None:
        row = tk.Frame(parent, bg=BG)
        row.pack(fill="x", pady=(0, self.px(12)))
        for i in range(3):
            row.columnconfigure(i, weight=1, uniform="tile")
        T = PANEL  # 信息卡浅色底，与白底主区形成层次

        # 鼠标坐标
        c1 = Card(row, self.theme, pad=12, tint=T)
        c1.grid(row=0, column=0, sticky="nsew", padx=(0, self.px(8)))
        tk.Label(c1.body, text="鼠标实时坐标", bg=T, fg=SUB,
                 font=self.theme.font(9)).pack(anchor="w")
        self.lbl_pos = tk.Label(c1.body, text="X: 0    Y: 0", bg=T, fg=TEXT,
                                font=self.theme.font(15, True, mono=True))
        self.lbl_pos.pack(anchor="w", pady=(self.px(4), 0))

        # 光标处颜色
        c2 = Card(row, self.theme, pad=12, tint=T)
        c2.grid(row=0, column=1, sticky="nsew", padx=self.px(4))
        tk.Label(c2.body, text="光标处颜色", bg=T, fg=SUB,
                 font=self.theme.font(9)).pack(anchor="w")
        line = tk.Frame(c2.body, bg=T)
        line.pack(anchor="w", pady=(self.px(4), 0))
        self.sw_cursor = ColorSwatch(line, self.theme, "#FFFFFF", 26, 22)
        self.sw_cursor.pack(side="left")
        self.lbl_color = tk.Label(line, text="#FFFFFF", bg=T, fg=TEXT,
                                  font=self.theme.font(15, True, mono=True))
        self.lbl_color.pack(side="left", padx=(self.px(8), 0))

        # 运行统计
        c3 = Card(row, self.theme, pad=12, tint=T)
        c3.grid(row=0, column=2, sticky="nsew", padx=(self.px(8), 0))
        tk.Label(c3.body, text="本次运行统计", bg=T, fg=SUB,
                 font=self.theme.font(9)).pack(anchor="w")
        self.lbl_stats = tk.Label(c3.body, text="点击 0 次 · 触发 0 次", bg=T, fg=TEXT,
                                  font=self.theme.font(15, True, mono=True))
        self.lbl_stats.pack(anchor="w", pady=(self.px(4), 0))

    # -------------------------------------------------- 选项卡
    def _build_tabs(self, parent) -> None:
        self.notebook = ttk.Notebook(parent)
        self.notebook.pack(fill="x", pady=(0, self.px(12)))

        manual = tk.Frame(self.notebook, bg=BG, highlightbackground=BORDER,
                          highlightthickness=1)
        smart = tk.Frame(self.notebook, bg=BG, highlightbackground=BORDER,
                         highlightthickness=1)
        self.notebook.add(manual, text="  手动连点  ")
        self.notebook.add(smart, text="  智能连点（颜色监测）  ")
        self._build_manual(manual)
        self._build_smart(smart)

    def _build_manual(self, parent) -> None:
        wrap = tk.Frame(parent, bg=BG)
        wrap.pack(fill="both", expand=True, padx=self.px(14), pady=self.px(14))
        wrap.columnconfigure(0, weight=1, uniform="col")
        wrap.columnconfigure(1, weight=1, uniform="col")

        box = ttk.Labelframe(wrap, text="点击设置")
        box.grid(row=0, column=0, sticky="nsew", padx=(0, self.px(7)))
        ttk.Label(box, text="鼠标按键").grid(row=0, column=0, sticky="w", pady=self.px(4))
        ttk.Combobox(box, textvariable=self.m_button, values=BUTTONS.labels,
                     state="readonly", width=12).grid(row=0, column=1, sticky="w",
                                                      padx=(self.px(8), 0))
        ttk.Label(box, text="点击方式").grid(row=0, column=2, sticky="e",
                                         padx=(self.px(14), 0))
        ttk.Combobox(box, textvariable=self.m_type, values=CLICK_TYPES.labels,
                     state="readonly", width=7).grid(row=0, column=3, sticky="w",
                                                     padx=(self.px(8), 0))

        ttk.Label(box, text="点击间隔").grid(row=1, column=0, sticky="w", pady=self.px(4))
        f = tk.Frame(box, bg=BG)
        f.grid(row=1, column=1, sticky="w", padx=(self.px(8), 0))
        ttk.Spinbox(f, from_=1, to=600000, textvariable=self.m_interval,
                    width=8, increment=10).pack(side="left")
        ttk.Label(f, text="毫秒", style="Sub.TLabel").pack(side="left", padx=(self.px(5), 0))
        ttk.Label(box, text="随机浮动").grid(row=1, column=2, sticky="e",
                                        padx=(self.px(14), 0))
        f2 = tk.Frame(box, bg=BG)
        f2.grid(row=1, column=3, sticky="w", padx=(self.px(8), 0))
        ttk.Spinbox(f2, from_=0, to=90, textvariable=self.m_jitter, width=4).pack(side="left")
        ttk.Label(f2, text="%", style="Sub.TLabel").pack(side="left", padx=(self.px(4), 0))

        ttk.Label(box, text="连点次数").grid(row=2, column=0, sticky="w", pady=self.px(4))
        f3 = tk.Frame(box, bg=BG)
        f3.grid(row=2, column=1, columnspan=3, sticky="w", padx=(self.px(8), 0))
        ttk.Radiobutton(f3, text="无限连点", variable=self.m_count_mode,
                        value="infinite").pack(side="left")
        ttk.Radiobutton(f3, text="指定", variable=self.m_count_mode,
                        value="fixed").pack(side="left", padx=(self.px(12), 0))
        ttk.Spinbox(f3, from_=1, to=9999999, textvariable=self.m_count,
                    width=8).pack(side="left", padx=(self.px(5), 0))
        ttk.Label(f3, text="次", style="Sub.TLabel").pack(side="left", padx=(self.px(4), 0))

        ttk.Label(box, text="按下时长").grid(row=3, column=0, sticky="w", pady=self.px(4))
        f4 = tk.Frame(box, bg=BG)
        f4.grid(row=3, column=1, sticky="w", padx=(self.px(8), 0))
        ttk.Spinbox(f4, from_=0, to=2000, textvariable=self.m_hold, width=8).pack(side="left")
        ttk.Label(f4, text="毫秒", style="Sub.TLabel").pack(side="left", padx=(self.px(5), 0))
        ttk.Label(box, text="启动延迟").grid(row=3, column=2, sticky="e",
                                        padx=(self.px(14), 0))
        f5 = tk.Frame(box, bg=BG)
        f5.grid(row=3, column=3, sticky="w", padx=(self.px(8), 0))
        ttk.Spinbox(f5, from_=0, to=600, textvariable=self.m_delay, width=4).pack(side="left")
        ttk.Label(f5, text="秒", style="Sub.TLabel").pack(side="left", padx=(self.px(4), 0))

        box2 = ttk.Labelframe(wrap, text="点击位置")
        box2.grid(row=0, column=1, sticky="nsew", padx=(self.px(7), 0))
        ttk.Radiobutton(box2, text="跟随鼠标当前位置（推荐）", variable=self.m_pos_mode,
                        value="cursor").grid(row=0, column=0, columnspan=4, sticky="w",
                                             pady=self.px(4))
        ttk.Radiobutton(box2, text="固定屏幕坐标", variable=self.m_pos_mode,
                        value="fixed").grid(row=1, column=0, columnspan=4, sticky="w",
                                            pady=self.px(2))
        f6 = tk.Frame(box2, bg=BG)
        f6.grid(row=2, column=0, columnspan=4, sticky="w", pady=self.px(4))
        ttk.Label(f6, text="X").pack(side="left")
        ttk.Spinbox(f6, from_=-20000, to=20000, textvariable=self.m_x,
                    width=7).pack(side="left", padx=(self.px(4), self.px(10)))
        ttk.Label(f6, text="Y").pack(side="left")
        ttk.Spinbox(f6, from_=-20000, to=20000, textvariable=self.m_y,
                    width=7).pack(side="left", padx=(self.px(4), self.px(10)))
        ttk.Button(f6, text="拾取当前坐标", style="Mini.TButton",
                   command=lambda: self._pick_point()).pack(side="left")
        self.lbl_pick_tip = ttk.Label(
            box2, text="提示：把鼠标移到目标位置后按 %s 可随时拾取坐标。"
                       % self.hotkeys["pick_point"].label,
            style="Sub.TLabel", wraplength=self.px(320))
        self.lbl_pick_tip.grid(row=3, column=0, columnspan=4, sticky="w",
                               pady=(self.px(6), 0))

    def _build_smart(self, parent) -> None:
        wrap = tk.Frame(parent, bg=BG)
        wrap.pack(fill="both", expand=True, padx=self.px(14), pady=self.px(14))
        wrap.columnconfigure(0, weight=1, uniform="col")
        wrap.columnconfigure(1, weight=1, uniform="col")

        # ---- 监测区域
        box = ttk.Labelframe(wrap, text="监测区域与颜色")
        box.grid(row=0, column=0, sticky="nsew", padx=(0, self.px(7)))
        line = tk.Frame(box, bg=BG)
        line.grid(row=0, column=0, columnspan=3, sticky="w", pady=self.px(2))
        SolidButton(line, self.theme, "框选屏幕区域", command=self._pick_region,
                    kind="primary").pack(side="left")
        ttk.Button(line, text="刷新当前色", style="Mini.TButton",
                   command=self._probe_region).pack(side="left", padx=(self.px(8), 0))

        self.lbl_region = ttk.Label(box, text="尚未选择区域", style="Sub.TLabel")
        self.lbl_region.grid(row=1, column=0, columnspan=3, sticky="w", pady=(self.px(6), 0))

        cur = tk.Frame(box, bg=BG)
        cur.grid(row=2, column=0, columnspan=3, sticky="w", pady=(self.px(6), 0))
        ttk.Label(cur, text="区域当前色", style="Sub.TLabel").pack(side="left")
        self.sw_region = ColorSwatch(cur, self.theme, "#FFFFFF", 26, 20)
        self.sw_region.pack(side="left", padx=(self.px(8), self.px(6)))
        self.lbl_region_color = ttk.Label(cur, text="--", style="Accent.TLabel")
        self.lbl_region_color.pack(side="left")

        tgt = tk.Frame(box, bg=BG)
        tgt.grid(row=3, column=0, columnspan=3, sticky="w", pady=(self.px(10), 0))
        ttk.Label(tgt, text="目标颜色").pack(side="left")
        self.sw_target = ColorSwatch(tgt, self.theme, "#FFFFFF", 26, 20)
        self.sw_target.pack(side="left", padx=(self.px(8), self.px(6)))
        entry = ttk.Entry(tgt, textvariable=self.s_color, width=10)
        entry.pack(side="left")
        self.s_color.trace_add("write", lambda *a: self._sync_target_swatch())
        ttk.Button(tgt, text="取区域当前色", style="Mini.TButton",
                   command=self._use_region_color).pack(side="left", padx=(self.px(8), 0))
        ttk.Button(tgt, text="吸取光标处", style="Mini.TButton",
                   command=self._pick_color).pack(side="left", padx=(self.px(6), 0))

        row4 = tk.Frame(box, bg=BG)
        row4.grid(row=4, column=0, columnspan=3, sticky="w", pady=(self.px(10), 0))
        ttk.Label(row4, text="颜色容差").pack(side="left")
        ttk.Spinbox(row4, from_=0, to=255, textvariable=self.s_tolerance,
                    width=5).pack(side="left", padx=(self.px(8), self.px(4)))
        ttk.Label(row4, text="/255", style="Sub.TLabel").pack(side="left")
        ttk.Label(row4, text="检测间隔").pack(side="left", padx=(self.px(16), 0))
        ttk.Spinbox(row4, from_=10, to=60000, textvariable=self.s_check,
                    width=7, increment=10).pack(side="left", padx=(self.px(8), self.px(4)))
        ttk.Label(row4, text="毫秒", style="Sub.TLabel").pack(side="left")

        row5 = tk.Frame(box, bg=BG)
        row5.grid(row=5, column=0, columnspan=3, sticky="w", pady=(self.px(8), 0))
        ttk.Label(row5, text="采样方式").pack(side="left")
        ttk.Combobox(row5, textvariable=self.s_sample, values=SAMPLES.labels,
                     state="readonly", width=14).pack(side="left", padx=(self.px(8), 0))
        ttk.Label(row5, text="占比阈值").pack(side="left", padx=(self.px(12), 0))
        ttk.Spinbox(row5, from_=1, to=100, textvariable=self.s_ratio,
                    width=4).pack(side="left", padx=(self.px(6), self.px(4)))
        ttk.Label(row5, text="%", style="Sub.TLabel").pack(side="left")

        # ---- 触发与动作
        box2 = ttk.Labelframe(wrap, text="触发条件与动作")
        box2.grid(row=0, column=1, sticky="nsew", padx=(self.px(7), 0))
        r0 = tk.Frame(box2, bg=BG)
        r0.grid(row=0, column=0, sticky="w", pady=self.px(2))
        ttk.Label(r0, text="触发方式").pack(side="left")
        ttk.Combobox(r0, textvariable=self.s_trigger, values=TRIGGERS.labels,
                     state="readonly", width=20).pack(side="left", padx=(self.px(8), 0))

        ttk.Radiobutton(box2, text="触发后连点若干次（推荐）", variable=self.s_action,
                        value="burst").grid(row=1, column=0, sticky="w", pady=(self.px(8), 0))
        r1 = tk.Frame(box2, bg=BG)
        r1.grid(row=2, column=0, sticky="w", pady=self.px(2), padx=(self.px(20), 0))
        ttk.Label(r1, text="点击").pack(side="left")
        ttk.Spinbox(r1, from_=1, to=9999, textvariable=self.s_burst,
                    width=5).pack(side="left", padx=self.px(4))
        ttk.Label(r1, text="次 · 冷却").pack(side="left")
        ttk.Spinbox(r1, from_=0, to=600000, textvariable=self.s_cooldown, width=6,
                    increment=50).pack(side="left", padx=self.px(4))
        ttk.Label(r1, text="毫秒", style="Sub.TLabel").pack(side="left")
        r2 = tk.Frame(box2, bg=BG)
        r2.grid(row=3, column=0, sticky="w", pady=self.px(2), padx=(self.px(20), 0))
        ttk.Label(r2, text="最多触发").pack(side="left")
        ttk.Spinbox(r2, from_=0, to=999999, textvariable=self.s_max_trig,
                    width=6).pack(side="left", padx=self.px(4))
        ttk.Label(r2, text="次（0 表示不限）", style="Sub.TLabel").pack(side="left")

        ttk.Radiobutton(box2, text="条件满足期间持续连点", variable=self.s_action,
                        value="hold").grid(row=4, column=0, sticky="w", pady=(self.px(8), 0))
        ttk.Label(box2, text="连点速度沿用「手动连点」页的按键与间隔设置。",
                  style="Sub.TLabel").grid(row=5, column=0, sticky="w",
                                           padx=(self.px(20), 0))

        r3 = tk.Frame(box2, bg=BG)
        r3.grid(row=6, column=0, sticky="w", pady=(self.px(10), 0))
        ttk.Label(r3, text="点击位置").pack(side="left")
        ttk.Combobox(r3, textvariable=self.s_pos, values=POSITIONS.labels,
                     state="readonly", width=14).pack(side="left", padx=(self.px(8), 0))
        r4 = tk.Frame(box2, bg=BG)
        r4.grid(row=7, column=0, sticky="w", pady=(self.px(6), 0))
        ttk.Label(r4, text="X").pack(side="left")
        ttk.Spinbox(r4, from_=-20000, to=20000, textvariable=self.s_x,
                    width=7).pack(side="left", padx=(self.px(4), self.px(10)))
        ttk.Label(r4, text="Y").pack(side="left")
        ttk.Spinbox(r4, from_=-20000, to=20000, textvariable=self.s_y,
                    width=7).pack(side="left", padx=(self.px(4), self.px(10)))
        ttk.Button(r4, text="拾取当前坐标", style="Mini.TButton",
                   command=self._pick_point).pack(side="left")

    # -------------------------------------------------- 快捷键
    def _build_hotkeys(self, parent) -> None:
        card = Card(parent, self.theme, "全局快捷键",
                    "点击后按下新的按键即可修改，Esc 取消", pad=12)
        card.pack(fill="x", pady=(0, self.px(12)))
        row = tk.Frame(card.body, bg=BG)
        row.pack(fill="x")
        labels = [("toggle", "启动 / 停止连点"), ("stop", "紧急停止"),
                  ("pick_point", "拾取鼠标坐标"), ("pick_color", "吸取光标颜色")]
        self.pickers = {}
        for i, (name, text) in enumerate(labels):
            picker = HotkeyPicker(row, self.theme, text, self.hotkeys[name],
                                  on_change=lambda hk, n=name: self._set_hotkey(n, hk),
                                  on_capture=self._on_capture)
            picker.pack(side="left", padx=(0, self.px(24)))
            self.pickers[name] = picker

    # -------------------------------------------------- 控制条
    def _build_controls(self, parent) -> None:
        bar = tk.Frame(parent, bg=PANEL, highlightbackground=BORDER, highlightthickness=1)
        bar.pack(fill="x", pady=(0, self.px(12)))
        inner = tk.Frame(bar, bg=PANEL)
        inner.pack(fill="x", padx=self.px(12), pady=self.px(10))

        self.btn_run = SolidButton(inner, self.theme,
                                   "开始连点（%s）" % self.hotkeys["toggle"].label,
                                   command=self._toggle, kind="primary", big=True)
        self.btn_run.pack(side="left")
        tk.Label(inner, text="运行中可随时按快捷键停止；固定坐标模式会移动鼠标指针。",
                 bg=PANEL, fg=SUB, font=self.theme.font(9)).pack(side="left",
                                                                 padx=(self.px(14), 0))
        ttk.Button(inner, text="清空日志", style="Mini.TButton",
                   command=self._clear_log).pack(side="right")

    # -------------------------------------------------- 日志
    def _build_log(self, parent) -> None:
        card = Card(parent, self.theme, "运行日志", pad=12)
        card.pack(fill="both", expand=True)
        holder = tk.Frame(card.body, bg=BG)
        holder.pack(fill="both", expand=True)
        self.log = tk.Text(holder, height=7, bg=BG, fg=TEXT, relief="flat",
                           font=self.theme.font(9, mono=True), wrap="word",
                           highlightbackground=BORDER, highlightthickness=1,
                           padx=self.px(8), pady=self.px(6))
        self.log.pack(side="left", fill="both", expand=True)
        bar = ttk.Scrollbar(holder, orient="vertical", command=self.log.yview)
        bar.pack(side="right", fill="y")
        self.log.configure(yscrollcommand=bar.set, state="disabled")
        self.log.tag_configure("time", foreground=SUB)
        self.log.tag_configure("info", foreground=TEXT)
        self.log.tag_configure("trigger", foreground=ACCENT)
        self.log.tag_configure("error", foreground=DANGER)
        self.log.tag_configure("ok", foreground=SUCCESS)
        self.log.tag_configure("warn", foreground=WARN)

    # ================================================== 交互
    def _toggle(self) -> None:
        if self.engine.is_running:
            self.engine.stop("已停止连点。")
            return
        if self.notebook.index("current") == 0:
            cfg = self._manual_config()
            self.engine.start_manual(cfg)
        else:
            if self.region is None:
                self._log("请先点击「框选屏幕区域」选择需要监测的区域。", "warn")
                return
            self.engine.start_smart(self._manual_config(), self._smart_config())

    def _manual_config(self) -> ManualConfig:
        return ManualConfig(
            button=BUTTONS.value(self.m_button.get(), "left"),
            double=CLICK_TYPES.value(self.m_type.get(), "single") == "double",
            interval_ms=to_float(self.m_interval.get(), 100, 1, 600000),
            jitter_pct=to_float(self.m_jitter.get(), 0, 0, 90),
            hold_ms=to_float(self.m_hold.get(), 10, 0, 2000),
            infinite=self.m_count_mode.get() == "infinite",
            count=to_int(self.m_count.get(), 100, 1, 9999999),
            position_mode=self.m_pos_mode.get(),
            fixed_x=to_int(self.m_x.get(), 0, -20000, 20000),
            fixed_y=to_int(self.m_y.get(), 0, -20000, 20000),
            start_delay_s=to_float(self.m_delay.get(), 0, 0, 600),
        )

    def _smart_config(self) -> SmartConfig:
        rgb = hex_to_rgb(self.s_color.get()) or (255, 255, 255)
        return SmartConfig(
            region=self.region or (0, 0, 10, 10),
            trigger=TRIGGERS.value(self.s_trigger.get(), "match"),
            sample=SAMPLES.value(self.s_sample.get(), "average"),
            target_rgb=rgb,
            tolerance=to_int(self.s_tolerance.get(), 20, 0, 255),
            ratio_pct=to_float(self.s_ratio.get(), 30, 1, 100),
            check_interval_ms=to_float(self.s_check.get(), 100, 10, 60000),
            action=self.s_action.get(),
            burst_count=to_int(self.s_burst.get(), 1, 1, 9999),
            cooldown_ms=to_float(self.s_cooldown.get(), 300, 0, 600000),
            max_triggers=to_int(self.s_max_trig.get(), 0, 0, 999999),
            click_position=POSITIONS.value(self.s_pos.get(), "region_center"),
            fixed_x=to_int(self.s_x.get(), 0, -20000, 20000),
            fixed_y=to_int(self.s_y.get(), 0, -20000, 20000),
        )

    # -------------------------------------------------- 区域 / 取色
    def _pick_region(self) -> None:
        self.root.withdraw()
        self.root.after(160, self._show_picker)

    def _show_picker(self) -> None:
        RegionPicker(self.root, self.theme, on_done=self._on_region,
                     on_cancel=self._on_region_cancel)

    def _on_region(self, region) -> None:
        self.region = normalize_region(region)
        self.root.deiconify()
        self._update_region_label()
        self._probe_region(log=False)
        x1, y1, x2, y2 = self.region
        self._log("已选择监测区域 (%d, %d) - (%d, %d)，尺寸 %d × %d。"
                  % (x1, y1, x2, y2, x2 - x1, y2 - y1), "ok")

    def _on_region_cancel(self) -> None:
        self.root.deiconify()

    def _update_region_label(self) -> None:
        if not self.region:
            self.lbl_region.configure(text="尚未选择区域")
            return
        x1, y1, x2, y2 = self.region
        self.lbl_region.configure(
            text="区域：(%d, %d) - (%d, %d)    尺寸：%d × %d"
                 % (x1, y1, x2, y2, x2 - x1, y2 - y1))

    def _probe_region(self, log: bool = True) -> str | None:
        if not self.region:
            if log:
                self._log("请先框选监测区域。", "warn")
            return None
        sample = sample_region(self.grabber, self.region)
        if sample is None:
            if log:
                self._log("区域取色失败，请重试。", "error")
            return None
        hex_color = rgb_to_hex(sample.avg)
        self.sw_region.set_color(hex_color)
        self.lbl_region_color.configure(text=hex_color)
        return hex_color

    def _use_region_color(self) -> None:
        hex_color = self._probe_region()
        if hex_color:
            self.s_color.set(hex_color)
            self._log("已将区域当前色 %s 设为目标颜色。" % hex_color, "ok")

    def _sync_target_swatch(self) -> None:
        rgb = hex_to_rgb(self.s_color.get())
        self.sw_target.set_color(rgb_to_hex(rgb) if rgb else BG)

    def _pick_point(self) -> None:
        x, y = get_cursor_pos()
        if self.notebook.index("current") == 0:
            self.m_x.set(str(x))
            self.m_y.set(str(y))
            self.m_pos_mode.set("fixed")
        else:
            self.s_x.set(str(x))
            self.s_y.set(str(y))
            self.s_pos.set(POSITIONS.label("fixed"))
        self._log("已拾取坐标 (%d, %d)。" % (x, y), "ok")

    def _pick_color(self) -> None:
        x, y = get_cursor_pos()
        hex_color = rgb_to_hex(get_pixel(x, y))
        self.s_color.set(hex_color)
        self._log("已吸取 (%d, %d) 处颜色 %s 作为目标颜色。" % (x, y, hex_color), "ok")

    # -------------------------------------------------- 热键
    def _set_hotkey(self, name: str, hotkey: Hotkey) -> None:
        for other, hk in self.hotkeys.items():
            if other != name and hk.label == hotkey.label:
                self._log("%s 已被其他功能占用，请换一个按键。" % hotkey.label, "warn")
                self.pickers[name].set_hotkey(self.hotkeys[name])
                return
        self.hotkeys[name] = hotkey
        self._rebind_hotkeys()
        self._refresh_hotkey_text()
        self._log("快捷键已更新：%s → %s" % (name, hotkey.label), "ok")

    def _rebind_hotkeys(self) -> None:
        actions = {
            "toggle": lambda: self.events.put({"kind": "hotkey", "name": "toggle"}),
            "stop": lambda: self.events.put({"kind": "hotkey", "name": "stop"}),
            "pick_point": lambda: self.events.put({"kind": "hotkey", "name": "pick_point"}),
            "pick_color": lambda: self.events.put({"kind": "hotkey", "name": "pick_color"}),
        }
        for name, hotkey in self.hotkeys.items():
            self.listener.bind(name, hotkey, actions[name])

    def _refresh_hotkey_text(self) -> None:
        if not self.engine.is_running:
            self.btn_run.configure(text="开始连点（%s）" % self.hotkeys["toggle"].label)
        try:
            self.lbl_pick_tip.configure(
                text="提示：把鼠标移到目标位置后按 %s 可随时拾取坐标。"
                     % self.hotkeys["pick_point"].label)
        except Exception:
            pass

    def _on_capture(self, capturing: bool) -> None:
        self._capturing_hotkey = capturing
        self.listener.set_enabled(not capturing)

    # -------------------------------------------------- 事件循环
    def _tick(self) -> None:
        x, y = get_cursor_pos()
        self.lbl_pos.configure(text="X: %-6d Y: %-6d" % (x, y))
        hex_color = rgb_to_hex(get_pixel(x, y))
        self.sw_cursor.set_color(hex_color)
        self.lbl_color.configure(text=hex_color)
        self.lbl_stats.configure(text="点击 %d 次 · 触发 %d 次"
                                      % (self.engine.clicks, self.engine.triggers))
        now = time.time()
        if (self.region and not self.engine.is_running
                and self.notebook.index("current") == 1
                and now - self._last_region_probe > 0.5):
            self._last_region_probe = now
            self._probe_region(log=False)
        self.root.after(60, self._tick)

    def _drain(self) -> None:
        try:
            while True:
                event = self.events.get_nowait()
                self._handle(event)
        except queue.Empty:
            pass
        self.root.after(50, self._drain)

    def _handle(self, event: dict) -> None:
        kind = event.get("kind")
        if kind == "hotkey":
            name = event.get("name")
            if name == "toggle":
                self._toggle()
            elif name == "stop":
                if self.engine.is_running:
                    self.engine.stop("紧急停止。")
                    self._log("已通过 %s 紧急停止。" % self.hotkeys["stop"].label, "warn")
            elif name == "pick_point":
                self._pick_point()
            elif name == "pick_color":
                self._pick_color()
            return
        if kind == "state":
            self._set_running(bool(event.get("running")))
            if not event.get("running"):
                self._log("运行结束：共点击 %d 次，触发 %d 次。"
                          % (self.engine.clicks, self.engine.triggers), "info")
            return
        tag = {"trigger": "trigger", "error": "error"}.get(kind, "info")
        text = event.get("text")
        if text:
            self._log(text, tag)

    def _set_running(self, running: bool) -> None:
        if running:
            self.badge.configure(text="  ● 运行中  ", bg="#E8FFEA", fg=SUCCESS)
            self.btn_run.set_kind("danger", "停止连点（%s）" % self.hotkeys["toggle"].label)
        else:
            self.badge.configure(text="  ● 就绪  ", bg=CHIP, fg=SUB)
            self.btn_run.set_kind("primary", "开始连点（%s）" % self.hotkeys["toggle"].label)

    # -------------------------------------------------- 日志
    def _log(self, text: str, tag: str = "info") -> None:
        self.log.configure(state="normal")
        self.log.insert("end", time.strftime("[%H:%M:%S] "), "time")
        self.log.insert("end", text + "\n", tag)
        if int(self.log.index("end-1c").split(".")[0]) > 400:
            self.log.delete("1.0", "100.0")
        self.log.see("end")
        self.log.configure(state="disabled")

    def _clear_log(self) -> None:
        self.log.configure(state="normal")
        self.log.delete("1.0", "end")
        self.log.configure(state="disabled")

    # -------------------------------------------------- 配置
    def _config_dict(self) -> dict:
        return {
            "manual": {
                "button": self.m_button.get(), "type": self.m_type.get(),
                "interval": self.m_interval.get(), "jitter": self.m_jitter.get(),
                "hold": self.m_hold.get(), "count_mode": self.m_count_mode.get(),
                "count": self.m_count.get(), "pos_mode": self.m_pos_mode.get(),
                "x": self.m_x.get(), "y": self.m_y.get(), "delay": self.m_delay.get(),
            },
            "smart": {
                "trigger": self.s_trigger.get(), "sample": self.s_sample.get(),
                "color": self.s_color.get(), "tolerance": self.s_tolerance.get(),
                "ratio": self.s_ratio.get(), "check": self.s_check.get(),
                "action": self.s_action.get(), "burst": self.s_burst.get(),
                "cooldown": self.s_cooldown.get(), "max_trig": self.s_max_trig.get(),
                "pos": self.s_pos.get(), "x": self.s_x.get(), "y": self.s_y.get(),
                "region": list(self.region) if self.region else None,
            },
            "hotkeys": {k: v.label for k, v in self.hotkeys.items()},
        }

    def _load_config(self) -> None:
        self._sync_target_swatch()
        if not os.path.exists(CONFIG_PATH):
            return
        try:
            with open(CONFIG_PATH, "r", encoding="utf-8") as fp:
                data = json.load(fp)
        except Exception:
            return
        manual = data.get("manual", {})
        pairs = [(self.m_button, "button"), (self.m_type, "type"),
                 (self.m_interval, "interval"), (self.m_jitter, "jitter"),
                 (self.m_hold, "hold"), (self.m_count_mode, "count_mode"),
                 (self.m_count, "count"), (self.m_pos_mode, "pos_mode"),
                 (self.m_x, "x"), (self.m_y, "y"), (self.m_delay, "delay")]
        for var, key in pairs:
            if key in manual:
                var.set(str(manual[key]))
        smart = data.get("smart", {})
        pairs = [(self.s_trigger, "trigger"), (self.s_sample, "sample"),
                 (self.s_color, "color"), (self.s_tolerance, "tolerance"),
                 (self.s_ratio, "ratio"), (self.s_check, "check"),
                 (self.s_action, "action"), (self.s_burst, "burst"),
                 (self.s_cooldown, "cooldown"), (self.s_max_trig, "max_trig"),
                 (self.s_pos, "pos"), (self.s_x, "x"), (self.s_y, "y")]
        for var, key in pairs:
            if key in smart:
                var.set(str(smart[key]))
        region = smart.get("region")
        if isinstance(region, (list, tuple)) and len(region) == 4:
            self.region = normalize_region(region)
            self._update_region_label()
        for name, label in (data.get("hotkeys") or {}).items():
            hotkey = Hotkey.parse(label)
            if hotkey and name in self.hotkeys:
                self.hotkeys[name] = hotkey
                if name in getattr(self, "pickers", {}):
                    self.pickers[name].set_hotkey(hotkey)
        self._sync_target_swatch()
        self._refresh_hotkey_text()

    def _save_config(self) -> None:
        try:
            with open(CONFIG_PATH, "w", encoding="utf-8") as fp:
                json.dump(self._config_dict(), fp, ensure_ascii=False, indent=2)
        except Exception:
            pass

    def _on_close(self) -> None:
        self.engine.stop()
        try:
            self.listener.stop()
        except Exception:
            pass
        self._save_config()
        try:
            self.grabber.close()
        except Exception:
            pass
        self.root.destroy()


def center_window(root: tk.Tk, width: int, height: int) -> None:
    root.update_idletasks()
    sw = root.winfo_screenwidth()
    sh = root.winfo_screenheight()
    width = min(width, max(600, sw - 40))
    height = min(height, max(560, sh - 90))
    x = max(0, (sw - width) // 2)
    y = max(0, (sh - height) // 3)
    root.geometry("%dx%d+%d+%d" % (width, height, x, y))
