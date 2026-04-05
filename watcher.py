"""
watcher.py
==========
File system watcher with 5-minute intelligent batch window.

HOW THE BATCH WINDOW WORKS:
─────────────────────────────
  Old behavior:  detect change → wait 3s debounce → commit immediately
  
  New behavior:  detect FIRST change → open a 5-minute collection window
                 ↓
                 keep accumulating more changes during the window
                 ↓
                 at window end → analyze ALL changes together → ONE smart commit
                 ↓
                 if NO meaningful changes accumulated → skip commit
                 ↓
                 close window → wait for next change → repeat

  This means:
  - You save a.py at 2:00 → window opens, timer starts
  - You save b.py at 2:02 → added to the window
  - You save a.py again at 2:04 → updated in the window  
  - At 2:05 → agent wakes up, sees ALL 3 saves, makes ONE commit
  
  Result: fewer, smarter, more meaningful commits
  Config: "batch_window_seconds": 300   (5 minutes default)
          "batch_window_seconds": 60    (1 minute)
          "batch_window_seconds": 0     (disable, commit immediately)
"""

import time
import os
from datetime import datetime, timedelta
from typing import Callable, Optional


# ─────────────────────────────────────────────
# Skip lists
# ─────────────────────────────────────────────

SKIP_DIRS = {
    ".git", "__pycache__", "node_modules", "venv", ".env",
    "build", "dist", ".next", ".nuxt", "target", ".tox",
    ".pytest_cache", ".mypy_cache", ".idea", ".vscode"
}

SKIP_FILES = {
    ".agent_pid", ".agent_log.txt", ".agent_state.json"
}


# ─────────────────────────────────────────────
# Snapshot helpers
# ─────────────────────────────────────────────

def _snapshot(path: str) -> dict:
    """Build {rel_path: (mtime, size)} snapshot of all tracked files."""
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
    return any(old[k] != new.get(k) for k in old)


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
# Tee Logger
# ─────────────────────────────────────────────

class TeeLogger:
    """Writes to both terminal and log file simultaneously."""

    def __init__(self, log_file: str = None, silent: bool = False):
        self.log_file = log_file
        self.silent   = silent

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
        self.write(message)

    def ok(self, msg):   self.write(msg, "[OK] ")
    def warn(self, msg): self.write(msg, "[!!] ")
    def err(self, msg):  self.write(msg, "[XX] ")


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
        self.skipped      = 0    # windows that opened but had nothing worth committing

    def uptime(self) -> str:
        secs   = int(time.time() - self.started)
        h, rem = divmod(secs, 3600)
        m, s   = divmod(rem, 60)
        if h:   return f"{h}h {m}m"
        if m:   return f"{m}m {s}s"
        return f"{s}s"

    def summary(self) -> str:
        return (
            f"Uptime: {self.uptime()} | Cycles: {self.cycles} | "
            f"Commits: {self.commits_made} | Skipped: {self.skipped} | "
            f"Errors: {self.errors}"
        )


# ─────────────────────────────────────────────
# Batch Window
# ─────────────────────────────────────────────

class BatchWindow:
    """
    Tracks an open collection window.

    Timeline:
      t=0:00  First file change detected → window opens
      t=0:02  More changes → accumulated
      t=5:00  Window expires → commit triggered
      t=5:00  Window resets → waiting for next first-change
    """

    def __init__(self, window_secs: int):
        self.window_secs    = window_secs
        self._open          = False
        self._opened_at     = 0.0
        self._change_count  = 0
        self._first_desc    = ""

    def is_open(self) -> bool:
        return self._open

    def is_expired(self) -> bool:
        if not self._open:
            return False
        return time.time() >= self._opened_at + self.window_secs

    def open(self, desc: str):
        """Open a new window when the first change is detected."""
        self._open         = True
        self._opened_at    = time.time()
        self._change_count = 1
        self._first_desc   = desc

    def record(self):
        """Record another change during an open window."""
        self._change_count += 1

    def close(self):
        """Close the window (called after commit or skip)."""
        self._open         = False
        self._change_count = 0
        self._first_desc   = ""

    def time_remaining(self) -> float:
        if not self._open:
            return 0.0
        return max(0.0, (self._opened_at + self.window_secs) - time.time())

    def elapsed(self) -> float:
        if not self._open:
            return 0.0
        return time.time() - self._opened_at

    def change_count(self) -> int:
        return self._change_count

    def summary(self) -> str:
        return (
            f"{self._change_count} change event(s) over "
            f"{self.elapsed():.0f}s"
        )


# ─────────────────────────────────────────────
# Main Watcher
# ─────────────────────────────────────────────

