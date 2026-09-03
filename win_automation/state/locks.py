"""
Cross-process and cross-thread file locking mechanism for Windows and POSIX.
Uses msvcrt.locking on Windows with non-blocking retry loop, fcntl on POSIX,
and threading.RLock for process-internal synchronization.
"""

from __future__ import annotations

import os
import sys
import time
import threading
from typing import Optional

# Platform-specific lock imports
_IS_WINDOWS = sys.platform == "win32"
if _IS_WINDOWS:
    import msvcrt
else:
    try:
        import fcntl
    except ImportError:
        fcntl = None


class FileLockTimeoutError(TimeoutError):
    """Raised when file lock acquisition exceeds the specified timeout."""
    pass


class _PathLockInfo:
    def __init__(self) -> None:
        self.thread_lock = threading.RLock()
        self.owner_thread: Optional[int] = None
        self.depth: int = 0
        self.file_obj: Any = None


class FileLock:
    """
    A robust, reentrant cross-process file lock.
    Combines threading.RLock for intra-process thread-safety with
    operating system file locks (msvcrt on Windows, fcntl on POSIX)
    for inter-process safety.
    """

    _registry_lock = threading.Lock()
    _path_info: dict[str, _PathLockInfo] = {}

    def __init__(self, lock_file: str, timeout: float = 10.0, poll_interval: float = 0.002):
        self.lock_file = os.path.abspath(lock_file)
        self.timeout = float(timeout)
        self.poll_interval = float(poll_interval)
        self._holding_count = 0

        # Retrieve or create lock state info for this canonical path
        with self._registry_lock:
            if self.lock_file not in self._path_info:
                self._path_info[self.lock_file] = _PathLockInfo()
            self._info = self._path_info[self.lock_file]

    def acquire(self, timeout: Optional[float] = None) -> bool:
        """
        Acquire the file lock within the given timeout (in seconds).
        Returns True if acquired, raises FileLockTimeoutError on timeout.
        """
        effective_timeout = self.timeout if timeout is None else float(timeout)
        start_time = time.monotonic()
        curr_thread = threading.get_ident()

        # Step 1: Intra-process lock
        thread_acquired = self._info.thread_lock.acquire(timeout=effective_timeout)
        if not thread_acquired:
            raise FileLockTimeoutError(
                f"Timed out after {effective_timeout:.2f}s waiting for intra-process lock on {self.lock_file}"
            )

        try:
            # Reentrant check: if the current thread already holds the OS lock on this path
            if self._info.owner_thread == curr_thread and self._info.depth > 0:
                self._info.depth += 1
                self._holding_count += 1
                return True

            # Ensure parent directory exists
            lock_dir = os.path.dirname(self.lock_file)
            if lock_dir:
                os.makedirs(lock_dir, exist_ok=True)

            # Step 2: Open lock file
            if self._info.file_obj is None or self._info.file_obj.closed:
                self._info.file_obj = open(self.lock_file, "a+b")

            fd = self._info.file_obj.fileno()

            # Step 3: Inter-process lock loop with timeout
            while True:
                try:
                    if _IS_WINDOWS:
                        self._info.file_obj.seek(0, os.SEEK_SET)
                        msvcrt.locking(fd, msvcrt.LK_NBLCK, 1)
                    elif fcntl is not None:
                        fcntl.flock(fd, fcntl.LOCK_EX | fcntl.LOCK_NB)
                    # Acquired successfully
                    self._info.owner_thread = curr_thread
                    self._info.depth = 1
                    self._holding_count += 1
                    return True
                except (OSError, PermissionError):
                    # Check timeout
                    elapsed = time.monotonic() - start_time
                    if elapsed >= effective_timeout:
                        raise FileLockTimeoutError(
                            f"Timed out after {effective_timeout:.2f}s waiting for inter-process lock on {self.lock_file}"
                        )
                    # Adaptive sleep before retry
                    time.sleep(min(self.poll_interval, max(0.001, effective_timeout - elapsed)))
        except Exception:
            if self._info.depth == 0 and self._info.file_obj:
                try:
                    self._info.file_obj.close()
                except Exception:
                    pass
                self._info.file_obj = None
            self._info.thread_lock.release()
            raise

    def release(self) -> None:
        """Release the file lock."""
        if self._holding_count == 0:
            return

        self._holding_count -= 1
        self._info.depth -= 1
        if self._info.depth == 0:
            try:
                if self._info.file_obj and not self._info.file_obj.closed:
                    fd = self._info.file_obj.fileno()
                    try:
                        if _IS_WINDOWS:
                            self._info.file_obj.seek(0, os.SEEK_SET)
                            msvcrt.locking(fd, msvcrt.LK_UNLCK, 1)
                        elif fcntl is not None:
                            fcntl.flock(fd, fcntl.LOCK_UN)
                    except (OSError, ValueError):
                        pass
                    self._info.file_obj.close()
                    self._info.file_obj = None
                self._info.owner_thread = None
            finally:
                self._info.thread_lock.release()
        else:
            self._info.thread_lock.release()

    def is_locked(self) -> bool:
        """Check if currently locked by this instance."""
        return self._holding_count > 0

    def __enter__(self) -> FileLock:
        self.acquire()
        return self

    def __exit__(self, exc_type, exc_val, exc_tb) -> None:
        self.release()

    def __del__(self) -> None:
        try:
            while self._holding_count > 0:
                self.release()
        except Exception:
            pass
