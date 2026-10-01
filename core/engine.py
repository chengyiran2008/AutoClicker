# -*- coding: utf-8 -*-
"""连点引擎：手动连点 + 基于屏幕颜色的智能触发连点。"""
from __future__ import annotations

import random
import threading
import time
from dataclasses import dataclass, field

from . import winapi

MAX_SAMPLE_POINTS = 2500


# ---------------------------------------------------------------- 配置


@dataclass
class ManualConfig:
    button: str = "left"          # left / right / middle
    double: bool = False          # 双击
    interval_ms: float = 100.0    # 两次点击的间隔
    jitter_pct: float = 0.0       # 间隔随机浮动 ±%
    hold_ms: float = 10.0         # 按下时长
    infinite: bool = True         # 无限连点
    count: int = 100              # 指定次数
    position_mode: str = "cursor"  # cursor / fixed
    fixed_x: int = 0
    fixed_y: int = 0
    start_delay_s: float = 0.0    # 启动前延迟


@dataclass
class SmartConfig:
    region: tuple = (0, 0, 100, 100)   # x1, y1, x2, y2（屏幕坐标）
    trigger: str = "match"             # match / mismatch / change
    sample: str = "average"            # average(区域平均色) / ratio(像素占比)
    target_rgb: tuple = (255, 255, 255)
    tolerance: int = 20                # 0-255，单通道最大允许偏差
    ratio_pct: float = 30.0            # ratio 模式的占比阈值
    check_interval_ms: float = 100.0   # 检测间隔
    action: str = "burst"              # burst(触发点击N次) / hold(满足期间持续连点)
    burst_count: int = 1
    cooldown_ms: float = 300.0         # 触发后冷却
    max_triggers: int = 0              # 0 = 不限
    click_position: str = "region_center"  # region_center / cursor / fixed
    fixed_x: int = 0
    fixed_y: int = 0
    reset_baseline: bool = True        # 变化检测：触发后重置基准


@dataclass
class Sample:
    avg: tuple
    pixels: list = field(default_factory=list)


# ---------------------------------------------------------------- 采样与比较


def color_diff(c1, c2) -> int:
    return max(abs(int(a) - int(b)) for a, b in zip(c1, c2))


