"""
ai_engine.py
============
All AI communication with local Ollama.

KEY IMPROVEMENTS in this version:
  - Commit messages are generated FROM ACTUAL DIFF CONTENT, not just filenames
  - The AI reads real code changes (added/removed lines) to write specific messages
  - Two-pass strategy: first understand WHAT changed, then write the message
  - Strict output cleaning so messages are never generic ("update files")
  - Better JSON parsing for commit planning with retry logic
"""

import json
import re
import urllib.request
import urllib.error
from typing import Optional


class AIEngine:

    def __init__(self, config: dict):
        cfg = config.get("ollama", {})
        self.base_url    = cfg.get("base_url",    "http://localhost:11434")
        self.model       = cfg.get("model",       "qwen2.5-coder:1.5b")
        self.timeout     = cfg.get("timeout",     120)
        self.temperature = cfg.get("temperature", 0.2)  # Lower = more deterministic messages

    # ──────────────────────────────────────────────────
    # Health check
    # ──────────────────────────────────────────────────

    def is_available(self) -> tuple[bool, str]:
        try:
            req = urllib.request.Request(f"{self.base_url}/api/tags")
            with urllib.request.urlopen(req, timeout=10) as resp:
                data   = json.loads(resp.read())
                models = [m["name"] for m in data.get("models", [])]
                base   = self.model.split(":")[0]
                found  = any(m == self.model or m.startswith(base) for m in models)
                if not found:
                    avail = ", ".join(models) or "none"
                    return False, (
                        f"Model '{self.model}' not found. Available: {avail}\n"
                        f"Fix: ollama pull {self.model}"
                    )
                return True, f"Model '{self.model}' is ready."
        except urllib.error.URLError:
            return False, "Cannot connect to Ollama. Run: ollama serve"
        except Exception as e:
            return False, f"Ollama check failed: {e}"

    # ──────────────────────────────────────────────────
    # Core API call
    # ──────────────────────────────────────────────────

    def _chat(self, system: str, user: str, max_tokens: int = 512) -> str:
        payload = {
            "model":   self.model,
            "messages": [
                {"role": "system", "content": system},
                {"role": "user",   "content": user},
            ],
            "stream":  False,
            "options": {
                "temperature": self.temperature,
                "num_predict": max_tokens,
                "stop": ["\n\n\n"],   # prevent runaway responses
            }
        }
        try:
            body = json.dumps(payload).encode()
            req  = urllib.request.Request(
                f"{self.base_url}/api/chat",
                data=body,
                headers={"Content-Type": "application/json"},
                method="POST"
            )
            with urllib.request.urlopen(req, timeout=self.timeout) as resp:
                return json.loads(resp.read()).get("message", {}).get("content", "").strip()
        except urllib.error.URLError as e:
            raise ConnectionError(f"Ollama connection failed: {e}")
        except Exception as e:
            raise RuntimeError(f"AI call failed: {e}")

    # ──────────────────────────────────────────────────
    # Diff extraction helpers
    # ──────────────────────────────────────────────────

    def _extract_meaningful_diff(self, repo_state: dict, files: list = None) -> str:
        """
        Extract the most informative parts of the diff for the AI.

        Strategy:
          1. Prefer actual changed lines (+/-) over file names alone
          2. For new files: read their content (since git diff shows nothing)
          3. Truncate intelligently: keep more lines from smaller diffs
          4. Always include file headers so AI knows which file changed
        """
        diff         = repo_state.get("diff", "")
        untracked    = repo_state.get("untracked_content", "")
        staged_diff  = repo_state.get("staged_diff", "")

        # Use staged diff if working tree diff is empty
        active_diff = diff or staged_diff

        # Filter diff to only relevant files if specified
        if files and active_diff:
            filtered_sections = []
            current_section   = []
            in_relevant       = False
            for line in active_diff.splitlines():
                if line.startswith("diff --git"):
                    if in_relevant and current_section:
                        filtered_sections.extend(current_section)
                    current_section = [line]
                    in_relevant     = any(f in line for f in files)
                else:
                    current_section.append(line)
            if in_relevant and current_section:
                filtered_sections.extend(current_section)
            active_diff = "\n".join(filtered_sections)

        # Build the context block
        parts = []

        if active_diff:
            # Extract changed lines only (+ and - lines) for compactness
            changed_lines = []
            file_header   = ""
            for line in active_diff.splitlines():
                if line.startswith("diff --git") or line.startswith("--- ") or line.startswith("+++ "):
                    file_header = line
                    changed_lines.append(line)
                elif line.startswith("@@"):
                    changed_lines.append(line)
                elif line.startswith("+") or line.startswith("-"):
                    changed_lines.append(line)

            if changed_lines:
                parts.append("=== CODE CHANGES (+ added, - removed) ===")
                parts.append("\n".join(changed_lines[:200]))  # max 200 change lines

        if untracked:
            parts.append("=== NEW FILE CONTENTS ===")
            parts.append(untracked[:2000])

        return "\n\n".join(parts) if parts else "(no diff available)"

    def _classify_change_type(self, diff_content: str, files: list) -> str:
        """
        Heuristic to detect the most likely commit type before asking AI.
        This helps guide the AI toward the right conventional commit prefix.
        """
        diff_lower  = diff_content.lower()
        files_lower = " ".join(files).lower()

        # Test files
        if any(f in files_lower for f in ["test_", "_test", ".spec.", "tests/", "__tests__"]):
            return "test"
        # Docs
        if all(f.endswith((".md", ".rst", ".txt", ".pdf")) for f in files if f):
            return "docs"
        # Style/formatting
        if all(f.endswith((".css", ".scss", ".less", ".sass")) for f in files if f):
            return "style"
        # Config/chore
        if all(f in ("package.json", "pyproject.toml", "setup.cfg", ".gitignore",
                     "Makefile", "CMakeLists.txt", "requirements.txt", ".env.example")
               for f in files if f):
            return "chore"
        # Bug fix signals
        fix_signals = ["fix", "bug", "error", "exception", "crash", "null",
                       "undefined", "traceback", "segfault", "overflow"]
        if any(s in diff_lower for s in fix_signals):
            return "fix"
        # Feature signals
        feat_signals = ["def ", "function ", "class ", "const ", "export ",
                        "module ", "endpoint", "route", "api", "handler"]
        if any(s in diff_lower for s in feat_signals):
            return "feat"
        # Refactor signals
        refactor_signals = ["rename", "move", "extract", "cleanup", "reorganize",
                            "restructure", "simplify"]
        if any(s in diff_lower for s in refactor_signals):
            return "refactor"
        return "feat"  # Default

    # ──────────────────────────────────────────────────
    # Task 1: Generate commit message FROM ACTUAL DIFF
    # ──────────────────────────────────────────────────

    def generate_commit_message(self, repo_state: dict, files: list = None) -> str:
        """
        Generate a meaningful commit message by reading ACTUAL CODE CHANGES.

        Two-pass strategy:
          Pass 1: What specifically changed in the code?
          Pass 2: Write the commit message based on that understanding.

        This produces messages like:
          "feat(auth): add JWT token validation in middleware"
        Instead of:
          "feat: update auth.py"
        """
        status    = repo_state.get("status", {})
        target    = files or (
            status.get("modified", []) +
            status.get("added",    []) +
            status.get("deleted",  [])
        )

        diff_content  = self._extract_meaningful_diff(repo_state, target)
        commit_type   = self._classify_change_type(diff_content, target)

        # ── Pass 1: Understand the change ──
        understand_system = (
            "You are a senior software engineer doing code review. "
            "Read the diff below and answer in ONE sentence: "
            "What specific functionality was added, changed, or fixed? "
            "Be concrete — name the function/class/feature affected. "
            "No fluff. No 'this commit'. Just the fact."
        )
        understand_user = f"""
Files: {target[:10]}

{diff_content}

What specifically changed in this code? (one sentence, be concrete)
""".strip()

        try:
            understanding = self._chat(understand_system, understand_user, max_tokens=100)
            understanding = understanding.split("\n")[0].strip()
        except Exception:
            understanding = f"changes to {', '.join(target[:3])}"

        # ── Pass 2: Write the commit message ──
        message_system = (
            "You write Git commit messages using conventional commits format.\n"
            "Format: type(scope): description\n\n"
            "Types: feat, fix, refactor, docs, style, test, chore\n"
            "Rules:\n"
            "  - STRICTLY under 72 characters total\n"
            "  - Use imperative mood: add, fix, remove, update, implement\n"
            "  - scope = the module/file/component affected (short, lowercase)\n"
            "  - description = what it does, NOT what you did\n"
            "  - No period at end\n"
            "  - NO generic messages like 'update files' or 'make changes'\n\n"
            "The message MUST reflect the ACTUAL code change described.\n"
            f"Most likely type for this change: {commit_type}\n\n"
            "Return ONLY the commit message. Nothing else. No quotes."
        )

        # Derive scope from file names
        scope = self._derive_scope(target)

        message_user = f"""
What changed: {understanding}
Files: {target[:5]}
Scope hint: {scope}

Write the commit message now.
""".strip()

        try:
            result = self._chat(message_system, message_user, max_tokens=80)
        except Exception:
            result = ""

        return self._clean_commit_message(result, commit_type, scope, understanding)

    def _derive_scope(self, files: list) -> str:
        """Derive a short scope name from the list of changed files."""
        if not files:
            return ""

        # Common scope patterns
        dirs = set()
        for f in files:
            parts = f.replace("\\", "/").split("/")
            if len(parts) > 1:
                dirs.add(parts[0])   # top-level directory = scope

        if len(dirs) == 1:
            scope = list(dirs)[0]
        elif len(dirs) > 1:
            # Multiple dirs — use common prefix or first file's name without ext
            scope = list(dirs)[0]
        else:
            # Single flat file — use filename without extension
            scope = files[0].rsplit(".", 1)[0].replace("/", "-")

        # Shorten and clean
        scope = re.sub(r"[^a-z0-9\-_]", "", scope.lower())
        return scope[:20] if scope else ""

    def _clean_commit_message(self, raw: str, commit_type: str,
                               scope: str, understanding: str) -> str:
        """
        Clean and validate the AI's commit message.
        Falls back to a constructed message if AI output is bad.
        """
        if not raw:
            return self._construct_fallback(commit_type, scope, understanding)

        # Take first non-empty line
        line = ""
        for l in raw.splitlines():
            l = l.strip().strip('"\'`*#').strip()
            if l:
                line = l
                break

        if not line:
            return self._construct_fallback(commit_type, scope, understanding)

        # Must start with a conventional commit type
        valid_types = ["feat", "fix", "refactor", "docs", "style", "test", "chore", "perf", "ci", "build"]
        has_type    = any(line.startswith(t) for t in valid_types)

        if not has_type:
            # Prepend the detected type
            if scope:
                line = f"{commit_type}({scope}): {line}"
            else:
                line = f"{commit_type}: {line}"

        # Enforce length
        if len(line) > 72:
            # Try to trim description part only
            colon_pos = line.find(": ")
            if colon_pos != -1:
                prefix = line[:colon_pos + 2]
                desc   = line[colon_pos + 2:]
                max_desc = 72 - len(prefix)
                if max_desc > 10:
                    line = prefix + desc[:max_desc - 3] + "..."
                else:
                    line = line[:69] + "..."
            else:
                line = line[:69] + "..."

        # Reject generic messages
        generic = ["update files", "make changes", "update code", "add code",
                   "modify files", "changes", "updates", "fix issues", "improve code"]
        if any(line.lower().endswith(g) or line.lower().split(": ")[-1] in g for g in generic):
            return self._construct_fallback(commit_type, scope, understanding)

        return line

    def _construct_fallback(self, commit_type: str, scope: str, understanding: str) -> str:
        """Build a commit message from the understanding string when AI fails."""
        # Extract key phrase from understanding
        understanding = understanding.strip().rstrip(".")
        # Remove filler starts
        for filler in ["This change ", "The code ", "This commit ", "Changes "]:
            if understanding.startswith(filler):
                understanding = understanding[len(filler):]
                break

        desc = understanding[:50] if understanding else f"update {scope or 'code'}"
        # Make imperative: "added" -> "add", "fixed" -> "fix"
        words = desc.split()
        if words and words[0].endswith("ed") and len(words[0]) > 3:
            words[0] = words[0][:-2]  # crude but effective: "fixed" -> "fix"
        desc = " ".join(words)

        if scope:
            return f"{commit_type}({scope}): {desc}"[:72]
        return f"{commit_type}: {desc}"[:72]

    # ──────────────────────────────────────────────────
    # Task 2: Plan commits (group files logically)
    # ──────────────────────────────────────────────────

    def plan_commits(self, repo_state: dict) -> list[dict]:
        """
        Group file changes into logical commits.
        Each commit should represent ONE coherent change.

        Returns: [{"message": "...", "files": [...], "reason": "..."}]
        """
        status    = repo_state.get("status", {})
        all_files = (
            status.get("modified", []) +
            status.get("added",    []) +
            status.get("deleted",  [])
        )

        if not all_files:
            return []

        # For small changesets (1-3 files), skip planning — one commit is fine
        if len(all_files) <= 3:
            msg = self.generate_commit_message(repo_state, all_files)
            return [{"message": msg, "files": all_files, "reason": "Small changeset"}]

        diff_content = self._extract_meaningful_diff(repo_state)

        system = (
            "You are a senior engineer grouping file changes into Git commits.\n"
            "RULES:\n"
            "1. Each commit = ONE logical unit of work\n"
            "2. Related files go in the same commit\n"
            "3. Unrelated features/fixes go in separate commits\n"
            "4. Use conventional commit format: type(scope): description\n"
            "5. Max 3 commits (do NOT over-split)\n"
            "6. If unsure, ONE commit is better than splitting wrong\n\n"
            "IMPORTANT: Return ONLY valid JSON array. No text before or after.\n"
            "Schema: [{\"message\": \"feat(x): ...\", \"files\": [\"a.py\"], \"reason\": \"...\"}]"
        )

        user = f"""
All changed files: {json.dumps(all_files)}

Code changes:
{diff_content[:3000]}

Group these into logical commits. Return JSON only.
""".strip()

        raw = self._chat(system, user, max_tokens=800)

        # Parse JSON — try multiple strategies
        plans = self._parse_json_plans(raw)

        if plans:
            # Validate and fix each plan's commit message
            validated = []
            for plan in plans:
                if not isinstance(plan, dict) or "files" not in plan:
                    continue
                files = [str(f) for f in plan.get("files", [])]
                if not files:
                    continue
                msg = str(plan.get("message", "")).strip()
                # Validate the message — regenerate if it looks bad
                if not self._is_good_message(msg):
                    msg = self.generate_commit_message(repo_state, files)
                validated.append({
                    "message": msg,
                    "files":   files,
                    "reason":  str(plan.get("reason", ""))
                })
            if validated:
                return validated

        # Fallback: one commit with everything
        msg = self.generate_commit_message(repo_state, all_files)
        return [{"message": msg, "files": all_files, "reason": "Fallback single commit"}]

    def _parse_json_plans(self, raw: str) -> list:
        """Try hard to extract a JSON array from AI output."""
        if not raw:
            return []

        # Strategy 1: Find JSON array directly
        start = raw.find("[")
        end   = raw.rfind("]") + 1
        if start != -1 and end > start:
            try:
                return json.loads(raw[start:end])
            except json.JSONDecodeError:
                pass

        # Strategy 2: Find JSON object (single commit returned as object)
        start = raw.find("{")
        end   = raw.rfind("}") + 1
        if start != -1 and end > start:
            try:
                obj = json.loads(raw[start:end])
                return [obj]
            except json.JSONDecodeError:
                pass

        # Strategy 3: Extract with regex — find all {...} blocks
        blocks = re.findall(r'\{[^{}]+\}', raw, re.DOTALL)
        if blocks:
            plans = []
            for block in blocks:
                try:
                    plans.append(json.loads(block))
                except json.JSONDecodeError:
                    pass
            return plans

        return []

    def _is_good_message(self, msg: str) -> bool:
        """Return True if the message looks like a good conventional commit."""
        if not msg or len(msg) < 10 or len(msg) > 72:
            return False
        valid_types = ["feat", "fix", "refactor", "docs", "style", "test",
                       "chore", "perf", "ci", "build"]
        if not any(msg.startswith(t) for t in valid_types):
            return False
        generic = ["update files", "make changes", "update code",
                   "add code", "changes", "updates"]
        if any(g in msg.lower() for g in generic):
            return False
        return True

    # ──────────────────────────────────────────────────
    # Task 3: Summarize changes (for display)
    # ──────────────────────────────────────────────────

    def summarize_changes(self, repo_state: dict) -> str:
        diff_content = self._extract_meaningful_diff(repo_state)
        status       = repo_state.get("status", {})

        system = (
            "You are reviewing a code diff. Summarize what changed in 1-2 sentences. "
            "Be specific: name the functions/features/files affected. "
            "No markdown. No 'this commit'. Start with a verb."
        )
        user = f"""
Modified: {status.get('modified', [])}
New:      {status.get('added', [])}
Deleted:  {status.get('deleted', [])}

{diff_content[:2000]}

Summarize the changes.
""".strip()

        try:
            result = self._chat(system, user, max_tokens=120)
            return result.split("\n")[0].strip() if result else "Code changes detected."
        except Exception:
            return "Code changes detected."

    # ──────────────────────────────────────────────────
    # Task 4: Initial commit message
    # ──────────────────────────────────────────────────

    def generate_initial_commit_message(self, repo_state: dict) -> str:
        status    = repo_state.get("status", {})
        added     = status.get("added", [])
        untracked = repo_state.get("untracked_content", "")[:2000]

        system = (
            "Write the first Git commit message for a new project. "
            "Look at the files and detect the tech stack. "
            "Be specific: 'feat: initialize React TypeScript app with Vite' "
            "not just 'initial commit'. "
            "Use conventional commit format. Max 72 chars. "
            "Return ONLY the message. No quotes."
        )
        user = f"""
Files: {added[:20]}

Content preview:
{untracked}

Write the initial commit message.
""".strip()

        try:
            result = self._chat(system, user, max_tokens=80)
            result = result.strip().strip('"\'`').split("\n")[0].strip()
            if self._is_good_message(result):
                return result
        except Exception:
            pass
        return "chore: initial project setup"

    # ──────────────────────────────────────────────────
    # Task 5: Should we commit at all?
    # ──────────────────────────────────────────────────

    def should_commit(self, repo_state: dict) -> tuple[bool, str]:
        """Only called for suspicious/junk-only changesets."""
        status    = repo_state.get("status", {})
        all_files = (
            status.get("modified", []) +
            status.get("added",    []) +
            status.get("deleted",  [])
        )
        if not all_files:
            return False, "No changes."

        system = (
            "Decide if these file changes are worth a Git commit. "
            "Be LIBERAL — only return false for truly empty or binary-only changes. "
            "Return JSON: {\"commit\": true/false, \"reason\": \"one sentence\"}"
        )
        user = f"""
Files: {all_files}
Content: {repo_state.get('untracked_content', '')[:500]}

Should these be committed?
""".strip()

        try:
            raw   = self._chat(system, user, max_tokens=100)
            start = raw.find("{")
            end   = raw.rfind("}") + 1
            if start != -1 and end > start:
                data = json.loads(raw[start:end])
                return bool(data.get("commit", True)), str(data.get("reason", ""))
        except Exception:
            pass
        return True, "Defaulting to commit."

    # ──────────────────────────────────────────────────
    # Task 6: Explain build errors
    # ──────────────────────────────────────────────────

    def analyze_error(self, error_output: str, project_type: str) -> str:
        system = (
            "You are helping a developer fix a build error. "
            "Explain what went wrong in 2 sentences and suggest the fix. "
            "Be specific. No markdown."
        )
        user = f"Project: {project_type}\n\nError:\n{error_output[:1500]}\n\nExplain and suggest fix."
        try:
            return self._chat(system, user, max_tokens=150)
        except Exception:
            return "Build failed. Check the error output above."

    # ──────────────────────────────────────────────────
    # Task 7: Suggest branch name
    # ──────────────────────────────────────────────────

    def suggest_branch_name(self, repo_state: dict) -> str:
        diff_content = self._extract_meaningful_diff(repo_state)
        status       = repo_state.get("status", {})
        all_files    = (
            status.get("modified", []) +
            status.get("added",    []) +
            status.get("deleted",  [])
        )

        system = (
            "Suggest a Git branch name for these changes. "
            "Format: prefix/short-description (kebab-case). "
            "Prefixes: feature/, fix/, refactor/, docs/, chore/. "
            "Max 50 chars. Return ONLY the branch name."
        )
        user = f"Files: {all_files[:8]}\n\nChanges:\n{diff_content[:800]}\n\nBranch name:"

        try:
            result = self._chat(system, user, max_tokens=30)
            result = result.strip().strip('"\'`').split("\n")[0].strip()
            result = re.sub(r"[^a-z0-9\-/]", "-", result.lower())
            if result and len(result) > 5:
                return result[:50]
        except Exception:
            pass
        return "feature/ai-changes"