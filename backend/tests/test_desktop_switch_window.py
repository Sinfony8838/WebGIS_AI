from unittest.mock import Mock

import pytest

from backend.app.desktop_switch_window import (
    BrowserWindow, SwitchPalette, WindowsDesktop, DwmThumbnail, fit_preview, clamp_position, is_webgis_browser,
)


@pytest.mark.parametrize("executable,title,expected", [
    ("C:/Program Files/Google/chrome.exe", "地理智能教学平台 - Chrome", True),
    (r"C:\Edge\msedge.exe", "WebGIS - Microsoft Edge", True),
    ("firefox.exe", "webgis 教学", True),
    ("chrome.exe", "其他页面", False),
    ("POWERPNT.EXE", "WebGIS.pptx", False),
    ("Codex.exe", "WebGIS", False),
    ("evil.exe", "地理智能教学平台", False),
])
def test_only_visible_webgis_browser_titles_are_candidates(executable, title, expected):
    assert is_webgis_browser(executable, title) is expected


@pytest.mark.parametrize("point,area,expected", [
    ((-50, -40), (0, 0, 1920, 1040), (0, 0)),
    ((1900, 1000), (0, 0, 1920, 1040), (1628, 872)),
    ((-1800, 900), (-1920, 0, 0, 1040), (-1800, 872)),
    ((80, 80), (0, 0, 200, 100), (0, 0)),
])
def test_palette_stays_in_monitor_work_area(point, area, expected):
    assert clamp_position(*point, 292, 168, area) == expected


def make_palette():
    palette = SwitchPalette.__new__(SwitchPalette)
    palette.operation = palette.target = palette.ppt_target = palette.chooser = None
    palette.context_menu = None
    palette.preview = palette.thumbnail = palette.preview_target = palette.preview_kind = None
    palette.desktop = Mock()
    palette.actions = Mock()
    palette.last_target = "webgis"
    return palette


def window(**kwargs):
    return BrowserWindow(**({"handle": 45, "pid": 90, "created": 123,
                            "executable": "chrome.exe", "title": "WebGIS"} | kwargs))


@pytest.mark.parametrize("current", [None, window(pid=91), window(created=124), window(executable="msedge.exe")])
def test_closed_or_recycled_window_cannot_be_activated(current):
    desktop = WindowsDesktop.__new__(WindowsDesktop)
    desktop.describe = Mock(return_value=current)
    desktop.user = Mock()
    with pytest.raises(ValueError, match="重新选择"):
        desktop.activate_browser(window())
    desktop.user.SetForegroundWindow.assert_not_called()
    desktop.user.ShowWindow.assert_not_called()


def test_minimized_browser_restored_and_actual_foreground_reported():
    desktop = WindowsDesktop.__new__(WindowsDesktop)
    desktop.describe = Mock(return_value=window())
    desktop.user = Mock()
    desktop.user.IsIconic.return_value = True
    desktop.user.GetForegroundWindow.return_value = 45
    assert desktop.activate_browser(window()) is True
    desktop.user.ShowWindow.assert_called_once_with(45, 9)
    desktop.user.GetForegroundWindow.return_value = 99
    assert desktop.activate_browser(window()) is False


@pytest.mark.parametrize("count", [0, 2])
def test_palette_does_not_guess_between_browser_windows(count):
    palette = make_palette()
    palette.operation = None
    palette.target = None
    palette.desktop = Mock()
    palette.desktop.browsers.return_value = [window(handle=i) for i in range(count)]
    palette.choose_window = Mock()
    palette.focus_webgis()
    palette.choose_window.assert_called_once_with("webgis")
    palette.desktop.activate_browser.assert_not_called()
    palette.desktop.open_site.assert_not_called()


def test_closed_browser_binding_is_not_used_for_preview_or_activation():
    palette = make_palette()
    palette.target = window()
    palette.desktop.validate.side_effect = ValueError("已关闭")
    palette.desktop.browsers.return_value = []
    palette.choose_window = Mock()
    palette.show_preview = Mock()
    palette.focus_webgis()
    assert palette.target is None
    palette.choose_window.assert_called_once_with("webgis")
    palette.show_preview.assert_not_called()
    palette.desktop.expand.assert_not_called()


