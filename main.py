# -*- coding: utf-8 -*-
"""轻点 · 鼠标连点器 —— 程序入口。

依赖：仅 Python 标准库（tkinter + ctypes），Windows 平台。
运行：python main.py   或双击 run.bat
"""
from __future__ import annotations

import os
import sys
import traceback
import tkinter as tk
from tkinter import messagebox

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))

from core.winapi import enable_dpi_awareness  # noqa: E402
from ui.app import ClickerApp, center_window  # noqa: E402

def _app_dir() -> str:
    """程序目录：打包成 exe 后取 exe 所在目录，否则取源码包根目录。"""
    if getattr(sys, "frozen", False):
        return os.path.dirname(sys.executable)
    return os.path.dirname(os.path.abspath(__file__))


_LAUNCH_LOG = os.path.join(_app_dir(), "launch.log")


def _log(msg: str) -> None:
    """启动日志：pythonw 下没有控制台，任何异常都必须落盘。"""
    try:
        with open(_LAUNCH_LOG, "a", encoding="utf-8") as f:
            f.write(msg + "\n")
    except Exception:
        pass


def _hook(exc_type, exc_value, exc_tb) -> None:
    _log("UNHANDLED EXCEPTION:\n" + "".join(traceback.format_exception(exc_type, exc_value, exc_tb)))


def main() -> int:
    if sys.platform != "win32":
        print("本程序依赖 Windows API，只能在 Windows 上运行。")
        return 1

    enable_dpi_awareness()
    root = tk.Tk()
    try:
        app = ClickerApp(root)
    except Exception as exc:
        messagebox.showerror("启动失败", "初始化界面时出错：\n%s" % exc)
        raise
    center_window(root, app.px(950), app.px(770))

    if os.environ.get("AUTOCLICKER_SELFTEST") == "1":
        def _finish():
            print("SELFTEST: 界面构建成功，无异常。")
            app._on_close()
        root.after(1200, _finish)

    root.mainloop()
    return 0


if __name__ == "__main__":
    sys.excepthook = _hook
    _log("=== launch: python=%s, cwd=%s ===" % (sys.executable, os.getcwd()))
    try:
        sys.exit(main())
    except SystemExit:
        raise
    except Exception:
        _log("MAIN FAILED:\n" + traceback.format_exc())
        raise
