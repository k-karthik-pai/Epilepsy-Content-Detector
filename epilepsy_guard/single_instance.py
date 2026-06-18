from __future__ import annotations

import ctypes
import sys
from ctypes import wintypes


ERROR_ALREADY_EXISTS = 183


class SingleInstanceLock:
    def __init__(self, name: str) -> None:
        self._handle = None
        self._kernel32 = None
        if sys.platform != "win32":
            raise RuntimeError("Single-instance locking currently requires Windows.")

        self._kernel32 = ctypes.WinDLL("kernel32", use_last_error=True)
        self._kernel32.CreateMutexW.argtypes = [wintypes.LPVOID, wintypes.BOOL, wintypes.LPCWSTR]
        self._kernel32.CreateMutexW.restype = wintypes.HANDLE
        self._kernel32.CloseHandle.argtypes = [wintypes.HANDLE]
        self._kernel32.CloseHandle.restype = wintypes.BOOL
        self._handle = self._kernel32.CreateMutexW(None, False, name)
        if not self._handle:
            raise ctypes.WinError(ctypes.get_last_error())

        self.acquired = ctypes.get_last_error() != ERROR_ALREADY_EXISTS
        if not self.acquired:
            self.close()

    def close(self) -> None:
        if not self._handle or not self._kernel32:
            return
        self._kernel32.CloseHandle(self._handle)
        self._handle = None

    def __enter__(self) -> SingleInstanceLock:
        return self

    def __exit__(self, _exc_type, _exc, _traceback) -> None:
        self.close()

    def __del__(self) -> None:
        self.close()
