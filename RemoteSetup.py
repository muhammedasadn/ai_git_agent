"""
remote_setup.py
===============
Interactive GitHub/GitLab remote setup wizard.

When the user starts the agent on a project with no remote configured,
this module:
  1. Asks for the GitHub/GitLab repo URL
  2. Validates the URL format
  3. Adds it as 'origin' with git remote add
  4. Tests the connection (optional)
  5. Saves the URL to .agent_remote so it's remembered

This runs ONCE per project — after that, the agent uses the saved remote.
"""

import os
import re
import sys
import json

import git_handler


# ─────────────────────────────────────────────
# State file — remembers the remote per project
# ─────────────────────────────────────────────

AGENT_STATE_FILE = ".agent_state.json"


def _state_path(repo_path: str) -> str:
    return os.path.join(repo_path, AGENT_STATE_FILE)


def load_state(repo_path: str) -> dict:
    """Load agent state for this repo (remote URL, push enabled, etc.)."""
    path = _state_path(repo_path)
    if os.path.exists(path):
        try:
            with open(path) as f:
                return json.load(f)
        except Exception:
            pass
    return {}


def save_state(repo_path: str, state: dict):
    """Save agent state for this repo."""
    path = _state_path(repo_path)
    try:
        with open(path, "w") as f:
            json.dump(state, f, indent=2)
        # Add to .gitignore so it doesn't get committed
        _add_to_gitignore(repo_path, AGENT_STATE_FILE)
    except Exception as e:
        print(f"  Warning: could not save state: {e}")


def _add_to_gitignore(repo_path: str, pattern: str):
    """Add a pattern to .gitignore if not already there."""
    gitignore = os.path.join(repo_path, ".gitignore")
    try:
        existing = ""
        if os.path.exists(gitignore):
            with open(gitignore) as f:
                existing = f.read()
        if pattern not in existing:
            with open(gitignore, "a") as f:
                f.write(f"\n# AI Git Agent\n{pattern}\n")
    except Exception:
        pass


# ─────────────────────────────────────────────
# URL Validation
# ─────────────────────────────────────────────

def validate_remote_url(url: str) -> tuple[bool, str]:
    """
    Validate a GitHub/GitLab/Bitbucket URL.

    Supports:
      https://github.com/user/repo.git
      https://github.com/user/repo
      git@github.com:user/repo.git
      https://gitlab.com/user/repo.git
    """
    url = url.strip()

    if not url:
        return False, "URL cannot be empty."

    # HTTPS format
    https_pattern = r"^https?://[a-zA-Z0-9\-\.]+/[a-zA-Z0-9\-_\.]+/[a-zA-Z0-9\-_\.]+(?:\.git)?$"
    # SSH format
    ssh_pattern = r"^git@[a-zA-Z0-9\-\.]+:[a-zA-Z0-9\-_\.]+/[a-zA-Z0-9\-_\.]+(?:\.git)?$"

    if re.match(https_pattern, url) or re.match(ssh_pattern, url):
        return True, ""

    # Loose check: at minimum must contain a slash and a dot
    if "/" in url and "." in url:
        return True, ""  # Accept loosely

    return False, (
        f"Invalid URL format: {url}\n"
        "  Expected: https://github.com/username/repo  or  git@github.com:username/repo.git"
    )


def normalize_url(url: str) -> str:
    """Ensure the URL ends with .git for consistency."""
    url = url.strip()
    if url and not url.endswith(".git"):
        url += ".git"
    return url


# ─────────────────────────────────────────────
# Color helpers (inline, no Logger dependency)
# ─────────────────────────────────────────────

def _tty():
    return hasattr(sys.stdout, "isatty") and sys.stdout.isatty()

def _cyan(t):   return f"\033[96m{t}\033[0m" if _tty() else t
def _green(t):  return f"\033[92m{t}\033[0m" if _tty() else t
def _yellow(t): return f"\033[93m{t}\033[0m" if _tty() else t
def _red(t):    return f"\033[91m{t}\033[0m" if _tty() else t
def _bold(t):   return f"\033[1m{t}\033[0m"  if _tty() else t
def _dim(t):    return f"\033[2m{t}\033[0m"  if _tty() else t


# ─────────────────────────────────────────────
# Main Setup Wizard
# ─────────────────────────────────────────────

