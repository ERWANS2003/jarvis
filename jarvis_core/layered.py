"""Fenetres a transparence par pixel (Windows, « layered windows »).

Tkinter ne sait rendre transparente qu'une couleur exacte, ce qui laisse des
bords crenelés et un liseré autour des formes rondes. Ici, une image RGBA
(Pillow) est confiee directement a Windows via `UpdateLayeredWindow` : chaque
pixel a sa propre opacite, le halo se fond dans le bureau, et les clics
traversent les zones entierement transparentes.

Tkinter garde la gestion des evenements (clics, glisser) et de la position.
"""

from __future__ import annotations

import ctypes
import sys
from ctypes import wintypes

GWL_EXSTYLE = -20
WS_EX_LAYERED = 0x00080000
WS_EX_TOOLWINDOW = 0x00000080   # pas d'entree dans Alt+Tab
ULW_ALPHA = 0x00000002
AC_SRC_OVER = 0x00
AC_SRC_ALPHA = 0x01


def supported() -> bool:
    return sys.platform == "win32"


def enable_dpi_awareness() -> None:
    """Rendu net sur les ecrans mis a l'echelle (125 %, 150 %...)."""
    if not supported():
        return
    try:
        ctypes.windll.shcore.SetProcessDpiAwareness(2)
    except Exception:
        try:
            ctypes.windll.user32.SetProcessDPIAware()
        except Exception:
            pass


class _POINT(ctypes.Structure):
    _fields_ = [("x", wintypes.LONG), ("y", wintypes.LONG)]


class _SIZE(ctypes.Structure):
    _fields_ = [("cx", wintypes.LONG), ("cy", wintypes.LONG)]


class _BLEND(ctypes.Structure):
    _fields_ = [("BlendOp", ctypes.c_ubyte), ("BlendFlags", ctypes.c_ubyte),
                ("SourceConstantAlpha", ctypes.c_ubyte), ("AlphaFormat", ctypes.c_ubyte)]


class _BITMAPINFOHEADER(ctypes.Structure):
    _fields_ = [("biSize", wintypes.DWORD), ("biWidth", wintypes.LONG),
                ("biHeight", wintypes.LONG), ("biPlanes", wintypes.WORD),
                ("biBitCount", wintypes.WORD), ("biCompression", wintypes.DWORD),
                ("biSizeImage", wintypes.DWORD), ("biXPelsPerMeter", wintypes.LONG),
                ("biYPelsPerMeter", wintypes.LONG), ("biClrUsed", wintypes.DWORD),
                ("biClrImportant", wintypes.DWORD)]


def _api():
    user32, gdi32 = ctypes.windll.user32, ctypes.windll.gdi32
    handle = ctypes.c_void_p
    user32.GetDC.restype = handle
    user32.GetDC.argtypes = (handle,)
    user32.ReleaseDC.argtypes = (handle, handle)
    user32.GetWindowLongPtrW.restype = ctypes.c_ssize_t
    user32.GetWindowLongPtrW.argtypes = (handle, ctypes.c_int)
    user32.SetWindowLongPtrW.restype = ctypes.c_ssize_t
    user32.SetWindowLongPtrW.argtypes = (handle, ctypes.c_int, ctypes.c_ssize_t)
    user32.UpdateLayeredWindow.argtypes = (
        handle, handle, ctypes.POINTER(_POINT), ctypes.POINTER(_SIZE), handle,
        ctypes.POINTER(_POINT), wintypes.DWORD, ctypes.POINTER(_BLEND), wintypes.DWORD)
    gdi32.CreateCompatibleDC.restype = handle
    gdi32.CreateCompatibleDC.argtypes = (handle,)
    gdi32.CreateDIBSection.restype = handle
    gdi32.CreateDIBSection.argtypes = (handle, ctypes.c_void_p, wintypes.UINT,
                                       ctypes.POINTER(ctypes.c_void_p), handle,
                                       wintypes.DWORD)
    gdi32.SelectObject.restype = handle
    gdi32.SelectObject.argtypes = (handle, handle)
    gdi32.DeleteObject.argtypes = (handle,)
    gdi32.DeleteDC.argtypes = (handle,)
    return user32, gdi32


def premultiplied_bgra(image) -> bytes:
    """Octets BGRA premultiplies (format attendu par Windows)."""
    premultiplied = image.convert("RGBA").convert("RGBa")
    r, g, b, a = premultiplied.split()
    from PIL import Image

    return Image.merge("RGBA", (b, g, r, a)).tobytes()


class LayeredWindow:
    """Associe une fenetre Tk sans bordure a des images RGBA."""

    def __init__(self, toplevel):
        self.toplevel = toplevel
        toplevel.update_idletasks()
        self.user32, self.gdi32 = _api()
        frame = toplevel.wm_frame()
        self.hwnd = int(frame, 16) if frame else toplevel.winfo_id()
        style = self.user32.GetWindowLongPtrW(self.hwnd, GWL_EXSTYLE)
        self.user32.SetWindowLongPtrW(self.hwnd, GWL_EXSTYLE,
                                      style | WS_EX_LAYERED | WS_EX_TOOLWINDOW)
        self.size = (0, 0)

    def show(self, image) -> bool:
        """Affiche `image` (RGBA). La taille de la fenetre suit celle de l'image."""
        width, height = image.size
        if (width, height) != self.size:
            self.size = (width, height)
            self.toplevel.geometry(f"{width}x{height}")
        data = premultiplied_bgra(image)
        header = _BITMAPINFOHEADER(ctypes.sizeof(_BITMAPINFOHEADER), width, -height,
                                   1, 32, 0, 0, 0, 0, 0, 0)
        screen = self.user32.GetDC(None)
        memory = self.gdi32.CreateCompatibleDC(screen)
        bits = ctypes.c_void_p()
        bitmap = self.gdi32.CreateDIBSection(memory, ctypes.byref(header), 0,
                                             ctypes.byref(bits), None, 0)
        if not bitmap:
            self.gdi32.DeleteDC(memory)
            self.user32.ReleaseDC(None, screen)
            return False
        ctypes.memmove(bits, data, len(data))
        previous = self.gdi32.SelectObject(memory, bitmap)
        ok = self.user32.UpdateLayeredWindow(
            self.hwnd, screen, None, ctypes.byref(_SIZE(width, height)), memory,
            ctypes.byref(_POINT(0, 0)), 0,
            ctypes.byref(_BLEND(AC_SRC_OVER, 0, 255, AC_SRC_ALPHA)), ULW_ALPHA)
        self.gdi32.SelectObject(memory, previous)
        self.gdi32.DeleteObject(bitmap)
        self.gdi32.DeleteDC(memory)
        self.user32.ReleaseDC(None, screen)
        return bool(ok)


__all__ = ["supported", "enable_dpi_awareness", "LayeredWindow", "premultiplied_bgra"]
