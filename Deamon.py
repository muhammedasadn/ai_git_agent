"""
daemon.py
=========
Background Daemon Mode for the AI Git Agent.

This module lets the agent run PERSISTENTLY in the background —
even after you close the terminal that started it.

How it works:
  START:  python main.py --daemon start /path/to/repo
          - Forks a background process (detaches from terminal)
          - Writes PID to .agent_state.json
          - The background process watches forever + auto-commits + auto-pushes
          - You can close the terminal — the agent keeps running

  STATUS: python main.py --daemon status /path/to/repo
          - Shows if the daemon is running
          - Shows the PID, uptime, last commit time
          - Shows recent activity log

  STOP:   python main.py --daemon stop /path/to/repo
          - Sends SIGTERM to the background process
          - Cleans up PID file

  LOGS:   python main.py --daemon logs /path/to/repo
          - Shows the last 50 lines of the agent's activity log

The daemon writes all its output to:
  .agent_log.txt   (in the repo directory)
"""

import os
import sys
import signal
import time
import json
import subprocess
from datetime import datetime


# ─────────────────────────────────────────────
# File paths
# ─────────────────────────────────────────────

def _pid_file(repo_path: str) -> str:
    return os.path.join(repo_path, ".agent_pid")

def _log_file(repo_path: str) -> str:
    return os.path.join(repo_path, ".agent_log.txt")

def _state_file(repo_path: str) -> str:
    return os.path.join(repo_path, ".agent_state.json")


# ─────────────────────────────────────────────
# Color helpers
# ─────────────────────────────────────────────

def _tty():
    return hasattr(sys.stdout, "isatty") and sys.stdout.isatty()

def _c(text, code):
    return f"\033[{code}m{text}\033[0m" if _tty() else text

def cyan(t):   return _c(t, "96")
def green(t):  return _c(t, "92")
def yellow(t): return _c(t, "93")
def red(t):    return _c(t, "91")
def bold(t):   return _c(t, "1")
def dim(t):    return _c(t, "2")


# ─────────────────────────────────────────────
# PID management
# ─────────────────────────────────────────────

def _write_pid(repo_path: str, pid: int):
    with open(_pid_file(repo_path), "w") as f:
        f.write(str(pid))
    _gitignore_add(repo_path, ".agent_pid")
    _gitignore_add(repo_path, ".agent_log.txt")


def _read_pid(repo_path: str) -> int | None:
    pid_file = _pid_file(repo_path)
    if not os.path.exists(pid_file):
        return None
    try:
        with open(pid_file) as f:
            return int(f.read().strip())
    except Exception:
        return None


def _clear_pid(repo_path: str):
    pid_file = _pid_file(repo_path)
    if os.path.exists(pid_file):
        os.remove(pid_file)


def _is_process_alive(pid: int) -> bool:
    """Check if a process with given PID is running."""
    try:
        os.kill(pid, 0)  # signal 0 = just check, don't kill
        return True
    except (ProcessLookupError, PermissionError):
        return False


def _gitignore_add(repo_path: str, pattern: str):
    gi = os.path.join(repo_path, ".gitignore")
    try:
        existing = open(gi).read() if os.path.exists(gi) else ""
        if pattern not in existing:
            with open(gi, "a") as f:
                f.write(f"\n{pattern}\n")
    except Exception:
        pass


# ─────────────────────────────────────────────
# Log file helpers
# ─────────────────────────────────────────────

def _log_write(repo_path: str, message: str):
    """Append a timestamped line to the agent log file."""
    ts = datetime.now().strftime("%Y-%m-%d %H:%M:%S")
    line = f"[{ts}] {message}"
    try:
        with open(_log_file(repo_path), "a") as f:
            f.write(line + "\n")
    except Exception:
        pass


def _log_read(repo_path: str, lines: int = 50) -> list[str]:
    """Read last N lines from agent log file."""
    log = _log_file(repo_path)
    if not os.path.exists(log):
        return []
    try:
        with open(log) as f:
            all_lines = f.readlines()
        return [l.rstrip() for l in all_lines[-lines:]]
    except Exception:
        return []


# ─────────────────────────────────────────────
# State helpers
# ─────────────────────────────────────────────

def _load_state(repo_path: str) -> dict:
    sf = _state_file(repo_path)
    if os.path.exists(sf):
        try:
            with open(sf) as f:
                return json.load(f)
        except Exception:
            pass
    return {}


def _save_state(repo_path: str, data: dict):
    sf = _state_file(repo_path)
    try:
        existing = _load_state(repo_path)
        existing.update(data)
        with open(sf, "w") as f:
            json.dump(existing, f, indent=2)
    except Exception:
        pass


# ─────────────────────────────────────────────
# Daemon Controller
# ─────────────────────────────────────────────

