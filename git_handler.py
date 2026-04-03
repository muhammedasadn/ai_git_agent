"""
git_handler.py
==============
Handles all raw Git operations using subprocess calls.
Think of this as a clean wrapper around the `git` CLI —
no AI logic here, just reliable Git execution and output parsing.
"""

import subprocess
import os
import socket
from typing import Optional


# ─────────────────────────────────────────────
# Internal helper: run a git command safely
# ─────────────────────────────────────────────

def _run(cmd: list[str], cwd: str, capture: bool = True) -> tuple[int, str, str]:
    """
    Run a shell command in the given directory.

    Returns:
        (return_code, stdout, stderr)
    """
    try:
        result = subprocess.run(
            cmd,
            cwd=cwd,
            capture_output=capture,
            text=True,
            timeout=60
        )
        return result.returncode, result.stdout.strip(), result.stderr.strip()
    except FileNotFoundError:
        return 1, "", f"Command not found: {cmd[0]}"
    except subprocess.TimeoutExpired:
        return 1, "", f"Command timed out: {' '.join(cmd)}"
    except Exception as e:
        return 1, "", str(e)


# ─────────────────────────────────────────────
# Repository Validation & Initialization
# ─────────────────────────────────────────────

def is_git_repo(path: str) -> bool:
    """Check if the given path is inside a Git repository."""
    code, _, _ = _run(["git", "rev-parse", "--git-dir"], path)
    return code == 0


def get_repo_root(path: str) -> Optional[str]:
    """Return the absolute root path of the Git repository."""
    code, out, _ = _run(["git", "rev-parse", "--show-toplevel"], path)
    return out if code == 0 else None


def init_repo(path: str) -> tuple[bool, str]:
    """
    Initialize a new Git repository at the given path.
    Also configures a default user name/email if not set globally.
    Returns (success, message).
    """
    code, out, err = _run(["git", "init"], path)
    if code != 0:
        return False, err or out

    # Auto-configure user identity if not set (needed for first commit)
    _ensure_git_identity(path)

    return True, out


def _ensure_git_identity(path: str):
    """
    If git user.name / user.email are not configured globally,
    set sensible local defaults so commits don't fail.
    """
    # Check if global identity exists
    code_name, name, _ = _run(["git", "config", "--global", "user.name"], path)
    code_email, email, _ = _run(["git", "config", "--global", "user.email"], path)

    if code_name != 0 or not name.strip():
        # Use system hostname as a fallback name
        hostname = socket.gethostname().split(".")[0]
        _run(["git", "config", "--local", "user.name", f"AI Agent ({hostname})"], path)

    if code_email != 0 or not email.strip():
        _run(["git", "config", "--local", "user.email", "ai-agent@localhost"], path)


def has_any_commits(path: str) -> bool:
    """Return True if the repo has at least one commit."""
    code, _, _ = _run(["git", "rev-parse", "HEAD"], path)
    return code == 0


def get_gitignore_patterns(path: str) -> list[str]:
    """Return patterns from .gitignore if it exists."""
    gitignore = os.path.join(path, ".gitignore")
    if not os.path.exists(gitignore):
        return []
    try:
        with open(gitignore) as f:
            return [l.strip() for l in f if l.strip() and not l.startswith("#")]
    except Exception:
        return []


# ─────────────────────────────────────────────
# Repository State
# ─────────────────────────────────────────────

def get_status(path: str) -> dict:
    """
    Run `git status --porcelain` and parse the output into structured data.

    Returns a dict with:
      - modified: list of modified tracked files
      - added: list of new untracked files
      - deleted: list of deleted files
      - staged: list of already-staged files
      - raw: raw porcelain output
    """
    code, out, err = _run(["git", "status", "--porcelain"], path)

    if code != 0:
        return {"error": err, "modified": [], "added": [], "deleted": [], "staged": [], "raw": ""}

    modified, added, deleted, staged = [], [], [], []

    for line in out.splitlines():
        if len(line) < 3:
            continue
        index_status = line[0]   # staged area
        worktree_status = line[1]  # working tree area
        filename = line[3:]

        # Staged changes (index)
        if index_status in ("M", "A", "D", "R", "C"):
            staged.append(filename)

        # Working tree changes
        if worktree_status == "M":
            modified.append(filename)
        elif worktree_status == "?":
            # Untracked new files (show as ?? in porcelain)
            pass

        # Fully untracked new files
        if line[:2] == "??":
            added.append(filename)

        # Deleted files
        if worktree_status == "D" or index_status == "D":
            deleted.append(filename)

    return {
        "modified": modified,
        "added": added,
        "deleted": deleted,
        "staged": staged,
        "raw": out,
        "error": None
    }


