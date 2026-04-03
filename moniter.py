
#!/usr/bin/env python3
"""
monitor.py
==========
Real-time Log Monitor TUI for the AI Git Agent.

A terminal UI that shows:
  - Live agent status (running/stopped, uptime)
  - Real-time log stream (color-coded)
  - Commit history with hashes
  - Push history
  - File change events
  - Error alerts
  - Keyboard controls

Usage:
  python monitor.py                    # monitor current directory
  python monitor.py /path/to/repo     # monitor specific repo
  python monitor.py --compact         # compact single-column layout

Controls:
  q / Ctrl+C   Quit monitor
  c            Clear log display
  r            Refresh now
  s            Start daemon (if stopped)
  x            Stop daemon
  l            Toggle log level filter (ALL / INFO / COMMITS / ERRORS)
  h            Show help

Built with Python's curses — no external dependencies.
"""

import curses
import os
import sys
import time
import json
import signal
import argparse
from datetime import datetime, timedelta
from collections import deque


# ─────────────────────────────────────────────
# Constants
# ─────────────────────────────────────────────

REFRESH_INTERVAL = 2.0     # seconds between screen refreshes
LOG_BUFFER_SIZE  = 500     # max log lines to keep in memory
AGENT_FILES      = {
    "pid":   ".agent_pid",
    "log":   ".agent_log.txt",
    "state": ".agent_state.json",
}

# Log line categories (for color-coding)
CAT_COMMIT  = "commit"
CAT_PUSH    = "push"
CAT_ERROR   = "error"
CAT_WARNING = "warning"
CAT_INFO    = "info"
CAT_CHANGE  = "change"
CAT_AI      = "ai"
CAT_SYSTEM  = "system"


# ─────────────────────────────────────────────
# Log line parser
# ─────────────────────────────────────────────

def categorize_line(line: str) -> str:
    """Assign a category to a log line for color-coding."""
    lower = line.lower()
    if "[*]" in line or "commit" in lower and ("[" in line and "]" in line):
        return CAT_COMMIT
    if "push" in lower and ("ok" in lower or "pushed" in lower):
        return CAT_PUSH
    if "[xx]" in lower or "error" in lower or "failed" in lower or "fatal" in lower:
        return CAT_ERROR
    if "[!!]" in lower or "warning" in lower or "warn" in lower or "blocked" in lower:
        return CAT_WARNING
    if "[ai]" in lower or "ai:" in lower or "summary" in lower:
        return CAT_AI
    if "change" in lower or "detected" in lower or "modified" in lower or "new file" in lower:
        return CAT_CHANGE
    if "daemon" in lower or "started" in lower or "stopped" in lower or "preflight" in lower:
        return CAT_SYSTEM
    return CAT_INFO


def parse_log_line(raw: str) -> dict:
    """Parse a raw log line into {timestamp, message, category}."""
    raw = raw.rstrip()
    # Try to extract timestamp from [HH:MM:SS] prefix
    ts  = ""
    msg = raw
    if raw.startswith("[") and "]" in raw[:12]:
        end = raw.index("]")
        ts  = raw[1:end]
        msg = raw[end+1:].strip()
    return {
        "timestamp": ts,
        "message":   msg,
        "raw":       raw,
        "category":  categorize_line(raw),
    }


# ─────────────────────────────────────────────
# State reader
# ─────────────────────────────────────────────

