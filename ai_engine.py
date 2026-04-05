"""
ai_engine.py
============
AI engine with dual backend support:
  1. Gemini (Google AI Free API) — primary, better quality
  2. Ollama (local)              — fallback when Gemini unavailable

Gemini Free API limits (as of 2024):
  - gemini-1.5-flash: 15 requests/min, 1M tokens/min, 1500 req/day  (FREE)
  - gemini-1.5-pro:   2 requests/min, 32k tokens/min, 50 req/day    (FREE)
  - gemini-2.0-flash: 15 requests/min                               (FREE)

We use gemini-1.5-flash by default (best free tier limits).

Setup:
  1. Go to https://aistudio.google.com/app/apikey
  2. Click "Create API Key" (free, no credit card)
  3. Add to config.json:
     "gemini": { "api_key": "AIza..." }
  OR set environment variable:
     export GEMINI_API_KEY="AIza..."

If Gemini is not configured → automatically falls back to Ollama.
"""

import json
import os
import re
import urllib.request
import urllib.error
from typing import Optional


# ─────────────────────────────────────────────
# Gemini Backend
# ─────────────────────────────────────────────

class GeminiBackend:
    """
    Google Gemini API client.
    Uses the free REST API — no SDK needed, just urllib.
    
    API docs: https://ai.google.dev/api/generate-content
    """

    BASE_URL = "https://generativelanguage.googleapis.com/v1beta/models"

    def __init__(self, api_key: str, model: str = "gemini-1.5-flash",
                 temperature: float = 0.2, timeout: int = 60):
        self.api_key     = api_key
        self.model       = model
        self.temperature = temperature
        self.timeout     = timeout

    def is_available(self) -> tuple[bool, str]:
        """Verify the API key works with a minimal test call."""
        if not self.api_key:
            return False, "Gemini API key not configured."
        try:
            # List models endpoint — cheapest possible check
            url = f"{self.BASE_URL}?key={self.api_key}"
            req = urllib.request.Request(url)
            with urllib.request.urlopen(req, timeout=10) as resp:
                data = json.loads(resp.read())
                models = [m.get("name", "") for m in data.get("models", [])]
                # Check if our model is available
                model_short = self.model.split("/")[-1]
                found = any(model_short in m for m in models)
                if not found and models:
                    # Use first available flash model
                    flash = [m for m in models if "flash" in m]
                    if flash:
                        self.model = flash[0].split("/")[-1]
                return True, f"Gemini '{self.model}' ready (free tier)"
        except urllib.error.HTTPError as e:
            if e.code == 400:
                return False, "Gemini API key is invalid. Check your key at https://aistudio.google.com/app/apikey"
            if e.code == 403:
                return False, "Gemini API key unauthorized. Make sure Generative Language API is enabled."
            return False, f"Gemini API error {e.code}: {e.reason}"
        except urllib.error.URLError:
            return False, "Cannot reach Gemini API. Check internet connection."
        except Exception as e:
            return False, f"Gemini check failed: {e}"

    def chat(self, system: str, user: str, max_tokens: int = 512) -> str:
        """
        Send a message to Gemini and return the response.
        
        Gemini uses "contents" format, not "messages".
        System instructions go in "system_instruction".
        """
        url = f"{self.BASE_URL}/{self.model}:generateContent?key={self.api_key}"

        payload = {
            "system_instruction": {
                "parts": [{"text": system}]
            },
            "contents": [
                {
                    "role": "user",
                    "parts": [{"text": user}]
                }
            ],
            "generationConfig": {
                "temperature":     self.temperature,
                "maxOutputTokens": max_tokens,
                "stopSequences":   ["\n\n\n"],
            },
            "safetySettings": [
                # Disable safety filters for code review content
                {"category": "HARM_CATEGORY_HARASSMENT",        "threshold": "BLOCK_NONE"},
                {"category": "HARM_CATEGORY_HATE_SPEECH",       "threshold": "BLOCK_NONE"},
                {"category": "HARM_CATEGORY_SEXUALLY_EXPLICIT", "threshold": "BLOCK_NONE"},
                {"category": "HARM_CATEGORY_DANGEROUS_CONTENT", "threshold": "BLOCK_NONE"},
            ]
        }

        try:
            body = json.dumps(payload).encode("utf-8")
            req  = urllib.request.Request(
                url,
                data=body,
                headers={"Content-Type": "application/json"},
                method="POST"
            )
            with urllib.request.urlopen(req, timeout=self.timeout) as resp:
                data = json.loads(resp.read())
                # Extract text from Gemini response structure
                candidates = data.get("candidates", [])
                if not candidates:
                    raise RuntimeError(f"Gemini returned no candidates: {data}")
                content = candidates[0].get("content", {})
                parts   = content.get("parts", [])
                if not parts:
                    raise RuntimeError("Gemini returned empty parts")
                return parts[0].get("text", "").strip()

        except urllib.error.HTTPError as e:
            body_text = ""
            try:
                body_text = e.read().decode()
                err_data  = json.loads(body_text)
                err_msg   = err_data.get("error", {}).get("message", "")
            except Exception:
                err_msg = body_text[:200]

            if e.code == 429:
                raise RuntimeError(
                    f"Gemini rate limit hit. "
                    f"Free tier: 15 req/min for flash. Wait 60s and retry.\n{err_msg}"
                )
            if e.code == 400:
                raise RuntimeError(f"Gemini bad request: {err_msg}")
            raise RuntimeError(f"Gemini HTTP {e.code}: {err_msg}")

        except urllib.error.URLError as e:
            raise ConnectionError(f"Gemini connection failed: {e}")
        except Exception as e:
            raise RuntimeError(f"Gemini call failed: {e}")


