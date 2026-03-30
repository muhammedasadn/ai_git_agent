"""
agent.py
========
Core agent orchestrator.

New in v3:
  - Remote setup wizard integrated into preflight
  - auto_push always works in watch/daemon mode
  - watch() and watch_forever() (daemon) both use persistent push
  - Logging goes to file in daemon mode via TeeLogger
  - First-run remote setup: if no remote, asks for URL once
"""

import os
import sys
from datetime import datetime
from typing import Optional

import git_handler
from ai_engine import AIEngine
from validator import Validator, detect_project_type
from watcher import Watcher, TeeLogger
from remote_setup import RemoteSetup, load_state, save_state, get_saved_remote


# ─────────────────────────────────────────────
# Console Logger
# ─────────────────────────────────────────────

class Logger:
    RESET   = "\033[0m"
    BOLD    = "\033[1m"
    DIM     = "\033[2m"
    CYAN    = "\033[96m"
    GREEN   = "\033[92m"
    YELLOW  = "\033[93m"
    RED     = "\033[91m"
    BLUE    = "\033[94m"
    MAGENTA = "\033[95m"
    WHITE   = "\033[97m"

    def __init__(self, verbose=False, use_unicode=False, log_file=None, silent=False):
        self.verbose  = verbose
        self.log_file = log_file
        self.silent   = silent   # silent = don't print to console (daemon mode)
        if use_unicode:
            self.SYM_STEP   = "●"
            self.SYM_OK     = "✓"
            self.SYM_WARN   = "⚠"
            self.SYM_ERR    = "✗"
            self.SYM_ARROW  = "→"
            self.SYM_COMMIT = "◆"
            self.SYM_AI     = "[AI]"
            self.SYM_DIV    = "─"
            self.SYM_INIT   = "★"
        else:
            self.SYM_STEP   = ">>"
            self.SYM_OK     = "[OK]"
            self.SYM_WARN   = "[!!]"
            self.SYM_ERR    = "[XX]"
            self.SYM_ARROW  = "  ->"
            self.SYM_COMMIT = "[*]"
            self.SYM_AI     = "[AI]"
            self.SYM_DIV    = "-"
            self.SYM_INIT   = "[GIT]"

    def _ts(self):
        return datetime.now().strftime("%H:%M:%S")

    def _tty(self):
        return hasattr(sys.stdout, "isatty") and sys.stdout.isatty()

    def _c(self, text, color):
        if self.silent:
            return text
        return f"{color}{text}{self.RESET}" if self._tty() else text

    def _out(self, line: str):
        """Print to console and optionally write to log file."""
        if not self.silent:
            print(line, flush=True)
        if self.log_file:
            try:
                with open(self.log_file, "a") as f:
                    f.write(f"[{self._ts()}] {line}\n")
            except Exception:
                pass

    def step(self, msg):
        sym = self._c(self.SYM_STEP, self.CYAN)
        self._out(f"\n{sym} {self._c(msg, self.BOLD + self.WHITE)}")

    def info(self, msg):
        sym = self._c(self.SYM_ARROW, self.BLUE)
        self._out(f"{sym} {msg}")

    def success(self, msg):
        sym = self._c(self.SYM_OK, self.GREEN)
        self._out(f"  {sym} {self._c(msg, self.GREEN)}")

    def warning(self, msg):
        sym = self._c(self.SYM_WARN, self.YELLOW)
        self._out(f"  {sym} {self._c(msg, self.YELLOW)}")

    def error(self, msg):
        sym = self._c(self.SYM_ERR, self.RED)
        self._out(f"  {sym} {self._c(msg, self.RED)}")

    def ai(self, label, msg):
        sym = self._c(self.SYM_AI, self.MAGENTA)
        self._out(f"  {sym} {self._c(label + ':', self.MAGENTA)} {msg}")

    def commit_line(self, hash_, msg):
        sym = self._c(self.SYM_COMMIT, self.YELLOW)
        h   = self._c(f"[{hash_}]", self.YELLOW)
        m   = self._c(msg, self.WHITE)
        self._out(f"  {sym} {h} {m}")

    def init_action(self, msg):
        sym = self._c(self.SYM_INIT, self.CYAN)
        self._out(f"  {sym} {self._c(msg, self.CYAN)}")

    def divider(self):
        line = self._c(self.SYM_DIV * 60, self.DIM)
        self._out(f"\n{line}")

    def header(self, title):
        self.divider()
        self._out(f"  {self._c(title.upper(), self.BOLD + self.CYAN)}")
        self.divider()

    def dim(self, msg):
        if self.verbose:
            self._out(f"     {self._c(msg, self.DIM)}")

    def plain(self, msg):
        self._out(f"  {msg}")

    def blank(self):
        if not self.silent:
            print(flush=True)

    def confirm(self, question, default=True):
        hint = "[Y/n]" if default else "[y/N]"
        sym = self._c("  ?", self.CYAN)
        try:
            answer = input(f"{sym} {question} {hint}: ").strip().lower()
        except (EOFError, KeyboardInterrupt):
            return default
        if not answer:
            return default
        return answer in ("y", "yes")