class RepoState:
    """Reads live state of the agent for a given repo."""

    def __init__(self, repo_path: str):
        self.repo_path = repo_path

    def _path(self, key: str) -> str:
        return os.path.join(self.repo_path, AGENT_FILES[key])

    def get_pid(self) -> int | None:
        p = self._path("pid")
        if not os.path.exists(p):
            return None
        try:
            return int(open(p).read().strip())
        except Exception:
            return None

    def is_running(self) -> bool:
        pid = self.get_pid()
        if not pid:
            return False
        try:
            os.kill(pid, 0)
            return True
        except (ProcessLookupError, PermissionError):
            return False

    def get_state(self) -> dict:
        p = self._path("state")
        if not os.path.exists(p):
            return {}
        try:
            return json.load(open(p))
        except Exception:
            return {}

    def get_uptime(self) -> str:
        state = self.get_state()
        started = state.get("daemon_started")
        if not started:
            return "unknown"
        try:
            start_dt = datetime.fromisoformat(started)
            delta    = datetime.now() - start_dt
            h, rem   = divmod(int(delta.total_seconds()), 3600)
            m, s     = divmod(rem, 60)
            if h:
                return f"{h}h {m}m"
            elif m:
                return f"{m}m {s}s"
            return f"{s}s"
        except Exception:
            return "unknown"

    def read_log_lines(self, n: int = 200) -> list[str]:
        p = self._path("log")
        if not os.path.exists(p):
            return []
        try:
            with open(p) as f:
                lines = f.readlines()
            return [l.rstrip() for l in lines[-n:]]
        except Exception:
            return []

    def get_commit_history(self) -> list[dict]:
        """Read last N commits from git log."""
        try:
            import subprocess
            result = subprocess.run(
                ["git", "log", "--pretty=format:%h|||%s|||%cr", "-15"],
                cwd=self.repo_path,
                capture_output=True, text=True, timeout=5
            )
            commits = []
            for line in result.stdout.strip().splitlines():
                parts = line.split("|||", 2)
                if len(parts) == 3:
                    commits.append({
                        "hash":    parts[0],
                        "message": parts[1],
                        "when":    parts[2],
                    })
            return commits
        except Exception:
            return []

    def get_branch(self) -> str:
        try:
            import subprocess
            r = subprocess.run(
                ["git", "branch", "--show-current"],
                cwd=self.repo_path, capture_output=True, text=True, timeout=3
            )
            return r.stdout.strip() or "unknown"
        except Exception:
            return "unknown"

    def get_remote(self) -> str:
        state = self.get_state()
        if state.get("remote_url"):
            return state["remote_url"]
        try:
            import subprocess
            r = subprocess.run(
                ["git", "remote", "get-url", "origin"],
                cwd=self.repo_path, capture_output=True, text=True, timeout=3
            )
            return r.stdout.strip() or "(none)"
        except Exception:
            return "(none)"

    def count_uncommitted(self) -> int:
        try:
            import subprocess
            r = subprocess.run(
                ["git", "status", "--porcelain"],
                cwd=self.repo_path, capture_output=True, text=True, timeout=3
            )
            return len([l for l in r.stdout.strip().splitlines() if l.strip()])
        except Exception:
            return 0


# ─────────────────────────────────────────────
# Filter levels
# ─────────────────────────────────────────────

FILTERS = ["ALL", "COMMITS", "ERRORS", "AI", "INFO"]

def filter_lines(lines: list[dict], level: str) -> list[dict]:
    if level == "ALL":
        return lines
    if level == "COMMITS":
        return [l for l in lines if l["category"] in (CAT_COMMIT, CAT_PUSH)]
    if level == "ERRORS":
        return [l for l in lines if l["category"] in (CAT_ERROR, CAT_WARNING)]
    if level == "AI":
        return [l for l in lines if l["category"] == CAT_AI]
    return lines


# ─────────────────────────────────────────────
# Color scheme
# ─────────────────────────────────────────────

# Color pair IDs
CP_HEADER    = 1
CP_STATUS_OK = 2
CP_STATUS_NO = 3
CP_COMMIT    = 4
CP_PUSH      = 5
CP_ERROR     = 6
CP_WARNING   = 7
CP_AI        = 8
CP_CHANGE    = 9
CP_DIM       = 10
CP_TITLE     = 11
CP_BORDER    = 12
CP_SYSTEM    = 13
CP_KEY       = 14


