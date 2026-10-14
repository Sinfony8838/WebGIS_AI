"""Teacher-session switch palette. No web/runtime imports or file persistence.

Window discovery and activation are deliberately local: no browser can supply
a HWND, executable, title or file path. Browser candidates must visibly display
WebGIS, and a remembered handle is checked again before every activation.
"""
from __future__ import annotations

import ctypes
from ctypes import wintypes
from dataclasses import dataclass
import ntpath
import queue
import subprocess
import threading
import time
from pathlib import Path

BROWSERS = frozenset({"chrome.exe", "msedge.exe", "firefox.exe", "brave.exe", "opera.exe"})
WEBGIS_TITLES = ("地理智能教学平台", "webgis")
WEBGIS_SITE = "https://webgisai.com"


def is_webgis_browser(executable: str, title: str) -> bool:
    return (ntpath.basename(executable).lower() in BROWSERS
            and any(marker in title.lower() for marker in WEBGIS_TITLES))


def clamp_position(x: int, y: int, width: int, height: int, area: tuple[int, int, int, int]):
    left, top, right, bottom = area
    return (max(left, min(x, max(left, right - width))),
            max(top, min(y, max(top, bottom - height))))


@dataclass(frozen=True)
class BrowserWindow:
    handle: int
    pid: int
    created: int
    executable: str
    title: str


def fit_preview(width: int, height: int, source_width: int, source_height: int):
    """Letterbox without stretching a slide or changing the source window."""
    if min(width, height, source_width, source_height) <= 0:
        raise ValueError("预览尺寸不可用。")
    ratio = min(width / source_width, height / source_height)
    w, h = max(1, round(source_width * ratio)), max(1, round(source_height * ratio))
    x, y = (width - w) // 2, (height - h) // 2
    return x, y, x + w, y + h


