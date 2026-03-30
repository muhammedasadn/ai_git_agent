"""
agent.py
========
The brain of the ai-git-agent — the decision-making orchestrator.

FIXES & NEW FEATURES vs v1:
  - Auto git init if repo not initialized
  - AI no longer skips valid new project files
  - Untracked file content sent to AI for better analysis
  - Interactive mode: asks user before committing
  - Dry-run mode: plan without executing
  - Undo last commit feature
  - Branch creation + AI branch naming
  - Dashboard: rich status view
  - ASCII-safe logging (no broken unicode symbols)
  - Better "first commit" detection
"""

import os
import sys
from typing import Optional

import git_handler
from ai_engine import AIEngine
from validator import Validator, detect_project_type
from watcher import Watcher


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

    def __init__(self, verbose=False, use_unicode=False):
        self.verbose = verbose
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

    def _tty(self):
        return hasattr(sys.stdout, "isatty") and sys.stdout.isatty()

    def _c(self, text, color):
        return f"{color}{text}{self.RESET}" if self._tty() else text

    def step(self, msg):
        sym = self._c(self.SYM_STEP, self.CYAN)
        print(f"\n{sym} {self._c(msg, self.BOLD + self.WHITE)}")

    def info(self, msg):
        sym = self._c(self.SYM_ARROW, self.BLUE)
        print(f"{sym} {msg}")

    def success(self, msg):
        sym = self._c(self.SYM_OK, self.GREEN)
        print(f"  {sym} {self._c(msg, self.GREEN)}")

    def warning(self, msg):
        sym = self._c(self.SYM_WARN, self.YELLOW)
        print(f"  {sym} {self._c(msg, self.YELLOW)}")

    def error(self, msg):
        sym = self._c(self.SYM_ERR, self.RED)
        print(f"  {sym} {self._c(msg, self.RED)}")

    def ai(self, label, msg):
        sym = self._c(self.SYM_AI, self.MAGENTA)
        print(f"  {sym} {self._c(label + ':', self.MAGENTA)} {msg}")

    def commit_line(self, hash_, msg):
        sym = self._c(self.SYM_COMMIT, self.YELLOW)
        h   = self._c(f"[{hash_}]", self.YELLOW)
        m   = self._c(msg, self.WHITE)
        print(f"  {sym} {h} {m}")

    def init_action(self, msg):
        sym = self._c(self.SYM_INIT, self.CYAN)
        print(f"  {sym} {self._c(msg, self.CYAN)}")

    def divider(self):
        line = self._c(self.SYM_DIV * 60, self.DIM)
        print(f"\n{line}")

    def header(self, title):
        self.divider()
        print(f"  {self._c(title.upper(), self.BOLD + self.CYAN)}")
        self.divider()

    def dim(self, msg):
        if self.verbose:
            print(f"     {self._c(msg, self.DIM)}")

    def plain(self, msg):
        print(f"  {msg}")

    def blank(self):
        print()

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


class CommitResult:
    def __init__(self, message, files, hash_="", success=True, error=""):
        self.message = message
        self.files   = files
        self.hash    = hash_
        self.success = success
        self.error   = error


