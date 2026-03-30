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

        return repo_state

    # ── Phase 2: AI Analysis ─────────────────────────────────────

    def _ai_analyze(self, repo_state):
        self.log.step("I'm analyzing the changes with AI...")

        status    = repo_state["status"]
        modified  = status.get("modified", [])
        added     = status.get("added",    [])
        deleted   = status.get("deleted",  [])
        all_files = modified + added + deleted

        if not all_files:
            self.log.warning("No files to commit.")
            return None

        is_first = not repo_state.get("has_commits", True)

        # ── First commit: always commit, just generate a good message ──
        if is_first:
            self.log.info("First commit in this repository — generating initial commit...")
            try:
                msg = self.ai.generate_initial_commit_message(repo_state)
            except Exception:
                msg = "chore: initial project setup"
            self.log.ai("Message", msg)
            return [{"message": msg, "files": all_files, "reason": "Initial commit"}]

        # ── AI summary ──
        try:
            summary = self.ai.summarize_changes(repo_state)
            self.log.ai("Summary", summary)
        except Exception as e:
            self.log.warning(f"AI summary unavailable: {e}")

        # ── Smart commit decision (don't skip real files) ──
        junk_patterns = ["package-lock.json", "yarn.lock", ".DS_Store",
                         "Thumbs.db", ".pyc", "__pycache__"]
        real_files = [f for f in all_files
                      if not any(j in f for j in junk_patterns)]

        if not real_files:
            # All files look like auto-generated junk
            self.log.warning("All changes appear to be auto-generated files.")
            if not self.interactive or not self.log.confirm("Commit anyway?", default=False):
                self.log.info("Skipping commit.")
                return None
        else:
            self.log.dim(f"  {len(real_files)} real source file(s) — proceeding with commit")

        # ── AI commit planning ──
        self.log.step("I'm splitting changes into logical commits...")
        try:
            plans = self.ai.plan_commits(repo_state)
        except Exception as e:
            self.log.warning(f"AI planning failed ({e}) — using single commit")
            try:
                msg = self.ai.generate_commit_message(repo_state)
            except Exception:
                msg = "chore: update project files"
            plans = [{"message": msg, "files": all_files, "reason": "Fallback single commit"}]

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
            self.log.warning(f"Capping at {self.max_commits} commits")
            plans = plans[:self.max_commits]

        if self.interactive:
            self.log.blank()
            if not self.log.confirm(f"Proceed with {len(plans)} commit(s)?"):
                self.log.info("Aborted by user.")
                return None

        return plans

    # ── Phase 3: Validation ──────────────────────────────────────

    def _validate(self, path):
        self.log.step("Running build/test validation...")
        project_type = self.validator.detect(path)
        self.log.info(f"Project type : {project_type.value}")

        result = self.validator.run(path, project_type)

        if result.skipped:
            self.log.info(f"Validation skipped (no validator for {project_type.value})")
            return True

        if result.passed:
            self.log.success("Build/tests passed")
            return True

        self.log.error("Build/tests FAILED — stopping before commit")
        self.log.blank()
        err_text = (result.error or result.output).strip()
        for line in err_text.splitlines()[-15:]:
            self.log.plain(f"  | {line}")

        self.log.blank()
        self.log.step("Asking AI to explain the error...")
        try:
            explanation = self.ai.analyze_error(err_text, project_type.value)
            self.log.ai("Explanation", explanation)
        except Exception:
            pass

        if self.interactive:
            if self.log.confirm("Commit anyway (dangerous)?", default=False):
                self.log.warning("Proceeding despite failure (user override)")
                return True

        return False

    # ── Phase 4: Execute Commits ─────────────────────────────────

    def _execute_commits(self, path, plans, repo_state):
        if self.dry_run:
            self.log.step("[DRY RUN] Would create these commits:")
            for i, p in enumerate(plans, 1):
                self.log.plain(f"  {i}. {p['message']}")
                for f in p.get("files", []):
                    self.log.dim(f"     {f}")
            self.log.info("Dry run complete — no changes made.")
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
            message  = plan["message"]
            planned  = plan.get("files", [])
            is_last  = (i == len(plans))

            self.log.info(f"Commit {i}/{len(plans)}: {message}")

            to_stage = [f for f in planned if f in all_changed and f not in done]

            # Last commit catches any stragglers
            if is_last:
                remaining = all_changed - done
                for f in remaining:
                    if f not in to_stage:
                        to_stage.append(f)

            if not to_stage:
                self.log.warning("  No files for this commit — skipping")
                continue

            for f in to_stage:
                self.log.dim(f"  staging: {f}")

            ok, err = git_handler.stage_files(path, to_stage)
            if not ok:
                self.log.dim(f"  Selective stage failed ({err}), using git add -A")
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

    # ── Phase 5: Push ────────────────────────────────────────────

    def _push(self, path):
        remotes = git_handler.get_remotes(path)
        if not remotes:
            self.log.warning("No remote configured — skipping push")
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
            self.log.info("Push manually: git push")
            return False

    # ── Phase 6: Report ──────────────────────────────────────────

    def _report(self, results, pushed, path):
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
            self.log.success("All commits pushed to remote")
        elif ok:
            self.log.info("Commits are local. Push manually: git push")

        if not ok and not bad:
            self.log.info("No commits created this run.")

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