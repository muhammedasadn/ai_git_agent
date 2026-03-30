"""
ai_engine.py
============
Handles all communication with the local Ollama AI model.

This is the "brain" module — it takes structured context from the agent
and returns AI-generated decisions, summaries, and commit messages.

We use the Ollama HTTP API directly (no extra libraries needed).
"""

import json
import urllib.request
import urllib.error
from typing import Optional


class AIEngine:
    """
    Wrapper around the Ollama REST API.

    Ollama exposes a simple HTTP API:
      POST /api/generate   → streaming or single response
      POST /api/chat       → chat-style (we use this for better context)
      GET  /api/tags       → list available models
    """

    def __init__(self, config: dict):
        ollama_cfg = config.get("ollama", {})
        self.base_url = ollama_cfg.get("base_url", "http://localhost:11434")
        self.model = ollama_cfg.get("model", "qwen2.5-coder:1.5b")
        self.timeout = ollama_cfg.get("timeout", 120)
        self.temperature = ollama_cfg.get("temperature", 0.3)

    # ─────────────────────────────────────────
    # Health Check
    # ─────────────────────────────────────────

    def is_available(self) -> tuple[bool, str]:
        """
        Check if Ollama is running and the model is available.
        Returns (available, message).
        """
        try:
            url = f"{self.base_url}/api/tags"
            req = urllib.request.Request(url)
            with urllib.request.urlopen(req, timeout=10) as resp:
                data = json.loads(resp.read())
                models = [m["name"] for m in data.get("models", [])]

                # Check if our model is available (handle tag variations)
                model_base = self.model.split(":")[0]
                found = any(
                    m == self.model or m.startswith(model_base)
                    for m in models
                )

                if not found:
                    available_str = ", ".join(models) if models else "none"
                    return False, (
                        f"Model '{self.model}' not found.\n"
                        f"Available models: {available_str}\n"
                        f"Run: ollama pull {self.model}"
                    )
                return True, f"Model '{self.model}' is ready."

        except urllib.error.URLError:
            return False, (
                "Cannot connect to Ollama.\n"
                "Make sure Ollama is running: ollama serve"
            )
        except Exception as e:
            return False, f"Unexpected error checking Ollama: {e}"

    # ─────────────────────────────────────────
    # Core API Call
    # ─────────────────────────────────────────

    def _chat(self, system_prompt: str, user_message: str) -> Optional[str]:
        """
        Send a chat message to Ollama and return the response text.
        Uses the /api/chat endpoint with non-streaming mode.
        """
        payload = {
            "model": self.model,
            "messages": [
                {"role": "system", "content": system_prompt},
                {"role": "user", "content": user_message}
            ],
            "stream": False,
            "options": {
                "temperature": self.temperature,
                "num_predict": 1024
            }
        }

        try:
            url = f"{self.base_url}/api/chat"
            body = json.dumps(payload).encode("utf-8")
            req = urllib.request.Request(
                url,
                data=body,
                headers={"Content-Type": "application/json"},
                method="POST"
            )

            with urllib.request.urlopen(req, timeout=self.timeout) as resp:
                data = json.loads(resp.read())
                return data.get("message", {}).get("content", "").strip()

        except urllib.error.URLError as e:
            raise ConnectionError(f"Ollama connection failed: {e}")
        except json.JSONDecodeError as e:
            raise ValueError(f"Invalid JSON from Ollama: {e}")
        except Exception as e:
            raise RuntimeError(f"AI call failed: {e}")

    def _generate(self, prompt: str) -> Optional[str]:
        """
        Use the simpler /api/generate endpoint.
        Fallback if chat doesn't work well for a task.
        """
        payload = {
            "model": self.model,
            "prompt": prompt,
            "stream": False,
            "options": {
                "temperature": self.temperature,
                "num_predict": 512
            }
        }

        try:
            url = f"{self.base_url}/api/generate"
            body = json.dumps(payload).encode("utf-8")
            req = urllib.request.Request(
                url,
                data=body,
                headers={"Content-Type": "application/json"},
                method="POST"
            )

            with urllib.request.urlopen(req, timeout=self.timeout) as resp:
                data = json.loads(resp.read())
                return data.get("response", "").strip()

        except Exception as e:
            raise RuntimeError(f"AI generate call failed: {e}")

    # ─────────────────────────────────────────
    # Task 1: Summarize Repository Changes
    # ─────────────────────────────────────────

    def summarize_changes(self, repo_state: dict) -> str:
        """
        Ask the AI to summarize what has changed in the repo.
        Returns a plain-English summary.
        """
        system = (
            "You are a senior software engineer reviewing a Git repository. "
            "Summarize the changes concisely and clearly. "
            "Focus on WHAT changed and WHY it might matter. "
            "Be direct. No markdown. 3-5 sentences maximum."
        )

        status = repo_state.get("status", {})
        diff = repo_state.get("diff", "")[:3000]  # Truncate large diffs
        diff_stat = repo_state.get("diff_stat", "")

        user_msg = f"""
Branch: {repo_state.get('branch', 'unknown')}

Modified files: {status.get('modified', [])}
New files: {status.get('added', [])}
Deleted files: {status.get('deleted', [])}

Diff stats:
{diff_stat}

Diff (truncated to 3000 chars):
{diff}

Please summarize what these changes represent.
""".strip()

        return self._chat(system, user_msg)

    # ─────────────────────────────────────────
    # Task 2: Plan Commits (split into logical groups)
    # ─────────────────────────────────────────

    def plan_commits(self, repo_state: dict) -> list[dict]:
        """
        Ask the AI to split changes into logical commit groups.

        Returns a list of commit plan dicts:
        [
          {
            "message": "feat: add user authentication",
            "files": ["auth.py", "models/user.py"],
            "reason": "These files all relate to authentication"
          },
          ...
        ]
        """
        system = (
            "You are a senior software engineer. "
            "Your task is to group file changes into logical Git commits. "
            "Each commit must represent ONE coherent change (feature, fix, refactor, docs, etc.).\n\n"
            "Rules:\n"
            "1. Related files go together in one commit\n"
            "2. Unrelated changes must be in separate commits\n"
            "3. Use conventional commit format: type(scope): description\n"
            "   Types: feat, fix, refactor, docs, style, test, chore\n"
            "4. If everything belongs together, return ONE commit\n\n"
            "IMPORTANT: Respond ONLY with valid JSON. No explanations before or after.\n"
            "Format:\n"
            '[\n'
            '  {\n'
            '    "message": "feat: add login endpoint",\n'
            '    "files": ["api/auth.py", "tests/test_auth.py"],\n'
            '    "reason": "Core authentication feature"\n'
            '  }\n'
            ']'
        )

        status = repo_state.get("status", {})
        diff = repo_state.get("diff", "")[:4000]

        all_files = (
            status.get("modified", []) +
            status.get("added", []) +
            status.get("deleted", [])
        )

        user_msg = f"""
Files changed: {json.dumps(all_files)}

Diff (truncated):
{diff}

Group these into logical commits. Return JSON only.
""".strip()

        raw = self._chat(system, user_msg)

        # Parse JSON response
        try:
            # Try to extract JSON array even if there's surrounding text
            start = raw.find("[")
            end = raw.rfind("]") + 1
            if start != -1 and end > start:
                json_str = raw[start:end]
                plans = json.loads(json_str)
                # Validate structure
                validated = []
                for plan in plans:
                    if isinstance(plan, dict) and "message" in plan and "files" in plan:
                        validated.append({
                            "message": str(plan["message"]).strip(),
                            "files": [str(f) for f in plan.get("files", [])],
                            "reason": str(plan.get("reason", ""))
                        })
                if validated:
                    return validated
        except (json.JSONDecodeError, KeyError, TypeError):
            pass

        # Fallback: if AI returns garbage, make one commit with all files
        fallback_msg = self.generate_commit_message(repo_state)
        return [{
            "message": fallback_msg,
            "files": all_files,
            "reason": "All changes grouped into one commit (AI parsing failed)"
        }]

    # ─────────────────────────────────────────
    # Task 3: Generate a Single Commit Message
    # ─────────────────────────────────────────

    def generate_commit_message(self, repo_state: dict, files: list[str] = None) -> str:
        """
        Ask the AI to write a single commit message for the current changes.
        Uses conventional commit format.
        """
        system = (
            "You are a senior developer writing Git commit messages. "
            "Use conventional commits format: type(scope): short description\n"
            "Types: feat, fix, refactor, docs, style, test, chore\n"
            "Rules:\n"
            "- Max 72 characters\n"
            "- Imperative mood (add, fix, update — NOT added, fixed, updated)\n"
            "- No period at end\n"
            "- Be specific and meaningful\n"
            "Return ONLY the commit message. Nothing else."
        )

        status = repo_state.get("status", {})
        diff = repo_state.get("diff", "")[:2000]

        target_files = files or (
            status.get("modified", []) +
            status.get("added", []) +
            status.get("deleted", [])
        )

        user_msg = f"""
Files involved: {target_files}
Branch: {repo_state.get('branch', 'unknown')}

Diff:
{diff}

Write a single commit message for these changes.
""".strip()

        result = self._chat(system, user_msg).strip()

        # Clean up: remove quotes, markdown, extra lines
        result = result.strip('"\'`').split("\n")[0].strip()

        # Enforce length
        if len(result) > 72:
            result = result[:69] + "..."

        # Ensure it's not empty
        if not result:
            result = "chore: update files"

        return result

    # ─────────────────────────────────────────
    # Task 4: Analyze Build/Validation Errors
    # ─────────────────────────────────────────

    def analyze_error(self, error_output: str, project_type: str) -> str:
        """
        Ask the AI to explain a build or test failure in plain English.
        Returns a human-readable explanation and suggested fix.
        """
        system = (
            "You are a senior developer helping a junior understand a build error. "
            "Explain the error clearly and suggest how to fix it. "
            "Be concise. Max 5 sentences. No markdown."
        )

        user_msg = f"""
Project type: {project_type}

Error output:
{error_output[:2000]}

Explain what went wrong and how to fix it.
""".strip()

        return self._chat(system, user_msg)

    # ─────────────────────────────────────────
    # Task 5: Decide if Changes Are Worth Committing
    # ─────────────────────────────────────────

    def should_commit(self, repo_state: dict) -> tuple[bool, str]:
        """
        Ask the AI whether the current changes are meaningful enough to commit.
        NOTE: This is ONLY called for all-junk-file scenarios.
        Real source files always get committed — see agent.py.
        Returns (should_commit, reason).
        """
        system = (
            "You are a code reviewer. Decide if the given changes are worth committing. "
            "Be LIBERAL — err on the side of committing. "
            "Only return false for: purely empty files with zero content, "
            "or files that are 100% identical to what was there before. "
            "New project files, config files, README files ARE worth committing. "
            "Return JSON only: {\"commit\": true/false, \"reason\": \"explanation\"}"
        )

        status = repo_state.get("status", {})
        diff_stat = repo_state.get("diff_stat", "")
        untracked = repo_state.get("untracked_content", "")[:1000]

        all_files = (
            status.get("modified", []) +
            status.get("added", []) +
            status.get("deleted", [])
        )

        if not all_files:
            return False, "No changes detected."

        user_msg = f"""
Files: {all_files}
Stats: {diff_stat}
New file content preview:
{untracked}

Should these changes be committed? Remember: be liberal, err on the side of committing.
""".strip()

        raw = self._chat(system, user_msg)

        try:
            start = raw.find("{")
            end = raw.rfind("}") + 1
            if start != -1 and end > start:
                data = json.loads(raw[start:end])
                return bool(data.get("commit", True)), str(data.get("reason", ""))
        except (json.JSONDecodeError, KeyError):
            pass

        # Default: YES, commit
        return True, "Proceeding with commit (AI decision unavailable)."

    # ─────────────────────────────────────────
    # Task 6: Generate Initial Commit Message
    # ─────────────────────────────────────────

    def generate_initial_commit_message(self, repo_state: dict) -> str:
        """
        Generate a message specifically for the very first commit of a project.
        Analyzes the project structure to write something meaningful.
        """
        system = (
            "You are writing the first commit message for a new project. "
            "Look at the files and write a meaningful initial commit message. "
            "Use conventional commit format. Common choices: "
            "'chore: initial project setup', 'feat: initialize React app', "
            "'chore: bootstrap Node.js API project'. "
            "Be specific about the tech stack if visible. "
            "Return ONLY the commit message. No quotes, no explanation."
        )

        status = repo_state.get("status", {})
        added  = status.get("added", [])
        untracked = repo_state.get("untracked_content", "")[:2000]

        user_msg = f"""
New files in this project: {added[:20]}

File content preview:
{untracked}

Write the initial commit message.
""".strip()

        result = self._chat(system, user_msg).strip().strip('"\'`').split("\n")[0].strip()
        return result if result else "chore: initial project setup"

    # ─────────────────────────────────────────
    # Task 7: Suggest Branch Name
    # ─────────────────────────────────────────

    def suggest_branch_name(self, repo_state: dict) -> str:
        """
        Suggest a git branch name based on current uncommitted changes.
        Returns a slug like 'feature/add-user-auth' or 'fix/login-crash'.
        """
        system = (
            "You are suggesting a Git branch name based on uncommitted changes. "
            "Use kebab-case with a prefix: feature/, fix/, refactor/, docs/, chore/. "
            "Examples: 'feature/add-login-page', 'fix/null-pointer-crash', "
            "'refactor/clean-up-api-routes'. "
            "Max 50 characters. Return ONLY the branch name. Nothing else."
        )

        status = repo_state.get("status", {})
        diff   = repo_state.get("diff", "")[:1500]
        all_files = (
            status.get("modified", []) +
            status.get("added", []) +
            status.get("deleted", [])
        )

        user_msg = f"""
Files changed: {all_files[:10]}
Diff preview: {diff[:500]}

Suggest a branch name.
""".strip()

        result = self._chat(system, user_msg).strip().strip('"\'`').split("\n")[0].strip()
        # Sanitize
        import re
        result = re.sub(r"[^a-z0-9\-/]", "-", result.lower())
        return result if result else "feature/ai-changes"