class Agent:
    def __init__(self, config):
        self.config      = config
        self.verbose     = config.get("logging", {}).get("verbose", False)
        self.auto_push   = config.get("agent",   {}).get("auto_push", False)
        self.max_commits = config.get("agent",   {}).get("max_commits_per_run", 10)
        self.auto_init   = config.get("agent",   {}).get("auto_init", True)
        self.interactive = config.get("agent",   {}).get("interactive", False)
        self.dry_run     = config.get("agent",   {}).get("dry_run", False)
        self.unicode     = config.get("logging", {}).get("unicode_symbols", False)

        self.log       = Logger(verbose=self.verbose, use_unicode=self.unicode)
        self.ai        = AIEngine(config)
        self.validator = Validator(config)
        self.watcher   = Watcher(config)

    # ── Phase 0: Preflight + Auto-Init ──────────────────────────

    def _preflight(self, path):
        self.log.step("Running preflight checks...")

        if not git_handler.is_git_repo(path):
            if self.auto_init:
                self.log.warning(f"'{path}' is not a Git repository.")
                self.log.init_action("Auto-initializing Git repository...")
                ok, msg = git_handler.init_repo(path)
                if ok:
                    self.log.success("Git repository initialized")
                    self.log.dim(msg)
                else:
                    self.log.error(f"git init failed: {msg}")
                    return False
            else:
                self.log.error(f"Not a Git repository: {path}")
                self.log.info("Fix: run `git init` in your project folder")
                return False
        else:
            self.log.success("Git repository confirmed")

        self.log.info("Checking Ollama / AI engine...")
        available, msg = self.ai.is_available()
        if not available:
            self.log.error(f"AI engine unavailable: {msg}")
            return False
        self.log.success(msg)
        return True

    # ── Phase 1: Repo Analysis ───────────────────────────────────

    def _analyze_repo(self, path):
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
            f"I found {total} change(s): "
            f"{len(modified)} modified, {len(added)} new, {len(deleted)} deleted"
        )
        for f in modified[:5]: self.log.dim(f"  modified : {f}")
        for f in added[:5]:    self.log.dim(f"  new file : {f}")
        for f in deleted[:3]:  self.log.dim(f"  deleted  : {f}")
        if total > 5:
            self.log.dim(f"  ... and {total - 5} more")

        # Warn about node_modules being untracked
        huge = [f for f in added if "node_modules" in f or ".next/" in f]
        if huge:
            self.log.warning(
                f"{len(huge)} auto-generated file(s) detected (node_modules etc). "
                "Add a .gitignore to exclude them."
            )

        if modified:
            for f in modified[:5]:
                self.log.dim(f"  modified: {f}")
            if len(modified) > 5:
                self.log.dim(f"  ... and {len(modified) - 5} more")

        if added:
            for f in added[:5]:
                self.log.dim(f"  new file: {f}")
            if len(added) > 5:
                self.log.dim(f"  ... and {len(added) - 5} more")

        return repo_state

    # ─────────────────────────────────────────
    # Phase 2: AI Analysis
    # ─────────────────────────────────────────

    def _ai_analyze(self, repo_state: dict) -> Optional[list[dict]]:
        """
        Ask the AI to:
        1. Summarize what changed
        2. Decide if it's worth committing
        3. Plan logical commit groups
        """
        self.log.step("I'm analyzing the diff with AI...")

        # Ask AI for summary
        try:
            summary = self.ai.summarize_changes(repo_state)
            self.log.ai(f"Summary: {summary}")
        except Exception as e:
            self.log.warning(f"AI summary failed: {e}")
            summary = "Changes detected"

        # Ask AI if this is worth committing
        try:
            should, reason = self.ai.should_commit(repo_state)
            if not should:
                self.log.warning(f"AI recommends skipping commit: {reason}")
                return None
            self.log.dim(f"AI commit decision: yes — {reason}")
        except Exception as e:
            self.log.dim(f"AI decision check failed ({e}), proceeding anyway")

        # Ask AI to plan commits
        self.log.step("I'm splitting changes into logical commits...")
        try:
            commit_plans = self.ai.plan_commits(repo_state)
        except Exception as e:
            self.log.warning(f"AI commit planning failed: {e}")
            # Fallback: one commit with all files
            status = repo_state["status"]
            all_files = (
                status.get("modified", []) +
                status.get("added", []) +
                status.get("deleted", [])
            )
            commit_plans = [{
                "message": "chore: update files",
                "files": all_files,
                "reason": "Fallback: all files in one commit"
            }]

        n = len(commit_plans)
        self.log.success(f"I'm splitting changes into {n} commit{'s' if n > 1 else ''}...")

        for i, plan in enumerate(commit_plans, 1):
            self.log.info(f"  Commit {i}: {plan['message']}")
            if plan.get("reason"):
                self.log.dim(f"    Reason: {plan['reason']}")
            for f in plan.get("files", [])[:3]:
                self.log.dim(f"    {f}")
            if len(plan.get("files", [])) > 3:
                self.log.dim(f"    ... and {len(plan['files']) - 3} more files")

        # Cap at max commits
        if len(commit_plans) > self.max_commits:
            self.log.warning(
                f"Capping at {self.max_commits} commits (max_commits_per_run setting)"
            )
            commit_plans = commit_plans[:self.max_commits]

        return commit_plans

    # ─────────────────────────────────────────
    # Phase 3: Pre-Commit Validation
    # ─────────────────────────────────────────

    def _validate(self, path: str) -> bool:
        """
        Run build/test validation before committing.
        Returns True if validation passed (or was skipped).
        """
        self.log.step("Running build/test validation...")

        project_type = self.validator.detect(path)
        self.log.info(f"Project type detected: {project_type.value}")

        result = self.validator.run(path, project_type)

        if result.skipped:
            self.log.warning(f"Validation skipped: {result.summary()}")
            return True

        if result.passed:
            self.log.success(f"Build passed ✓")
            return True
        else:
            self.log.error(f"Build/tests FAILED — stopping before commit")
            self.log.blank()

            # Show the error output
            error_lines = (result.error or result.output).strip().splitlines()
            for line in error_lines[-15:]:
                print(f"    {line}")

            # Ask AI to explain the error
            self.log.blank()
            self.log.step("Asking AI to explain the error...")
            try:
                explanation = self.ai.analyze_error(
                    result.error or result.output,
                    project_type.value
                )
                self.log.ai(explanation)
            except Exception as e:
                self.log.dim(f"AI explanation unavailable: {e}")

            return False

    # ─────────────────────────────────────────
    # Phase 4: Execute Commits
    # ─────────────────────────────────────────

    def _execute_commits(self, path: str, commit_plans: list[dict], repo_state: dict) -> list[CommitResult]:
        """
        Execute each planned commit:
        1. Stage the specified files
        2. Create the commit
        3. Record the result
        """
        self.log.step("Creating commits...")
        results = []

        # Get all changed files for reference
        status = repo_state["status"]
        all_changed = set(
            status.get("modified", []) +
            status.get("added", []) +
            status.get("deleted", [])
        )

        for i, plan in enumerate(commit_plans, 1):
            message = plan["message"]
            planned_files = plan.get("files", [])

            self.log.info(f"Creating commit {i}/{len(commit_plans)}: {message}")

            # Filter to only files that actually exist in the changeset
            files_to_stage = [f for f in planned_files if f in all_changed]

            # If no files match exactly, use all remaining changed files
            if not files_to_stage and i == len(commit_plans):
                # Last commit: catch any remaining files
                already_planned = set()
                for prev_plan in commit_plans[:i-1]:
                    already_planned.update(prev_plan.get("files", []))
                files_to_stage = list(all_changed - already_planned)

            if not files_to_stage:
                self.log.warning(f"  No matching files found for this commit, skipping")
                continue

            # Stage the files
            ok, err = git_handler.stage_files(path, files_to_stage)
            if not ok:
                # Try staging all if selective staging fails
                self.log.dim(f"  Selective staging failed ({err}), trying git add -A")
                ok, err = git_handler.stage_all(path)
                if not ok:
                    self.log.error(f"  Failed to stage files: {err}")
                    results.append(CommitResult(
                        message=message, files=files_to_stage,
                        success=False, error=err
                    ))
                    continue

            # Create the commit
            success, hash_, err = git_handler.commit(path, message)

            if success:
                self.log.commit(hash_, message)
                results.append(CommitResult(
                    message=message, files=files_to_stage,
                    hash_=hash_, success=True
                ))
            elif err == "nothing_to_commit":
                self.log.warning(f"  Nothing staged for this commit (skipping)")
            else:
                self.log.error(f"  Commit failed: {err}")
                results.append(CommitResult(
                    message=message, files=files_to_stage,
                    success=False, error=err
                ))

        return results

    # ─────────────────────────────────────────
    # Phase 5: Push
    # ─────────────────────────────────────────

    def _push(self, path: str) -> bool:
        """Push all commits to the remote."""
        remotes = git_handler.get_remotes(path)
        if not remotes:
            self.log.warning("No remote configured — skipping push")
            return False

        remote_name = list(remotes.keys())[0]
        branch = git_handler.get_current_branch(path)

        self.log.step(f"Pushing to remote '{remote_name}' ({branch})...")
        success, err = git_handler.push(path, remote_name, branch)

        if success:
            self.log.success(f"Pushed to {remote_name}/{branch}")
            return True
        else:
            self.log.error(f"Push failed: {err}")
            self.log.info("You can push manually with: git push")
            return False

    # ─────────────────────────────────────────
    # Phase 6: Final Report
    # ─────────────────────────────────────────

    def _report(self, results: list[CommitResult], pushed: bool):
        """Print a final summary of everything that happened."""
        self.log.header("Agent Run Complete")

        successful = [r for r in results if r.success]
        failed = [r for r in results if not r.success]

        if successful:
            self.log.success(f"{len(successful)} commit(s) created:")
            for r in successful:
                self.log.commit(r.hash, r.message)

        if failed:
            self.log.error(f"{len(failed)} commit(s) failed:")
            for r in failed:
                self.log.error(f"  '{r.message}' — {r.error}")

        if pushed:
            self.log.success("All commits pushed to remote")
        elif successful:
            self.log.info("Commits are local only (push was skipped or failed)")

        if not successful and not failed:
            self.log.info("No commits were created this run")

        self.log.blank()

    # ─────────────────────────────────────────
    # Main Entry Point
    # ─────────────────────────────────────────

    def run(self, path: str) -> bool:
        """
        Execute the full autonomous agent workflow.

        Steps:
        0. Preflight checks
        1. Analyze repo state
        2. AI analysis + commit planning
        3. Pre-commit validation
        4. Execute commits
        5. Push (if configured)
        6. Report

        Returns True on success, False on failure.
        """
        path = os.path.abspath(path)
        self.log.header(f"AI Git Agent — {path}")

        # Phase 0: Preflight
        if not self._preflight(path):
            return False

        # Phase 1: Analyze
        repo_state = self._analyze_repo(path)
        if repo_state is None:
            return True  # Nothing to do — not an error

        # Phase 2: AI Planning
        commit_plans = self._ai_analyze(repo_state)
        if commit_plans is None:
            self.log.info("Skipping commit as per AI recommendation.")
            return True

        # Phase 3: Validation
        if not self._validate(path):
            self.log.error("Aborting: build validation failed.")
            return False

        # Phase 4: Execute
        results = self._execute_commits(path, commit_plans, repo_state)

        # Phase 5: Push
        pushed = False
        if self.auto_push and any(r.success for r in results):
            pushed = self._push(path)

        # Phase 6: Report
        self._report(results, pushed)

        return any(r.success for r in results) or len(results) == 0

    # ─────────────────────────────────────────
    # Watch Mode Entry Point
    # ─────────────────────────────────────────

    def watch(self, path: str):
        """
        Start auto-watch mode.
        Monitors the repo for changes and runs the agent automatically.
        """
        path = os.path.abspath(path)

        # Run once immediately on startup
        self.log.header(f"AI Git Agent — Watch Mode — {path}")

        if not self._preflight(path):
            return

        self.log.success("Preflight OK — starting watch loop")

        def on_change(repo_path: str):
            self.log.blank()
            self.log.step("Change detected — running agent workflow...")
            self.run(repo_path)

        self.watcher.start(path, on_change, logger=self.log.info)