"""Model Windows thread enumeration without depending on snapshot ordering."""
import ctypes
from types import SimpleNamespace

import pytest

from web_bridge.execution.processes import WindowsGroup


class Function:
    def __init__(self, callback): self.callback = callback
    def __call__(self, *args): return self.callback(*args)


class Kernel:
    def __init__(self, threads):
        self.threads = threads
        self.counts = {thread: count for thread, owner, count in threads}
        self.resumed = []
        self.closed = []
        self.index = 0
        self.CreateJobObjectW = Function(lambda *args: 100)
        self.SetInformationJobObject = Function(lambda *args: True)
        self.AssignProcessToJobObject = Function(lambda *args: True)
        self.CloseHandle = Function(lambda handle: self.closed.append(handle))
        self.TerminateJobObject = Function(lambda *args: True)
        self.CreateToolhelp32Snapshot = Function(lambda *args: 200)
        self.Thread32First = Function(self.first)
        self.Thread32Next = Function(self.next)
        self.OpenThread = Function(lambda access, inherit, thread: thread)
        self.ResumeThread = Function(self.resume)

    def fill(self, pointer):
        if self.index >= len(self.threads): return False
        thread, owner, count = self.threads[self.index]
        pointer._obj.thread, pointer._obj.owner = thread, owner
        return True

    def first(self, snapshot, pointer):
        self.index = 0
        return self.fill(pointer)

    def next(self, snapshot, pointer):
        self.index += 1
        return self.fill(pointer)

    def resume(self, thread):
        self.resumed.append(thread)
        previous = self.counts[thread]
        self.counts[thread] = max(0, previous-1)
        return previous


@pytest.mark.parametrize('helper_count', [0, 1])
def test_primary_thread_runs_when_another_owned_thread_is_enumerated_first(monkeypatch, helper_count):
    kernel = Kernel([(10, 9, 1), (20, 7, helper_count), (30, 7, 1)])
    monkeypatch.setattr(ctypes, 'WinDLL', lambda *args, **kwargs: kernel, raising=False)
    group = WindowsGroup(SimpleNamespace(pid=7, _handle=50))
    try:
        assert kernel.counts[30] == 0, 'The original command must not remain suspended.'
        assert 10 not in kernel.resumed, 'Unrelated process threads must remain untouched.'
        assert kernel.resumed.count(30) == 1
    finally: group.close()
    assert {20, 30, 100, 200}.issubset(kernel.closed)


def test_external_suspend_count_is_not_removed_or_reported_as_running(monkeypatch):
    kernel = Kernel([(30, 7, 2)])
    monkeypatch.setattr(ctypes, 'WinDLL', lambda *args, **kwargs: kernel, raising=False)
    with pytest.raises(OSError, match='resume suspended'):
        WindowsGroup(SimpleNamespace(pid=7, _handle=50))
    assert kernel.counts[30] == 1
    assert kernel.resumed == [30]
    assert {30, 100, 200}.issubset(kernel.closed)