def test_showing_palette_does_not_activate_or_restore_powerpoint():
    desktop = WindowsDesktop.__new__(WindowsDesktop)
    desktop.user = Mock()
    desktop.palette_handle = Mock(return_value=42)
    desktop.show_palette(Mock(), True)
    desktop.user.ShowWindow.assert_called_once_with(42, 4)
    desktop.user.SetWindowPos.assert_called_once_with(42, -1, 0, 0, 0, 0, 0x13)
    desktop.user.SetForegroundWindow.assert_not_called()


@pytest.mark.parametrize("last_target,expected", [("ppt", "webgis"), ("webgis", "ppt")])
def test_single_click_switches_to_the_other_surface(last_target, expected):
    palette = make_palette()
    palette.drag_origin = (0, 0, 80, 80)
    palette.dragged = False
    palette.operation = None
    palette.last_target = last_target
    palette.focus_webgis, palette.focus_ppt = Mock(), Mock()
    palette._release(None)
    (palette.focus_webgis if expected == "webgis" else palette.focus_ppt).assert_called_once()
    (palette.focus_ppt if expected == "webgis" else palette.focus_webgis).assert_not_called()
    assert palette.drag_origin is None


@pytest.mark.parametrize("dragged,operation", [(True, None), (False, "pending")])
def test_drag_or_pending_switch_never_dispatches_another_click(dragged, operation):
    palette = make_palette()
    palette.drag_origin = (0, 0, 80, 80)
    palette.dragged, palette.operation = dragged, operation
    palette.focus_webgis, palette.focus_ppt = Mock(), Mock()
    palette._release(None)
    palette.focus_webgis.assert_not_called()
    palette.focus_ppt.assert_not_called()


def test_palette_keeps_keyboard_activation_but_mouse_does_not_take_focus():
    desktop = WindowsDesktop.__new__(WindowsDesktop)
    desktop.user = Mock()
    desktop.user.GetWindowLongW.side_effect = lambda _, kind: 0x08000080 if kind == -20 else 0x00C40000
    desktop.palette_handle = Mock(return_value=42)
    desktop.controls = Mock()
    desktop.subclass_callback = lambda callback: callback
    desktop.configure_palette(Mock())
    desktop.user.SetWindowLongW.assert_any_call(42, -20, 0x40000)
    desktop.user.SetWindowLongW.assert_any_call(42, -16, 0)
    assert desktop._palette_message(42, 0x21, 0, 0, 1, 0) == 3
    desktop.controls.DefSubclassProc.assert_not_called()
    desktop._palette_message(42, 0x82, 0, 0, 1, 0)
    desktop.controls.RemoveWindowSubclass.assert_called_once_with(42, desktop._palette_callback, 1)
    desktop.controls.DefSubclassProc.assert_called_once_with(42, 0x82, 0, 0)


def test_native_open_website_does_not_remember_an_unverified_browser_handle():
    palette = make_palette()
    palette.target = None
    palette.chooser = Mock()
    chooser = palette.chooser
    palette.desktop = Mock()
    palette.open_site()
    palette.desktop.open_site.assert_called_once_with()
    chooser.destroy.assert_called_once()
    assert palette.chooser is None and palette.target is None


def test_native_browser_launcher_uses_only_registered_browser_and_fixed_site(tmp_path, monkeypatch):
    from contextlib import nullcontext
    import sys
    from types import SimpleNamespace
    from backend.app import desktop_switch_window as module

    executable = tmp_path / "msedge.exe"
    executable.write_text("synthetic; never executed")
    registry = SimpleNamespace(HKEY_CURRENT_USER=1, HKEY_LOCAL_MACHINE=2, KEY_WOW64_64KEY=256,
                               KEY_WOW64_32KEY=512, KEY_READ=16,
                               OpenKey=Mock(return_value=nullcontext("synthetic-registry")),
                               QueryValueEx=Mock(return_value=(str(executable), 1)))
    monkeypatch.setitem(sys.modules, "winreg", registry)
    launch = Mock()
    monkeypatch.setattr(module.subprocess, "Popen", launch)
    desktop = WindowsDesktop.__new__(WindowsDesktop)
    desktop.open_site()
    launch.assert_called_once_with([str(executable), "--new-window", "https://webgisai.com"],
                                   stdout=module.subprocess.DEVNULL, stderr=module.subprocess.DEVNULL)
    launch.reset_mock()
    registry.QueryValueEx.return_value = (str(tmp_path / "other.exe"), 1)
    with pytest.raises(OSError, match="未找到"):
        desktop.open_site()
    launch.assert_not_called()


