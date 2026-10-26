"""Retain command descendants independently of their original process leader."""

import os
import signal
import threading


class WindowsGroup:
    def __init__(self, process):
        import ctypes
        from ctypes import wintypes as w

        self.lock = threading.Lock()
        self.api = ctypes.WinDLL("kernel32", use_last_error=True)
        self.handle = None

        class BASIC(ctypes.Structure):
            _fields_ = [
                ("per_process", ctypes.c_int64),
                ("per_job", ctypes.c_int64),
                ("flags", w.DWORD),
                ("min_ws", ctypes.c_size_t),
                ("max_ws", ctypes.c_size_t),
                ("active", w.DWORD),
                ("affinity", ctypes.c_size_t),
                ("priority", w.DWORD),
                ("scheduling", w.DWORD),
            ]

        class IO(ctypes.Structure):
            _fields_ = [
                (name, ctypes.c_uint64)
                for name in (
                    "reads",
                    "writes",
                    "other",
                    "read_bytes",
                    "write_bytes",
                    "other_bytes",
                )
            ]

        class LIMITS(ctypes.Structure):
            _fields_ = [
                ("basic", BASIC),
                ("io", IO),
                ("process_memory", ctypes.c_size_t),
                ("job_memory", ctypes.c_size_t),
                ("peak_process", ctypes.c_size_t),
                ("peak_job", ctypes.c_size_t),
            ]

        api = self.api
        api.CreateJobObjectW.argtypes = [ctypes.c_void_p, w.LPCWSTR]
        api.CreateJobObjectW.restype = w.HANDLE
        api.CloseHandle.argtypes = [w.HANDLE]
        api.SetInformationJobObject.argtypes = [
            w.HANDLE,
            ctypes.c_int,
            ctypes.c_void_p,
            w.DWORD,
        ]
        api.AssignProcessToJobObject.argtypes = [w.HANDLE, w.HANDLE]
        api.TerminateJobObject.argtypes = [w.HANDLE, w.UINT]
        self.handle = api.CreateJobObjectW(None, None)
        limits = LIMITS()
        limits.basic.flags = 0x2000
        if (
            not self.handle
            or not api.SetInformationJobObject(
                self.handle, 9, ctypes.byref(limits), ctypes.sizeof(limits)
            )
            or not api.AssignProcessToJobObject(self.handle, int(process._handle))
        ):
            self.close()
            raise OSError("Unable to establish owned Windows process group.")

        class THREAD(ctypes.Structure):
            _fields_ = [
                ("size", w.DWORD),
                ("usage", w.DWORD),
                ("thread", w.DWORD),
                ("owner", w.DWORD),
                ("base", w.LONG),
                ("delta", w.LONG),
                ("flags", w.DWORD),
            ]

        api.CreateToolhelp32Snapshot.argtypes = [w.DWORD, w.DWORD]
        api.CreateToolhelp32Snapshot.restype = w.HANDLE
        api.Thread32First.argtypes = [w.HANDLE, ctypes.POINTER(THREAD)]
        api.Thread32Next.argtypes = [w.HANDLE, ctypes.POINTER(THREAD)]
        api.OpenThread.argtypes = [w.DWORD, w.BOOL, w.DWORD]
        api.OpenThread.restype = w.HANDLE
        api.ResumeThread.argtypes = [w.HANDLE]
        snapshot = api.CreateToolhelp32Snapshot(4, 0)
        entry = THREAD()
        entry.size = ctypes.sizeof(entry)
        resumed = False
        try:
            ok = api.Thread32First(snapshot, ctypes.byref(entry))
            while ok:
                if entry.owner == process.pid:
                    thread = api.OpenThread(2, False, entry.thread)
                    if thread:
                        try:
                            resumed = api.ResumeThread(thread) != 0xFFFFFFFF
                        finally:
                            api.CloseHandle(thread)
                    break
                ok = api.Thread32Next(snapshot, ctypes.byref(entry))
        finally:
            api.CloseHandle(snapshot)
        if not resumed:
            self.close()
            raise OSError("Unable to resume owned command.")

    def kill(self):
        with self.lock:
            if self.handle:
                self.api.TerminateJobObject(self.handle, 1)

    def close(self):
        with self.lock:
            if self.handle:
                self.api.CloseHandle(self.handle)
                self.handle = None


def kill_posix_group(pid):
    try:
        os.killpg(pid, signal.SIGKILL)
    except ProcessLookupError:
        pass
