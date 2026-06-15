from __future__ import annotations

import ctypes
from ctypes import wintypes

from .models import Monitor


user32 = ctypes.WinDLL("user32", use_last_error=True)
gdi32 = ctypes.WinDLL("gdi32", use_last_error=True)
shcore = ctypes.WinDLL("shcore", use_last_error=True)

SRCCOPY = 0x00CC0020
CAPTUREBLT = 0x40000000
DIB_RGB_COLORS = 0
BI_RGB = 0
COLORONCOLOR = 3
MONITORINFOF_PRIMARY = 1
WDA_EXCLUDEFROMCAPTURE = 0x00000011


class RECT(ctypes.Structure):
    _fields_ = [
        ("left", wintypes.LONG),
        ("top", wintypes.LONG),
        ("right", wintypes.LONG),
        ("bottom", wintypes.LONG),
    ]


class MONITORINFOEXW(ctypes.Structure):
    _fields_ = [
        ("cbSize", wintypes.DWORD),
        ("rcMonitor", RECT),
        ("rcWork", RECT),
        ("dwFlags", wintypes.DWORD),
        ("szDevice", wintypes.WCHAR * 32),
    ]


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


class RGBQUAD(ctypes.Structure):
    _fields_ = [
        ("rgbBlue", wintypes.BYTE),
        ("rgbGreen", wintypes.BYTE),
        ("rgbRed", wintypes.BYTE),
        ("rgbReserved", wintypes.BYTE),
    ]


class BITMAPINFO(ctypes.Structure):
    _fields_ = [
        ("bmiHeader", BITMAPINFOHEADER),
        ("bmiColors", RGBQUAD * 1),
    ]


MonitorEnumProc = ctypes.WINFUNCTYPE(
    wintypes.BOOL,
    wintypes.HMONITOR,
    wintypes.HDC,
    ctypes.POINTER(RECT),
    wintypes.LPARAM,
)


def enable_dpi_awareness() -> None:
    try:
        shcore.SetProcessDpiAwareness(2)
    except Exception:
        try:
            user32.SetProcessDPIAware()
        except Exception:
            pass


def enumerate_monitors() -> list[Monitor]:
    monitors: list[Monitor] = []

    def callback(hmonitor, _hdc, _rect, _lparam):
        info = MONITORINFOEXW()
        info.cbSize = ctypes.sizeof(MONITORINFOEXW)
        if not user32.GetMonitorInfoW(hmonitor, ctypes.byref(info)):
            raise ctypes.WinError(ctypes.get_last_error())
        rect = info.rcMonitor
        device = info.szDevice.rstrip("\x00") or f"monitor-{len(monitors) + 1}"
        monitors.append(
            Monitor(
                id=device,
                left=rect.left,
                top=rect.top,
                width=rect.right - rect.left,
                height=rect.bottom - rect.top,
                primary=bool(info.dwFlags & MONITORINFOF_PRIMARY),
            )
        )
        return True

    if not user32.EnumDisplayMonitors(0, None, MonitorEnumProc(callback), 0):
        raise ctypes.WinError(ctypes.get_last_error())
    return monitors


def capture_bgra(monitor: Monitor) -> bytes:
    return capture_bgra_scaled(monitor, monitor.width, monitor.height)


def capture_bgra_scaled(monitor: Monitor, width: int, height: int) -> bytes:
    source_width = monitor.width
    source_height = monitor.height
    if source_width <= 0 or source_height <= 0 or width <= 0 or height <= 0:
        raise ValueError(f"Invalid monitor dimensions: {monitor}")

    screen_dc = user32.GetDC(None)
    if not screen_dc:
        raise ctypes.WinError(ctypes.get_last_error())
    memory_dc = None
    bitmap = None
    old_bitmap = None
    try:
        memory_dc = gdi32.CreateCompatibleDC(screen_dc)
        if not memory_dc:
            raise ctypes.WinError(ctypes.get_last_error())
        bitmap = gdi32.CreateCompatibleBitmap(screen_dc, width, height)
        if not bitmap:
            raise ctypes.WinError(ctypes.get_last_error())
        old_bitmap = gdi32.SelectObject(memory_dc, bitmap)
        if not old_bitmap:
            raise ctypes.WinError(ctypes.get_last_error())

        gdi32.SetStretchBltMode(memory_dc, COLORONCOLOR)
        if not gdi32.StretchBlt(
            memory_dc,
            0,
            0,
            width,
            height,
            screen_dc,
            monitor.left,
            monitor.top,
            source_width,
            source_height,
            SRCCOPY | CAPTUREBLT,
        ):
            raise ctypes.WinError(ctypes.get_last_error())

        bitmap_info = BITMAPINFO()
        bitmap_info.bmiHeader.biSize = ctypes.sizeof(BITMAPINFOHEADER)
        bitmap_info.bmiHeader.biWidth = width
        bitmap_info.bmiHeader.biHeight = -height
        bitmap_info.bmiHeader.biPlanes = 1
        bitmap_info.bmiHeader.biBitCount = 32
        bitmap_info.bmiHeader.biCompression = BI_RGB
        size = width * height * 4
        buffer = (ctypes.c_ubyte * size)()
        scan_lines = gdi32.GetDIBits(
            memory_dc,
            bitmap,
            0,
            height,
            ctypes.byref(buffer),
            ctypes.byref(bitmap_info),
            DIB_RGB_COLORS,
        )
        if scan_lines != height:
            raise ctypes.WinError(ctypes.get_last_error())
        return bytes(buffer)
    finally:
        if old_bitmap and memory_dc:
            gdi32.SelectObject(memory_dc, old_bitmap)
        if bitmap:
            gdi32.DeleteObject(bitmap)
        if memory_dc:
            gdi32.DeleteDC(memory_dc)
        user32.ReleaseDC(None, screen_dc)


def exclude_window_from_capture(hwnd: int) -> bool:
    if not hwnd:
        return False
    return bool(user32.SetWindowDisplayAffinity(wintypes.HWND(hwnd), WDA_EXCLUDEFROMCAPTURE))


def is_hotkey_pressed(vk_code: int) -> bool:
    return bool(user32.GetAsyncKeyState(vk_code) & 0x8000)
