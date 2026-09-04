"""Persistent file logging: tee stdout/stderr to logs/agent-YYYY-MM-DD.log.

Modules use print() — instead of converting them to the logging module,
we intercept the streams so each line goes to both the console and today's
log file. Rolls over at local midnight; files older than BACKUP_COUNT days
are deleted. Under pythonw (avvia_agente.bat) stdout is None and logs would
be lost entirely; here they still land on disk.
"""

import glob
import io
import logging
import os
import sys
from datetime import datetime

LOG_DIR = "logs"
BACKUP_COUNT = 30  # days to keep

_installed = False


class _DailyFileHandler(logging.Handler):
    """Write to logs/agent-YYYY-MM-DD.log; open a new file at midnight."""

    def __init__(self, log_dir: str, backup_count: int = BACKUP_COUNT):
        super().__init__()
        self.log_dir = log_dir
        self.backup_count = backup_count
        self._day: str | None = None
        self._stream: io.TextIOWrapper | None = None

    def _path_for(self, day: str) -> str:
        return os.path.join(self.log_dir, f"agent-{day}.log")

    def _ensure_stream(self) -> None:
        day = datetime.now().strftime("%Y-%m-%d")
        if day == self._day and self._stream is not None:
            return
        if self._stream is not None:
            try:
                self._stream.close()
            except OSError:
                pass
            self._stream = None
        self._day = day
        path = self._path_for(day)
        self._stream = open(path, "a", encoding="utf-8")
        self._prune()

    def _prune(self) -> None:
        files = sorted(glob.glob(os.path.join(self.log_dir, "agent-*.log")))
        for old in files[: max(0, len(files) - self.backup_count)]:
            try:
                os.remove(old)
            except OSError:
                pass

    def emit(self, record: logging.LogRecord) -> None:
        try:
            self._ensure_stream()
            assert self._stream is not None
            self._stream.write(self.format(record) + "\n")
            self._stream.flush()
        except Exception:
            self.handleError(record)

    def close(self) -> None:
        try:
            if self._stream is not None:
                self._stream.close()
                self._stream = None
        finally:
            super().close()


class _Tee(io.TextIOBase):
    def __init__(self, original, logger: logging.Logger, level: int):
        self._orig = original
        self._logger = logger
        self._level = level
        self._buf = ""

    def write(self, s: str) -> int:
        if self._orig is not None:
            try:
                self._orig.write(s)
            except Exception:
                pass
        self._buf += s
        while "\n" in self._buf:
            line, self._buf = self._buf.split("\n", 1)
            if line.strip():
                try:
                    self._logger.log(self._level, line)
                except Exception:
                    pass
        return len(s)

    def flush(self) -> None:
        if self._orig is not None:
            try:
                self._orig.flush()
            except Exception:
                pass

    @property
    def encoding(self) -> str:
        return getattr(self._orig, "encoding", None) or "utf-8"

    def isatty(self) -> bool:
        try:
            return bool(self._orig and self._orig.isatty())
        except Exception:
            return False


def _migrate_legacy_log() -> None:
    """If logs/agent.log still exists, fold it into today's daily file."""
    legacy = os.path.join(LOG_DIR, "agent.log")
    if not os.path.isfile(legacy):
        return
    today = os.path.join(LOG_DIR, f"agent-{datetime.now().strftime('%Y-%m-%d')}.log")
    try:
        if not os.path.exists(today):
            os.rename(legacy, today)
        else:
            with open(legacy, encoding="utf-8", errors="replace") as src, open(
                today, "a", encoding="utf-8"
            ) as dst:
                dst.write(src.read())
            os.remove(legacy)
    except OSError:
        pass


def setup() -> None:
    """Idempotent: install the stdout/stderr tee once."""
    global _installed
    if _installed:
        return
    try:
        os.makedirs(LOG_DIR, exist_ok=True)
        _migrate_legacy_log()
        handler = _DailyFileHandler(LOG_DIR, backup_count=BACKUP_COUNT)
        handler.setFormatter(
            logging.Formatter("%(asctime)s %(message)s", datefmt="%Y-%m-%d %H:%M:%S")
        )
        logger = logging.getLogger("tube_assistant")
        logger.setLevel(logging.INFO)
        logger.propagate = False
        logger.handlers.clear()
        logger.addHandler(handler)
        sys.stdout = _Tee(sys.stdout, logger, logging.INFO)
        sys.stderr = _Tee(sys.stderr, logger, logging.ERROR)
        _installed = True
    except OSError:
        # disk/permissions: better to run without file logs than without the agent
        pass
