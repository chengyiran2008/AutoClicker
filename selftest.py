# -*- coding: utf-8 -*-
"""逻辑自检：不产生任何真实鼠标点击（点击动作被替换为计数器）。

用法：python selftest.py
"""
from __future__ import annotations

import os
import sys
import time

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))

from core import engine, winapi  # noqa: E402
from core.hotkey import Hotkey  # noqa: E402

FAILED = []


def check(name: str, ok: bool, detail: str = "") -> None:
    print("%s %s%s" % ("[PASS]" if ok else "[FAIL]", name,
                       ("  -> " + detail) if detail else ""))
    if not ok:
        FAILED.append(name)


def fake_clicks():
    """屏蔽真实点击，返回计数器。"""
    counter = {"down": 0, "up": 0}
    winapi.mouse_down = lambda button="left": counter.__setitem__("down", counter["down"] + 1)
    winapi.mouse_up = lambda button="left": counter.__setitem__("up", counter["up"] + 1)
    winapi.set_cursor_pos = lambda x, y: None
    return counter


def main() -> int:
    winapi.enable_dpi_awareness()

    # ---- 基础 Win32
    x, y = winapi.get_cursor_pos()
    check("读取鼠标坐标", isinstance(x, int) and isinstance(y, int), "(%d, %d)" % (x, y))
    rgb = winapi.get_pixel(4, 4)
    check("屏幕单点取色", len(rgb) == 3, winapi.rgb_to_hex(rgb))
    grabber = winapi.ScreenGrabber()
    sample = engine.sample_region(grabber, (0, 0, 160, 120))
    check("区域抓取与平均色", sample is not None and len(sample.pixels) > 0,
          "%s / %d 个采样点" % (winapi.rgb_to_hex(sample.avg), len(sample.pixels)))
    grabber.close()

    # ---- 颜色与区域工具
    check("颜色差计算", engine.color_diff((10, 20, 30), (12, 60, 30)) == 40)
    check("像素匹配占比", abs(engine.match_ratio([(255, 255, 255)] * 8 + [(0, 0, 0)] * 2,
                                             (255, 255, 255), 10) - 0.8) < 1e-6)
    check("像素差异占比", abs(engine.diff_ratio([(0, 0, 0)] * 5 + [(90, 0, 0)] * 5,
                                            [(0, 0, 0)] * 10, 20) - 0.5) < 1e-6)
    check("区域归一化", engine.normalize_region((300, 200, 100, 50)) == (100, 50, 300, 200))
    check("HEX 解析", winapi.hex_to_rgb("#1AFF03") == (26, 255, 3)
          and winapi.hex_to_rgb("12,34,56") == (12, 34, 56)
          and winapi.hex_to_rgb("zzz") is None)
    check("热键解析", Hotkey.parse("Ctrl+Shift+F6").label == "Ctrl+Shift+F6"
          and Hotkey.parse("不存在") is None)

    # ---- 手动连点（固定次数）
    counter = fake_clicks()
    eng = engine.ClickerEngine()
    cfg = engine.ManualConfig(interval_ms=10, hold_ms=0, infinite=False, count=20)
    started = time.perf_counter()
    eng.start_manual(cfg)
    while eng.is_running and time.perf_counter() - started < 5:
        time.sleep(0.02)
    cost = time.perf_counter() - started
    check("手动连点指定次数", eng.clicks == 20 and counter["down"] == 20,
          "点击 %d 次 / 耗时 %.0fms" % (eng.clicks, cost * 1000))
    check("连点间隔精度", 0.17 < cost < 0.30, "预期约 190ms，实际 %.0fms" % (cost * 1000))

    # ---- 手动连点（无限 + 停止）
    eng2 = engine.ClickerEngine()
    eng2.start_manual(engine.ManualConfig(interval_ms=5, hold_ms=0, infinite=True))
    time.sleep(0.25)
    running_before = eng2.is_running
    eng2.stop()
    time.sleep(0.15)
    check("无限连点可被停止", running_before and not eng2.is_running,
          "停止前已点击 %d 次" % eng2.clicks)

    # ---- 智能连点（模拟颜色命中）
    engine.sample_region = lambda g, r: engine.Sample((255, 0, 0), [(255, 0, 0)] * 10)
    eng3 = engine.ClickerEngine()
    smart = engine.SmartConfig(region=(0, 0, 20, 20), trigger="match", sample="average",
                               target_rgb=(255, 0, 0), tolerance=10,
                               check_interval_ms=10, action="burst", burst_count=3,
                               cooldown_ms=10, max_triggers=2)
    eng3.start_smart(engine.ManualConfig(interval_ms=5, hold_ms=0), smart)
    deadline = time.perf_counter() + 5
    while eng3.is_running and time.perf_counter() < deadline:
        time.sleep(0.02)
    check("智能触发次数上限", eng3.triggers == 2, "触发 %d 次" % eng3.triggers)
    check("智能触发点击数量", eng3.clicks == 6, "点击 %d 次（2 次触发 × 3 连点）" % eng3.clicks)

    # ---- 智能连点（颜色不匹配则不触发）
    engine.sample_region = lambda g, r: engine.Sample((0, 0, 255), [(0, 0, 255)] * 10)
    eng4 = engine.ClickerEngine()
    eng4.start_smart(engine.ManualConfig(interval_ms=5, hold_ms=0),
                     engine.SmartConfig(region=(0, 0, 20, 20), trigger="match",
                                        target_rgb=(255, 0, 0), tolerance=10,
                                        check_interval_ms=10))
    time.sleep(0.3)
    no_trigger = eng4.triggers == 0 and eng4.clicks == 0
    eng4.stop()
    time.sleep(0.1)
    check("条件不满足时不点击", no_trigger)

    if FAILED:
        print("\n结果：%d 项失败 -> %s" % (len(FAILED), ", ".join(FAILED)))
        return 1
    print("\n结果：全部通过。")
    return 0


if __name__ == "__main__":
    sys.exit(main())
