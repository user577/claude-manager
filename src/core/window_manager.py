import ctypes
import ctypes.wintypes as wt
from dataclasses import dataclass

user32 = ctypes.windll.user32


@dataclass
class Rect:
    x: int
    y: int
    w: int
    h: int


def get_work_area() -> Rect:
    """Get primary monitor work area (excludes taskbar)."""
    rect = wt.RECT()
    SPI_GETWORKAREA = 0x0030
    user32.SystemParametersInfoW(SPI_GETWORKAREA, 0, ctypes.byref(rect), 0)
    return Rect(rect.left, rect.top, rect.right - rect.left, rect.bottom - rect.top)


def compute_layout(work: Rect, layout: str, count: int) -> list[Rect]:
    """Compute window positions for the given layout and count."""
    positions = []

    if layout == "grid_2x2":
        cols = 2 if count > 1 else 1
        rows = 2 if count > 2 else 1
        cw = work.w // cols
        ch = work.h // rows
        for i in range(min(count, 4)):
            r = i // cols
            c = i % cols
            positions.append(Rect(work.x + c * cw, work.y + r * ch, cw, ch))

    elif layout == "vertical":
        ch = work.h // count
        for i in range(count):
            positions.append(Rect(work.x, work.y + i * ch, work.w, ch))

    elif layout == "horizontal":
        cw = work.w // count
        for i in range(count):
            positions.append(Rect(work.x + i * cw, work.y, cw, work.h))

    elif layout == "single":
        for _ in range(count):
            positions.append(Rect(work.x, work.y, work.w, work.h))

    return positions


def move_window(hwnd: int, pos: Rect):
    """Move and resize a window."""
    user32.MoveWindow(hwnd, pos.x, pos.y, pos.w, pos.h, True)


def set_foreground(hwnd: int):
    user32.SetForegroundWindow(hwnd)


# Callback type for EnumWindows
_WNDENUMPROC = ctypes.WINFUNCTYPE(wt.BOOL, wt.HWND, wt.LPARAM)


def find_windows_by_title(title_substring: str) -> list[int]:
    """Find all top-level windows whose title contains the substring."""
    results = []

    def callback(hwnd, _lparam):
        length = user32.GetWindowTextLengthW(hwnd)
        if length > 0:
            buf = ctypes.create_unicode_buffer(length + 1)
            user32.GetWindowTextW(hwnd, buf, length + 1)
            if title_substring in buf.value:
                results.append(hwnd)
        return True

    user32.EnumWindows(_WNDENUMPROC(callback), 0)
    return results


def tile_windows(hwnds: list[int], positions: list[Rect]):
    """Move a list of windows to their target positions."""
    for hwnd, pos in zip(hwnds, positions):
        move_window(hwnd, pos)
        set_foreground(hwnd)
