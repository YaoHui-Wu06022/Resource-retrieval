"""进程内按主机限制并发与请求间隔的调度门。"""

import threading
import time
from urllib.parse import urlparse


DEFAULT_MAX_WORKERS = 8
DEFAULT_HOST_MAX_WORKERS = 1
DEFAULT_HOST_MIN_INTERVAL = 0.3


def extract_url_host(source_url: str) -> str:
    """从网址中提取小写主机名。"""
    return (urlparse(str(source_url or '')).hostname or '').lower()


class HostRequestGate:
    """按主机串行或限量调度请求，并保持同一主机的最小请求间隔。"""

    def __init__(
        self,
        host_max_workers=DEFAULT_HOST_MAX_WORKERS,
        min_interval=DEFAULT_HOST_MIN_INTERVAL,
        clock=time.monotonic,
        sleeper=time.sleep,
    ):
        self._host_max_workers = max(1, int(host_max_workers or 1))
        self._min_interval = max(0.0, float(min_interval or 0.0))
        self._clock = clock
        self._sleeper = sleeper
        self._lock = threading.Lock()
        self._semaphores = {}
        self._last_start_times = {}

    def acquire(self, host: str) -> None:
        """占用一个同主机并发名额，并等待到允许的请求时刻。"""
        if not host:
            return
        with self._lock:
            semaphore = self._semaphores.get(host)
            if semaphore is None:
                semaphore = threading.Semaphore(self._host_max_workers)
                self._semaphores[host] = semaphore
        semaphore.acquire()
        with self._lock:
            now = self._clock()
            scheduled_start = max(
                now, self._last_start_times.get(host, now)
            )
            self._last_start_times[host] = (
                scheduled_start + self._min_interval
            )
            wait_seconds = scheduled_start - now
        if wait_seconds > 0:
            self._sleeper(wait_seconds)

    def release(self, host: str) -> None:
        """释放一个同主机并发名额。"""
        if not host:
            return
        with self._lock:
            semaphore = self._semaphores.get(host)
        if semaphore is not None:
            semaphore.release()