class WindowsDesktop:
    def __init__(self):
        self.user = ctypes.WinDLL("user32", use_last_error=True)
        # Apply only to this connector process, before creating Tk windows.
        # Physical desktop coordinates then agree with dragging/clamping, and
        # Windows does not bitmap-stretch the logo on high-DPI teacher displays.
        try:
            self.user.SetProcessDpiAwarenessContext.argtypes = [wintypes.HANDLE]
            self.user.SetProcessDpiAwarenessContext.restype = wintypes.BOOL
            self.user.SetProcessDpiAwarenessContext(wintypes.HANDLE(-4))
        except AttributeError:
            pass  # Older Windows keeps its existing process DPI behavior.
        self.kernel = ctypes.WinDLL("kernel32", use_last_error=True)
        self.controls = ctypes.WinDLL("comctl32", use_last_error=True)
        self.subclass_callback = ctypes.WINFUNCTYPE(
            ctypes.c_ssize_t, wintypes.HWND, wintypes.UINT, wintypes.WPARAM,
            wintypes.LPARAM, ctypes.c_size_t, ctypes.c_size_t)
        self.controls.SetWindowSubclass.argtypes = [wintypes.HWND, self.subclass_callback,
                                                    ctypes.c_size_t, ctypes.c_size_t]
        self.controls.SetWindowSubclass.restype = wintypes.BOOL
        self.controls.RemoveWindowSubclass.argtypes = [wintypes.HWND, self.subclass_callback, ctypes.c_size_t]
        self.controls.RemoveWindowSubclass.restype = wintypes.BOOL
        self.controls.DefSubclassProc.argtypes = [wintypes.HWND, wintypes.UINT, wintypes.WPARAM, wintypes.LPARAM]
        self.controls.DefSubclassProc.restype = ctypes.c_ssize_t
        self.callback = ctypes.WINFUNCTYPE(wintypes.BOOL, wintypes.HWND, wintypes.LPARAM)
        signatures = {
            "GetForegroundWindow": ([], wintypes.HWND),
            "GetAncestor": ([wintypes.HWND, wintypes.UINT], wintypes.HWND),
            "GetCursorPos": ([ctypes.POINTER(wintypes.POINT)], wintypes.BOOL),
            "GetWindowRect": ([wintypes.HWND, ctypes.POINTER(wintypes.RECT)], wintypes.BOOL),
            "IsWindowVisible": ([wintypes.HWND], wintypes.BOOL),
            "GetWindowTextW": ([wintypes.HWND, wintypes.LPWSTR, ctypes.c_int], ctypes.c_int),
            "GetClassNameW": ([wintypes.HWND, wintypes.LPWSTR, ctypes.c_int], ctypes.c_int),
            "GetWindowThreadProcessId": ([wintypes.HWND, ctypes.POINTER(wintypes.DWORD)], wintypes.DWORD),
            "EnumWindows": ([self.callback, wintypes.LPARAM], wintypes.BOOL),
            "SetForegroundWindow": ([wintypes.HWND], wintypes.BOOL),
            "IsIconic": ([wintypes.HWND], wintypes.BOOL),
            "ShowWindow": ([wintypes.HWND, ctypes.c_int], wintypes.BOOL),
            "ShowWindowAsync": ([wintypes.HWND, ctypes.c_int], wintypes.BOOL),
            "SetWindowPos": ([wintypes.HWND, wintypes.HWND, ctypes.c_int, ctypes.c_int,
                              ctypes.c_int, ctypes.c_int, wintypes.UINT], wintypes.BOOL),
            "GetWindowLongW": ([wintypes.HWND, ctypes.c_int], wintypes.LONG),
            "SetWindowLongW": ([wintypes.HWND, ctypes.c_int, wintypes.LONG], wintypes.LONG),
        }
        for name, (args, result) in signatures.items():
            method = getattr(self.user, name)
            method.argtypes, method.restype = args, result
        self.kernel.OpenProcess.argtypes = [wintypes.DWORD, wintypes.BOOL, wintypes.DWORD]
        self.kernel.OpenProcess.restype = wintypes.HANDLE
        self.kernel.QueryFullProcessImageNameW.argtypes = [wintypes.HANDLE, wintypes.DWORD,
                                                        wintypes.LPWSTR, ctypes.POINTER(wintypes.DWORD)]
        self.kernel.QueryFullProcessImageNameW.restype = wintypes.BOOL
        self.kernel.GetProcessTimes.argtypes = [wintypes.HANDLE] + [ctypes.POINTER(wintypes.FILETIME)] * 4
        self.kernel.GetProcessTimes.restype = wintypes.BOOL
        self.kernel.CloseHandle.argtypes = [wintypes.HANDLE]
        self.kernel.CloseHandle.restype = wintypes.BOOL

    def describe(self, handle: int, kind="webgis") -> BrowserWindow | None:
        if not self.user.IsWindowVisible(handle):
            return None
        pid = wintypes.DWORD()
        self.user.GetWindowThreadProcessId(handle, ctypes.byref(pid))
        process = self.kernel.OpenProcess(0x1000, False, pid.value)  # query limited information
        if not process:
            return None
        try:
            path = ctypes.create_unicode_buffer(32768)
            size = wintypes.DWORD(len(path))
            times = [wintypes.FILETIME() for _ in range(4)]
            if not self.kernel.QueryFullProcessImageNameW(process, 0, path, ctypes.byref(size)):
                return None
            if not self.kernel.GetProcessTimes(process, *[ctypes.byref(t) for t in times]):
                return None
            executable = ntpath.basename(path.value).lower()
            if kind == "ppt":
                if executable != "powerpnt.exe":
                    return None
                window_class = ctypes.create_unicode_buffer(128)
                self.user.GetClassNameW(handle, window_class, len(window_class))
                # Do not preview/activate Office authentication or security dialogs.
                if window_class.value not in {"PPTFrameClass", "screenClass"}:
                    return None
            elif executable not in BROWSERS:
                return None
            title = ctypes.create_unicode_buffer(2048)
            self.user.GetWindowTextW(handle, title, len(title))
            if kind != "ppt" and not is_webgis_browser(path.value, title.value):
                return None
            created = (times[0].dwHighDateTime << 32) | times[0].dwLowDateTime
            return BrowserWindow(handle, pid.value, created, path.value, title.value)
        finally:
            self.kernel.CloseHandle(process)

    def windows(self, kind="webgis") -> list[BrowserWindow]:
        found = []
        def collect(handle, _):
            item = self.describe(handle, kind)
            if item:
                found.append(item)
            return True
        callback = self.callback(collect)
        self.user.EnumWindows(callback, 0)
        return found

    def browsers(self) -> list[BrowserWindow]:
        return self.windows("webgis")

    def powerpoints(self) -> list[BrowserWindow]:
        return self.windows("ppt")

    def validate(self, target: BrowserWindow, kind="webgis"):
        current = self.describe(target.handle) if kind == "webgis" else self.describe(target.handle, kind)
        if current is None or (current.pid, current.created, current.executable) != (
                target.pid, target.created, target.executable):
            raise ValueError("原窗口已关闭或切到其他网页，请重新选择。")
        return current

    def activate_browser(self, target: BrowserWindow) -> bool:
        self.validate(target)
        if self.user.IsIconic(target.handle):
            self.user.ShowWindow(target.handle, 9)
        self.user.SetForegroundWindow(target.handle)
        return self.user.GetForegroundWindow() == target.handle

    def expand(self, target: BrowserWindow, kind: str) -> bool:
        self.validate(target, kind)
        window_class = ctypes.create_unicode_buffer(128)
        self.user.GetClassNameW(target.handle, window_class, len(window_class))
        # Restore an existing slide show; never restart it or resize its screen.
        command = 9 if window_class.value == "screenClass" else 3
        self.user.ShowWindowAsync(target.handle, command)
        accepted = self.user.SetForegroundWindow(target.handle)
        deadline = time.monotonic() + 0.35
        while accepted and self.user.GetForegroundWindow() != target.handle and time.monotonic() < deadline:
            time.sleep(0.02)
        return self.user.GetForegroundWindow() == target.handle

    def open_site(self):
        """Explicit native choice only; fixed site in a new browser window."""
        import winreg
        for browser in ("msedge.exe", "chrome.exe"):
            for hive in (winreg.HKEY_CURRENT_USER, winreg.HKEY_LOCAL_MACHINE):
                for view in (winreg.KEY_WOW64_64KEY, winreg.KEY_WOW64_32KEY):
                    try:
                        with winreg.OpenKey(hive, rf"SOFTWARE\Microsoft\Windows\CurrentVersion\App Paths\{browser}",
                                            0, winreg.KEY_READ | view) as key:
                            executable = winreg.QueryValueEx(key, "")[0]
                        if not isinstance(executable, str):
                            continue
                        path = Path(executable)
                        if path.name.lower() != browser or not path.is_file():
                            continue
                        subprocess.Popen([str(path), "--new-window", WEBGIS_SITE],
                                         stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
                        return
                    except OSError:
                        continue
        raise OSError("未找到已安装的 Edge / Chrome，请自行在独立浏览器窗口打开 WebGIS。")

    def palette_handle(self, root) -> int:
        return self.user.GetAncestor(root.winfo_id(), 2) or root.winfo_id()

    def palette_dpi(self, root) -> float:
        function = getattr(self.user, "GetDpiForWindow", None)
        if function:
            function.argtypes, function.restype = [wintypes.HWND], wintypes.UINT
            dpi = function(self.palette_handle(root))
            if dpi:
                return dpi
        return root.winfo_fpixels("1i")

    def show_palette(self, root, visible: bool):
        handle = self.palette_handle(root)
        self.user.ShowWindow(handle, 4 if visible else 0)  # no activation; leave slide show running
        if visible:
            self.user.SetWindowPos(handle, -1, 0, 0, 0, 0, 0x13)  # TOPMOST / no move, resize, activation

    def cursor_position(self) -> tuple[int, int]:
        point = wintypes.POINT()
        if not self.user.GetCursorPos(ctypes.byref(point)):
            raise OSError("无法读取鼠标位置，已停止本次拖动。")
        return point.x, point.y

    def palette_rect(self, root) -> tuple[int, int, int, int]:
        rect = wintypes.RECT()
        if not self.user.GetWindowRect(self.palette_handle(root), ctypes.byref(rect)):
            raise OSError("无法读取悬浮球位置，已停止本次拖动。")
        return rect.left, rect.top, rect.right, rect.bottom

    def move_palette(self, root, x: int, y: int, width: int, height: int):
        # Tk owns client sizing and frame offsets. A leading '+' followed by a
        # signed coordinate also supports monitors left/above the primary;
        # '-300' alone would instead mean an offset from the right edge.
        root.geometry(f"{width}x{height}+{x}+{y}")
        root.update_idletasks()
        # Raise without overriding Tk's wrapper/client dimensions on each drag.
        if not self.user.SetWindowPos(self.palette_handle(root), -1, 0, 0, 0, 0, 0x13):
            raise OSError("位置已更新，但 Windows 未确认显示层级。请重新显示悬浮球。")

    def configure_palette(self, root):
        handle = self.palette_handle(root)
        # Mouse presses do not take slide-show focus, but explicit taskbar /
        # keyboard activation stays available. Only this owned Tk window is
        # subclassed; unrelated applications' windows are never modified.
        style = self.user.GetWindowLongW(handle, -20)
        self.user.SetWindowLongW(handle, -20, (style | 0x40000) & ~0x08000080)
        # Tk creates the undecorated popup. Do not strip native frame bits
        # behind its geometry manager: stale border metrics can crop the canvas.
        # The extended APPWINDOW style above keeps explicit taskbar access.
        self.user.SetWindowPos(handle, 0, 0, 0, 0, 0, 0x37)
        self._palette_callback = self.subclass_callback(self._palette_message)
        if not self.controls.SetWindowSubclass(handle, self._palette_callback, 1, 0):
            raise OSError("无法启用悬浮球鼠标焦点保护。")

    def _palette_message(self, handle, message, wparam, lparam, subclass, _):
        if message == 0x21:  # WM_MOUSEACTIVATE: retain input, do not activate
            return 3  # MA_NOACTIVATE
        if message == 0x82:  # WM_NCDESTROY: detach before the owned window dies
            self.controls.RemoveWindowSubclass(handle, self._palette_callback, subclass)
        return self.controls.DefSubclassProc(handle, message, wparam, lparam)

    def foreground(self) -> int:
        return self.user.GetForegroundWindow()

    def is_powerpoint_window(self, handle: int) -> bool:
        pid = wintypes.DWORD()
        self.user.GetWindowThreadProcessId(handle, ctypes.byref(pid))
        process = self.kernel.OpenProcess(0x1000, False, pid.value)
        if not process:
            return False
        try:
            path = ctypes.create_unicode_buffer(32768)
            size = wintypes.DWORD(len(path))
            return bool(self.kernel.QueryFullProcessImageNameW(process, 0, path, ctypes.byref(size))
                        and ntpath.basename(path.value).lower() == "powerpnt.exe")
        finally:
            self.kernel.CloseHandle(process)

    def work_area(self, x: int, y: int) -> tuple[int, int, int, int]:
        class MonitorInfo(ctypes.Structure):
            _fields_ = [("size", wintypes.DWORD), ("monitor", wintypes.RECT),
                        ("work", wintypes.RECT), ("flags", wintypes.DWORD)]
        self.user.MonitorFromPoint.argtypes = [wintypes.POINT, wintypes.DWORD]
        self.user.MonitorFromPoint.restype = wintypes.HANDLE
        self.user.GetMonitorInfoW.argtypes = [wintypes.HANDLE, ctypes.POINTER(MonitorInfo)]
        self.user.GetMonitorInfoW.restype = wintypes.BOOL
        monitor = self.user.MonitorFromPoint(wintypes.POINT(x, y), 2)
        info = MonitorInfo()
        info.size = ctypes.sizeof(info)
        if not self.user.GetMonitorInfoW(monitor, ctypes.byref(info)):
            raise OSError("无法读取屏幕范围。")
        return info.work.left, info.work.top, info.work.right, info.work.bottom


class DwmThumbnail:
    """Windows-composited live view; no pixel readback, encoding or uploads."""
    class Properties(ctypes.Structure):
        _fields_ = [("flags", wintypes.DWORD), ("destination", wintypes.RECT),
                    ("source", wintypes.RECT), ("opacity", wintypes.BYTE),
                    ("visible", wintypes.BOOL), ("client_only", wintypes.BOOL)]

    def __init__(self, destination: int, source: int):
        self.dwm = ctypes.WinDLL("dwmapi", use_last_error=True)
        self.dwm.DwmRegisterThumbnail.argtypes = [wintypes.HWND, wintypes.HWND, ctypes.POINTER(wintypes.HANDLE)]
        self.dwm.DwmRegisterThumbnail.restype = wintypes.LONG
        self.dwm.DwmUnregisterThumbnail.argtypes = [wintypes.HANDLE]
        self.dwm.DwmUnregisterThumbnail.restype = wintypes.LONG
        self.dwm.DwmQueryThumbnailSourceSize.argtypes = [wintypes.HANDLE, ctypes.POINTER(wintypes.SIZE)]
        self.dwm.DwmQueryThumbnailSourceSize.restype = wintypes.LONG
        self.dwm.DwmUpdateThumbnailProperties.argtypes = [wintypes.HANDLE, ctypes.POINTER(self.Properties)]
        self.dwm.DwmUpdateThumbnailProperties.restype = wintypes.LONG
        self.handle = wintypes.HANDLE()
        if self.dwm.DwmRegisterThumbnail(destination, source, ctypes.byref(self.handle)) != 0:
            raise OSError("Windows 无法显示该窗口预览，可点击放大进入原应用。")

    def update(self, x: int, y: int, width: int, height: int):
        size = wintypes.SIZE()
        if self.dwm.DwmQueryThumbnailSourceSize(self.handle, ctypes.byref(size)) != 0:
            raise OSError("原窗口预览已不可用。")
        left, top, right, bottom = fit_preview(width, height, size.cx, size.cy)
        props = self.Properties()
        props.flags = 1 | 4 | 8 | 16  # destination, opacity, visible, client area
        props.destination = wintypes.RECT(x + left, y + top, x + right, y + bottom)
        props.opacity, props.visible, props.client_only = 255, True, False
        if self.dwm.DwmUpdateThumbnailProperties(self.handle, ctypes.byref(props)) != 0:
            raise OSError("Windows 窗口预览未能更新。")

    def close(self):
        if self.handle:
            self.dwm.DwmUnregisterThumbnail(self.handle)
            self.handle = wintypes.HANDLE()


class SwitchPalette:
    """Native two-step switching; Tk on main thread, workers only queue events."""
    def __init__(self, actions, desktop=None):
        import tkinter as tk
        self.tk = tk
        self.desktop = desktop or WindowsDesktop()
        self.actions = actions
        self.events = queue.Queue()
        self.target = None
        self.ppt_target = None
        self.operation = None
        self.chooser = None
        self.context_menu = None
        self.preview = None
        self.thumbnail = None
        self.preview_target = None
        self.preview_kind = None
        self.drag_origin = None
        self.dragged = False
        self.last_target = "webgis"
        self.tick_count = 0
        self.last_foreground = None
        self.root = tk.Tk()
        self.root.overrideredirect(True)
        dpi = self.desktop.palette_dpi(self.root)
        self.root.tk.call("tk", "scaling", dpi / 72.0)
        self.scale = max(1.0, dpi / 96.0)
        px = self.px = lambda value: round(value * self.scale)
        self.palette_size = px(48)
        self.edge_margin = px(8)
        self.drag_threshold = px(6)
        self.root.title("WebGIS · PPT 悬浮球")
        self.root.resizable(False, False)
        self.root.attributes("-topmost", True)
        self.root.configure(bg="#ff00ff")
        self.root.attributes("-transparentcolor", "#ff00ff")
        self.root.protocol("WM_DELETE_WINDOW", self.hide)
        self.canvas = tk.Canvas(self.root, width=self.palette_size, height=self.palette_size, bg="#ff00ff", highlightthickness=0, cursor="hand2")
        self.canvas.pack()
        # Compact neutral shell; the application mark carries the colour.
        self.canvas.create_oval(*[px(v) for v in (4, 7, 46, 48)], fill="#edf0f3", outline="")
        self.canvas.create_oval(*[px(v) for v in (3, 5, 45, 47)], fill="#e3e8ed", outline="")
        self.ring = self.canvas.create_oval(*[px(v) for v in (2, 2, 44, 44)], fill="#fff", outline="#e2e8ed", width=1)
        # A code-drawn presentation mark; no external image download or Office branding asset.
        self.canvas.create_oval(*[px(v) for v in (17, 12, 35, 30)], fill="#f5ba9d", outline="", tags="ppt")
        self.canvas.create_arc(*[px(v) for v in (17, 12, 35, 30)], start=0, extent=90, fill="#d35230", outline="", tags="ppt")
        self.canvas.create_rectangle(*[px(v) for v in (10, 15, 26, 31)], fill="#c43e1c", outline="", tags="ppt")
        self.canvas.create_text(px(18), px(23), text="P", fill="#fff", font=("Segoe UI", 11, "bold"), tags="ppt")
        logo = Path(__file__).resolve().parents[2] / "frontend/src/assets/brand/geobot-platform-logo.png"
        try:
            source = tk.PhotoImage(file=str(logo))
            self.logo = source.subsample(max(1, (source.width() + px(30) - 1) // px(30)))
            self.canvas.create_image(px(23), px(23), image=self.logo, tags="webgis")
        except (tk.TclError, OSError):
            self.canvas.create_text(px(23), px(23), text="Geo", fill="#17586d", font=("Microsoft YaHei UI", 9, "bold"), tags="webgis")
        self.badge = self.canvas.create_oval(*[px(v) for v in (34, 34, 41, 41)], fill="#e4a334", outline="#fff", width=1, state="hidden")
        self._badge()
        self.canvas.bind("<ButtonPress-1>", self._drag_begin)
        self.canvas.bind("<B1-Motion>", self._drag)
        self.canvas.bind("<ButtonRelease-1>", self._release)
        self.canvas.bind("<Button-3>", self._menu)
        self.canvas.bind("<Enter>", lambda _: self.canvas.itemconfigure(self.ring, fill="#f5f8fa", outline="#ccd8df"))
        self.canvas.bind("<Leave>", lambda _: self.canvas.itemconfigure(self.ring, fill="#fff", outline="#e2e8ed"))
        self.root.bind("<Return>", lambda _: self._toggle())
        self.root.bind("<space>", lambda _: self._toggle())
        self.root.geometry(f"{self.palette_size}x{self.palette_size}")
        self.root.update_idletasks()
        self.desktop.configure_palette(self.root)
        area = self.desktop.work_area(0, 0)
        self._place(area[2] - self.palette_size - px(20), area[3] - self.palette_size - px(20))
        self.desktop.show_palette(self.root, True)
        self.root.after(75, self._tick)

    def request_show(self) -> dict:
        event = threading.Event()
        self.events.put(event)
        if not event.wait(3):
            raise RuntimeError("桌面小窗未响应。")
        return {"status": "shown"}

    def notify_show(self):
        self.events.put(None)

    def _tick(self):
        try:
            while True:
                event = self.events.get_nowait()
                self.desktop.show_palette(self.root, True)
                if event:
                    event.set()
        except queue.Empty:
            pass
        if self.operation:
            result = self.actions.get(self.operation)
            if result and result["status"] != "pending":
                self.operation = None
                if result.get("status") in {"opened", "focused"}:
                    # Launch only when no existing native frame was found. COM
                    # results never choose/reopen a file for the preview flow.
                    self.focus_ppt(allow_launch=False)
                else:
                    self._notice(result.get("message") or "PowerPoint 未能启动，请检查 Office 提示框。")
                self._badge()
        self.tick_count += 1
        if self.tick_count % 7 == 0:
            foreground = self.desktop.foreground()
            # A browser can change tabs without changing its native handle.
            ppt = self.desktop.describe(foreground, "ppt")
            browser = None if ppt else self.desktop.describe(foreground)
            if ppt:
                self.ppt_target, self.last_target = ppt, "ppt"
            elif browser:
                self.target, self.last_target = browser, "webgis"
            self._badge()
            self.last_foreground = foreground
            self._refresh_preview()
        self.root.after(75, self._tick)

    def _badge(self):
        web = self.last_target == "ppt"
        self.canvas.itemconfigure("ppt", state="hidden" if web else "normal")
        self.canvas.itemconfigure("webgis", state="normal" if web else "hidden")
        self.canvas.itemconfigure(self.badge, state="normal" if self.operation else "hidden")

    def _notice(self, text):
        from tkinter import messagebox
        messagebox.showinfo("WebGIS / PPT", text, parent=self.root)

    def _menu(self, event):
        # Reuse one menu across right clicks, including its bound callbacks.
        if self.context_menu is None:
            menu = self.context_menu = self.tk.Menu(self.root, tearoff=False)
            menu.add_command(label="预览 PPT", command=self.focus_ppt)
            menu.add_command(label="预览 WebGIS", command=self.focus_webgis)
            menu.add_separator()
            menu.add_command(label="选择 PowerPoint 窗口…", command=lambda: self.choose_window("ppt"))
            menu.add_command(label="选择 WebGIS 窗口…", command=self.choose_browser)
            menu.add_command(label="隐藏悬浮球", command=self.hide)
        menu = self.context_menu
        for index in (0, 1, 3, 4):
            menu.entryconfigure(index, state="disabled" if self.operation else "normal")
        try:
            menu.tk_popup(event.x_root, event.y_root)
        finally:
            menu.grab_release()

    def hide(self):
        self.close_preview()
        if self.chooser:
            self.chooser.destroy()
            self.chooser = None
        self.desktop.show_palette(self.root, False)

    def _place(self, x, y):
        width = height = self.palette_size
        left, top, right, bottom = self.desktop.work_area(x + width // 2, y + height // 2)
        margin = min(self.edge_margin, max(0, (right - left - width) // 2),
                     max(0, (bottom - top - height) // 2))
        area = (left + margin, top + margin, right - margin, bottom - margin)
        x, y = clamp_position(x, y, width, height, area)
        self.desktop.move_palette(self.root, x, y, width, height)

    def _drag_begin(self, _):
        self.drag_origin = None
        self.dragged = False
        try:
            # Movement uses SetWindowPos: sample cursor and owned window from
            # the same desktop API, not Tk's cached geometry/event coordinates.
            sx, sy = self.desktop.cursor_position()
            x, y, _, _ = self.desktop.palette_rect(self.root)
            self.drag_origin = (sx, sy, x, y)
        except OSError as exc:
            self._notice(str(exc))

    def _drag(self, _):
        if self.drag_origin:
            try:
                sx, sy, x, y = self.drag_origin
                cx, cy = self.desktop.cursor_position()
                if self.dragged or abs(cx - sx) + abs(cy - sy) >= self.drag_threshold:
                    if not self.dragged:
                        self.close_preview()
                    self.dragged = True
                    self._place(x + cx - sx, y + cy - sy)
            except OSError as exc:
                self.drag_origin = None
                self._notice(str(exc))

    def _release(self, _):
        origin, self.drag_origin = self.drag_origin, None
        if origin and self.dragged:
            self.desktop.show_palette(self.root, True)
        elif origin and not self.operation:
            self._toggle()

    def _toggle(self):
        if self.operation:
            return
        kind = "webgis" if self.last_target == "ppt" else "ppt"
        if self.preview and self.preview_kind == kind:
            self.close_preview()
        elif kind == "ppt":
            self.focus_ppt()
        else:
            self.focus_webgis()

    def _resolve(self, kind):
        field = "ppt_target" if kind == "ppt" else "target"
        remembered = getattr(self, field)
        if remembered:
            try:
                return self.desktop.validate(remembered, kind)
            except ValueError:
                setattr(self, field, None)
        candidates = self.desktop.powerpoints() if kind == "ppt" else self.desktop.browsers()
        if len(candidates) == 1:
            setattr(self, field, candidates[0])
            return candidates[0]
        if candidates or kind == "webgis":
            self.choose_window(kind)
        return None

    def focus_ppt(self, allow_launch=True):
        if self.operation:
            return
        try:
            target = self._resolve("ppt")
            if target:
                self.show_preview(target, "ppt")
            elif not self.chooser and allow_launch:
                # Existing windows always win, including when COM/ROT is unavailable.
                self.operation = self.actions.start("launch")
                self.canvas.itemconfigure(self.badge, state="normal")
            elif not self.chooser:
                self._notice("PowerPoint 已启动但没有可预览的主窗口，请检查 Office 提示框。")
        except (ValueError, OSError, RuntimeError) as exc:
            self._notice(str(exc))

    def focus_webgis(self):
        if self.operation:
            return
        try:
            target = self._resolve("webgis")
            if target:
                self.show_preview(target, "webgis")
        except (ValueError, OSError) as exc:
            self._notice(str(exc))

    def choose_browser(self):
        self.choose_window("webgis")

    def choose_window(self, kind):
        if self.operation:
            return
        self.close_preview()
        candidates = self.desktop.powerpoints() if kind == "ppt" else self.desktop.browsers()
        if self.chooser:
            self.chooser.destroy()
        dialog = self.tk.Toplevel(self.root)
        self.chooser = dialog
        label = "PowerPoint" if kind == "ppt" else "WebGIS"
        dialog.title(f"选择 {label} 窗口")
        dialog.attributes("-topmost", True)
        self.tk.Label(dialog, text=f"只预览你选择的 {label} 窗口", padx=16, pady=12).pack()
        if not candidates:
            self.tk.Label(dialog, text="未找到可用窗口，请先打开应用并保持网页标签可见。", padx=16, pady=8).pack()
            if kind == "webgis":
                self.tk.Button(dialog, text="用独立浏览器打开 WebGIS", command=self.open_site, padx=12, pady=10).pack(fill="x", padx=12, pady=4)
        for candidate in candidates:
            def select(item=candidate):
                setattr(self, "ppt_target" if kind == "ppt" else "target", item)
                dialog.destroy()
                self.chooser = None
                try:
                    self.show_preview(item, kind)
                except (ValueError, OSError) as exc:
                    self._notice(str(exc))
            self.tk.Button(dialog, text=candidate.title[:100], command=select, padx=12, pady=10).pack(fill="x", padx=12, pady=4)
        def dismiss():
            dialog.destroy()
            self.chooser = None
        self.tk.Button(dialog, text="取消", command=dismiss).pack(pady=10)
        dialog.protocol("WM_DELETE_WINDOW", dismiss)

    def show_preview(self, target, kind):
        self.desktop.validate(target, kind)
        self.close_preview()
        self.preview_target, self.preview_kind = target, kind
        dialog = self.preview = self.tk.Toplevel(self.root)
        label = "PowerPoint" if kind == "ppt" else "WebGIS"
        dialog.title(f"{label} · 实时预览")
        dialog.configure(bg="#f5f8fb")
        dialog.attributes("-topmost", True)
        dialog.resizable(False, False)
        px = self.px
        self.tk.Label(dialog, text=f"{label}   实时预览", anchor="w", bg="#f5f8fb", fg="#22394c",
                      font=("Microsoft YaHei UI", 11, "bold"), padx=14, pady=12).pack(fill="x")
        self.preview_area = self.tk.Canvas(dialog, width=px(400), height=px(225), bg="#182732", highlightthickness=0)
        self.preview_area.pack(padx=px(12))
        self.preview_status = self.tk.Label(dialog, text="预览不操作原窗口；点放大进入", bg="#f5f8fb", fg="#536d7e", pady=5)
        self.preview_status.pack(fill="x")
        footer = self.tk.Frame(dialog, bg="#f5f8fb")
        footer.pack(fill="x", padx=12, pady=(0, 12))
        self.tk.Button(footer, text=f"放大进入 {label}  ↗", command=self.expand_preview,
                       bg="#d35230" if kind == "ppt" else "#147b90", fg="white", relief="flat", padx=14, pady=8).pack(side="right")
        self.tk.Button(footer, text="收起", command=self.close_preview, relief="flat", padx=12, pady=8).pack(side="left")
        dialog.protocol("WM_DELETE_WINDOW", self.close_preview)
        dialog.bind("<Escape>", lambda _: self.close_preview())
        dialog.update_idletasks()
        width, height = dialog.winfo_width(), dialog.winfo_height()
        left, top, _, _ = self.desktop.palette_rect(self.root)
        x, y = left + self.palette_size - width, top - height - px(12)
        x, y = clamp_position(x, y, width, height, self.desktop.work_area(x, y))
        self.desktop.move_palette(dialog, x, y, width, height)
        try:
            self.thumbnail = DwmThumbnail(self.desktop.palette_handle(dialog), target.handle)
            self._refresh_preview()
        except OSError:
            self.close_thumbnail()
            self.preview_status.configure(text="实时预览不可用；可点放大进入原窗口")

    def _refresh_preview(self):
        if not self.preview:
            return
        try:
            self.desktop.validate(self.preview_target, self.preview_kind)
        except ValueError:
            self.close_thumbnail()
            self.preview_status.configure(text="原窗口已关闭或网页已切换，请收起后重新选择")
            return
        if self.thumbnail:
            area, dialog = self.preview_area, self.preview
            try:
                self.thumbnail.update(area.winfo_rootx() - dialog.winfo_rootx(),
                                      area.winfo_rooty() - dialog.winfo_rooty(), area.winfo_width(), area.winfo_height())
                minimized = self.desktop.user.IsIconic(self.preview_target.handle)
                self.preview_status.configure(text="原窗口已最小化，预览可能暂停；点放大恢复" if minimized else "实时预览 · 点放大进入原应用")
            except (OSError, ValueError):
                self.close_thumbnail()
                self.preview_status.configure(text="实时预览不可用；可点放大进入原窗口")

    def expand_preview(self):
        if not self.preview_target:
            return
        target, kind = self.preview_target, self.preview_kind
        try:
            if self.desktop.expand(target, kind):
                self.last_target = kind
                self.close_preview()
                self._badge()
            else:
                self.preview_status.configure(text="Windows 未允许切换，请点击原应用任务栏")
        except (ValueError, OSError) as exc:
            self.close_thumbnail()
            self.preview_status.configure(text=str(exc))

    def close_thumbnail(self):
        if self.thumbnail:
            self.thumbnail.close()
            self.thumbnail = None

    def close_preview(self):
        self.close_thumbnail()
        if self.preview:
            self.preview.destroy()
            self.preview = None
        self.preview_target = self.preview_kind = None

    def open_site(self):
        try:
            self.desktop.open_site()
            if self.chooser:
                self.chooser.destroy()
                self.chooser = None
        except OSError as exc:
            self._notice(str(exc))

    def run(self):
        try:
            self.root.mainloop()
        finally:
            self.close_thumbnail()
