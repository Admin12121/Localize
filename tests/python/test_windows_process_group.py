"""Validate owned Windows process creation without depending on thread ordering."""
import ctypes
from types import SimpleNamespace

import pytest

from web_bridge.execution.processes import WindowsGroup


class Function:
    def __init__(self, callback):
        self.callback = callback

    def __call__(self, *args):
        return self.callback(*args)


class Kernel:
    def __init__(self, assign=True):
        self.closed = []
        self.terminated = []
        self.CreateJobObjectW = Function(lambda *args: 100)
        self.SetInformationJobObject = Function(lambda *args: True)
        self.AssignProcessToJobObject = Function(lambda *args: assign)
        self.CloseHandle = Function(self.closed.append)
        self.TerminateJobObject = Function(lambda handle, code: self.terminated.append((handle, code)))


class Native:
    def __init__(self, status=0):
        self.calls = []
        self.status = status
        self.NtResumeProcess = Function(self.resume)

    def resume(self, handle):
        self.calls.append(handle)
        return self.status


def dll_patch(monkeypatch, kernel, native):
    def dll(name, **kwargs):
        if name == 'kernel32':
            return kernel
        if name == 'ntdll':
            return native
        raise AssertionError('Unexpected Windows DLL: ' + name)
    monkeypatch.setattr(ctypes, 'WinDLL', dll, raising=False)


def test_windows_group_resumes_the_owned_process_only_after_job_assignment(monkeypatch):
    kernel, native = Kernel(), Native()
    dll_patch(monkeypatch, kernel, native)
    group = WindowsGroup(SimpleNamespace(pid=7, _handle=50))
    assert native.calls == [50], 'Resume the process handle, not arbitrary snapshot threads.'
    group.kill()
    assert kernel.terminated == [(100, 1)]
    group.close()
    assert kernel.closed == [100]


def test_windows_group_fails_closed_if_process_resume_fails(monkeypatch):
    kernel, native = Kernel(), Native(-1073741823)  # NTSTATUS 0xC0000001
    dll_patch(monkeypatch, kernel, native)
    with pytest.raises(OSError, match=r'NTSTATUS 0xc0000001'):
        WindowsGroup(SimpleNamespace(pid=7, _handle=50))
    assert native.calls == [50]
    assert kernel.closed == [100], 'Closing job terminates the unstarted process.'


def test_windows_group_does_not_resume_if_job_assignment_fails(monkeypatch):
    kernel, native = Kernel(assign=False), Native()
    dll_patch(monkeypatch, kernel, native)
    with pytest.raises(OSError, match='establish owned Windows process group'):
        WindowsGroup(SimpleNamespace(pid=7, _handle=50))
    assert native.calls == []
    assert kernel.closed == [100]