def get_current_branch(path: str) -> str:
    """Return the name of the currently active branch."""
    code, out, _ = _run(["git", "branch", "--show-current"], path)
    if code == 0 and out:
        return out
    # Fallback for detached HEAD state
    code2, out2, _ = _run(["git", "rev-parse", "--short", "HEAD"], path)
    return f"detached@{out2}" if code2 == 0 else "unknown"


def get_all_branches(path: str) -> list[str]:
    """Return a list of all local branches."""
    code, out, _ = _run(["git", "branch"], path)
    if code != 0:
        return []
    return [b.strip().lstrip("* ") for b in out.splitlines()]


def get_remotes(path: str) -> dict:
    """
    Run `git remote -v` and return a dict mapping remote names to URLs.
    Example: {"origin": "https://github.com/user/repo.git"}
    """
    code, out, _ = _run(["git", "remote", "-v"], path)
    remotes = {}
    if code == 0:
        for line in out.splitlines():
            parts = line.split()
            if len(parts) >= 2 and "(fetch)" in line:
                remotes[parts[0]] = parts[1]
    return remotes


def get_last_commit_hash(path: str) -> Optional[str]:
    """Return the short hash of the most recent commit."""
    code, out, _ = _run(["git", "rev-parse", "--short", "HEAD"], path)
    return out if code == 0 else None


def get_commit_log(path: str, n: int = 5) -> list[dict]:
    """Return the last N commits as a list of dicts with hash and message."""
    fmt = "--pretty=format:%h|||%s"
    code, out, _ = _run(["git", "log", fmt, f"-{n}"], path)
    commits = []
    if code == 0:
        for line in out.splitlines():
            parts = line.split("|||", 1)
            if len(parts) == 2:
                commits.append({"hash": parts[0], "message": parts[1]})
    return commits


# ─────────────────────────────────────────────
# Diff Operations
# ─────────────────────────────────────────────

def get_diff(path: str) -> str:
    """Get the unstaged diff (working tree vs index)."""
    _, out, _ = _run(["git", "diff"], path)
    return out


def get_staged_diff(path: str) -> str:
    """Get the staged diff (index vs HEAD)."""
    _, out, _ = _run(["git", "diff", "--cached"], path)
    return out


def get_diff_stat(path: str) -> str:
    """Get a short summary of unstaged changes (files + line counts)."""
    _, out, _ = _run(["git", "diff", "--stat"], path)
    return out


def get_file_diff(path: str, filepath: str) -> str:
    """Get the diff for a single specific file."""
    _, out, _ = _run(["git", "diff", filepath], path)
    if not out:
        _, out, _ = _run(["git", "diff", "--cached", filepath], path)
    return out


def get_untracked_content(path: str, files: list[str], max_chars: int = 3000) -> str:
    """
    For new/untracked files, read a snippet of their content
    so the AI can understand what they contain (since git diff
    shows nothing for untracked files).
    """
    snippets = []
    total = 0
    for f in files[:10]:  # Cap at 10 files
        full_path = os.path.join(path, f)
        if not os.path.isfile(full_path):
            continue
        try:
            with open(full_path, "r", errors="replace") as fh:
                content = fh.read(500)  # First 500 chars per file
            snippets.append(f"=== {f} ===\n{content}")
            total += len(content)
            if total > max_chars:
                break
        except Exception:
            snippets.append(f"=== {f} === [binary or unreadable]")
    return "\n\n".join(snippets)


# ─────────────────────────────────────────────
# Staging Operations
# ─────────────────────────────────────────────

def stage_files(path: str, files: list[str]) -> tuple[bool, str]:
    """
    Stage specific files for commit.
    Returns (success, error_message).
    """
    if not files:
        return False, "No files provided to stage."

    code, _, err = _run(["git", "add", "--"] + files, path)
    if code != 0:
        return False, err
    return True, ""


def stage_all(path: str) -> tuple[bool, str]:
    """Stage all changes (tracked + untracked)."""
    code, _, err = _run(["git", "add", "-A"], path)
    return (code == 0, err)


def unstage_all(path: str) -> tuple[bool, str]:
    """Unstage everything (reset HEAD)."""
    code, _, err = _run(["git", "reset", "HEAD"], path)
    return (code == 0, err)


# ─────────────────────────────────────────────
# Commit Operations
# ─────────────────────────────────────────────