class RemoteSetup:
    """
    Interactive wizard to set up a GitHub/GitLab remote for the project.

    Usage:
        setup = RemoteSetup()
        url = setup.run(repo_path)
        # url is the configured remote URL, or None if skipped
    """

    def run(self, repo_path: str) -> str | None:
        """
        Run the remote setup wizard.
        Returns the remote URL if configured, None if skipped.
        """
        print()
        print(_bold(_cyan("=" * 60)))
        print(_bold(_cyan("  REMOTE REPOSITORY SETUP")))
        print(_bold(_cyan("=" * 60)))
        print()
        print("  This project has no remote (GitHub/GitLab) configured.")
        print("  The agent needs a remote to push your commits automatically.")
        print()
        print(_dim("  Options:"))
        print(_dim("    1. Enter your GitHub/GitLab repo URL now"))
        print(_dim("    2. Skip (commits will be local only)"))
        print()

        # Check saved state first
        state = load_state(repo_path)
        if state.get("remote_url"):
            saved = state["remote_url"]
            print(f"  Found saved remote: {_cyan(saved)}")
            answer = self._ask("Use this remote? [Y/n]", default="y")
            if answer.lower() in ("", "y", "yes"):
                return self._apply_remote(repo_path, saved, state)

        # Ask for URL
        while True:
            print()
            url = self._ask(
                _cyan("  Enter remote URL") +
                _dim(" (or press Enter to skip)") +
                "\n  > "
            )

            if not url.strip():
                print()
                print(_yellow("  [!!] Skipping remote setup."))
                print(_yellow("       Commits will be saved locally only."))
                print(_yellow("       Run again with --setup-remote to configure later."))
                return None

            valid, err = validate_remote_url(url)
            if not valid:
                print(_red(f"  [XX] {err}"))
                print()
                print(_dim("  Example URLs:"))
                print(_dim("    https://github.com/yourusername/your-repo"))
                print(_dim("    git@github.com:yourusername/your-repo.git"))
                continue

            url = normalize_url(url)
            print()
            print(f"  Remote URL: {_cyan(url)}")

            # Ask about push authentication method
            push_method = self._ask_push_method(url)

            confirm = self._ask(f"  Add this as remote origin? [Y/n]", default="y")
            if confirm.lower() not in ("", "y", "yes"):
                continue

            return self._apply_remote(repo_path, url, state, push_method)

    def _apply_remote(self, repo_path: str, url: str,
                      state: dict, push_method: str = "https") -> str | None:
        """Add the remote to git config and save state."""

        # Remove existing origin if present
        existing = git_handler.get_remotes(repo_path)
        if "origin" in existing:
            if existing["origin"] == url:
                print(_green("  [OK] Remote already configured correctly."))
                return url
            # Different URL — update it
            code, _, err = git_handler._run(
                ["git", "remote", "set-url", "origin", url], repo_path
            )
            if code == 0:
                print(_green(f"  [OK] Remote updated to: {url}"))
            else:
                print(_red(f"  [XX] Failed to update remote: {err}"))
                return None
        else:
            code, _, err = git_handler._run(
                ["git", "remote", "add", "origin", url], repo_path
            )
            if code != 0:
                print(_red(f"  [XX] Failed to add remote: {err}"))
                return None
            print(_green(f"  [OK] Remote 'origin' added: {url}"))

        # Save to state
        state["remote_url"]    = url
        state["push_method"]   = push_method
        state["auto_push"]     = True
        save_state(repo_path, state)

        # Print auth instructions if HTTPS
        if url.startswith("https://") and "github.com" in url:
            self._print_https_instructions(url)

        return url

    def _ask_push_method(self, url: str) -> str:
        """Ask user how they authenticate for pushing."""
        if url.startswith("git@"):
            print(_green("  [OK] SSH URL detected — using SSH key authentication"))
            print(_dim("       Make sure your SSH key is added to GitHub/GitLab."))
            return "ssh"

        # HTTPS — explain token requirement
        print()
        print(_yellow("  [!!] HTTPS URL detected."))
        print("       GitHub requires a Personal Access Token (PAT) for pushing.")
        print()
        print(_dim("  To create a token:"))
        print(_dim("    1. Go to: https://github.com/settings/tokens/new"))
        print(_dim("    2. Check 'repo' scope"))
        print(_dim("    3. Copy the token"))
        print()
        print(_dim("  To store credentials locally (one time):"))
        print(_dim("    git config --global credential.helper store"))
        print(_dim("    Then push once manually — git will save your token."))
        print()
        return "https"

    def _print_https_instructions(self, url: str):
        """Print post-setup instructions for HTTPS push."""
        print()
        print(_bold("  IMPORTANT — First Push Setup:"))
        print("  Before the agent can push automatically, authenticate once:")
        print()
        print(_cyan("    git config --global credential.helper store"))
        print(_cyan("    git push origin main"))
        print()
        print("  Git will ask for username + token, then remember it forever.")
        print()

    def _ask(self, prompt: str, default: str = "") -> str:
        """Safe input() wrapper."""
        try:
            return input(f"  {prompt} ").strip() or default
        except (EOFError, KeyboardInterrupt):
            return default


# ─────────────────────────────────────────────
# Quick helpers used by agent
# ─────────────────────────────────────────────

def get_saved_remote(repo_path: str) -> str | None:
    """Return the saved remote URL from state file, or None."""
    state = load_state(repo_path)
    return state.get("remote_url")


def is_push_enabled(repo_path: str) -> bool:
    """Return True if push is enabled in saved state."""
    state = load_state(repo_path)
    return state.get("auto_push", False)