# ─────────────────────────────────────────────
# Ollama Backend (local fallback)
# ─────────────────────────────────────────────

class OllamaBackend:
    """Local Ollama fallback backend."""

    def __init__(self, base_url: str, model: str,
                 temperature: float, timeout: int):
        self.base_url    = base_url
        self.model       = model
        self.temperature = temperature
        self.timeout     = timeout

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
                        f"Ollama model '{self.model}' not found. "
                        f"Available: {avail}. Run: ollama pull {self.model}"
                    )
                return True, f"Ollama '{self.model}' ready (local)"
        except urllib.error.URLError:
            return False, "Ollama not running. Start with: ollama serve"
        except Exception as e:
            return False, f"Ollama check failed: {e}"

    def chat(self, system: str, user: str, max_tokens: int = 512) -> str:
        payload = {
            "model":    self.model,
            "messages": [
                {"role": "system", "content": system},
                {"role": "user",   "content": user},
            ],
            "stream":  False,
            "options": {
                "temperature": self.temperature,
                "num_predict": max_tokens,
                "stop":        ["\n\n\n"],
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
            raise RuntimeError(f"Ollama call failed: {e}")


# ─────────────────────────────────────────────
# Rate limiter for Gemini free tier
# ─────────────────────────────────────────────

import time as _time

class RateLimiter:
    """
    Simple rate limiter for Gemini free tier.
    gemini-1.5-flash: 15 requests per minute.
    We cap at 12/min to be safe (leaves buffer).
    """

    def __init__(self, requests_per_minute: int = 12):
        self.rpm        = requests_per_minute
        self.min_gap    = 60.0 / requests_per_minute   # seconds between requests
        self._last_call = 0.0

    def wait_if_needed(self):
        now     = _time.time()
        elapsed = now - self._last_call
        if elapsed < self.min_gap:
            wait = self.min_gap - elapsed
            _time.sleep(wait)
        self._last_call = _time.time()


# ─────────────────────────────────────────────
# Main AIEngine — auto-selects backend
# ─────────────────────────────────────────────

class AIEngine:
    """
    Unified AI engine that uses Gemini if configured, Ollama as fallback.
    
    Auto-detection order:
      1. GEMINI_API_KEY environment variable
      2. config.json → "gemini" → "api_key"
      3. Falls back to Ollama
    
    All public methods work identically regardless of which backend is active.
    """

    def __init__(self, config: dict):
        # ── Gemini config ──
        gemini_cfg  = config.get("gemini", {})
        gemini_key  = (
            os.environ.get("GEMINI_API_KEY", "").strip() or
            gemini_cfg.get("api_key", "").strip()
        )
        gemini_model = gemini_cfg.get("model", "gemini-1.5-flash")
        temperature  = gemini_cfg.get("temperature", 0.2)

        # ── Ollama config ──
        ollama_cfg = config.get("ollama", {})
        ollama_url = ollama_cfg.get("base_url",    "http://localhost:11434")
        ollama_mdl = ollama_cfg.get("model",       "qwen2.5-coder:1.5b")
        timeout    = ollama_cfg.get("timeout",     120)
        ol_temp    = ollama_cfg.get("temperature", 0.2)

        # ── Build backends ──
        self._gemini = GeminiBackend(
            api_key=gemini_key, model=gemini_model,
            temperature=temperature, timeout=60
        ) if gemini_key else None

        self._ollama = OllamaBackend(
            base_url=ollama_url, model=ollama_mdl,
            temperature=ol_temp, timeout=timeout
        )

        self._active_backend: Optional[object] = None
        self._backend_name   = "none"
        self._rate_limiter   = RateLimiter(requests_per_minute=12)

    # ──────────────────────────────────────────
    # Backend selection
    # ──────────────────────────────────────────

    def is_available(self) -> tuple[bool, str]:
        """
        Try Gemini first, fall back to Ollama.
        Returns (available, status_message).
        """
        # Try Gemini
        if self._gemini:
            ok, msg = self._gemini.is_available()
            if ok:
                self._active_backend = self._gemini
                self._backend_name   = "gemini"
                return True, f"[Gemini] {msg}"
            else:
                # Gemini configured but failed — warn and try Ollama
                print(f"  [!!] Gemini unavailable: {msg}")
                print(f"       Falling back to Ollama...")

        # Try Ollama
        ok, msg = self._ollama.is_available()
        if ok:
            self._active_backend = self._ollama
            self._backend_name   = "ollama"
            return True, f"[Ollama] {msg}"

        # Neither available
        self._active_backend = None
        if self._gemini:
            return False, (
                "Neither Gemini nor Ollama is available.\n"
                "  Gemini: check your API key at https://aistudio.google.com/app/apikey\n"
                "  Ollama: run `ollama serve`"
            )
        return False, (
            f"Ollama unavailable: {msg}\n"
            "  OR configure Gemini: add GEMINI_API_KEY to environment\n"
            "  OR add to config.json: \"gemini\": {\"api_key\": \"AIza...\"}"
        )

    def _chat(self, system: str, user: str, max_tokens: int = 512) -> str:
        """Route to active backend, with automatic Ollama fallback on Gemini errors."""
        if self._active_backend is None:
            self.is_available()
        if self._active_backend is None:
            raise RuntimeError("No AI backend available.")

        # Rate limit Gemini calls
        if self._backend_name == "gemini":
            self._rate_limiter.wait_if_needed()

        try:
            return self._active_backend.chat(system, user, max_tokens)
        except RuntimeError as e:
            msg = str(e)
            # Gemini rate limit → wait and retry once
            if "rate limit" in msg.lower() and self._backend_name == "gemini":
                print("  [!!] Gemini rate limit — waiting 60s...")
                _time.sleep(61)
                self._rate_limiter._last_call = 0
                return self._active_backend.chat(system, user, max_tokens)
            # Gemini other error → fall back to Ollama
            if self._backend_name == "gemini":
                print(f"  [!!] Gemini error ({e}) — falling back to Ollama")
                ok, omsg = self._ollama.is_available()
                if ok:
                    self._active_backend = self._ollama
                    self._backend_name   = "ollama"
                    return self._ollama.chat(system, user, max_tokens)
            raise

    def get_backend_name(self) -> str:
        return self._backend_name

    # ──────────────────────────────────────────
    # Diff extraction
    # ──────────────────────────────────────────

    def _extract_meaningful_diff(self, repo_state: dict, files: list = None) -> str:
        """
        Extract changed lines (+/-) from diff for AI analysis.
        For new untracked files: read their content.
        """
        diff        = repo_state.get("diff", "")
        staged_diff = repo_state.get("staged_diff", "")
        untracked   = repo_state.get("untracked_content", "")
        active_diff = diff or staged_diff

        # Filter to specific files if given
        if files and active_diff:
            sections, current, in_rel = [], [], False
            for line in active_diff.splitlines():
                if line.startswith("diff --git"):
                    if in_rel and current:
                        sections.extend(current)
                    current = [line]
                    in_rel  = any(f in line for f in files)
                else:
                    current.append(line)
            if in_rel and current:
                sections.extend(current)
            active_diff = "\n".join(sections)

        parts = []

        if active_diff:
            changed = []
            for line in active_diff.splitlines():
                if any(line.startswith(p) for p in
                       ("diff --git", "--- ", "+++ ", "@@", "+", "-")):
                    changed.append(line)
            if changed:
                parts.append("=== CODE DIFF (+ added / - removed) ===")
                parts.append("\n".join(changed[:300]))

        if untracked:
            parts.append("=== NEW FILE CONTENTS ===")
            parts.append(untracked[:2000])

        return "\n\n".join(parts) if parts else "(no diff available)"

    def _classify_change_type(self, diff: str, files: list) -> str:
        """Pre-classify the change type to guide the AI."""
        dl = diff.lower()
        fl = " ".join(files).lower()

        if any(p in fl for p in ["test_", "_test", ".spec.", "tests/", "__tests__"]):
            return "test"
        if all(f.endswith((".md", ".rst", ".txt")) for f in files if f):
            return "docs"
        if all(f.endswith((".css", ".scss", ".less")) for f in files if f):
            return "style"
        fix_kw = ["fix", "bug", "error", "exception", "crash", "null",
                  "undefined", "traceback", "404", "500"]
        if any(k in dl for k in fix_kw):
            return "fix"
        feat_kw = ["def ", "function ", "class ", "const ", "export ",
                   "route", "endpoint", "handler", "component", "module"]
        if any(k in dl for k in feat_kw):
            return "feat"
        if any(k in dl for k in ["rename", "move", "extract", "cleanup", "refactor"]):
            return "refactor"
        return "feat"

    def _derive_scope(self, files: list) -> str:
        """Extract scope from file paths (top-level directory or filename)."""
        if not files:
            return ""
        dirs = {f.replace("\\", "/").split("/")[0]
                for f in files if "/" in f}
        if len(dirs) == 1:
            scope = list(dirs)[0]
        elif dirs:
            scope = sorted(dirs, key=len)[0]
        else:
            scope = files[0].rsplit(".", 1)[0]
        return re.sub(r"[^a-z0-9\-_]", "", scope.lower())[:20]

    # ──────────────────────────────────────────
    # Task 1: Generate commit message
    # ──────────────────────────────────────────

    def generate_commit_message(self, repo_state: dict, files: list = None) -> str:
        """
        Generate a meaningful commit message from ACTUAL CODE CHANGES.
        
        Two-pass strategy:
          Pass 1: What specifically changed? (reads real diff lines)
          Pass 2: Write the commit message based on that understanding
        
        With Gemini this produces very specific messages like:
          "feat(auth): add JWT expiry check in validateToken middleware"
        Instead of:
          "feat: update auth.py"
        """
        status = repo_state.get("status", {})
        target = files or (
            status.get("modified", []) +
            status.get("added",    []) +
            status.get("deleted",  [])
        )

        diff_content = self._extract_meaningful_diff(repo_state, target)
        commit_type  = self._classify_change_type(diff_content, target)
        scope        = self._derive_scope(target)

        # ── Pass 1: Understand the change ──────────────────
        system1 = (
            "You are a senior engineer doing code review. "
            "Read the diff and answer in EXACTLY ONE sentence: "
            "What specific functionality was added, changed, or fixed? "
            "Name the exact function/class/component affected. "
            "Be concrete. No filler words. No 'this commit'. "
            "Start with a verb in past tense."
        )
        user1 = f"""Files changed: {target[:8]}

{diff_content}

One sentence: what specifically changed?"""

        try:
            understanding = self._chat(system1, user1, max_tokens=80)
            understanding = understanding.strip().split("\n")[0]
        except Exception:
            understanding = f"updated {', '.join(target[:2])}"

        # ── Pass 2: Write the commit message ───────────────
        system2 = (
            "You write Git commit messages in conventional commits format.\n\n"
            "Format: type(scope): imperative description\n\n"
            "Types: feat, fix, refactor, docs, style, test, chore, perf\n\n"
            "STRICT RULES:\n"
            "  1. TOTAL length MUST be under 72 characters\n"
            "  2. Use imperative mood: add, fix, remove, update, implement, extract\n"
            "     NOT: added, fixed, removed, updating\n"
            "  3. scope = the module/component name (lowercase, no spaces)\n"
            "  4. description = what it does, specific, not generic\n"
            "  5. NO period at the end\n"
            "  6. NO generic descriptions: 'update files', 'make changes', "
            "'fix issues', 'improve code'\n"
            "  7. The description MUST reflect what the diff actually shows\n\n"
            f"Detected change type: {commit_type}\n"
            f"Scope hint: {scope}\n\n"
            "Output ONLY the commit message. No quotes. No explanation."
        )
        user2 = f"""What changed: {understanding}
Files: {target[:5]}
Scope: {scope}

Write the commit message:"""

        try:
            result = self._chat(system2, user2, max_tokens=80)
        except Exception:
            result = ""

        return self._clean_message(result, commit_type, scope, understanding)

    def _clean_message(self, raw: str, ctype: str, scope: str, understanding: str) -> str:
        """Validate and clean the commit message, construct fallback if bad."""
        if not raw:
            return self._fallback_message(ctype, scope, understanding)

        # Take first non-empty line, strip markdown
        line = ""
        for l in raw.splitlines():
            l = l.strip().strip('"\'`*#>').strip()
            if l:
                line = l
                break

        if not line:
            return self._fallback_message(ctype, scope, understanding)

        # Must start with a valid type
        valid = ["feat", "fix", "refactor", "docs", "style",
                 "test", "chore", "perf", "ci", "build"]
        if not any(line.startswith(t) for t in valid):
            if scope:
                line = f"{ctype}({scope}): {line}"
            else:
                line = f"{ctype}: {line}"

        # Enforce 72-char limit
        if len(line) > 72:
            colon = line.find(": ")
            if colon != -1:
                prefix  = line[:colon + 2]
                desc    = line[colon + 2:]
                max_d   = 72 - len(prefix)
                line    = prefix + (desc[:max_d - 3] + "..." if max_d > 10 else desc[:10])
            else:
                line = line[:69] + "..."

        # Reject generic messages
        generic = ["update files", "make changes", "update code", "add code",
                   "fix issues", "improve code", "modify", "changes", "updates"]
        desc_part = line.split(": ", 1)[-1].lower()
        if any(g == desc_part or desc_part.startswith(g) for g in generic):
            return self._fallback_message(ctype, scope, understanding)

        return line

    def _fallback_message(self, ctype: str, scope: str, understanding: str) -> str:
        """Construct message from understanding string when AI output is unusable."""
        text = understanding.strip().rstrip(".")
        # Remove filler prefixes
        for filler in ["This change ", "The code ", "This commit ", "I ", "We "]:
            if text.lower().startswith(filler.lower()):
                text = text[len(filler):]
                break
        # Make imperative: trim -ed endings
        words = text.split()
        if words and len(words[0]) > 4:
            w = words[0].lower()
            if w.endswith("ed") and not w.endswith("eed"):
                words[0] = w[:-2]  # "added" → "add", "fixed" → "fix"
            elif w.endswith("ing"):
                words[0] = w[:-3]  # "adding" → "add"
        desc = " ".join(words)[:50] if words else f"update {scope or 'code'}"
        base = f"{ctype}({scope}): {desc}" if scope else f"{ctype}: {desc}"
        return base[:72]

    # ──────────────────────────────────────────
    # Task 2: Plan commits
    # ──────────────────────────────────────────

    def plan_commits(self, repo_state: dict) -> list[dict]:
        """
        Group file changes into logical commits.
        With Gemini, the groupings are much more semantically accurate.
        """
        status    = repo_state.get("status", {})
        all_files = (
            status.get("modified", []) +
            status.get("added",    []) +
            status.get("deleted",  [])
        )

        if not all_files:
            return []

        # Small changesets: skip planning overhead
        if len(all_files) <= 3:
            msg = self.generate_commit_message(repo_state, all_files)
            return [{"message": msg, "files": all_files, "reason": "Small changeset"}]

        diff_content = self._extract_meaningful_diff(repo_state)

        system = (
            "You are a senior engineer grouping code changes into Git commits.\n\n"
            "GROUPING RULES:\n"
            "  1. Each commit = one logical unit of work\n"
            "  2. Related files (same feature/fix/module) → same commit\n"
            "  3. Unrelated changes → separate commits\n"
            "  4. Max 3 commits total — do NOT over-split\n"
            "  5. When in doubt: ONE commit is better than wrong splits\n\n"
            "MESSAGE RULES:\n"
            "  - Use conventional commits: type(scope): description\n"
            "  - Under 72 characters\n"
            "  - Specific and meaningful — name the feature/function affected\n\n"
            "OUTPUT: Return ONLY a JSON array. No text before or after.\n"
            "Schema: "
            '[{"message": "feat(scope): description", '
            '"files": ["path/file.py"], '
            '"reason": "why grouped together"}]'
        )

        user = f"""Changed files: {json.dumps(all_files)}

Code changes:
{diff_content[:4000]}

Group into logical commits. Return JSON only."""

        try:
            raw   = self._chat(system, user, max_tokens=1000)
            plans = self._parse_json(raw)
        except Exception:
            plans = []

        if plans:
            validated = []
            for p in plans:
                if not isinstance(p, dict) or not p.get("files"):
                    continue
                pfiles = [str(f) for f in p["files"]]
                msg    = str(p.get("message", ""))
                if not self._is_good_message(msg):
                    msg = self.generate_commit_message(repo_state, pfiles)
                validated.append({
                    "message": msg,
                    "files":   pfiles,
                    "reason":  str(p.get("reason", ""))
                })
            if validated:
                return validated

        # Fallback: single commit
        msg = self.generate_commit_message(repo_state, all_files)
        return [{"message": msg, "files": all_files, "reason": "Single commit fallback"}]

    def _parse_json(self, raw: str) -> list:
        """Extract JSON array from AI response robustly."""
        if not raw:
            return []
        # Direct array
        s, e = raw.find("["), raw.rfind("]") + 1
        if s != -1 and e > s:
            try:
                return json.loads(raw[s:e])
            except json.JSONDecodeError:
                pass
        # Single object
        s, e = raw.find("{"), raw.rfind("}") + 1
        if s != -1 and e > s:
            try:
                return [json.loads(raw[s:e])]
            except json.JSONDecodeError:
                pass
        # Regex fallback
        blocks = re.findall(r'\{[^{}]+\}', raw, re.DOTALL)
        result = []
        for b in blocks:
            try:
                result.append(json.loads(b))
            except Exception:
                pass
        return result

    def _is_good_message(self, msg: str) -> bool:
        if not msg or len(msg) < 10 or len(msg) > 72:
            return False
        valid = ["feat", "fix", "refactor", "docs", "style",
                 "test", "chore", "perf", "ci", "build"]
        if not any(msg.startswith(t) for t in valid):
            return False
        generic = ["update files", "make changes", "update code", "changes", "updates"]
        return not any(g in msg.lower() for g in generic)

    # ──────────────────────────────────────────
    # Task 3: Summarize changes
    # ──────────────────────────────────────────

    def summarize_changes(self, repo_state: dict) -> str:
        diff    = self._extract_meaningful_diff(repo_state)
        status  = repo_state.get("status", {})
        backend = self.get_backend_name()

        system = (
            "You are reviewing a code diff. "
            "Summarize what changed in 1-2 sentences. "
            "Be specific: name the exact functions/components/features affected. "
            "Start with a verb. No markdown. No 'this commit'."
        )
        user = f"""Modified: {status.get('modified', [])}
New:      {status.get('added', [])}
Deleted:  {status.get('deleted', [])}

{diff[:3000]}

Summarize the changes:"""

        try:
            result = self._chat(system, user, max_tokens=120)
            return result.split("\n")[0].strip()
        except Exception:
            return "Code changes detected."

    # ──────────────────────────────────────────
    # Task 4: Initial commit message
    # ──────────────────────────────────────────

    def generate_initial_commit_message(self, repo_state: dict) -> str:
        status    = repo_state.get("status", {})
        added     = status.get("added", [])
        untracked = repo_state.get("untracked_content", "")[:2500]

        system = (
            "Write the first Git commit message for a new project. "
            "Detect the tech stack from the files and content. "
            "Write something specific: "
            "'feat: initialize React TypeScript app with Vite and Tailwind' "
            "NOT 'initial commit'. "
            "Use conventional format. Under 72 chars. "
            "Return ONLY the commit message. No quotes."
        )
        user = f"""Files: {added[:20]}

Content:
{untracked}

Write the initial commit message:"""

        try:
            result = self._chat(system, user, max_tokens=80)
            result = result.strip().strip('"\'`').split("\n")[0].strip()
            if self._is_good_message(result):
                return result
        except Exception:
            pass
        return "chore: initial project setup"

    # ──────────────────────────────────────────
    # Task 5: Should commit?
    # ──────────────────────────────────────────

    def should_commit(self, repo_state: dict) -> tuple[bool, str]:
        status    = repo_state.get("status", {})
        all_files = (
            status.get("modified", []) +
            status.get("added",    []) +
            status.get("deleted",  [])
        )
        if not all_files:
            return False, "No changes."

        system = (
            "Decide if these file changes deserve a Git commit. "
            "Be LIBERAL — commit unless the changes are truly trivial "
            "(empty files, binary blobs, or zero meaningful content). "
            "New source files, configs, READMEs all deserve commits. "
            "Return JSON only: {\"commit\": true, \"reason\": \"one sentence\"}"
        )
        user = f"""Files: {all_files}
Content preview: {repo_state.get('untracked_content', '')[:500]}

Should these be committed? Return JSON:"""

        try:
            raw = self._chat(system, user, max_tokens=80)
            s, e = raw.find("{"), raw.rfind("}") + 1
            if s != -1 and e > s:
                data = json.loads(raw[s:e])
                return bool(data.get("commit", True)), str(data.get("reason", ""))
        except Exception:
            pass
        return True, "Defaulting to commit."

    # ──────────────────────────────────────────
    # Task 6: Explain errors
    # ──────────────────────────────────────────

    def analyze_error(self, error_output: str, project_type: str) -> str:
        system = (
            "Help a developer fix a build/test error. "
            "In 2 sentences: what went wrong and how to fix it. "
            "Be specific. No markdown."
        )
        user = f"Project: {project_type}\n\nError:\n{error_output[:2000]}\n\nExplain and fix:"
        try:
            return self._chat(system, user, max_tokens=150)
        except Exception:
            return "Build failed. Check the error output above."

    # ──────────────────────────────────────────
    # Task 7: Suggest branch name
    # ──────────────────────────────────────────

    def suggest_branch_name(self, repo_state: dict) -> str:
        diff      = self._extract_meaningful_diff(repo_state)
        status    = repo_state.get("status", {})
        all_files = (
            status.get("modified", []) +
            status.get("added",    []) +
            status.get("deleted",  [])
        )

        system = (
            "Suggest a Git branch name. "
            "Format: prefix/short-description (kebab-case). "
            "Prefixes: feature/, fix/, refactor/, docs/, chore/. "
            "Max 50 chars. Return ONLY the branch name. No quotes."
        )
        user = f"Files: {all_files[:8]}\nChanges:\n{diff[:800]}\nBranch name:"

        try:
            result = self._chat(system, user, max_tokens=25)
            result = result.strip().strip('"\'`').split("\n")[0]
            result = re.sub(r"[^a-z0-9\-/]", "-", result.lower()).strip("-")
            if result and len(result) > 5:
                return result[:50]
        except Exception:
            pass
        return "feature/ai-changes"