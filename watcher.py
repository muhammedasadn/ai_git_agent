"""
watcher.py
==========
Auto-Watch Mode — monitors the repository for file changes
and triggers the agent workflow automatically.

How it works:
1. Every N seconds, scan the repo for changes
2. If changes are detected, wait for a debounce period (to batch rapid saves)
3. Trigger the full agent workflow
4. Repeat until the user presses Ctrl+C

This is useful for "set it and forget it" workflows where you want
the agent to automatically commit your work as you code.
"""

import time
import os
import hashlib
from typing import Callable, Optional


# ─────────────────────────────────────────────
# Repo Snapshot (for change detection)
# ─────────────────────────────────────────────

def _get_repo_snapshot(path: str) -> dict:
    """
    Build a snapshot of all tracked + untracked files with their
    modification times and sizes. Used to detect changes between polls.

    Returns a dict: {filepath: (mtime, size)}
    """
    snapshot = {}

    for root, dirs, files in os.walk(path):
        # Skip .git directory entirely
        dirs[:] = [d for d in dirs if d not in {
            ".git", "__pycache__", "node_modules", "venv", ".env", "build", "dist"
        }]

        for filename in files:
            filepath = os.path.join(root, filename)
            try:
                stat = os.stat(filepath)
                rel_path = os.path.relpath(filepath, path)
                snapshot[rel_path] = (stat.st_mtime, stat.st_size)
            except OSError:
                pass  # File was deleted during scan

    return snapshot


def _snapshot_changed(old: dict, new: dict) -> bool:
    """
    Compare two snapshots and return True if anything changed.
    Detects: new files, deleted files, modified files.
    """
    if set(old.keys()) != set(new.keys()):
        return True  # Files added or removed

    for key in old:
        if old[key] != new.get(key):
            return True  # File modified

    return False


def _describe_changes(old: dict, new: dict) -> str:
    """Return a human-readable description of what changed."""
    old_keys = set(old.keys())
    new_keys = set(new.keys())

    added = new_keys - old_keys
    deleted = old_keys - new_keys
    modified = {k for k in old_keys & new_keys if old[k] != new[k]}

    parts = []
    if added:
        parts.append(f"{len(added)} new file(s)")
    if deleted:
        parts.append(f"{len(deleted)} deleted file(s)")
    if modified:
        parts.append(f"{len(modified)} modified file(s)")

    return ", ".join(parts) if parts else "unknown changes"


# ─────────────────────────────────────────────
# Main Watcher Class
# ─────────────────────────────────────────────

class Watcher:
    """
    Monitors a Git repository for changes and triggers a callback.

    Usage:
        def on_change(path):
            agent.run(path)

        watcher = Watcher(config)
        watcher.start(repo_path, on_change)
    """

    def __init__(self, config: dict):
        watcher_config = config.get("agent", {})
        self.poll_interval = watcher_config.get("watch_interval_seconds", 10)
        self.debounce = watcher_config.get("watch_debounce_seconds", 3)
        self._running = False

    def start(
        self,
        path: str,
        callback: Callable[[str], None],
        logger: Optional[Callable[[str], None]] = None
    ) -> None:
        """
        Start watching the repository.
        Calls `callback(path)` whenever changes are detected.
        Blocks until Ctrl+C.

        Args:
            path: Repository path to watch
            callback: Function to call when changes are detected
            logger: Optional logging function (defaults to print)
        """
        log = logger or print

        self._running = True
        log("👁  Watch mode started. Press Ctrl+C to stop.")
        log(f"   Polling every {self.poll_interval}s with {self.debounce}s debounce")
        log("")

        # Take initial snapshot
        snapshot = _get_repo_snapshot(path)
        log(f"   Initial snapshot: {len(snapshot)} files tracked")
        log("")

        try:
            while self._running:
                time.sleep(self.poll_interval)

                # Check for changes
                new_snapshot = _get_repo_snapshot(path)

                if _snapshot_changed(snapshot, new_snapshot):
                    change_desc = _describe_changes(snapshot, new_snapshot)
                    log(f"🔔 Changes detected: {change_desc}")
                    log(f"   Waiting {self.debounce}s for more changes (debounce)...")

                    # Debounce: wait and re-check to batch rapid saves
                    time.sleep(self.debounce)
                    final_snapshot = _get_repo_snapshot(path)

                    # Update snapshot (even if we're about to process)
                    snapshot = final_snapshot

                    # Trigger the callback
                    log("▶  Triggering agent workflow...")
                    try:
                        callback(path)
                    except KeyboardInterrupt:
                        raise
                    except Exception as e:
                        log(f"⚠  Agent error during watch: {e}")
                        log("   Continuing to watch...")

                    log("")
                    log(f"👁  Watching for more changes...")
                else:
                    # No changes, update snapshot silently
                    snapshot = new_snapshot

        except KeyboardInterrupt:
            log("")
            log("⏹  Watch mode stopped by user.")
            self._running = False

    def stop(self) -> None:
        """Signal the watcher to stop on next poll."""
        self._running = False