def test_keyboard_repeat_during_pending_action_cannot_switch_again():
    palette = make_palette()
    palette.operation = "pending-native-action"
    palette.last_target = "ppt"
    palette.focus_webgis, palette.focus_ppt = Mock(), Mock()
    palette._toggle()
    palette.focus_webgis.assert_not_called()
    palette.focus_ppt.assert_not_called()


def test_drag_threshold_scales_and_release_does_not_toggle():
    from types import SimpleNamespace
    palette = make_palette()
    palette.drag_origin = (100, 100, 80, 80)
    palette.drag_threshold = 12
    palette.dragged = False
    palette.operation = None
    palette._place = Mock()
    palette.focus_webgis, palette.focus_ppt = Mock(), Mock()
    palette._drag(SimpleNamespace(x_root=104, y_root=100))
    palette._place.assert_not_called()
    palette._drag(SimpleNamespace(x_root=113, y_root=104))
    palette._place.assert_called_once_with(93, 84)
    palette._release(None)
    palette.focus_webgis.assert_not_called()
    palette.focus_ppt.assert_not_called()


def test_non_browser_caption_is_never_read():
    desktop = WindowsDesktop.__new__(WindowsDesktop)
    desktop.user, desktop.kernel = Mock(), Mock()
    desktop.user.IsWindowVisible.return_value = True
    desktop.kernel.OpenProcess.return_value = 77
    def image_name(_, __, buffer, ___):
        buffer.value = "C:/Office/POWERPNT.EXE"
        return True
    desktop.kernel.QueryFullProcessImageNameW.side_effect = image_name
    desktop.kernel.GetProcessTimes.return_value = True
    assert desktop.describe(42) is None
    desktop.user.GetWindowTextW.assert_not_called()
    desktop.kernel.CloseHandle.assert_called_once_with(77)


def test_existing_powerpoint_is_previewed_without_com_or_a_new_launch():
    palette = make_palette()
    existing = window(executable="POWERPNT.EXE", title="Synthetic QA deck")
    palette.desktop.powerpoints.return_value = [existing]
    palette.show_preview = Mock()
    palette.focus_ppt()
    palette.show_preview.assert_called_once_with(existing, "ppt")
    palette.actions.start.assert_not_called()
    palette.desktop.expand.assert_not_called()
    palette.focus_ppt()
    palette.actions.start.assert_not_called()


def test_multiple_powerpoints_need_selection_and_never_start_another():
    palette = make_palette()
    palette.desktop.powerpoints.return_value = [window(handle=1), window(handle=2)]
    def choose(kind):
        palette.chooser = Mock()
    palette.choose_window = Mock(side_effect=choose)
    palette.focus_ppt()
    palette.choose_window.assert_called_once_with("ppt")
    palette.actions.start.assert_not_called()


def test_only_absent_powerpoint_launches_once_until_result():
    palette = make_palette()
    palette.desktop.powerpoints.return_value = []
    palette.actions.start.return_value = "pending"
    palette.canvas, palette.badge = Mock(), "badge"
    palette.focus_ppt()
    palette.focus_ppt()
    palette.actions.start.assert_called_once_with("launch")


@pytest.mark.parametrize("kind", ["ppt", "webgis"])
def test_expand_flips_logo_only_after_verified_foreground(kind):
    palette = make_palette()
    palette.preview, palette.preview_status = Mock(), Mock()
    palette.preview_target, palette.preview_kind = window(), kind
    palette.close_preview, palette._badge = Mock(), Mock()
    before = palette.last_target
    palette.desktop.expand.return_value = False
    palette.expand_preview()
    assert palette.last_target == before
    palette.close_preview.assert_not_called()
    palette.preview_status.configure.assert_called_once()
    palette.desktop.expand.return_value = True
    palette.expand_preview()
    assert palette.last_target == kind
    palette.close_preview.assert_called_once()
    palette._badge.assert_called_once()


def test_stale_preview_cannot_focus_recycled_or_other_app_window():
    desktop = WindowsDesktop.__new__(WindowsDesktop)
    desktop.validate = Mock(side_effect=ValueError("stale"))
    desktop.user = Mock()
    with pytest.raises(ValueError):
        desktop.expand(window(), "ppt")
    desktop.user.ShowWindow.assert_not_called()
    desktop.user.SetForegroundWindow.assert_not_called()