def init_colors():
    curses.start_color()
    curses.use_default_colors()
    bg = -1  # transparent background

    curses.init_pair(CP_HEADER,    curses.COLOR_BLACK,  curses.COLOR_CYAN)
    curses.init_pair(CP_STATUS_OK, curses.COLOR_GREEN,  bg)
    curses.init_pair(CP_STATUS_NO, curses.COLOR_RED,    bg)
    curses.init_pair(CP_COMMIT,    curses.COLOR_YELLOW, bg)
    curses.init_pair(CP_PUSH,      curses.COLOR_GREEN,  bg)
    curses.init_pair(CP_ERROR,     curses.COLOR_RED,    bg)
    curses.init_pair(CP_WARNING,   curses.COLOR_YELLOW, bg)
    curses.init_pair(CP_AI,        curses.COLOR_MAGENTA,bg)
    curses.init_pair(CP_CHANGE,    curses.COLOR_CYAN,   bg)
    curses.init_pair(CP_DIM,       curses.COLOR_WHITE,  bg)
    curses.init_pair(CP_TITLE,     curses.COLOR_CYAN,   bg)
    curses.init_pair(CP_BORDER,    curses.COLOR_BLUE,   bg)
    curses.init_pair(CP_SYSTEM,    curses.COLOR_WHITE,  bg)
    curses.init_pair(CP_KEY,       curses.COLOR_BLACK,  curses.COLOR_WHITE)


def cat_color(cat: str) -> int:
    return {
        CAT_COMMIT:  curses.color_pair(CP_COMMIT)  | curses.A_BOLD,
        CAT_PUSH:    curses.color_pair(CP_PUSH)    | curses.A_BOLD,
        CAT_ERROR:   curses.color_pair(CP_ERROR)   | curses.A_BOLD,
        CAT_WARNING: curses.color_pair(CP_WARNING),
        CAT_AI:      curses.color_pair(CP_AI),
        CAT_CHANGE:  curses.color_pair(CP_CHANGE),
        CAT_SYSTEM:  curses.color_pair(CP_SYSTEM)  | curses.A_DIM,
        CAT_INFO:    curses.color_pair(CP_DIM),
    }.get(cat, curses.color_pair(CP_DIM))


# ─────────────────────────────────────────────
# Safe addstr helper
# ─────────────────────────────────────────────

def safe_addstr(win, y, x, text, attr=0, max_x=None):
    """Write text to curses window, clipping at screen edge."""
    try:
        h, w = win.getmaxyx()
        if y < 0 or y >= h:
            return
        if x < 0:
            text = text[-x:]
            x = 0
        limit = (max_x or w) - x - 1
        if limit <= 0:
            return
        text = str(text)[:limit]
        if attr:
            win.addstr(y, x, text, attr)
        else:
            win.addstr(y, x, text)
    except curses.error:
        pass


def draw_hline(win, y, x, width, char="-", attr=0):
    safe_addstr(win, y, x, char * width, attr)


def draw_box_title(win, y, x, width, title, attr=0):
    safe_addstr(win, y, x, f"[ {title} ]".ljust(width), attr)


# ─────────────────────────────────────────────
# Main Monitor TUI
# ─────────────────────────────────────────────