# ─────────────────────────────────────────────
# Commit Result
# ─────────────────────────────────────────────

class CommitResult:
    def __init__(self, message, files, hash_="", success=True, error=""):
        self.message = message
        self.files   = files
        self.hash    = hash_
        self.success = success
        self.error   = error


# ─────────────────────────────────────────────
# Agent
# ─────────────────────────────────────────────

class Agent:

    def __init__(self, config: dict, log_file: str = None, silent: bool = False):
        self.config      = config
        self.verbose     = config.get("logging", {}).get("verbose",         False)
        self.auto_push   = config.get("agent",   {}).get("auto_push",       False)
        self.max_commits = config.get("agent",   {}).get("max_commits_per_run", 10)
        self.auto_init   = config.get("agent",   {}).get("auto_init",       True)
        self.interactive = config.get("agent",   {}).get("interactive",     False)
        self.dry_run     = config.get("agent",   {}).get("dry_run",         False)
        self.unicode     = config.get("logging", {}).get("unicode_symbols", False)

        self.log       = Logger(verbose=self.verbose, use_unicode=self.unicode,
                                log_file=log_file, silent=silent)
        self.ai        = AIEngine(config)
        self.validator = Validator(config)
        self.watcher   = Watcher(config)

    # ─────────────────────────────────────────
    # Remote Setup Helper
    # ─────────────────────────────────────────

    def _ensure_remote(self, path: str) -> bool:
        """
        Make sure a remote is configured.
        If not, run the interactive setup wizard.
        Returns True if a remote is available or push should be skipped.
        """
        existing = git_handler.get_remotes(path)
        if existing:
            return True  # Already has a remote

        # Check saved state for URL
        saved_url = get_saved_remote(path)
        if saved_url:
            # Apply saved URL if not already in git config
            code, _, err = git_handler._run(
                ["git", "remote", "add", "origin", saved_url], path
            )
            if code == 0:
                self.log.success(f"Remote restored from saved state: {saved_url}")
            return True

        # No remote anywhere — run wizard if interactive, else warn and skip
        if self.interactive or not self.auto_push:
            self.log.warning("No remote configured.")
            if self.auto_push:
                wizard = RemoteSetup()
                url = wizard.run(path)
                if url:
                    self.auto_push = True
                    return True
                else:
                    self.auto_push = False
                    return False
        else:
            # Daemon/non-interactive: can't ask for URL, just skip push
            self.log.warning("No remote configured — push disabled for this session.")
            self.log.info("Run: python main.py --setup-remote  to add a remote")
            self.auto_push = False

        return False

    # ─────────────────────────────────────────
    # Phase 0: Preflight + Auto-Init
    # ─────────────────────────────────────────

    def _preflight(self, path: str) -> bool:
        self.log.step("Running preflight checks...")

        # 1. Git repo
        if not git_handler.is_git_repo(path):
            if self.auto_init:
                self.log.warning(f"Not a Git repository: {path}")
                self.log.init_action("Running git init automatically...")
                ok, msg = git_handler.init_repo(path)
                if ok:
                    self.log.success("Git repository initialized")
                else:
                    self.log.error(f"git init failed: {msg}")
                    return False
            else:
                self.log.error(f"Not a Git repository: {path}")
                self.log.info("Fix: cd into your project and run:  git init")
                return False
        else:
            self.log.success("Git repository confirmed")

        # 2. Remote setup (if auto_push is requested)
        if self.auto_push:
            self._ensure_remote(path)

        # 3. Ollama
        self.log.info("Checking Ollama / AI engine...")
        available, msg = self.ai.is_available()
        if not available:
            self.log.error(f"AI engine unavailable: {msg}")
            return False
        self.log.success(msg)

        return True

    # ─────────────────────────────────────────
    # Phase 1: Repo Analysis
    # ─────────────────────────────────────────

    def _analyze_repo(self, path: str) -> Optional[dict]:
        self.log.step("I'm checking the repo state...")

        repo_state = git_handler.get_full_repo_state(path)
        status     = repo_state["status"]

        if status.get("error"):
            self.log.error(f"Git error: {status['error']}")
            return None

        branch   = repo_state["branch"]
        remotes  = repo_state["remotes"]
        modified = status.get("modified", [])
        added    = status.get("added",    [])
        deleted  = status.get("deleted",  [])
        total    = len(modified) + len(added) + len(deleted)

        self.log.info(f"Branch : {branch}")
        if remotes:
            for name, url in remotes.items():
                self.log.info(f"Remote : {name} -> {url}")
        else:
            self.log.warning("No remote configured (push will be skipped)")

        if total == 0 and not status.get("staged"):
            self.log.warning("Working tree is clean — nothing to commit.")
            return None

        self.log.success(
            f"Found {total} change(s): "
            f"{len(modified)} modified, {len(added)} new, {len(deleted)} deleted"
        )
        for f in modified[:5]: self.log.dim(f"  modified : {f}")
        for f in added[:5]:    self.log.dim(f"  new file : {f}")
        for f in deleted[:3]:  self.log.dim(f"  deleted  : {f}")
        if total > 8:
            self.log.dim(f"  ... and {total - 8} more")

        return repo_state

    # ─────────────────────────────────────────
    # Phase 2: AI Analysis
    # ─────────────────────────────────────────

    def _ai_analyze(self, repo_state: dict) -> Optional[list]:
        self.log.step("Analyzing changes with AI...")

        status    = repo_state["status"]
        modified  = status.get("modified", [])
        added     = status.get("added",    [])
        deleted   = status.get("deleted",  [])
        all_files = modified + added + deleted

        if not all_files:
            self.log.warning("No files to commit.")
            return None

        is_first = not repo_state.get("has_commits", True)

        if is_first:
            self.log.info("First commit in repository — generating initial commit message...")
            try:
                msg = self.ai.generate_initial_commit_message(repo_state)
            except Exception:
                msg = "chore: initial project setup"
            self.log.ai("Message", msg)
            return [{"message": msg, "files": all_files, "reason": "Initial commit"}]

        # AI summary
        try:
            summary = self.ai.summarize_changes(repo_state)
            self.log.ai("Summary", summary)
        except Exception as e:
            self.log.warning(f"AI summary unavailable: {e}")

        # Smart commit decision
        junk = ["package-lock.json", "yarn.lock", ".DS_Store", "Thumbs.db", ".pyc"]
        real_files = [f for f in all_files if not any(j in f for j in junk)]

        if not real_files:
            self.log.warning("Only auto-generated files detected.")
            if not self.interactive or not self.log.confirm("Commit anyway?", default=False):
                return None

        # AI commit planning
        self.log.step("Planning logical commits...")
        try:
            plans = self.ai.plan_commits(repo_state)
        except Exception as e:
            self.log.warning(f"AI planning failed ({e}) — single commit fallback")
            try:
                msg = self.ai.generate_commit_message(repo_state)
            except Exception:
                msg = "chore: update project files"
            plans = [{"message": msg, "files": all_files, "reason": "Fallback"}]

        self.log.success(f"AI planned {len(plans)} commit(s)")
        for i, p in enumerate(plans, 1):
            self.log.plain(f"  {i}. {p['message']}")
            if p.get("reason"):
                self.log.dim(f"     Reason : {p['reason']}")
            for f in p.get("files", [])[:3]:
                self.log.dim(f"     File   : {f}")
            extra = len(p.get("files", [])) - 3
            if extra > 0:
                self.log.dim(f"     ... and {extra} more")

        if len(plans) > self.max_commits:
            plans = plans[:self.max_commits]

        if self.interactive:
            if not self.log.confirm(f"Proceed with {len(plans)} commit(s)?"):
                return None

        return plans

    # ─────────────────────────────────────────
    # Phase 3: Validation
    # ─────────────────────────────────────────

    def _validate(self, path: str) -> bool:
        self.log.step("Running build/test validation...")
        ptype  = self.validator.detect(path)
        self.log.info(f"Project type : {ptype.value}")
        result = self.validator.run(path, ptype)

        if result.skipped:
            self.log.info(f"Validation skipped ({ptype.value})")
            return True

        if result.passed:
            self.log.success("Build/tests passed")
            return True

        self.log.error("Build/tests FAILED — stopping before commit")
        err = (result.error or result.output).strip()
        for line in err.splitlines()[-15:]:
            self.log.plain(f"  | {line}")

        try:
            explanation = self.ai.analyze_error(err, ptype.value)
            self.log.ai("Explanation", explanation)
        except Exception:
            pass

        if self.interactive:
            if self.log.confirm("Commit anyway (dangerous)?", default=False):
                return True

        return False

    # ─────────────────────────────────────────
    # Phase 4: Execute Commits
    # ─────────────────────────────────────────

    def _execute_commits(self, path: str, plans: list, repo_state: dict) -> list:
        if self.dry_run:
            self.log.step("[DRY RUN] Planned commits:")
            for i, p in enumerate(plans, 1):
                self.log.plain(f"  {i}. {p['message']}")
            self.log.info("Dry run — no changes made.")
            return []

        self.log.step("Creating commits...")
        results = []
        status  = repo_state["status"]
        all_changed = set(
            status.get("modified", []) +
            status.get("added",    []) +
            status.get("deleted",  [])
        )
        done = set()

        for i, plan in enumerate(plans, 1):
            message = plan["message"]
            planned = plan.get("files", [])
            is_last = (i == len(plans))

            self.log.info(f"Commit {i}/{len(plans)}: {message}")

            to_stage = [f for f in planned if f in all_changed and f not in done]

            if is_last:
                remaining = all_changed - done
                for f in remaining:
                    if f not in to_stage:
                        to_stage.append(f)

            if not to_stage:
                self.log.warning("  No files — skipping")
                continue

            ok, err = git_handler.stage_files(path, to_stage)
            if not ok:
                ok, err = git_handler.stage_all(path)
                if not ok:
                    self.log.error(f"  Stage failed: {err}")
                    results.append(CommitResult(message=message, files=to_stage,
                                                success=False, error=err))
                    continue

            success, hash_, err = git_handler.commit(path, message)
            if success:
                self.log.commit_line(hash_, message)
                results.append(CommitResult(message=message, files=to_stage,
                                            hash_=hash_, success=True))
                done.update(to_stage)
            elif err == "nothing_to_commit":
                self.log.warning("  Nothing staged — skipping")
            else:
                self.log.error(f"  Commit failed: {err}")
                results.append(CommitResult(message=message, files=to_stage,
                                            success=False, error=err))

        return results

    # ─────────────────────────────────────────
    # Phase 5: Push
    # ─────────────────────────────────────────

    def _push(self, path: str) -> bool:
        remotes = git_handler.get_remotes(path)
        if not remotes:
            self.log.warning("No remote — skipping push")
            return False

        remote = list(remotes.keys())[0]
        branch = git_handler.get_current_branch(path)
        self.log.step(f"Pushing to '{remote}' ({branch})...")

        success, err = git_handler.push(path, remote, branch)
        if success:
            self.log.success(f"Pushed to {remote}/{branch}")
            return True
        else:
            self.log.error(f"Push failed: {err}")
            self.log.info("Try: git push  (you may need to authenticate)")
            return False

    # ─────────────────────────────────────────
    # Phase 6: Report
    # ─────────────────────────────────────────

    def _report(self, results: list, pushed: bool, path: str):
        self.log.header("Agent Run Complete")

        ok  = [r for r in results if r.success]
        bad = [r for r in results if not r.success]

        if ok:
            self.log.success(f"{len(ok)} commit(s) created:")
            for r in ok:
                self.log.commit_line(r.hash, r.message)

        if bad:
            self.log.error(f"{len(bad)} commit(s) failed:")
            for r in bad:
                self.log.error(f"  '{r.message}' -> {r.error}")

        if pushed:
            self.log.success("Commits pushed to remote")
        elif ok:
            self.log.info("Commits are local only.")

        if not ok and not bad:
            self.log.info("No commits created.")

        recent = git_handler.get_commit_log(path, n=3)
        if recent:
            self.log.blank()
            self.log.info("Recent commits:")
            for c in recent:
                self.log.plain(f"  [{c['hash']}] {c['message']}")

        self.log.blank()

    # ─────────────────────────────────────────
    # Main Run
    # ─────────────────────────────────────────

    def run(self, path: str) -> bool:
        path = os.path.abspath(path)
        self.log.header(f"AI Git Agent — {path}")

        if self.dry_run:
            self.log.warning("DRY RUN MODE — no commits will be made")

        if not self._preflight(path):
            return False

        repo_state = self._analyze_repo(path)
        if repo_state is None:
            return True

        plans = self._ai_analyze(repo_state)
        if plans is None:
            return True

        if not self._validate(path):
            self.log.error("Aborting: fix build errors, then re-run.")
            return False

        results = self._execute_commits(path, plans, repo_state)

        pushed = False
        if not self.dry_run and self.auto_push and any(r.success for r in results):
            pushed = self._push(path)

        self._report(results, pushed, path)
        return any(r.success for r in results) or len(results) == 0

    # ─────────────────────────────────────────
    # Setup Remote (standalone command)
    # ─────────────────────────────────────────

    def setup_remote(self, path: str):
        """Run the remote setup wizard as a standalone command."""
        path = os.path.abspath(path)
        self.log.header(f"Remote Setup — {path}")

        if not git_handler.is_git_repo(path):
            if self.auto_init:
                ok, msg = git_handler.init_repo(path)
                if not ok:
                    self.log.error(f"Cannot initialize repo: {msg}")
                    return
            else:
                self.log.error("Not a Git repository.")
                return

        wizard = RemoteSetup()
        url = wizard.run(path)
        if url:
            self.auto_push = True
            self.log.success(f"Remote configured: {url}")
            self.log.info("The agent will now push automatically.")
        else:
            self.log.warning("Remote setup skipped. You can run this again later.")

    # ─────────────────────────────────────────
    # Foreground Watch Mode
    # ─────────────────────────────────────────

    def watch(self, path: str):
        """
        Foreground watch: runs in terminal, Ctrl+C to stop.
        Auto-pushes if remote is configured.
        """
        path = os.path.abspath(path)
        self.log.header(f"AI Git Agent — Watch Mode — {path}")

        # Enable push for watch mode
        self.auto_push = True
        self.interactive = False  # No prompts in watch mode

        if not self._preflight(path):
            return

        remotes = git_handler.get_remotes(path)
        if remotes:
            self.log.success(f"Auto-push enabled -> {list(remotes.values())[0]}")
        else:
            self.log.warning("No remote — commits will be local only")
            self.log.info("Run: python main.py --setup-remote  to add GitHub/GitLab")

        self.log.blank()
        self.log.info("Watching for changes... (Ctrl+C to stop)")
        self.log.blank()

        def on_change(repo_path):
            self.run(repo_path)

        self.watcher.start(path, on_change, forever=False)

    # ─────────────────────────────────────────
    # Background (Daemon) Watch Mode
    # ─────────────────────────────────────────

    def watch_forever(self, path: str, log_file: str = None):
        """
        Background daemon watch: runs forever, never exits.
        Used by --daemon start. All output goes to log file.
        """
        path = os.path.abspath(path)

        # Reconfigure logger for daemon mode (file-only output)
        self.log = Logger(
            verbose=self.verbose,
            use_unicode=False,
            log_file=log_file or os.path.join(path, ".agent_log.txt"),
            silent=True  # Don't print to stdout (we're in background)
        )

        self.auto_push   = True
        self.interactive = False  # Never ask questions in background

        # Preflight silently
        if not self._preflight(path):
            return

        self.log.step("Daemon started — watching forever")
        self.log.info(f"Repo: {path}")

        def on_change(repo_path):
            self.run(repo_path)

        self.watcher.start(
            path,
            on_change,
            log_file=log_file or os.path.join(path, ".agent_log.txt"),
            forever=True   # Never exit on errors or signals
        )

    # ─────────────────────────────────────────
    # Undo Last Commit
    # ─────────────────────────────────────────

    def undo_last_commit(self, path: str):
        path = os.path.abspath(path)
        self.log.header(f"Undo Last Commit — {path}")

        if not git_handler.is_git_repo(path):
            self.log.error("Not a Git repository.")
            return
        if not git_handler.has_any_commits(path):
            self.log.error("No commits to undo.")
            return

        recent = git_handler.get_commit_log(path, n=1)
        if recent:
            self.log.info(f"Will undo: [{recent[0]['hash']}] {recent[0]['message']}")

        if self.interactive:
            if not self.log.confirm("Undo this commit? (changes are kept)"):
                self.log.info("Aborted.")
                return

        code, out, err = git_handler._run(["git", "reset", "--soft", "HEAD~1"], path)
        if code == 0:
            self.log.success("Last commit undone. Changes are back in working tree.")
        else:
            self.log.error(f"Undo failed: {err or out}")

    # ─────────────────────────────────────────
    # Create Branch
    # ─────────────────────────────────────────

    def create_branch(self, path: str, branch_name: str = "auto"):
        path = os.path.abspath(path)
        self.log.header(f"Create Branch — {path}")

        if not git_handler.is_git_repo(path):
            self.log.error("Not a Git repository.")
            return

        if not branch_name or branch_name == "auto":
            self.log.step("Asking AI to suggest a branch name...")
            repo_state = git_handler.get_full_repo_state(path)
            try:
                branch_name = self.ai.suggest_branch_name(repo_state)
                self.log.ai("Suggested", branch_name)
            except Exception:
                branch_name = "feature/ai-changes"

        branch_name = branch_name.replace(" ", "-").lower()[:50]
        self.log.info(f"Creating: {branch_name}")

        code, _, err = git_handler._run(["git", "checkout", "-b", branch_name], path)
        if code == 0:
            self.log.success(f"Switched to new branch: {branch_name}")
        else:
            self.log.error(f"Failed: {err}")

    # ─────────────────────────────────────────
    # Dashboard
    # ─────────────────────────────────────────

    def show_dashboard(self, path: str):
        path = os.path.abspath(path)
        self.log.header(f"Repository Dashboard — {path}")

        if not git_handler.is_git_repo(path):
            self.log.error("Not a Git repository.")
            return

        branch  = git_handler.get_current_branch(path)
        remotes = git_handler.get_remotes(path)
        status  = git_handler.get_status(path)
        commits = git_handler.get_commit_log(path, n=5)
        ptype   = detect_project_type(path)

        # Check daemon state
        from daemon import _read_pid, _is_process_alive
        pid     = _read_pid(path)
        running = pid and _is_process_alive(pid)

        self.log.info(f"Branch       : {branch}")
        self.log.info(f"Project type : {ptype.value}")
        if remotes:
            for n, u in remotes.items():
                self.log.info(f"Remote       : {n} -> {u}")
        else:
            self.log.warning("Remote       : none  (run --setup-remote to add one)")

        daemon_status = f"RUNNING (PID {pid})" if running else "NOT RUNNING"
        if running:
            self.log.success(f"Daemon       : {daemon_status}")
        else:
            self.log.warning(f"Daemon       : {daemon_status}")

        self.log.blank()
        modified = status.get("modified", [])
        added    = status.get("added",    [])
        deleted  = status.get("deleted",  [])
        total    = len(modified) + len(added) + len(deleted)

        if total == 0:
            self.log.success("Working tree is clean")
        else:
            self.log.plain(f"  Uncommitted: {total} file(s)")
            for f in modified: self.log.plain(f"    [M] {f}")
            for f in added:    self.log.plain(f"    [A] {f}")
            for f in deleted:  self.log.plain(f"    [D] {f}")

        if commits:
            self.log.blank()
            self.log.plain("  Recent commits:")
            for c in commits:
                self.log.plain(f"    [{c['hash']}] {c['message']}")
        else:
            self.log.warning("No commits yet.")

        self.log.blank()
        available, msg = self.ai.is_available()
        if available:
            self.log.success(f"AI Engine    : {msg}")
        else:
            self.log.error(f"AI Engine    : {msg}")
        self.log.blank()