@pytest.mark.parametrize("window_class,command", [("PPTFrameClass", 3), ("screenClass", 9)])
def test_expand_preserves_existing_show_and_maximizes_only_editor(window_class, command):
    desktop = WindowsDesktop.__new__(WindowsDesktop)
    desktop.validate = Mock()
    desktop.user = Mock()
    def class_name(_, buffer, __):
        buffer.value = window_class
        return len(window_class)
    desktop.user.GetClassNameW.side_effect = class_name
    desktop.user.GetForegroundWindow.return_value = 45
    assert desktop.expand(window(), "ppt") is True
    desktop.validate.assert_called_once_with(window(), "ppt")
    desktop.user.ShowWindowAsync.assert_called_once_with(45, command)
    desktop.user.ShowWindow.assert_not_called()
    desktop.user.SetForegroundWindow.assert_called_once_with(45)


@pytest.mark.parametrize("source,expected", [((1920, 1080), (0, 0, 400, 225)),
                                           ((1000, 1000), (87, 0, 312, 225)),
                                           ((1600, 900), (0, 0, 400, 225))])
def test_preview_keeps_geometry_aspect_ratio(source, expected):
    assert fit_preview(400, 225, *source) == expected


def test_dwm_live_preview_unregisters_once_and_never_reads_pixels(monkeypatch):
    import ctypes
    from ctypes import wintypes
    api = Mock()
    def register(destination, source, handle):
        assert (destination, source) == (42, 45)
        handle._obj.value = 123
        return 0
    api.DwmRegisterThumbnail.side_effect = register
    def source_size(handle, size):
        size._obj.cx, size._obj.cy = 1920, 1080
        return 0
    api.DwmQueryThumbnailSourceSize.side_effect = source_size
    api.DwmUpdateThumbnailProperties.return_value = 0
    monkeypatch.setattr(ctypes, "WinDLL", Mock(return_value=api), raising=False)
    thumbnail = DwmThumbnail(42, 45)
    thumbnail.update(12, 48, 400, 225)
    props = api.DwmUpdateThumbnailProperties.call_args.args[1]._obj
    assert props.flags == 29 and props.visible and props.opacity == 255
    assert (props.destination.left, props.destination.top, props.destination.right, props.destination.bottom) == (12, 48, 412, 273)
    thumbnail.close()
    thumbnail.close()
    api.DwmUnregisterThumbnail.assert_called_once()


def test_closing_preview_releases_native_thumbnail_before_tk_window():
    palette = make_palette()
    calls = []
    palette.thumbnail, palette.preview = Mock(), Mock()
    palette.thumbnail.close.side_effect = lambda: calls.append("unregister")
    palette.preview.destroy.side_effect = lambda: calls.append("destroy")
    palette.close_preview()
    assert calls == ["unregister", "destroy"]
    assert palette.preview is palette.thumbnail is palette.preview_target is None


def test_window_selection_cannot_override_pending_launch():
    palette = make_palette()
    palette.operation = "pending-launch"
    palette.close_preview = Mock()
    palette.choose_window("webgis")
    palette.close_preview.assert_not_called()
    palette.desktop.browsers.assert_not_called()


def test_context_menu_is_reused_and_stays_alive_until_selection():
    from types import SimpleNamespace
    palette = make_palette()
    palette.tk, palette.root = Mock(), Mock()
    event = SimpleNamespace(x_root=80, y_root=80)
    palette._menu(event)
    palette.operation = "pending-launch"
    palette._menu(event)
    palette.tk.Menu.assert_called_once()
    menu = palette.context_menu
    assert menu.tk_popup.call_count == 2
    menu.destroy.assert_not_called()
    for index in (0, 1, 3, 4):
        menu.entryconfigure.assert_any_call(index, state="disabled")


def test_same_browser_handle_switching_to_webgis_tab_updates_target_icon():
    import queue
    palette = make_palette()
    palette.events = queue.Queue()
    palette.tick_count = 6
    palette.last_foreground = 45
    palette.last_target = "ppt"
    palette.root, palette._badge, palette._refresh_preview = Mock(), Mock(), Mock()
    palette.desktop.foreground.return_value = 45
    palette.desktop.describe.side_effect = [None, window()]
    palette._tick()
    assert palette.last_target == "webgis"
    assert palette.target == window()
    palette.desktop.describe.assert_any_call(45)