def sample_region(grabber: winapi.ScreenGrabber, region) -> Sample | None:
    x1, y1, x2, y2 = normalize_region(region)
    raw, w, h = grabber.grab(x1, y1, x2 - x1, y2 - y1)
    if raw is None:
        return None
    total = w * h
    step = 1
    if total > MAX_SAMPLE_POINTS:
        step = int((total / MAX_SAMPLE_POINTS) ** 0.5) + 1
    pixels = []
    sr = sg = sb = 0
    for yy in range(0, h, step):
        row = yy * w * 4
        for xx in range(0, w, step):
            i = row + xx * 4
            b = raw[i]
            g = raw[i + 1]
            r = raw[i + 2]
            pixels.append((r, g, b))
            sr += r
            sg += g
            sb += b
    n = len(pixels) or 1
    return Sample((sr // n, sg // n, sb // n), pixels)


def normalize_region(region) -> tuple[int, int, int, int]:
    x1, y1, x2, y2 = (int(v) for v in region)
    left, right = min(x1, x2), max(x1, x2)
    top, bottom = min(y1, y2), max(y1, y2)
    if right - left < 1:
        right = left + 1
    if bottom - top < 1:
        bottom = top + 1
    return left, top, right, bottom


def match_ratio(pixels, target, tol: int) -> float:
    if not pixels:
        return 0.0
    tr, tg, tb = target
    hit = 0
    for r, g, b in pixels:
        if abs(r - tr) <= tol and abs(g - tg) <= tol and abs(b - tb) <= tol:
            hit += 1
    return hit / len(pixels)


def diff_ratio(pixels, base_pixels, tol: int) -> float:
    if not pixels or not base_pixels or len(pixels) != len(base_pixels):
        return 0.0
    changed = 0
    for (r, g, b), (br, bg, bb) in zip(pixels, base_pixels):
        if abs(r - br) > tol or abs(g - bg) > tol or abs(b - bb) > tol:
            changed += 1
    return changed / len(pixels)


# ---------------------------------------------------------------- 引擎


class ClickerEngine:
    """所有点击动作都在独立线程中执行，界面线程只负责收事件。"""

    def __init__(self, on_event=None) -> None:
        self._on_event = on_event
        self._thread: threading.Thread | None = None
        self._stop = threading.Event()
        self.mode: str | None = None
        self.clicks = 0
        self.triggers = 0

    # ---------------- 状态
    @property
    def is_running(self) -> bool:
        return self._thread is not None and self._thread.is_alive()

    def _emit(self, kind: str, text: str = "", **extra) -> None:
        if self._on_event:
            payload = {"kind": kind, "text": text}
            payload.update(extra)
            try:
                self._on_event(payload)
            except Exception:
                pass

    # ---------------- 启停
    def start_manual(self, cfg: ManualConfig) -> bool:
        return self._start("manual", self._manual_loop, (cfg,))

    def start_smart(self, manual_cfg: ManualConfig, smart_cfg: SmartConfig) -> bool:
        return self._start("smart", self._smart_loop, (manual_cfg, smart_cfg))

    def _start(self, mode: str, target, args) -> bool:
        if self.is_running:
            return False
        self._stop.clear()
        self.clicks = 0
        self.triggers = 0
        self.mode = mode
        self._thread = threading.Thread(target=self._guard, args=(target, args),
                                        daemon=True, name="clicker-%s" % mode)
        self._thread.start()
        self._emit("state", "运行中", running=True, mode=mode)
        return True

    def _guard(self, target, args) -> None:
        winapi.begin_timer_period(1)
        try:
            target(*args)
        except Exception as exc:  # pragma: no cover
            self._emit("error", "运行异常：%s" % exc)
        finally:
            winapi.end_timer_period(1)
            self.mode = None
            self._emit("state", "已停止", running=False,
                       clicks=self.clicks, triggers=self.triggers)

    def stop(self, reason: str = "") -> None:
        if self.is_running:
            self._stop.set()
            if reason:
                self._emit("log", reason)

    # ---------------- 计时与点击
    def _wait(self, seconds: float) -> bool:
        """精确等待；返回 False 表示被中断。"""
        if seconds <= 0:
            return not self._stop.is_set()
        end = time.perf_counter() + seconds
        while True:
            if self._stop.is_set():
                return False
            remain = end - time.perf_counter()
            if remain <= 0:
                return True
            if remain > 0.03:
                self._stop.wait(min(remain - 0.02, 0.05))
            elif remain > 0.002:
                time.sleep(0.001)
            else:
                time.sleep(0)  # 自旋补偿，保证毫秒级精度

    def _interval_seconds(self, cfg: ManualConfig) -> float:
        base = max(0.0, float(cfg.interval_ms)) / 1000.0
        if cfg.jitter_pct > 0:
            span = base * float(cfg.jitter_pct) / 100.0
            base = max(0.0, base + random.uniform(-span, span))
        return base

    def _click_once(self, cfg: ManualConfig, pos=None) -> None:
        if pos is not None:
            winapi.set_cursor_pos(pos[0], pos[1])
            time.sleep(0.002)
        hold = max(0.0, float(cfg.hold_ms)) / 1000.0
        winapi.mouse_down(cfg.button)
        if hold:
            time.sleep(hold)
        winapi.mouse_up(cfg.button)
        if cfg.double:
            time.sleep(0.03)
            winapi.mouse_down(cfg.button)
            if hold:
                time.sleep(hold)
            winapi.mouse_up(cfg.button)
        self.clicks += 1

    # ---------------- 手动连点
    def _manual_loop(self, cfg: ManualConfig) -> None:
        if cfg.start_delay_s > 0:
            self._emit("log", "%.1f 秒后开始连点…" % cfg.start_delay_s)
            if not self._wait(cfg.start_delay_s):
                return
        target = "跟随鼠标" if cfg.position_mode == "cursor" else "(%d, %d)" % (cfg.fixed_x, cfg.fixed_y)
        self._emit("log", "手动连点启动：%s 键 · 间隔 %.0fms · %s · %s"
                   % (_button_cn(cfg.button), cfg.interval_ms,
                      "无限次" if cfg.infinite else "%d 次" % cfg.count, target))
        pos = None if cfg.position_mode == "cursor" else (cfg.fixed_x, cfg.fixed_y)
        done = 0
        while not self._stop.is_set():
            self._click_once(cfg, pos)
            done += 1
            if not cfg.infinite and done >= max(1, int(cfg.count)):
                self._emit("log", "已完成 %d 次点击，自动停止。" % done)
                return
            if not self._wait(self._interval_seconds(cfg)):
                return

    # ---------------- 智能连点
    def _smart_loop(self, mcfg: ManualConfig, scfg: SmartConfig) -> None:
        grabber = winapi.ScreenGrabber()
        region = normalize_region(scfg.region)
        try:
            self._emit("log", "智能监测启动：区域 (%d,%d)-(%d,%d) · %s · %s · 容差 %d"
                       % (region[0], region[1], region[2], region[3],
                          _trigger_cn(scfg.trigger), _sample_cn(scfg.sample), scfg.tolerance))
            baseline: Sample | None = None
            check_wait = max(0.005, float(scfg.check_interval_ms) / 1000.0)
            click_pos = self._smart_click_pos(scfg, region)
            fail_count = 0
            while not self._stop.is_set():
                current = sample_region(grabber, region)
                if current is None:
                    fail_count += 1
                    if fail_count == 1:
                        self._emit("log", "区域取色失败，正在重试…")
                    if fail_count > 20:
                        self._emit("error", "多次取色失败，已停止监测。")
                        return
                    if not self._wait(check_wait):
                        return
                    continue
                fail_count = 0
                if baseline is None:
                    baseline = current
                    if scfg.trigger == "change":
                        self._emit("log", "已建立基准色 %s，等待变化…"
                                   % winapi.rgb_to_hex(baseline.avg))
                hit = self._evaluate(current, baseline, scfg)
                if not hit:
                    if not self._wait(check_wait):
                        return
                    continue

                self.triggers += 1
                self._emit("trigger", "条件满足（当前 %s）→ 触发第 %d 次"
                           % (winapi.rgb_to_hex(current.avg), self.triggers),
                           color=winapi.rgb_to_hex(current.avg), triggers=self.triggers)
                if scfg.action == "hold":
                    self._click_once(mcfg, click_pos)
                    if not self._wait(self._interval_seconds(mcfg)):
                        return
                else:
                    burst = max(1, int(scfg.burst_count))
                    for i in range(burst):
                        self._click_once(mcfg, click_pos)
                        if i != burst - 1 and not self._wait(self._interval_seconds(mcfg)):
                            return
                    if scfg.trigger == "change" and scfg.reset_baseline:
                        if not self._wait(0.05):
                            return
                        again = sample_region(grabber, region)
                        if again is not None:
                            baseline = again
                    if scfg.max_triggers and self.triggers >= scfg.max_triggers:
                        self._emit("log", "已达到最大触发次数 %d，自动停止。" % scfg.max_triggers)
                        return
                    if not self._wait(max(0.0, float(scfg.cooldown_ms) / 1000.0)):
                        return
        finally:
            grabber.close()

    @staticmethod
    def _smart_click_pos(scfg: SmartConfig, region):
        if scfg.click_position == "cursor":
            return None
        if scfg.click_position == "fixed":
            return (int(scfg.fixed_x), int(scfg.fixed_y))
        return ((region[0] + region[2]) // 2, (region[1] + region[3]) // 2)

    @staticmethod
    def _evaluate(current: Sample, baseline: Sample, scfg: SmartConfig) -> bool:
        tol = int(scfg.tolerance)
        threshold = max(0.0, float(scfg.ratio_pct)) / 100.0
        if scfg.trigger == "change":
            if scfg.sample == "average":
                return color_diff(current.avg, baseline.avg) > tol
            return diff_ratio(current.pixels, baseline.pixels, tol) >= threshold
        if scfg.sample == "average":
            matched = color_diff(current.avg, scfg.target_rgb) <= tol
        else:
            matched = match_ratio(current.pixels, scfg.target_rgb, tol) >= threshold
        return matched if scfg.trigger == "match" else not matched


# ---------------------------------------------------------------- 文案


def _button_cn(button: str) -> str:
    return {"left": "左", "right": "右", "middle": "中"}.get(button, "左")


def _trigger_cn(trigger: str) -> str:
    return {"match": "匹配目标色时触发", "mismatch": "偏离目标色时触发",
            "change": "颜色变化时触发"}.get(trigger, trigger)


def _sample_cn(sample: str) -> str:
    return {"average": "区域平均色", "ratio": "像素占比"}.get(sample, sample)