class Monitor:

    def __init__(self, repo_path: str, compact: bool = False):
        self.repo_path   = os.path.abspath(repo_path)
        self.compact     = compact
        self.state       = RepoState(self.repo_path)
        self.log_buf     = deque(maxlen=LOG_BUFFER_SIZE)
        self.log_offset  = 0
        self.filter_idx  = 0   # index into FILTERS
        self.show_help   = False
        self.last_log_sz = 0
        self.alerts      = deque(maxlen=5)
        self._load_initial_log()

    def _load_initial_log(self):
        for raw in self.state.read_log_lines(200):
            self.log_buf.append(parse_log_line(raw))

    def _poll_log(self):
        """Append any new log lines since last check."""
        p = os.path.join(self.repo_path, AGENT_FILES["log"])
        if not os.path.exists(p):
            return
        try:
            sz = os.path.getsize(p)
            if sz <= self.last_log_sz:
                return
            self.last_log_sz = sz
            # Re-read last 50 lines and add new ones
            new_lines = self.state.read_log_lines(50)
            existing  = {e["raw"] for e in list(self.log_buf)[-50:]}
            for raw in new_lines:
                if raw not in existing:
                    parsed = parse_log_line(raw)
                    self.log_buf.append(parsed)
                    if parsed["category"] == CAT_ERROR:
                        self.alerts.append(parsed)
        except Exception:
            pass

    def run(self):
        curses.wrapper(self._main)

    def _main(self, stdscr):
        curses.curs_set(0)
        stdscr.nodelay(True)
        stdscr.timeout(int(REFRESH_INTERVAL * 1000))
        init_colors()

        while True:
            self._poll_log()
            h, w = stdscr.getmaxyx()
            stdscr.erase()

            try:
                if self.show_help:
                    self._draw_help(stdscr, h, w)
                elif self.compact or w < 100:
                    self._draw_compact(stdscr, h, w)
                else:
                    self._draw_full(stdscr, h, w)
                stdscr.refresh()
            except curses.error:
                pass

            key = stdscr.getch()
            if key == -1:
                continue

            ch = chr(key) if 0 < key < 256 else ""

            if ch in ("q", "Q") or key == 27:
                break
            elif ch in ("h", "H", "?"):
                self.show_help = not self.show_help
            elif ch in ("c", "C"):
                self.log_buf.clear()
                self.log_offset = 0
            elif ch in ("r", "R"):
                self._poll_log()
            elif ch in ("l", "L"):
                self.filter_idx = (self.filter_idx + 1) % len(FILTERS)
                self.log_offset = 0
            elif ch in ("s", "S"):
                self._daemon_start()
            elif ch in ("x", "X"):
                self._daemon_stop()
            elif key == curses.KEY_DOWN:
                self.log_offset = min(self.log_offset + 1,
                                      max(0, len(self.log_buf) - 5))
            elif key == curses.KEY_UP:
                self.log_offset = max(0, self.log_offset - 1)
            elif key == curses.KEY_NPAGE:  # Page Down
                self.log_offset = min(self.log_offset + 10,
                                      max(0, len(self.log_buf) - 5))
            elif key == curses.KEY_PPAGE:  # Page Up
                self.log_offset = max(0, self.log_offset - 10)
            elif key == curses.KEY_END:
                self.log_offset = 0  # Reset to bottom

    # ─────────────────────────────────────────
    # Full layout (wide terminals)
    # ─────────────────────────────────────────

    def _draw_full(self, win, h, w):
        """Two-column layout: left=status+commits, right=log."""
        left_w  = min(45, w // 3)
        right_w = w - left_w - 1
        split_x = left_w

        # Header bar
        self._draw_header(win, 0, w)

        # Left panel
        self._draw_status_panel(win, 2, 0, left_w, h - 4)

        # Vertical divider
        for row in range(2, h - 2):
            safe_addstr(win, row, split_x, "|",
                        curses.color_pair(CP_BORDER))

        # Right panel: log
        self._draw_log_panel(win, 2, split_x + 1, right_w, h - 4)

        # Footer / keybindings
        self._draw_footer(win, h - 2, w)

    # ─────────────────────────────────────────
    # Compact layout (narrow terminals)
    # ─────────────────────────────────────────

    def _draw_compact(self, win, h, w):
        self._draw_header(win, 0, w)
        # Mini status (2 lines)
        running = self.state.is_running()
        pid     = self.state.get_pid()
        status  = f"RUNNING (PID {pid})" if running else "STOPPED"
        color   = curses.color_pair(CP_STATUS_OK) if running else curses.color_pair(CP_STATUS_NO)
        safe_addstr(win, 2, 1, f"Daemon: {status}", color | curses.A_BOLD)
        safe_addstr(win, 3, 1, f"Branch: {self.state.get_branch()}  "
                                f"Filter: {FILTERS[self.filter_idx]}",
                    curses.color_pair(CP_DIM))
        # Log fills the rest
        self._draw_log_panel(win, 5, 0, w, h - 7)
        self._draw_footer(win, h - 2, w)

    # ─────────────────────────────────────────
    # Header
    # ─────────────────────────────────────────

    def _draw_header(self, win, y, w):
        title = "  AI GIT AGENT — LIVE MONITOR  "
        ts    = datetime.now().strftime("%H:%M:%S")
        bar   = title.ljust(w - len(ts) - 2) + ts + " "
        safe_addstr(win, y, 0, bar[:w],
                    curses.color_pair(CP_HEADER) | curses.A_BOLD)

        # Repo path on next line (dimmed)
        repo_line = f"  Repo: {self.repo_path}"
        safe_addstr(win, y + 1, 0, repo_line[:w],
                    curses.color_pair(CP_DIM) | curses.A_DIM)

    # ─────────────────────────────────────────
    # Status panel (left column)
    # ─────────────────────────────────────────

    def _draw_status_panel(self, win, y, x, width, height):
        row = y

        # ── Daemon status ──
        draw_box_title(win, row, x, width, "DAEMON STATUS",
                       curses.color_pair(CP_TITLE) | curses.A_BOLD)
        row += 1

        running = self.state.is_running()
        pid     = self.state.get_pid()
        uptime  = self.state.get_uptime() if running else "—"

        if running:
            safe_addstr(win, row, x + 1,
                        f"Status  : RUNNING",
                        curses.color_pair(CP_STATUS_OK) | curses.A_BOLD)
        else:
            safe_addstr(win, row, x + 1,
                        f"Status  : STOPPED",
                        curses.color_pair(CP_STATUS_NO) | curses.A_BOLD)
        row += 1

        safe_addstr(win, row, x + 1, f"PID     : {pid or '—'}",
                    curses.color_pair(CP_DIM))
        row += 1
        safe_addstr(win, row, x + 1, f"Uptime  : {uptime}",
                    curses.color_pair(CP_DIM))
        row += 1

        # ── Repo info ──
        row += 1
        draw_box_title(win, row, x, width, "REPOSITORY",
                       curses.color_pair(CP_TITLE) | curses.A_BOLD)
        row += 1

        branch  = self.state.get_branch()
        remote  = self.state.get_remote()
        pending = self.state.count_uncommitted()

        safe_addstr(win, row, x + 1, f"Branch  : {branch}"[:width - 2],
                    curses.color_pair(CP_CHANGE))
        row += 1

        # Truncate remote URL for display
        short_remote = remote
        if len(remote) > width - 12:
            short_remote = "..." + remote[-(width - 15):]
        safe_addstr(win, row, x + 1, f"Remote  : {short_remote}"[:width - 2],
                    curses.color_pair(CP_DIM))
        row += 1

        pending_color = (curses.color_pair(CP_WARNING)
                         if pending > 0 else curses.color_pair(CP_STATUS_OK))
        safe_addstr(win, row, x + 1, f"Pending : {pending} file(s)"[:width - 2],
                    pending_color)
        row += 1

        # ── Recent commits ──
        row += 1
        commits_height = min(8, (y + height) - row - 2)
        if commits_height > 2:
            draw_box_title(win, row, x, width, "RECENT COMMITS",
                           curses.color_pair(CP_TITLE) | curses.A_BOLD)
            row += 1
            commits = self.state.get_commit_history()
            for i, c in enumerate(commits[:commits_height]):
                if row >= y + height:
                    break
                hash_str = c["hash"]
                when     = c["when"][:8] if len(c["when"]) > 8 else c["when"]
                msg_max  = width - len(hash_str) - len(when) - 5
                msg      = c["message"][:msg_max] if msg_max > 5 else c["message"][:10]
                line     = f" {hash_str} {msg}"
                safe_addstr(win, row, x, line[:width - 1],
                            curses.color_pair(CP_COMMIT))
                safe_addstr(win, row, x + width - len(when) - 2, when,
                            curses.color_pair(CP_DIM) | curses.A_DIM)
                row += 1

        # ── Alerts ──
        if self.alerts and row < y + height - 2:
            row += 1
            draw_box_title(win, row, x, width, "RECENT ERRORS",
                           curses.color_pair(CP_ERROR) | curses.A_BOLD)
            row += 1
            for alert in list(self.alerts)[-3:]:
                if row >= y + height:
                    break
                safe_addstr(win, row, x + 1, alert["message"][:width - 3],
                            curses.color_pair(CP_ERROR))
                row += 1

    # ─────────────────────────────────────────
    # Log panel (right column)
    # ─────────────────────────────────────────

    def _draw_log_panel(self, win, y, x, width, height):
        cur_filter = FILTERS[self.filter_idx]

        draw_box_title(win, y, x, width,
                       f"LIVE LOG  [Filter: {cur_filter}]  [Up/Down: scroll]  [END: bottom]",
                       curses.color_pair(CP_TITLE) | curses.A_BOLD)

        all_lines    = list(self.log_buf)
        visible      = filter_lines(all_lines, cur_filter)
        max_visible  = height - 1
        total        = len(visible)

        # Auto-scroll to bottom unless user scrolled up
        if self.log_offset == 0:
            start = max(0, total - max_visible)
        else:
            start = max(0, total - max_visible - self.log_offset)

        display = visible[start : start + max_visible]

        for i, entry in enumerate(display):
            row = y + 1 + i
            if row >= y + height:
                break

            ts  = entry.get("timestamp", "")
            msg = entry.get("message", "")
            cat = entry.get("category", CAT_INFO)

            ts_str  = f"[{ts}] " if ts else ""
            color   = cat_color(cat)

            # Prefix icon for key events
            icon = {
                CAT_COMMIT:  "[*] ",
                CAT_PUSH:    "[^] ",
                CAT_ERROR:   "[X] ",
                CAT_WARNING: "[!] ",
                CAT_AI:      "[A] ",
                CAT_CHANGE:  "[~] ",
                CAT_SYSTEM:  "[.] ",
            }.get(cat, "    ")

            line = f"{ts_str}{icon}{msg}"
            safe_addstr(win, row, x, line[:width - 1], color)

        # Scroll indicator
        if total > max_visible:
            pct = int(100 * (start + max_visible) / max(total, 1))
            indicator = f" {pct}% ({total} lines) "
            safe_addstr(win, y, x + width - len(indicator) - 1,
                        indicator, curses.color_pair(CP_DIM) | curses.A_DIM)

    # ─────────────────────────────────────────
    # Footer
    # ─────────────────────────────────────────

    def _draw_footer(self, win, y, w):
        keys = [
            ("q", "Quit"),
            ("s", "Start"),
            ("x", "Stop"),
            ("l", "Filter"),
            ("c", "Clear"),
            ("r", "Refresh"),
            ("h", "Help"),
            ("↑↓", "Scroll"),
            ("END", "Bottom"),
        ]
        parts = []
        for k, label in keys:
            parts.append(f" {k}:{label} ")

        bar = " | ".join(parts)
        # Draw with alternating key highlight
        col = 0
        for k, label in keys:
            if col >= w - 2:
                break
            key_str  = f" {k}"
            lab_str  = f":{label} "
            safe_addstr(win, y, col, key_str,
                        curses.color_pair(CP_KEY) | curses.A_BOLD)
            col += len(key_str)
            safe_addstr(win, y, col, lab_str,
                        curses.color_pair(CP_DIM))
            col += len(lab_str)
            if col < w - 2:
                safe_addstr(win, y, col, "|", curses.color_pair(CP_BORDER))
                col += 1

    # ─────────────────────────────────────────
    # Help overlay
    # ─────────────────────────────────────────

    def _draw_help(self, win, h, w):
        self._draw_header(win, 0, w)

        box_h = 22
        box_w = 60
        by    = max(2, (h - box_h) // 2)
        bx    = max(0, (w - box_w) // 2)

        # Draw box
        for row in range(by, by + box_h):
            safe_addstr(win, row, bx, " " * box_w, curses.color_pair(CP_BORDER))

        title = "  KEYBOARD CONTROLS  "
        safe_addstr(win, by, bx + (box_w - len(title)) // 2, title,
                    curses.color_pair(CP_HEADER) | curses.A_BOLD)

        helps = [
            ("", ""),
            ("q / Ctrl+C / ESC", "Quit the monitor"),
            ("s",               "Start the daemon"),
            ("x",               "Stop the daemon"),
            ("l",               "Cycle log filter (ALL/COMMITS/ERRORS/AI)"),
            ("c",               "Clear log display"),
            ("r",               "Force refresh"),
            ("h / ?",           "Toggle this help screen"),
            ("", ""),
            ("UP / DOWN",       "Scroll log one line"),
            ("PAGE UP/DOWN",    "Scroll log 10 lines"),
            ("END",             "Jump to bottom (latest)"),
            ("", ""),
            ("LOG ICONS:", ""),
            ("[*]",             "Commit created"),
            ("[^]",             "Pushed to remote"),
            ("[X]",             "Error"),
            ("[!]",             "Warning"),
            ("[A]",             "AI activity"),
            ("[~]",             "File change detected"),
            ("", ""),
            ("Press h to close", ""),
        ]

        row = by + 1
        for key, desc in helps:
            if row >= by + box_h - 1:
                break
            if not key and not desc:
                row += 1
                continue
            if key.endswith(":"):
                safe_addstr(win, row, bx + 2, key,
                            curses.color_pair(CP_TITLE) | curses.A_BOLD)
            else:
                safe_addstr(win, row, bx + 2, f"{key:<20}",
                            curses.color_pair(CP_COMMIT) | curses.A_BOLD)
                safe_addstr(win, row, bx + 23, desc,
                            curses.color_pair(CP_DIM))
            row += 1

    # ─────────────────────────────────────────
    # Daemon actions from monitor
    # ─────────────────────────────────────────

    def _daemon_start(self):
        """Start daemon from within the monitor (briefly suspend curses)."""
        try:
            curses.endwin()
            print("\nStarting daemon...")
            import subprocess, sys
            main_py = os.path.join(os.path.dirname(__file__), "main.py")
            subprocess.Popen(
                [sys.executable, main_py, "--daemon", "start", self.repo_path],
                stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL
            )
            time.sleep(2)
            curses.doupdate()
            self.log_buf.append(parse_log_line(
                f"[{datetime.now().strftime('%H:%M:%S')}] [.] Daemon start requested from monitor"
            ))
        except Exception as e:
            self.log_buf.append(parse_log_line(f"Error starting daemon: {e}"))

    def _daemon_stop(self):
        """Stop daemon from within the monitor."""
        try:
            curses.endwin()
            print("\nStopping daemon...")
            import subprocess, sys
            main_py = os.path.join(os.path.dirname(__file__), "main.py")
            subprocess.run(
                [sys.executable, main_py, "--daemon", "stop", self.repo_path],
                stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL
            )
            time.sleep(1)
            curses.doupdate()
            self.log_buf.append(parse_log_line(
                f"[{datetime.now().strftime('%H:%M:%S')}] [.] Daemon stop requested from monitor"
            ))
        except Exception as e:
            self.log_buf.append(parse_log_line(f"Error stopping daemon: {e}"))


# ─────────────────────────────────────────────
# CLI entry point
# ─────────────────────────────────────────────

def main():
    parser = argparse.ArgumentParser(
        prog="ai-git-monitor",
        description="Real-time log monitor TUI for AI Git Agent",
        formatter_class=argparse.RawDescriptionHelpFormatter,
        epilog="""
Controls:
  q / ESC    Quit
  s          Start daemon
  x          Stop daemon
  l          Cycle log filter
  c          Clear log
  h          Help
  UP/DOWN    Scroll log
  END        Jump to latest
        """
    )
    parser.add_argument("path", nargs="?", default=".",
                        help="Repository path to monitor (default: current dir)")
    parser.add_argument("--compact", "-c", action="store_true",
                        help="Use compact single-column layout")
    args = parser.parse_args()

    path = os.path.abspath(args.path)

    if not os.path.isdir(path):
        print(f"ERROR: Not a directory: {path}")
        sys.exit(1)

    # Check terminal capability
    if not sys.stdout.isatty():
        print("ERROR: monitor.py must be run in an interactive terminal.")
        sys.exit(1)

    monitor = Monitor(path, compact=args.compact)

    try:
        monitor.run()
    except KeyboardInterrupt:
        pass

    print("\nMonitor closed.")


if __name__ == "__main__":
    main()