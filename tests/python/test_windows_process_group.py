"""Validate Windows Job Object ownership and primary-thread resumption."""
import ctypes

import pytest

from web_bridge.execution.processes import WindowsGroup, WindowsCreateProcessProxy


class Function:
    def __init__(self, callback):
        self.callback = callback

    def __call__(self, *args):
        return self.callback(*args)


class Kernel:
    def __init__(self, assign=True, previous=1):
        self.closed = []
        self.terminated = []
        self.resumed = []
        self.events = []
        self.CreateJobObjectW = Function(lambda *args: 100)
        self.SetInformationJobObject = Function(lambda *args: True)
        self.AssignProcessToJobObject = Function(self.assign)
        self.CloseHandle = Function(self.closed.append)
        self.TerminateJobObject = Function(lambda handle, code: self.terminated.append((handle, code)))
        self.ResumeThread = Function(self.resume)
        self.allowed = assign
        self.previous = previous

    def assign(self, job, process):
        self.events.append(('assign', job, process))
        return self.allowed

    def resume(self, thread):
        self.resumed.append(thread)
        self.events.append(('resume', thread))
        return self.previous


class Winapi:
    def __init__(self):
        self.flags = []
        self.closed = []
        self.terminated = []

    def CreateProcess(self, *args):
        self.flags.append(args[5])
        return 50, 60, 7, 8

    def TerminateProcess(self, handle, exit_code):
        self.terminated.append((handle, exit_code))

    def CloseHandle(self, handle):
        self.closed.append(handle)


def set_kernel(monkeypatch, kernel):
    monkeypatch.setattr(ctypes, 'WinDLL', lambda *args, **kwargs: kernel, raising=False)


def test_windows_group_resumes_exact_primary_thread_after_assignment(monkeypatch):
    kernel = Kernel()
    set_kernel(monkeypatch, kernel)
    group = WindowsGroup(50, 60)
    assert kernel.events == [('assign', 100, 50), ('resume', 60)]
    group.kill()
    assert kernel.terminated == [(100, 1)]
    group.close()
    assert kernel.closed == [100]


@pytest.mark.parametrize('previous', [0, 2, 0xFFFFFFFF])
def test_invalid_primary_thread_suspend_count_fails_closed(monkeypatch, previous):
    kernel = Kernel(previous=previous)
    set_kernel(monkeypatch, kernel)
    with pytest.raises(OSError, match='primary Windows thread'):
        WindowsGroup(50, 60)
    assert kernel.resumed == [60]
    assert kernel.closed == [100]


def test_assignment_failure_never_resumes(monkeypatch):
    kernel = Kernel(assign=False)
    set_kernel(monkeypatch, kernel)
    with pytest.raises(OSError, match='establish owned Windows process group'):
        WindowsGroup(50, 60)
    assert kernel.resumed == []
    assert kernel.closed == [100]


def test_process_proxy_suspends_and_binds_before_returning(monkeypatch):
    kernel = Kernel()
    set_kernel(monkeypatch, kernel)
    native = Winapi()
    proxy = WindowsCreateProcessProxy(native)
    original = [None, 'cmd.exe /d /c echo ok', None, None, False, 0x200, None, None, None]
    assert proxy.CreateProcess(*original) == (50, 60, 7, 8)
    assert native.flags == [0x204]
    assert kernel.events == [('assign', 100, 50), ('resume', 60)]
    proxy.group.close()


def test_proxy_terminates_unpublished_child_on_assignment_failure(monkeypatch):
    kernel = Kernel(assign=False)
    set_kernel(monkeypatch, kernel)
    native = Winapi()
    proxy = WindowsCreateProcessProxy(native)
    with pytest.raises(OSError, match='establish owned Windows process group'):
        proxy.CreateProcess(None, 'cmd', None, None, False, 0, None, None, None)
    assert native.terminated == [(50, 1)]
    assert native.closed == [60, 50]
    assert kernel.resumed == []


def test_proxy_does_not_start_unsupported_creation_call(monkeypatch):
    native = Winapi()
    proxy = WindowsCreateProcessProxy(native)
    with pytest.raises(OSError, match='creation arguments'):
        proxy.CreateProcess(None)
    assert native.flags == []


def test_proxy_terminates_unpublished_child_when_resume_fails(monkeypatch):
    kernel = Kernel(previous=0)
    set_kernel(monkeypatch, kernel)
    native = Winapi()
    proxy = WindowsCreateProcessProxy(native)
    with pytest.raises(OSError, match='primary Windows thread'):
        proxy.CreateProcess(None, 'powershell.exe', None, None, False, 0, None, None, None)
    assert kernel.events == [('assign', 100, 50), ('resume', 60)]
    assert native.terminated == [(50, 1)]
    assert native.closed == [60, 50]
    assert kernel.closed == [100]