class Watcher:
    """
    Repository watcher with intelligent batch-window commit strategy.

    Config keys (under "agent" in config.json):
      watch_interval_seconds   How often to poll filesystem (default: 5)
      batch_window_seconds     How long to collect changes before committing (default: 300)
      watch_debounce_seconds   Extra wait after last change in a burst (default: 3)
    """

    def __init__(self, config: dict):
        cfg = config.get("agent", {})
        self.poll_interval  = cfg.get("watch_interval_seconds",  5)
        self.batch_window   = cfg.get("batch_window_seconds",    300)   # 5 minutes
        self.debounce       = cfg.get("watch_debounce_seconds",  3)
        self._running       = False
        self.stats          = WatchStats()

    def start(
        self,
        path: str,
        callback: Callable[[str], None],
        logger:   Optional[Callable[[str], None]] = None,
        log_file: str  = None,
        forever:  bool = False,
    ) -> None:
        """
        Start the watch loop.

        Args:
            path:      Repo path to monitor
            callback:  Called with (path) after a batch window expires
            logger:    Log function
            log_file:  Path to log file (optional)
            forever:   Never exit on errors (daemon mode)
        """
        log = logger or TeeLogger(
            log_file=log_file,
            silent=(log_file is not None and forever)
        )

        self._running = True

        log("")
        log("Watch mode started")
        log(f"Repo         : {path}")
        log(f"Poll interval: every {self.poll_interval}s")

        if self.batch_window > 0:
            log(f"Batch window : {self.batch_window}s "
                f"({self.batch_window // 60}m {self.batch_window % 60}s) "
                f"-- changes collected before committing")
        else:
            log("Batch window : DISABLED -- commits immediately on change")

        log("Press Ctrl+C to stop")
        log("")

        snapshot     = _snapshot(path)
        batch        = BatchWindow(self.batch_window)

        log(f"Tracking {len(snapshot)} files. Waiting for changes...")
        log("")

        while self._running:
            try:
                time.sleep(self.poll_interval)
                new_snap = _snapshot(path)

                # ── Detect changes ──────────────────────────
                if _changed(snapshot, new_snap):
                    desc = _describe(snapshot, new_snap)

                    if self.batch_window <= 0:
                        # No batch window: commit immediately (old behavior)
                        snapshot = new_snap
                        log(f"Change detected: {desc} — committing immediately")
                        time.sleep(self.debounce)
                        snapshot = _snapshot(path)
                        self._fire(path, callback, log, forever, "immediate")

                    elif not batch.is_open():
                        # First change: open the batch window
                        batch.open(desc)
                        remaining = int(batch.time_remaining())
                        log(f"[BATCH] First change detected: {desc}")
                        log(f"[BATCH] Collection window opened — "
                            f"will commit in {remaining}s after accumulating changes")
                        snapshot = new_snap

                    else:
                        # More changes during open window
                        batch.record()
                        remaining = int(batch.time_remaining())
                        log(f"[BATCH] More changes: {desc} "
                            f"({batch.change_count()} events) — "
                            f"{remaining}s remaining in window")
                        snapshot = new_snap

                else:
                    snapshot = new_snap

                # ── Check if batch window has expired ───────
                if batch.is_open() and batch.is_expired():
                    log(f"[BATCH] Window expired — "
                        f"accumulated {batch.summary()}")
                    log(f"[BATCH] Analyzing all changes and committing...")

                    # Final debounce: wait a moment for any last saves
                    time.sleep(self.debounce)
                    snapshot = _snapshot(path)

                    batch.close()
                    self._fire(path, callback, log, forever, "batch")

            except KeyboardInterrupt:
                if not forever:
                    if batch.is_open():
                        log(f"[BATCH] Window interrupted — "
                            f"committing {batch.change_count()} accumulated change(s)...")
                        batch.close()
                        try:
                            callback(path)
                        except Exception:
                            pass
                    log("")
                    log("Watch mode stopped by user.")
                    break
                log("Interrupt ignored (daemon mode)")

            except Exception as e:
                self.stats.errors += 1
                log(f"Watcher error: {e}")
                if not forever:
                    raise
                log("Recovering in 5s...")
                time.sleep(5)

        self._running = False

    def _fire(
        self,
        path:     str,
        callback: Callable,
        log:      Callable,
        forever:  bool,
        mode:     str,
    ):
        """Execute the callback (agent run) and update stats."""
        self.stats.cycles += 1
        try:
            callback(path)
            self.stats.commits_made += 1
        except KeyboardInterrupt:
            raise
        except Exception as e:
            self.stats.errors += 1
            log(f"Agent error during {mode} commit: {e}")
            if not forever:
                raise
            log("Continuing watch (daemon mode)")

        log("")
        log(f"Watching... ({self.stats.summary()})")
        log("")

    def stop(self):
        self._running = False