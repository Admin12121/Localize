"""Supervise optional Chromium in a disposable process, including unresponsive JS."""
import concurrent.futures
import multiprocessing
import os
import queue
import signal
import threading


def child(connection, targets, allow_private, min_interval, pins):
    if os.name == 'posix': os.setsid()
    from web_bridge.web.client import Bridge
    bridge = Bridge(targets, allow_private=allow_private, min_interval=min_interval)
    bridge._pins = pins
    bridge._browser_queue = queue.Queue(maxsize=1)
    threading.Thread(target=bridge._browser_loop, daemon=True).start()
    try:
        while True:
            task = connection.recv()
            future = concurrent.futures.Future()
            bridge._browser_queue.put((future, *task))
            try: connection.send({'result': future.result(timeout=40)})
            except concurrent.futures.TimeoutError:
                connection.send({'error': 'Browser execution timed out; sessions were reset', 'reset': True})
            except Exception as exc: connection.send({'error': str(exc)})
    finally: connection.close()


class BrowserProcess:
    def __init__(self, targets, allow_private, min_interval, pins):
        self.config = (targets, allow_private, min_interval, pins)
        self.process = None
        self.lock = threading.Lock()

    def close(self):
        if not self.process: return
        if self.process.is_alive():
            if os.name == 'posix':
                try: os.killpg(self.process.pid, signal.SIGKILL)
                except ProcessLookupError: self.process.kill()
            else: self.process.kill()
        self.process.join(timeout=3)
        self.connection.close()
        self.process = None

    def call(self, *task):
        from web_bridge.web.client import BridgeError
        if not self.lock.acquire(timeout=1): raise BridgeError('Browser is busy')
        try:
            if self.process is None or not self.process.is_alive():
                self.close()
                ctx = multiprocessing.get_context('spawn')
                self.connection, child_connection = ctx.Pipe()
                self.process = ctx.Process(target=child, args=(child_connection, *self.config), daemon=True)
                self.process.start()
                child_connection.close()
            self.connection.send(task)
            if not self.connection.poll(45):
                self.close()
                raise BridgeError('Browser deadline exceeded; browser process and sessions were reset')
            response = self.connection.recv()
            if response.get('reset'): self.close()
            if 'error' in response: raise BridgeError(response['error'])
            return response['result']
        except (EOFError, OSError) as exc:
            self.close()
            raise BridgeError('Browser worker failed; retry to create a fresh session') from exc
        finally: self.lock.release()