def commit(path: str, message: str) -> tuple[bool, str, str]:
    """
    Create a commit with the given message.

    Returns:
        (success, commit_hash, error_message)
    """
    if not message or not message.strip():
        return False, "", "Commit message cannot be empty."

    code, out, err = _run(["git", "commit", "-m", message], path)

    if code != 0:
        # Check for "nothing to commit" — not a real error
        if "nothing to commit" in out.lower() or "nothing to commit" in err.lower():
            return False, "", "nothing_to_commit"
        return False, "", err or out

    # Extract the new commit hash
    hash_code, hash_out, _ = _run(["git", "rev-parse", "--short", "HEAD"], path)
    commit_hash = hash_out if hash_code == 0 else "unknown"

    return True, commit_hash, ""


# ─────────────────────────────────────────────
# Push Operations
# ─────────────────────────────────────────────

def get_default_branch(path: str) -> str:
    """
    Detect the repo's default branch name.
    Checks remote HEAD first, then falls back to common names.
    Always returns 'main' or 'master' — never a feature branch.
    """
    # Try to get from remote HEAD (most reliable)
    code, out, _ = _run(
        ["git", "symbolic-ref", "refs/remotes/origin/HEAD"], path
    )
    if code == 0 and out:
        # e.g. "refs/remotes/origin/main" → "main"
        return out.strip().split("/")[-1]

    # Try git remote show origin (slower but accurate)
    code2, out2, _ = _run(
        ["git", "remote", "show", "origin"], path
    )
    if code2 == 0:
        for line in out2.splitlines():
            line = line.strip()
            if line.startswith("HEAD branch:"):
                branch = line.split(":", 1)[1].strip()
                if branch and branch != "(unknown)":
                    return branch

    # Check if main exists
    code3, _, _ = _run(["git", "show-ref", "--verify", "refs/heads/main"], path)
    if code3 == 0:
        return "main"

    # Check if master exists
    code4, _, _ = _run(["git", "show-ref", "--verify", "refs/heads/master"], path)
    if code4 == 0:
        return "master"

    # Last resort: use current branch (only if it looks like a default)
    current = get_current_branch(path)
    if current in ("main", "master", "develop", "trunk"):
        return current

    # Hardcoded safe default
    return "main"


def push(path: str, remote: str = "origin", branch: Optional[str] = None) -> tuple[bool, str]:
    """
    Push commits to the remote repository.

    IMPORTANT: Always pushes to the DEFAULT branch (main/master).
    Never pushes to feature branches to prevent accidental repo damage.

    Returns (success, error_message).
    """
    # ALWAYS resolve to the default branch — never push to feature branches
    default = get_default_branch(path)
    current = get_current_branch(path)

    # If we're on a non-default branch, warn but push to default via merge ref
    # For now: only push if we're ON the default branch
    if current != default:
        return False, (
            f"PUSH BLOCKED: You are on branch '{current}', not '{default}'.\n"
            f"The agent only pushes to the default branch '{default}'.\n"
            f"To push manually: git checkout {default} && git merge {current} && git push"
        )

    target_branch = default

    # First try: normal push
    cmd = ["git", "push", remote, target_branch]
    code, out, err = _run(cmd, path)

    if code == 0:
        return True, ""

    combined = (err + " " + out).lower()

    # Handle "no upstream tracking" — set it automatically
    if "set-upstream" in combined or "no upstream" in combined or "has no upstream" in combined:
        cmd_up = ["git", "push", "--set-upstream", remote, target_branch]
        code2, out2, err2 = _run(cmd_up, path)
        if code2 == 0:
            return True, ""
        return False, err2 or out2

    # Handle "rejected" — remote has changes we don't have (need pull first)
    if "rejected" in combined or "non-fast-forward" in combined:
        return False, (
            f"Push rejected: remote '{remote}/{target_branch}' has new commits.\n"
            f"Fix: git pull --rebase origin {target_branch}  then try again."
        )

    # Handle auth errors
    if "authentication" in combined or "permission denied" in combined or "403" in combined:
        return False, (
            "Push failed: authentication error.\n"
            "Fix: make sure your token/SSH key is configured.\n"
            "For HTTPS: git config --global credential.helper store\n"
            "Then push once manually to save credentials."
        )

    return False, err or out


# ─────────────────────────────────────────────
# Repository Info Summary
# ─────────────────────────────────────────────

def get_full_repo_state(path: str) -> dict:
    """
    Collect all relevant repo state in one call.
    Used by the agent to build context for AI analysis.
    """
    status = get_status(path)
    added = status.get("added", [])

    return {
        "branch": get_current_branch(path),
        "remotes": get_remotes(path),
        "status": status,
        "diff": get_diff(path),
        "staged_diff": get_staged_diff(path),
        "diff_stat": get_diff_stat(path),
        "recent_commits": get_commit_log(path, n=3),
        "has_commits": has_any_commits(path),
        # For new files, include their actual content so AI can analyze them
        "untracked_content": get_untracked_content(path, added) if added else "",
    }