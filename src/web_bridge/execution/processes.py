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

        # Resume the Job Object's process: thread enumeration can leave its primary thread suspended.
        native = ctypes.WinDLL("ntdll")
        resume_process = native.NtResumeProcess
        resume_process.argtypes = [w.HANDLE]
        resume_process.restype = ctypes.c_long  # NTSTATUS
        status = resume_process(int(process._handle))
        if status != 0:
            self.close()
            raise OSError(
                "Unable to resume owned Windows command "
                f"(NTSTATUS 0x{status & 0xFFFFFFFF:08x})."
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


def kill_posix_group(pid):
    try:
        os.killpg(pid, signal.SIGKILL)
    except ProcessLookupError:
        pass
