<div align="center">

```
   ___  _____   ______ ___ ___________   ___   ____  _____   ________
  / _ |/  _/ | / / __ \/ _ /_  __/   | / _ | / ___/ / ___/  / __/ _ |
 / __ |/ // |/ / /_/ / __ |/ / / __ |/ __ |/ (_ / / (_ /  / _// __ |
/_/ |_/___/|___/\____/_/ |_/_/ /_/ |_/_/ |_|\___/  \___/  /___/_/ |_|
```

# AI Git Agent

**The autonomous, AI-powered Git agent that commits and pushes your code while you focus on building.**

Fully local · Free · No cloud required · Zero subscriptions

[![Python](https://img.shields.io/badge/Python-3.10+-blue?style=flat-square&logo=python)](https://python.org)
[![Gemini](https://img.shields.io/badge/Gemini-1.5%20Flash-orange?style=flat-square&logo=google)](https://aistudio.google.com)
[![Ollama](https://img.shields.io/badge/Ollama-Local%20AI-green?style=flat-square)](https://ollama.ai)
[![License](https://img.shields.io/badge/License-MIT-purple?style=flat-square)](LICENSE)

</div>

---

## What Is This?

You are a developer. You write code. You forget to commit. You push everything in one giant blob called `final final v3 REAL THIS TIME`. Your git history looks like a crime scene.

**AI Git Agent fixes this.**

You start the agent once. It watches your project silently in the background. Every 5 minutes it wakes up, reads every line you changed, asks Gemini (or your local AI) to understand the code, splits changes into logical groups, writes precise commit messages, and pushes to GitHub. All automatically. You never type `git commit` again.

```
You save auth.py          ┐
You save utils.py         │  5-minute window
You save auth.py again    │  accumulating...
You save styles.css       ┘

Agent wakes up → reads ALL changes → ONE smart commit:

  [a3f9b12] feat(auth): add JWT expiry validation in authenticate middleware
  [c1e7d44] style(ui): update login form spacing and button colors

  Pushed to origin/main ✓
```

---

## Features

| Feature | Description |
|---|---|
| **Smart Batch Window** | Collects changes for N minutes before committing — fewer, smarter commits |
| **Gemini AI** | Uses Google Gemini 1.5 Flash (free, 1500 req/day) for high-quality commit messages |
| **Ollama Fallback** | Auto-switches to local Ollama if Gemini is unavailable |
| **Auto git init** | Initializes git repo if project doesn't have one yet |
| **Remote Setup Wizard** | Interactive wizard to add GitHub/GitLab with one command |
| **Daemon Mode** | Runs in background, survives terminal close, auto-restarts on error |
| **Live Monitor TUI** | Real-time terminal dashboard showing commits, pushes, AI activity |
| **Default Branch Safety** | Only pushes to `main`/`master` — never to feature branches |
| **Build Validation** | Runs tests/build before committing — stops if broken |
| **Zero Dependencies** | Pure Python stdlib only — no pip install needed |

---

## Architecture

```
ai-git-agent/
│
├── main.py          ← CLI entry point — all commands start here
├── agent.py         ← Orchestrator — runs all 6 phases in order
├── ai_engine.py     ← Gemini + Ollama backends, commit message generation
├── git_handler.py   ← All git operations (status, diff, add, commit, push)
├── watcher.py       ← File system monitor with 5-min batch window
├── daemon.py        ← Background process management (start/stop/status)
├── monitor.py       ← Live TUI dashboard (curses-based)
├── validator.py     ← Build/test runner (CMake, Python, Node, Rust)
├── remote_setup.py  ← GitHub/GitLab remote setup wizard
└── config.json      ← All settings
```

**How a commit cycle works:**

```
Phase 0: Preflight   → Is git initialized? Is AI available?
Phase 1: Analyze     → git status, git diff, file counts
Phase 2: AI Planning → Gemini reads diff → groups files → writes messages
Phase 3: Validate    → Run tests/build (stops if broken)
Phase 4: Execute     → git add → git commit (per group)
Phase 5: Push        → git push origin main (default branch only)
Phase 6: Report      → Print commit hashes, messages, stats
```

---

## Requirements

- **Python 3.10+** (no extra packages needed)
- **Git** installed and configured
- **One of:**
  - Gemini API key (free at [aistudio.google.com](https://aistudio.google.com/app/apikey)) ← recommended
  - Ollama running locally with `qwen2.5-coder:1.5b` ← offline fallback

---

## Installation

```bash
# Clone the agent
git clone https://github.com/yourusername/ai-git-agent
cd ai-git-agent

# That's it. No pip install. No virtualenv. Just Python.
python main.py --help
```

---

## Setup: Get Your Free Gemini Key

> Gemini gives you **1,500 free requests per day** — no credit card, no subscription.

**Step 1:** Go to → [https://aistudio.google.com/app/apikey](https://aistudio.google.com/app/apikey)

**Step 2:** Click **"Create API Key"** → Copy the key (starts with `AIza`)

**Step 3:** Add it to the agent:

```bash
# Option A: Environment variable (recommended — permanent)
echo 'export GEMINI_API_KEY="AIzaSyYOURKEYHERE"' >> ~/.bashrc
source ~/.bashrc

# Option B: config.json
# Open config.json and fill in:
"gemini": {
  "api_key": "AIzaSyYOURKEYHERE"
}

# Option C: command line (temporary, for testing)
python main.py --gemini-key "AIzaSyYOURKEYHERE"
```

**Step 4:** Test it works:

```bash
python main.py --dashboard
# Should show: [Gemini] gemini-1.5-flash ready (free tier)
```

---

## Setup: Ollama (Offline Fallback)

If you don't want Gemini or have no internet:

```bash
# Install Ollama
curl -fsSL https://ollama.ai/install.sh | sh

# Pull the model
ollama pull qwen2.5-coder:1.5b

# Start Ollama server
ollama serve

# The agent will auto-detect it
```

The agent always tries Gemini first, then falls back to Ollama automatically.

---

## First Time Project Setup

```bash
# Navigate to your project
cd ~/Documents/myproject

# Step 1: Add your GitHub remote (only need to do this once)
python /path/to/ai-git-agent/main.py --setup-remote

# Output:
# ============================================================
#   REMOTE REPOSITORY SETUP
# ============================================================
#   Enter remote URL: https://github.com/yourusername/myproject
#   [OK] Remote 'origin' added
#   IMPORTANT: authenticate once with: git push origin main

# Step 2: Authenticate with GitHub (one time only)
git config --global credential.helper store
git push origin main
# Enter your GitHub username
# Enter your Personal Access Token (NOT your password)
# Git remembers it forever after this

# Step 3: Start the agent
python /path/to/ai-git-agent/main.py --daemon start .
```

---

## All Commands Reference

### Single-Run Commands

**Run once — commit current changes:**
```bash
python main.py
python main.py /path/to/project      # specify project path
```
Analyzes current changes, generates commit messages, commits. Does NOT push.

---

**Run once + push to remote:**
```bash
python main.py --push
python main.py -p
python main.py --push /path/to/project
```
Same as above but also pushes to `origin/main` after committing.

---

**Preview mode (dry run) — see what WOULD happen:**
```bash
python main.py --dry-run
python main.py -n
```
Shows the AI's commit plan without making any actual commits. Safe to run anytime.
```
[DRY RUN] Planned commits:
  1. feat(auth): add JWT token validation in middleware
  2. test(auth): add unit tests for token expiry
Dry run complete — no changes made.
```

---

**Interactive mode — confirm before each commit:**
```bash
python main.py --interactive
python main.py -i
```
The agent asks "Proceed with 2 commits? [Y/n]" before executing.

---

### Watch Modes (Continuous)

**Foreground watch — stays in terminal:**
```bash
python main.py --watch
python main.py -w
python main.py --watch /path/to/project
```
Watches for changes in your project. Collects changes for the batch window (default 5 min), then commits + pushes. Press **Ctrl+C** to stop.

```
Watch mode started
Repo         : /home/asad/Documents/voidcraft
Poll interval: every 5s
Batch window : 300s (5m 0s) -- changes collected before committing
Tracking 47 files. Waiting for changes...

[14:22:01] [BATCH] First change detected: 2 modified
[14:22:01] [BATCH] Collection window opened — will commit in 300s
[14:24:33] [BATCH] More changes: 1 modified (4 events) — 148s remaining
[14:27:01] [BATCH] Window expired — accumulated 4 change events over 300s
[14:27:01] [BATCH] Analyzing all changes and committing...

  [AI] Summary: Updated API routes with pagination and added error handling
  [*] [a3f9b12] feat(api): add pagination to user list endpoint
  [*] [c1e7d44] fix(api): handle null response in error middleware
  [OK] Pushed to origin/main
```

---

**Watch with custom batch window:**
```bash
# 5-minute window (default) — good for focused coding sessions
python main.py --watch --batch-window 300

# 1-minute window — good for quick iteration
python main.py --watch --batch-window 60

# 30-second window — almost instant
python main.py --watch --batch-window 30

# Commit instantly on every save (no window)
python main.py --watch --batch-window 0
```

---

### Daemon Mode (Background — Most Powerful)

The daemon runs **silently in the background** — even after you close the terminal. It watches your project 24/7, commits on the batch window schedule, and pushes to GitHub automatically.

**Start the daemon:**
```bash
python main.py --daemon start
python main.py --daemon start .
python main.py --daemon start /path/to/project
```
```
  [>>] Starting AI Git Agent daemon...
  Repo    : /home/asad/Documents/voidcraft
  Log file: /home/asad/Documents/voidcraft/.agent_log.txt

  [OK] Daemon started successfully
       PID     : 12847
       Log     : .agent_log.txt

  The agent is now running in the background.
  It will auto-commit and push whenever you save files.

  Commands:
    python main.py --daemon status    # check if running
    python main.py --daemon logs      # view activity log
    python main.py --daemon stop      # stop the agent
```

---

**Check if daemon is running:**
```bash
python main.py --daemon status
```
```
  [OK] Status  : RUNNING
       PID     : 12847
       Started : 2024-12-01T09:00:00

  Recent activity:
    [09:05:01] [*] feat(ui): update navbar component styles
    [09:05:01] [^] Pushed to origin/main
```

---

**View recent activity log:**
```bash
python main.py --daemon logs
```
Shows the last 50 lines of `.agent_log.txt` with color-coded output:
- Green = commits and pushes
- Yellow = warnings
- Red = errors
- Magenta = AI activity

---

**Stop the daemon:**
```bash
python main.py --daemon stop
```

---

**Restart the daemon:**
```bash
python main.py --daemon restart
```

---

**Daemon + custom batch window:**
```bash
# 5-minute window in background (default)
python main.py --daemon start --batch-window 300

# 1-minute window in background
python main.py --daemon start --batch-window 60

# Instant commits in background
python main.py --daemon start --batch-window 0
```

---

### Monitor Mode (Live TUI Dashboard)

The monitor is a full-screen terminal UI that shows everything happening in real time.

**Open the monitor:**
```bash
python main.py --monitor
python main.py -m
python main.py --monitor /path/to/project

# Or run monitor.py directly
python monitor.py
python monitor.py /path/to/project
python monitor.py --compact        # narrow terminal layout
```

**What you see:**
```
  AI GIT AGENT — LIVE MONITOR ───────────────────── 14:32:01
  Repo: /home/asad/Documents/voidcraft
  ─────────────────────────────────────────────────────────────
  [ DAEMON STATUS ]     │ [ LIVE LOG  Filter: ALL ]
  Status: RUNNING       │ [14:30] [~] Changes: 2 modified
  PID   : 12847         │ [14:30] [A] AI: Added login route
  Uptime: 12m 4s        │ [14:30] [*] feat(auth): add JWT
                        │ [14:30] [^] Pushed to origin/main
  [ REPOSITORY ]        │ [14:31] [~] Changes: 1 modified
  Branch : main         │ [14:31] [*] fix(api): handle null
  Remote : github.com   │ [14:31] [^] Pushed to origin/main
  Pending: 0 files      │
                        │
  [ RECENT COMMITS ]    │
  a3f9b feat(auth)...   │
  c1e7d fix(api)...     │
  ─────────────────────────────────────────────────────────────
  q:Quit | s:Start | x:Stop | l:Filter | c:Clear | h:Help
```

**Monitor keyboard controls:**

| Key | Action |
|---|---|
| `q` or `ESC` | Quit the monitor |
| `s` | Start the daemon |
| `x` | Stop the daemon |
| `l` | Cycle log filter: ALL → COMMITS → ERRORS → AI → INFO |
| `c` | Clear the log display |
| `r` | Force refresh |
| `h` or `?` | Show help overlay |
| `↑` / `↓` | Scroll log one line |
| `Page Up/Down` | Scroll log 10 lines |
| `End` | Jump to bottom (latest entries) |

---

**Monitor + daemon together (recommended workflow):**
```bash
# Terminal 1: start daemon in background
python main.py --daemon start .

# Terminal 2: watch it live in the monitor
python main.py --monitor .
```

---

### Utility Commands

**Show git status (no AI needed):**
```bash
python main.py --status
python main.py -s
```

**Show full dashboard:**
```bash
python main.py --dashboard
```
Shows: branch, remote, daemon status, pending files, recent commits, AI engine status.

**Undo last commit (keeps your changes):**
```bash
python main.py --undo
```
Does `git reset --soft HEAD~1` — your files stay untouched, just the commit is removed.

**Create a branch:**
```bash
python main.py --branch auto          # AI picks a name based on your changes
python main.py --branch feature/login # create specific branch
```

**Set up GitHub/GitLab remote:**
```bash
python main.py --setup-remote
```
Interactive wizard — asks for URL, validates it, adds it to git, prints auth instructions.

---

### All Flags Reference

```bash
python main.py [PATH] [FLAGS]

PATH                        Repository path (default: current directory)

# Modes
--push,        -p           Commit and push to remote
--watch,       -w           Foreground watch mode (Ctrl+C to stop)
--dry-run,     -n           Preview plan without committing
--interactive, -i           Ask confirmation at each step
--daemon COMMAND            Background daemon: start|stop|status|logs|restart
--monitor,     -m           Open live TUI dashboard
--setup-remote              Add GitHub/GitLab remote (interactive)
--undo                      Undo last commit (changes kept)
--branch [NAME]             Create branch (auto = AI picks name)
--dashboard                 Show status dashboard
--status,      -s           Show git status (no AI)

# Timing
--batch-window SECS         Seconds to collect changes before committing
                            300 = 5 minutes (default)
                            60  = 1 minute
                            0   = instant (commit immediately)

# AI
--gemini-key KEY            Set Gemini API key for this run
--model MODEL               Override Ollama model name

# Behavior
--no-validate               Skip build/test validation
--no-init                   Disable automatic git init
--compact                   Use compact layout in monitor

# Output
--verbose,     -v           Verbose debug logging
--unicode                   Use unicode symbols (modern terminals)
--config FILE               Use custom config.json file
--version                   Show version
--help,        -h           Show help
```

---

## Commit Modes Comparison

| Mode | Command | How it works | Best for |
|---|---|---|---|
| **Instant** | `--batch-window 0` | Commits immediately when any file changes | Fast debugging, testing |
| **30-second** | `--batch-window 30` | 30s collection window | Quick sprints |
| **1-minute** | `--batch-window 60` | 1min window | Active development |
| **5-minute** | `--batch-window 300` | 5min window (default) | Normal coding sessions |
| **Manual** | *(no watch)* | Run once on demand | Controlled commits |

---

## Typical Workflows

### Workflow 1: Daily Development (Recommended)

```bash
# Morning: start the agent
cd ~/Documents/myproject
python ~/ai-git-agent/main.py --daemon start .

# Code all day — agent runs silently in background
# Every 5 minutes it commits and pushes automatically

# Evening: check what it did
python ~/ai-git-agent/main.py --daemon logs

# Stop when done
python ~/ai-git-agent/main.py --daemon stop
```

### Workflow 2: Watch + Monitor (See Everything)

```bash
# Terminal 1
python main.py --watch --batch-window 60

# Terminal 2 (open second terminal)
python main.py --monitor
```

### Workflow 3: Sprint Session (Instant Commits)

```bash
# Commit and push every time you save a file
python main.py --watch --batch-window 0
```

### Workflow 4: Preview Before Committing

```bash
# See what the AI plans without doing anything
python main.py --dry-run

# If you like the plan, run for real
python main.py --push
```

### Workflow 5: One-Shot Manual Commit

```bash
# Just commit + push current changes right now
python main.py --push
```

### Workflow 6: Team Project — Safe Mode

```bash
# Review every commit before it happens
python main.py --watch --interactive --batch-window 300
```

---

## config.json Reference

```json
{
  "gemini": {
    "api_key": "AIzaSy...",       // Your Gemini API key
    "model": "gemini-1.5-flash",  // gemini-1.5-flash (free, fast) or gemini-1.5-pro
    "temperature": 0.2            // 0.0 = deterministic, 1.0 = creative
  },
  "ollama": {
    "base_url": "http://localhost:11434",
    "model": "qwen2.5-coder:1.5b",  // Any installed Ollama model
    "timeout": 120,
    "temperature": 0.2
  },
  "agent": {
    "auto_push": false,           // true = always push after commit
    "auto_init": true,            // true = run git init if needed
    "interactive": false,         // true = ask before every commit
    "dry_run": false,             // true = plan only, never commit
    "max_commits_per_run": 10,    // max commits in one agent run
    "watch_interval_seconds": 5,  // how often to check for changes
    "batch_window_seconds": 300,  // collect changes for N seconds (5min default)
    "watch_debounce_seconds": 3   // extra wait after last change in a burst
  },
  "validation": {
    "enabled": true,              // false = skip build/test check
    "fail_on_error": true,        // false = commit even if build fails
    "cmake_build_dir": "build",
    "python_test_command": "python -m pytest --tb=short -q"
  },
  "git": {
    "default_branch": "main"
  },
  "logging": {
    "verbose": false,             // true = extra debug output
    "unicode_symbols": false      // true = use ●✓⚠ symbols (modern terminals)
  }
}
```

---

## How Commit Messages Are Generated

The agent uses a **two-pass AI strategy** to write meaningful commit messages:

**Pass 1 — Understand the code change:**
```
AI reads actual +/- diff lines and answers:
"What specifically changed? Name the function/class/feature."
→ "Added JWT expiry check in the authenticate() function of auth middleware"
```

**Pass 2 — Write the commit message:**
```
Using that understanding:
→ "feat(auth): add JWT expiry validation in authenticate middleware"
```

**Result examples:**

| Bad (old approach) | Good (this agent) |
|---|---|
| `feat: update auth.py` | `feat(auth): add JWT token expiry validation` |
| `chore: update files` | `chore(deps): upgrade React to 18.3 and update peer deps` |
| `fix: fix bug` | `fix(api): handle null response in getUserById endpoint` |
| `add stuff` | `feat(ui): implement dark mode toggle with localStorage persistence` |

---

## How the 5-Minute Batch Window Works

```
Timeline of a coding session:

  2:00:00  You save main.py           → WINDOW OPENS (5min timer starts)
  2:01:30  You save utils.py          → collected (2 events in window)
  2:02:45  You save main.py again     → collected (3 events in window)
  2:04:00  You save test_main.py      → collected (4 events in window)
  2:05:00  WINDOW EXPIRES             →
           Agent reads ALL 4 changes together
           AI sees the full picture of what you built
           Groups into logical commits:
             [a3f9b] feat(main): add user authentication handler
             [c1e7d] test(main): add unit tests for auth handler
           Pushes both to origin/main

  2:05:01  Window resets — waiting for next change...
  2:07:22  You save styles.css        → NEW WINDOW OPENS
  ...
```

**Why this matters:** If you committed on every save, you'd get 4 commits with messages like "update main.py" × 3, "add test file". With the batch window, you get 2 meaningful commits that tell the story of what you actually built.

---

## Supported Project Types

| Project Type | Detection | Validation Command |
|---|---|---|
| Python | `setup.py`, `pyproject.toml`, `.py` files | `pytest` or `py_compile` |
| CMake / C++ | `CMakeLists.txt` | `cmake .. && cmake --build .` |
| Node.js / React | `package.json` | `npm test` or `npm run build` |
| Rust | `Cargo.toml` | `cargo check` |
| Makefile | `Makefile` | `make` |
| Unknown | — | Skipped (commits proceed) |

---

## Troubleshooting

**"Cannot connect to Ollama"**
```bash
ollama serve                    # start Ollama
curl http://localhost:11434/api/tags   # verify it's running
```

**"Gemini API key invalid"**
```bash
# Get a new key from:
# https://aistudio.google.com/app/apikey
export GEMINI_API_KEY="AIzaSy..."
```

**"Gemini rate limit hit"**
The agent waits 60 seconds and retries automatically.
For heavy use, add a second API key or switch to Ollama.

**"Push rejected: non-fast-forward"**
```bash
git pull --rebase origin main
python main.py --push          # try again
```

**"PUSH BLOCKED: You are on branch 'feature/x'"**
The agent only pushes to the default branch for safety.
```bash
git checkout main
git merge feature/x
python main.py --push
```

**"Build/tests FAILED"**
The agent stopped before committing (by design).
Fix the errors shown, then re-run.
Use `--no-validate` to skip this check.

**Daemon won't start**
```bash
# Check the log for errors
cat .agent_log.txt

# Kill any stuck processes
python main.py --daemon stop
python main.py --daemon start
```

---

## Gemini Free Tier Limits

| Model | Free Requests/min | Free Requests/day | Quality |
|---|---|---|---|
| `gemini-1.5-flash` | 15 | 1,500 | ⭐⭐⭐⭐ Fast, great |
| `gemini-2.0-flash` | 15 | 1,500 | ⭐⭐⭐⭐⭐ Best free |
| `gemini-1.5-pro` | 2 | 50 | ⭐⭐⭐⭐⭐ Slow, premium |

The agent uses `gemini-1.5-flash` by default. Change in config.json:
```json
"gemini": { "model": "gemini-2.0-flash" }
```

The built-in rate limiter caps at 12 requests/minute to stay safely under the 15/min limit.

---

## Project File Reference

| File | Purpose |
|---|---|
| `main.py` | CLI entry point — all commands parsed here |
| `agent.py` | Orchestrator — runs the 6-phase commit cycle |
| `ai_engine.py` | Gemini + Ollama AI clients, commit message logic |
| `git_handler.py` | All git operations via subprocess |
| `watcher.py` | File system monitor, batch window timer |
| `daemon.py` | Background process manager (fork, PID tracking) |
| `monitor.py` | Curses-based live TUI dashboard |
| `validator.py` | Build/test runner for different project types |
| `remote_setup.py` | GitHub/GitLab remote setup wizard |
| `config.json` | All configuration settings |
| `.agent_state.json` | Auto-created: saved remote URL, daemon state |
| `.agent_log.txt` | Auto-created: full activity log |
| `.agent_pid` | Auto-created: daemon process ID |

---

## License

MIT License — free for personal and commercial use.

---

<div align="center">

**Built for developers who ship, not for developers who commit.**

</div>
