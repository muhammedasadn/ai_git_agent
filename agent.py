"""
agent.py
========
The brain of the ai-git-agent — the decision-making orchestrator.

This module:
1. Collects repo state (via git_handler)
2. Asks the AI to analyze and plan (via ai_engine)
3. Validates the code (via validator)
4. Executes the plan (via git_handler)
5. Reports results clearly

Think of this as the "senior engineer" who delegates to specialists
but makes all the final decisions.
"""

import os
import sys
import time
from typing import Optional

import git_handler
from ai_engine import AIEngine
from validator import Validator, detect_project_type
from watcher import Watcher


# ─────────────────────────────────────────────
# Console Output (developer-like logging)
# ─────────────────────────────────────────────

class Logger:
    """
    Provides structured, color-coded terminal logging.
    The log style mimics how a real developer communicates about their work.
    """

    RESET = "\033[0m"
    BOLD = "\033[1m"
    DIM = "\033[2m"

    # Colors
    CYAN = "\033[96m"
    GREEN = "\033[92m"
    YELLOW = "\033[93m"
    RED = "\033[91m"
    BLUE = "\033[94m"
    MAGENTA = "\033[95m"
    WHITE = "\033[97m"

    def __init__(self, verbose: bool = False):
        self.verbose = verbose
        self._indent = 0

    def _supports_color(self) -> bool:
        return hasattr(sys.stdout, "isatty") and sys.stdout.isatty()

    def _color(self, text: str, color: str) -> str:
        if self._supports_color():
            return f"{color}{text}{self.RESET}"
        return text

    def step(self, message: str):
        """Main agent step — printed prominently."""
        prefix = self._color("●", self.CYAN)
        print(f"\n{prefix} {self._color(message, self.BOLD + self.WHITE)}")

    def info(self, message: str):
        """General information."""
        prefix = self._color("  →", self.BLUE)
        print(f"{prefix} {message}")

    def success(self, message: str):
        """Successful operation."""
        prefix = self._color("  ✓", self.GREEN)
        print(f"{prefix} {self._color(message, self.GREEN)}")

    def warning(self, message: str):
        """Warning — non-fatal."""
        prefix = self._color("  ⚠", self.YELLOW)
        print(f"{prefix} {self._color(message, self.YELLOW)}")

    def error(self, message: str):
        """Error — may be fatal."""
        prefix = self._color("  ✗", self.RED)
        print(f"{prefix} {self._color(message, self.RED)}")

    def ai(self, message: str):
        """AI-generated output."""
        prefix = self._color("  🤖", self.MAGENTA)
        print(f"{prefix} {self._color(message, self.MAGENTA)}")

    def commit(self, hash_: str, message: str):
        """Commit created."""
        hash_str = self._color(f"[{hash_}]", self.YELLOW)
        msg_str = self._color(message, self.WHITE)
        print(f"  {self._color('✓', self.GREEN)} {hash_str} {msg_str}")

    def divider(self):
        """Visual separator."""
        line = self._color("─" * 60, self.DIM)
        print(f"\n{line}")

    def header(self, title: str):
        """Section header."""
        self.divider()
        print(f"  {self._color(title.upper(), self.BOLD + self.CYAN)}")
        self.divider()

    def dim(self, message: str):
        """Subdued text for verbose-only info."""
        if self.verbose:
            print(f"  {self._color(message, self.DIM)}")

    def blank(self):
        print()


# ─────────────────────────────────────────────
# Commit Result
# ─────────────────────────────────────────────

class CommitResult:
    """Stores the result of a single commit operation."""

    def __init__(self, message: str, files: list[str], hash_: str = "",
                 success: bool = True, error: str = ""):
        self.message = message
        self.files = files
        self.hash = hash_
        self.success = success
        self.error = error


# ─────────────────────────────────────────────
# Agent Class
# ─────────────────────────────────────────────

class Agent:
    """
    The main autonomous Git agent.

    It combines AI reasoning with Git operations to:
    - Understand what changed
    - Plan logical commits
    - Validate before committing
    - Execute and report
    """

    def __init__(self, config: dict):
        self.config = config
        self.verbose = config.get("logging", {}).get("verbose", False)
        self.auto_push = config.get("agent", {}).get("auto_push", False)
        self.max_commits = config.get("agent", {}).get("max_commits_per_run", 10)

        self.log = Logger(verbose=self.verbose)
        self.ai = AIEngine(config)
        self.validator = Validator(config)
        self.watcher = Watcher(config)

    # ─────────────────────────────────────────
    # Phase 0: Preflight Checks
    # ─────────────────────────────────────────

    def _preflight(self, path: str) -> bool:
        """
        Check all prerequisites before starting the workflow.
        Returns True if everything is OK, False if we should abort.
        """
        # Check 1: Is this a Git repo?
        self.log.step("Running preflight checks...")

        if not git_handler.is_git_repo(path):
            self.log.error(f"'{path}' is not a Git repository.")
            self.log.info("Run: git init")
            return False
        self.log.success("Git repository confirmed")

        # Check 2: Is Ollama running with the right model?
        self.log.info("Checking Ollama / AI engine...")
        available, msg = self.ai.is_available()
        if not available:
            self.log.error(f"AI engine not available: {msg}")
            return False
        self.log.success(msg)

        return True

    # ─────────────────────────────────────────
    # Phase 1: Repository Analysis
    # ─────────────────────────────────────────

    def _analyze_repo(self, path: str) -> Optional[dict]:
        """
        Collect and display the current state of the repository.
        Returns repo_state dict or None if nothing to do.
        """
        self.log.step("I'm checking the repo state...")

        repo_state = git_handler.get_full_repo_state(path)
        status = repo_state["status"]

        if status.get("error"):
            self.log.error(f"Git error: {status['error']}")
            return None

        branch = repo_state["branch"]
        remotes = repo_state["remotes"]
        modified = status.get("modified", [])
        added = status.get("added", [])
        deleted = status.get("deleted", [])

        self.log.info(f"Branch: {branch}")

        if remotes:
            for name, url in remotes.items():
                self.log.info(f"Remote: {name} → {url}")
        else:
            self.log.warning("No remotes configured (push will be skipped)")

        # Summarize findings
        total = len(modified) + len(added) + len(deleted)

        if total == 0 and not status.get("staged"):
            self.log.warning("No changes detected in the working tree.")
            self.log.info("Nothing to commit.")
            return None

        self.log.success(
            f"I found {total} changed file(s): "
            f"{len(modified)} modified, {len(added)} new, {len(deleted)} deleted"
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