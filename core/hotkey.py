# -*- coding: utf-8 -*-
"""全局快捷键：后台线程轮询 GetAsyncKeyState，边沿触发，无需管理员权限。"""
from __future__ import annotations

import threading
import time
from dataclasses import dataclass

from .winapi import VK_CONTROL, VK_MENU, VK_SHIFT, is_key_down

MODIFIER_VKS = (VK_SHIFT, VK_CONTROL, VK_MENU)

# 虚拟键码 -> 显示名
VK_NAMES: dict[int, str] = {
    0x08: "Backspace", 0x09: "Tab", 0x0D: "Enter", 0x13: "Pause",
    0x14: "CapsLock", 0x1B: "Esc", 0x20: "Space", 0x21: "PageUp",
    0x22: "PageDown", 0x23: "End", 0x24: "Home", 0x25: "Left",
    0x26: "Up", 0x27: "Right", 0x28: "Down", 0x2D: "Insert",
    0x2E: "Delete", 0x5B: "Win", 0x90: "NumLock", 0x91: "ScrollLock",
    0x10: "Shift", 0x11: "Ctrl", 0x12: "Alt",
    0xBA: ";", 0xBB: "=", 0xBC: ",", 0xBD: "-", 0xBE: ".",
    0xBF: "/", 0xC0: "`", 0xDB: "[", 0xDC: "\\", 0xDD: "]", 0xDE: "'",
}
for _i in range(0x30, 0x3A):  # 0-9
    VK_NAMES[_i] = chr(_i)
for _i in range(0x41, 0x5B):  # A-Z
    VK_NAMES[_i] = chr(_i)
for _i in range(1, 25):  # F1-F24
    VK_NAMES[0x70 + _i - 1] = "F%d" % _i
for _i in range(0, 10):  # 小键盘
    VK_NAMES[0x60 + _i] = "Num%d" % _i
VK_NAMES.update({0x6A: "Num*", 0x6B: "Num+", 0x6D: "Num-", 0x6E: "Num.", 0x6F: "Num/"})

NAME_TO_VK = {v.lower(): k for k, v in VK_NAMES.items()}


def vk_name(vk: int) -> str:
    return VK_NAMES.get(int(vk), "VK%02X" % int(vk))


@dataclass(frozen=True)
class Hotkey:
    vk: int
    ctrl: bool = False
    alt: bool = False
    shift: bool = False

    @property
    def label(self) -> str:
        parts = []
        if self.ctrl:
            parts.append("Ctrl")
        if self.alt:
            parts.append("Alt")
        if self.shift:
            parts.append("Shift")
        parts.append(vk_name(self.vk))
        return "+".join(parts)

    @staticmethod
    def parse(label: str):
        """从 'Ctrl+Shift+F6' 之类的文本解析，失败返回 None。"""
        if not label:
            return None
        ctrl = alt = shift = False
        vk = None
        for raw in str(label).split("+"):
            key = raw.strip().lower()
            if not key:
                continue
            if key == "ctrl":
                ctrl = True
            elif key == "alt":
                alt = True
            elif key == "shift":
                shift = True
            else:
                vk = NAME_TO_VK.get(key)
                if vk is None:
                    return None
        if vk is None:
            return None
        return Hotkey(vk, ctrl, alt, shift)


class HotkeyListener(threading.Thread):
    """轮询式全局热键监听。回调在监听线程中执行，请只做投递动作。"""

    def __init__(self, poll_interval: float = 0.02) -> None:
        super().__init__(daemon=True, name="hotkey-listener")
        self._poll = poll_interval
        self._lock = threading.Lock()
        self._bindings: dict[str, tuple[Hotkey, callable]] = {}
        self._pressed: dict[str, bool] = {}
        self._enabled = True
        self._stop = threading.Event()

    # ---------------- 绑定管理
    def bind(self, name: str, hotkey: Hotkey | None, callback) -> None:
        with self._lock:
            if hotkey is None:
                self._bindings.pop(name, None)
            else:
                self._bindings[name] = (hotkey, callback)
            self._pressed[name] = True  # 避免绑定瞬间误触发

    def unbind(self, name: str) -> None:
        with self._lock:
            self._bindings.pop(name, None)

    def set_enabled(self, enabled: bool) -> None:
        """捕获新热键时应临时关闭，避免自触发。"""
        self._enabled = bool(enabled)
        if enabled:
            with self._lock:
                for name in self._bindings:
                    self._pressed[name] = True

    def stop(self) -> None:
        self._stop.set()

    # ---------------- 主循环
    def run(self) -> None:  # pragma: no cover - 依赖真实按键
        while not self._stop.is_set():
            if self._enabled:
                with self._lock:
                    items = list(self._bindings.items())
                mods = {
                    "ctrl": is_key_down(VK_CONTROL),
                    "alt": is_key_down(VK_MENU),
                    "shift": is_key_down(VK_SHIFT),
                }
                for name, (hotkey, callback) in items:
                    down = self._is_active(hotkey, mods)
                    was = self._pressed.get(name, False)
                    self._pressed[name] = down
                    if down and not was:
                        try:
                            callback()
                        except Exception:
                            pass
            time.sleep(self._poll)

    @staticmethod
    def _is_active(hotkey: Hotkey, mods: dict) -> bool:
        if not is_key_down(hotkey.vk):
            return False
        if hotkey.vk in MODIFIER_VKS:
            return True
        # 严格匹配修饰键，避免 F6 与 Ctrl+F6 相互串扰
        return (mods["ctrl"] == hotkey.ctrl
                and mods["alt"] == hotkey.alt
                and mods["shift"] == hotkey.shift)