class DaemonController:
    """
    Controls the background agent daemon process.

    start()  — fork and detach background agent
    stop()   — kill the background agent
    status() — print current status
    logs()   — print recent log lines
    """

    def start(self, repo_path: str, config: dict) -> bool:
        """
        Start the agent as a background daemon process.
        Returns True if started successfully.
        """
        repo_path = os.path.abspath(repo_path)

        # Check if already running
        pid = _read_pid(repo_path)
        if pid and _is_process_alive(pid):
            print(f"\n  {yellow('[!!]')} Agent is already running (PID {pid})")
            print(f"  {dim('Use: python main.py --daemon stop  to stop it')}")
            return False

        # Find the main.py location
        main_py = os.path.join(os.path.dirname(os.path.abspath(__file__)), "main.py")
        if not os.path.exists(main_py):
            print(f"  {red('[XX]')} Cannot find main.py at: {main_py}")
            return False

        log = _log_file(repo_path)

        # Build the command to run in background
        # --watch-forever is an internal flag that means: watch + never exit
        cmd = [
            sys.executable, main_py,
            "--watch-forever",   # internal daemon flag
            "--push",            # always push in daemon mode
            repo_path
        ]

        # Add verbose flag if config says so
        if config.get("logging", {}).get("verbose"):
            cmd.append("--verbose")

        print(f"\n  {cyan('[>>]')} Starting AI Git Agent daemon...")
        print(f"  {dim('Repo    :')} {repo_path}")
        print(f"  {dim('Log file:')} {log}")
        print()

        # Fork the background process
        # stdout/stderr redirect to log file
        log_fd = open(log, "a")
        log_fd.write(f"\n{'='*60}\n")
        log_fd.write(f"[{datetime.now().strftime('%Y-%m-%d %H:%M:%S')}] Daemon started\n")
        log_fd.flush()

        proc = subprocess.Popen(
            cmd,
            stdout=log_fd,
            stderr=log_fd,
            stdin=subprocess.DEVNULL,
            start_new_session=True,   # detach from terminal session
            close_fds=True
        )

        pid = proc.pid
        _write_pid(repo_path, pid)
        _save_state(repo_path, {
            "daemon_pid": pid,
            "daemon_started": datetime.now().isoformat(),
            "daemon_repo": repo_path,
        })

        # Brief check that it started
        time.sleep(1.5)
        if _is_process_alive(pid):
            print(f"  {green('[OK]')} Daemon started successfully")
            print(f"  {dim('PID     :')} {pid}")
            print(f"  {dim('Log     :')} {log}")
            print()
            print(f"  {bold('The agent is now running in the background.')}")
            print(f"  It will auto-commit and push whenever you save files.")
            print()
            print(f"  {cyan('Commands:')}")
            print(f"    python main.py --daemon status  {dim('# check if running')}")
            print(f"    python main.py --daemon logs    {dim('# view activity log')}")
            print(f"    python main.py --daemon stop    {dim('# stop the agent')}")
            print()
            return True
        else:
            print(f"  {red('[XX]')} Daemon failed to start. Check log:")
            print(f"    cat {log}")
            _clear_pid(repo_path)
            return False

    def stop(self, repo_path: str) -> bool:
        """Stop the background daemon."""
        repo_path = os.path.abspath(repo_path)

        pid = _read_pid(repo_path)
        if not pid:
            print(f"\n  {yellow('[!!]')} No daemon PID found for this repo.")
            print(f"  {dim('The agent may not be running.')}")
            return False

        if not _is_process_alive(pid):
            print(f"\n  {yellow('[!!]')} PID {pid} is not running (already stopped).")
            _clear_pid(repo_path)
            return True

        print(f"\n  {cyan('[>>]')} Stopping AI Git Agent daemon (PID {pid})...")

        try:
            os.kill(pid, signal.SIGTERM)
            # Wait up to 5 seconds for it to die
            for _ in range(10):
                time.sleep(0.5)
                if not _is_process_alive(pid):
                    break
            else:
                # Force kill if it didn't stop
                os.kill(pid, signal.SIGKILL)
                time.sleep(0.5)

            _clear_pid(repo_path)
            _log_write(repo_path, "Daemon stopped by user")
            print(f"  {green('[OK]')} Daemon stopped.")
            return True

        except Exception as e:
            print(f"  {red('[XX]')} Failed to stop daemon: {e}")
            return False

    def status(self, repo_path: str):
        """Print current daemon status."""
        repo_path = os.path.abspath(repo_path)

        print(f"\n{bold(cyan('=' * 60))}")
        print(f"{bold(cyan('  AI GIT AGENT — DAEMON STATUS'))}")
        print(f"{bold(cyan('=' * 60))}\n")

        print(f"  Repo : {repo_path}")

        pid = _read_pid(repo_path)
        state = _load_state(repo_path)

        if pid and _is_process_alive(pid):
            print(f"  {green('[OK]')} Status  : RUNNING")
            print(f"       PID     : {pid}")

            started = state.get("daemon_started", "unknown")
            print(f"       Started : {started}")

            # Show last few log lines
            recent = _log_read(repo_path, 5)
            if recent:
                print(f"\n  Recent activity:")
                for line in recent:
                    print(f"    {dim(line)}")
        else:
            print(f"  {yellow('[!!]')} Status  : NOT RUNNING")
            if pid:
                print(f"       Last PID: {pid} (dead)")
                _clear_pid(repo_path)

        remote = state.get("remote_url")
        if remote:
            print(f"\n  Remote  : {remote}")

        print()

    def logs(self, repo_path: str, n: int = 50):
        """Print recent daemon log lines."""
        repo_path = os.path.abspath(repo_path)
        log = _log_file(repo_path)

        print(f"\n{bold(cyan('AI GIT AGENT — LOG'))} ({log})\n")

        lines = _log_read(repo_path, n)
        if not lines:
            print(f"  {yellow('[!!]')} No log entries found.")
            print(f"       Start the daemon first: python main.py --daemon start")
        else:
            for line in lines:
                # Color key events
                if "ERROR" in line or "[XX]" in line:
                    print(f"  {red(line)}")
                elif "commit" in line.lower() or "push" in line.lower():
                    print(f"  {green(line)}")
                elif "WARNING" in line or "[!!]" in line:
                    print(f"  {yellow(line)}")
                else:
                    print(f"  {dim(line)}")
        print()