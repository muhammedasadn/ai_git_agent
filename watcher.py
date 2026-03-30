"""
watcher.py
==========
File system watcher — monitors repo for changes and triggers the agent.

Two modes:
  1. Foreground (--watch):   runs in terminal, Ctrl+C to stop
  2. Background (--daemon):  runs forever, writes to log file, never exits

Key improvements over v1:
  - ASCII-safe log messages (no broken unicode in cterm)
  - Tee logging: output goes to BOTH console and log file
  - Smarter debounce: accumulates multiple rapid saves before triggering
  - Stats tracking: commits made, files watched, uptime
  - Handles agent errors gracefully (logs and continues)
"""

import time
import os
from datetime import datetime
from typing import Callable, Optional


# ─────────────────────────────────────────────
# Snapshot helpers
# ─────────────────────────────────────────────

SKIP_DIRS = {
    ".git", "__pycache__", "node_modules", "venv", ".env",
    "build", "dist", ".next", ".nuxt", "target", ".tox",
    ".pytest_cache", ".mypy_cache"
}

SKIP_FILES = {
    ".agent_pid", ".agent_log.txt", ".agent_state.json"
}


def _snapshot(path: str) -> dict:
    """
    Build {relative_path: (mtime, size)} for every tracked file.
    Skips .git, node_modules, build dirs, and agent internal files.
    """
    snap = {}
    for root, dirs, files in os.walk(path):
        dirs[:] = [d for d in dirs if d not in SKIP_DIRS]
        for f in files:
            if f in SKIP_FILES:
                continue
            full = os.path.join(root, f)
            rel  = os.path.relpath(full, path)
            try:
                st = os.stat(full)
                snap[rel] = (st.st_mtime, st.st_size)
            except OSError:
                pass
    return snap


def _changed(old: dict, new: dict) -> bool:
    if set(old) != set(new):
        return True
    for k in old:
        if old[k] != new.get(k):
            return True
    return False


def _describe(old: dict, new: dict) -> str:
    added    = len(set(new) - set(old))
    deleted  = len(set(old) - set(new))
    modified = sum(1 for k in set(old) & set(new) if old[k] != new[k])
    parts = []
    if added:    parts.append(f"{added} new")
    if deleted:  parts.append(f"{deleted} deleted")
    if modified: parts.append(f"{modified} modified")
    return ", ".join(parts) if parts else "changes"


# ─────────────────────────────────────────────
# Tee Logger: writes to console + log file
# ─────────────────────────────────────────────

class TeeLogger:
    """
    Writes messages to both the terminal AND a log file.
    Used in daemon mode so you can see activity in both places.
    """

    def __init__(self, log_file: str = None, silent: bool = False):
        self.log_file = log_file
        self.silent   = silent   # if True: only write to file, not console

    def _ts(self) -> str:
        return datetime.now().strftime("%H:%M:%S")

    def write(self, message: str, prefix: str = ""):
        ts   = self._ts()
        line = f"[{ts}] {prefix}{message}"

        if not self.silent:
            print(line, flush=True)

        if self.log_file:
            try:
                with open(self.log_file, "a") as f:
                    f.write(line + "\n")
            except Exception:
                pass

    def __call__(self, message: str):
        """Makes TeeLogger callable — compatible with logger=fn usage."""
        self.write(message)

    def event(self, message: str):
        self.write(message, prefix=">> ")

    def ok(self, message: str):
        self.write(message, prefix="[OK] ")

    def warn(self, message: str):
        self.write(message, prefix="[!!] ")

    def err(self, message: str):
        self.write(message, prefix="[XX] ")

    def section(self, title: str):
        line = "-" * 50
        self.write(line)
        self.write(title)
        self.write(line)


# ─────────────────────────────────────────────
# Stats tracker
# ─────────────────────────────────────────────

class WatchStats:
    def __init__(self):
        self.started      = time.time()
        self.cycles       = 0
        self.commits_made = 0
        self.pushes_made  = 0
        self.errors       = 0

    def uptime(self) -> str:
        secs = int(time.time() - self.started)
        h, rem = divmod(secs, 3600)
        m, s   = divmod(rem, 60)
        if h:
            return f"{h}h {m}m {s}s"
        elif m:
            return f"{m}m {s}s"
        return f"{s}s"

    def summary(self) -> str:
        return (
            f"Uptime: {self.uptime()} | "
            f"Cycles: {self.cycles} | "
            f"Commits: {self.commits_made} | "
            f"Pushes: {self.pushes_made} | "
            f"Errors: {self.errors}"
        )


# ─────────────────────────────────────────────
# Main Watcher
# ─────────────────────────────────────────────

class Watcher:
    """
    Repository file watcher. Calls callback(path) when changes are detected.

    Supports two modes:
      - Foreground: runs in terminal until Ctrl+C
      - Background (daemon): runs forever, logs to file
    """

    def __init__(self, config: dict):
        agent_cfg         = config.get("agent", {})
        self.poll_interval = agent_cfg.get("watch_interval_seconds", 10)
        self.debounce      = agent_cfg.get("watch_debounce_seconds", 3)
        self._running      = False
        self.stats         = WatchStats()

    def start(
        self,
        path: str,
        callback: Callable[[str], None],
        logger: Optional[Callable[[str], None]] = None,
        log_file: str = None,
        forever: bool = False,
    ) -> None:
        """
        Start watching the repository.

        Args:
            path:      Repo path to watch
            callback:  Called with (path) when changes detected
            logger:    Log function (defaults to TeeLogger)
            log_file:  Path to write log file (optional)
            forever:   If True, never exit on errors (daemon mode)
        """
        # Set up logger
        if logger is None:
            tee = TeeLogger(log_file=log_file, silent=(log_file is not None and forever))
            log = tee
        else:
            log = logger

        self._running = True

        log("")
        log("Watch mode started")
        log(f"Repo    : {path}")
        log(f"Polling : every {self.poll_interval}s | debounce: {self.debounce}s")
        log("Press Ctrl+C to stop (or use: python main.py --daemon stop)")
        log("")

        # Take initial snapshot
        snapshot = _snapshot(path)
        log(f"Tracking {len(snapshot)} files")
        log("")

        while self._running:
            try:
                time.sleep(self.poll_interval)

                new_snap = _snapshot(path)

                if _changed(snapshot, new_snap):
                    desc = _describe(snapshot, new_snap)
                    log(f"Changes detected: {desc}")
                    log(f"Waiting {self.debounce}s (debounce)...")

                    # Debounce: wait for user to finish saving
                    time.sleep(self.debounce)
                    final_snap = _snapshot(path)
                    snapshot   = final_snap

                    log("Triggering agent workflow...")
                    self.stats.cycles += 1

                    try:
                        callback(path)
                        self.stats.commits_made += 1
                    except KeyboardInterrupt:
                        raise
                    except Exception as e:
                        self.stats.errors += 1
                        log(f"Agent error: {e}")
                        if not forever:
                            raise
                        log("Continuing to watch (daemon mode)...")

                    log("")
                    log(f"Watching... ({self.stats.summary()})")
                    log("")

                else:
                    snapshot = new_snap

            except KeyboardInterrupt:
                if not forever:
                    log("")
                    log("Watch mode stopped by user.")
                    break
                # In daemon mode, ignore Ctrl+C
                log("Caught interrupt — continuing (daemon mode)")

            except Exception as e:
                self.stats.errors += 1
                log(f"Watcher error: {e}")
                if not forever:
                    raise
                log("Recovering in 5s...")
                time.sleep(5)

        self._running = False

    def stop(self):
        """Signal the watcher to stop."""
        self._running = False