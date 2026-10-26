"""Retain command descendants independently of their original process leader."""

import os
import signal
import threading


class WindowsGroup:
    def __init__(self, process_handle, primary_thread_handle):
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
            or not api.AssignProcessToJobObject(self.handle, int(process_handle))
        ):
            self.close()
            raise OSError("Unable to establish owned Windows process group.")

        api.ResumeThread.argtypes = [w.HANDLE]
        api.ResumeThread.restype = w.DWORD
        previous = api.ResumeThread(int(primary_thread_handle))
        if previous != 1:
            self.close()
            raise OSError(
                "Unable to resume the command's primary Windows thread "
                f"(previous suspend count: {previous})."
            )

    def kill(self):
        with self.lock:
            if self.handle:
                self.api.TerminateJobObject(self.handle, 1)

    def close(self):
        with self.lock:
            if self.handle:
                self.api.CloseHandle(self.handle)
                self.handle = None


class WindowsCreateProcessProxy:
    def __init__(self, winapi):
        self.winapi = winapi
        self.group = None

    def __getattr__(self, key):
        return getattr(self.winapi, key)

    def CreateProcess(self, *args, **kwargs):
        params = list(args)
        if len(params) < 6:
            raise OSError("Unsupported Windows subprocess creation arguments.")
        params[5] = int(params[5]) | 0x4
        process_handle, thread_handle, pid, tid = self.winapi.CreateProcess(
            *params, **kwargs
        )
        try:
            self.group = WindowsGroup(process_handle, thread_handle)
        except BaseException:
            try:
                self.winapi.TerminateProcess(process_handle, 1)
            except OSError:
                pass
            finally:
                self.winapi.CloseHandle(thread_handle)
                self.winapi.CloseHandle(process_handle)
            raise
        return process_handle, thread_handle, pid, tid


def spawn_owned_windows(argv, **kwargs):
    import subprocess
    import types

    original = subprocess.Popen._execute_child
    if not isinstance(original, types.FunctionType):
        raise OSError("Windows process creation is unsupported by this Python runtime.")
    winapi = original.__globals__.get("_winapi")
    if not winapi or "CreateProcess" not in original.__code__.co_names:
        raise OSError("Windows process creation cannot be safely intercepted.")
    proxy = WindowsCreateProcessProxy(winapi)
    globals_copy = dict(original.__globals__)
    globals_copy["_winapi"] = proxy
    execute = types.FunctionType(
        original.__code__, globals_copy, original.__name__,
        original.__defaults__, original.__closure__,
    )
    execute.__kwdefaults__ = original.__kwdefaults__

    class OwnedPopen(subprocess.Popen):
        _execute_child = execute

    try:
        process = OwnedPopen(argv, **kwargs)
        if proxy.group is None:
            raise OSError("Windows command was not assigned to an owned process group.")
        return process, proxy.group
    except BaseException:
        if proxy.group is not None:
            proxy.group.close()
        raise


def kill_posix_group(pid):
    try:
        os.killpg(pid, signal.SIGKILL)
    except ProcessLookupError:
        pass
