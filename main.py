#!/usr/bin/env python3
"""
main.py
=======
CLI entry point for the AI Git Agent v3.

NEW COMMANDS:
  --setup-remote          Interactive wizard to add GitHub/GitLab remote
  --daemon start          Start agent as background process (survives terminal close)
  --daemon stop           Stop background agent
  --daemon status         Check if background agent is running
  --daemon logs           View recent activity from background agent
  --watch                 Foreground watch mode (Ctrl+C to stop)
  --watch-forever         Internal flag used by daemon (don't use directly)

WORKFLOW EXAMPLES:

  1. First time setup:
       python main.py --setup-remote        # add GitHub remote
       python main.py --daemon start .      # start background agent

  2. Start agent, walk away, come back later:
       python main.py --daemon start .
       # ... code all day ...
       python main.py --daemon status
       python main.py --daemon logs
       python main.py --daemon stop

  3. Foreground (watch terminal while it works):
       python main.py --watch

  4. Run once:
       python main.py --push

  5. Preview without committing:
       python main.py --dry-run
"""

import sys
import os
import json
import argparse


# ─────────────────────────────────────────────
# Config Loader
# ─────────────────────────────────────────────

def load_config(config_path=None):
    default_path = os.path.join(os.path.dirname(os.path.abspath(__file__)), "config.json")
    path = config_path or default_path

    defaults = {
        "ollama": {
            "base_url": "http://localhost:11434",
            "model": "qwen2.5-coder:1.5b",
            "timeout": 120,
            "temperature": 0.3
        },
        "agent": {
            "auto_push": False,
            "auto_init": True,
            "interactive": False,
            "dry_run": False,
            "max_commits_per_run": 10,
            "watch_interval_seconds": 10,
            "watch_debounce_seconds": 3
        },
        "validation": {
            "enabled": True,
            "fail_on_error": True,
            "cmake_build_dir": "build",
            "python_test_command": "python -m pytest --tb=short -q"
        },
        "git": {"default_branch": "main"},
        "logging": {
            "verbose": False,
            "unicode_symbols": False,
            "log_to_file": False,
            "log_file": "agent.log"
        }
    }

    if os.path.exists(path):
        try:
            with open(path) as f:
                loaded = json.load(f)
            for key, val in loaded.items():
                if isinstance(val, dict) and key in defaults:
                    defaults[key].update(val)
                else:
                    defaults[key] = val
        except json.JSONDecodeError as e:
            print(f"Warning: config.json invalid ({e}). Using defaults.")

    return defaults


# ─────────────────────────────────────────────
# Status-only mode (no AI)
# ─────────────────────────────────────────────

def show_status(path):
    import git_handler
    path = os.path.abspath(path)
    if not git_handler.is_git_repo(path):
        print(f"ERROR: Not a Git repository: {path}")
        sys.exit(1)

    print(f"\n── Repository Status: {path} ──\n")
    print(f"  Branch : {git_handler.get_current_branch(path)}")
    remotes = git_handler.get_remotes(path)
    for n, u in remotes.items():
        print(f"  Remote : {n} -> {u}")
    if not remotes:
        print("  Remote : (none — run: python main.py --setup-remote)")

    status   = git_handler.get_status(path)
    modified = status.get("modified", [])
    added    = status.get("added",    [])
    deleted  = status.get("deleted",  [])
    total    = len(modified) + len(added) + len(deleted)

    print()
    if total == 0:
        print("  [OK] Working tree is clean")
    else:
        for f in modified: print(f"  [M] {f}")
        for f in added:    print(f"  [A] {f}")
        for f in deleted:  print(f"  [D] {f}")

    commits = git_handler.get_commit_log(path, n=5)
    if commits:
        print()
        print("  Recent commits:")
        for c in commits:
            print(f"    [{c['hash']}] {c['message']}")
    print()


# ─────────────────────────────────────────────
# Argument Parsing
# ─────────────────────────────────────────────

def parse_args():
    parser = argparse.ArgumentParser(
        prog="ai-git-agent",
        description="Autonomous AI-powered Git agent (local Ollama, fully offline)",
        formatter_class=argparse.RawDescriptionHelpFormatter,
        epilog="""
QUICK START:
  python main.py --setup-remote       Add GitHub/GitLab remote (one time)
  python main.py --daemon start       Start background agent (auto-commit + push forever)
  python main.py --daemon status      Check if background agent is running
  python main.py --daemon logs        View recent commits and activity
  python main.py --daemon stop        Stop the background agent

OTHER COMMANDS:
  python main.py                      Run once (commit current changes)
  python main.py --push               Run once + push
  python main.py --watch              Foreground watch mode (Ctrl+C stops it)
  python main.py --dry-run            Preview what AI would commit (no changes)
  python main.py --interactive        Ask for confirmation at each step
  python main.py --undo               Undo last commit (keeps your changes)
  python main.py --branch auto        Create AI-suggested branch
  python main.py --dashboard          Rich status overview
  python main.py --status             Raw git status (no AI needed)

TIPS:
  - Use --unicode on modern terminals (iTerm2, GNOME Terminal, Windows Terminal)
  - Configure auto-push in config.json: "auto_push": true
  - The daemon writes logs to .agent_log.txt in your project folder
  - First time: run --setup-remote, then --daemon start
        """
    )

    parser.add_argument("path", nargs="?", default=".",
                        help="Git repository path (default: current directory)")

    # ── Single-run modes ──
    parser.add_argument("--push",        "-p",  action="store_true",
                        help="Commit and push to remote")
    parser.add_argument("--dry-run",     "-n",  action="store_true",
                        help="Show what would happen, don't commit")
    parser.add_argument("--interactive", "-i",  action="store_true",
                        help="Ask for confirmation at each step")

    # ── Watch modes ──
    parser.add_argument("--watch",       "-w",  action="store_true",
                        help="Foreground watch: commit on every save (Ctrl+C to stop)")
    parser.add_argument("--watch-forever",      action="store_true",
                        help=argparse.SUPPRESS)  # Internal: used by daemon

    # ── Daemon commands ──
    parser.add_argument("--daemon",             nargs="?", const="status",
                        choices=["start", "stop", "status", "logs", "restart"],
                        metavar="COMMAND",
                        help="Daemon control: start | stop | status | logs | restart")

    # ── Setup ──
    parser.add_argument("--setup-remote",       action="store_true",
                        help="Interactive wizard to add GitHub/GitLab remote")

    # ── Extra features ──
    parser.add_argument("--undo",               action="store_true",
                        help="Undo last commit (changes kept in working tree)")
    parser.add_argument("--branch",             nargs="?", const="auto",
                        metavar="NAME",
                        help="Create branch (auto = AI picks the name)")
    parser.add_argument("--dashboard",          action="store_true",
                        help="Show rich status dashboard")
    parser.add_argument("--status",      "-s",  action="store_true",
                        help="Show git status only (no AI)")

    # ── Config ──
    parser.add_argument("--no-validate",        action="store_true",
                        help="Skip build/test validation")
    parser.add_argument("--no-init",            action="store_true",
                        help="Disable automatic git init")
    parser.add_argument("--unicode",            action="store_true",
                        help="Use unicode symbols (modern terminals only)")
    parser.add_argument("--verbose",     "-v",  action="store_true",
                        help="Verbose logging")
    parser.add_argument("--model",              default=None,
                        help="Override Ollama model (e.g. codellama, llama3.2)")
    parser.add_argument("--config",             default=None,
                        help="Path to custom config.json")
    parser.add_argument("--version",            action="version",
                        version="ai-git-agent v3.0")

    return parser.parse_args()


# ─────────────────────────────────────────────
# Main
# ─────────────────────────────────────────────

def main():
    args = parse_args()

    # Fast path — no AI needed
    if args.status:
        show_status(args.path)
        sys.exit(0)

    # Load config
    config = load_config(args.config)

    # Apply CLI overrides
    if args.push:           config["agent"]["auto_push"]      = True
    if args.verbose:        config["logging"]["verbose"]      = True
    if args.unicode:        config["logging"]["unicode_symbols"] = True
    if args.no_validate:    config["validation"]["enabled"]   = False
    if args.no_init:        config["agent"]["auto_init"]      = False
    if args.dry_run:        config["agent"]["dry_run"]        = True
    if args.interactive:    config["agent"]["interactive"]    = True
    if args.model:          config["ollama"]["model"]         = args.model

    # ── Internal daemon flag: watch forever, log to file ──
    if args.watch_forever:
        from agent import Agent
        import os
        path     = os.path.abspath(args.path)
        log_file = os.path.join(path, ".agent_log.txt")
        config["agent"]["auto_push"]   = True
        config["agent"]["interactive"] = False
        agent = Agent(config, log_file=log_file, silent=True)
        try:
            agent.watch_forever(path, log_file=log_file)
        except Exception as e:
            with open(log_file, "a") as f:
                f.write(f"FATAL: {e}\n")
        sys.exit(0)

    from agent import Agent
    agent = Agent(config)

    try:
        # ── Daemon control ──
        if args.daemon:
            from daemon import DaemonController
            dc = DaemonController()
            path = os.path.abspath(args.path)

            if args.daemon == "start":
                dc.start(path, config)
            elif args.daemon == "stop":
                dc.stop(path)
            elif args.daemon == "status":
                dc.status(path)
            elif args.daemon == "logs":
                dc.logs(path)
            elif args.daemon == "restart":
                dc.stop(path)
                import time; time.sleep(1)
                dc.start(path, config)

        # ── Setup remote ──
        elif args.setup_remote:
            agent.setup_remote(args.path)

        # ── Undo ──
        elif args.undo:
            agent.undo_last_commit(args.path)

        # ── Create branch ──
        elif args.branch is not None:
            agent.create_branch(args.path, args.branch)

        # ── Dashboard ──
        elif args.dashboard:
            agent.show_dashboard(args.path)

        # ── Foreground watch ──
        elif args.watch:
            config["agent"]["auto_push"] = True
            agent.watch(args.path)

        # ── Single run ──
        else:
            success = agent.run(args.path)
            sys.exit(0 if success else 1)

    except KeyboardInterrupt:
        print("\n\nInterrupted.")
        sys.exit(0)
    except Exception as e:
        print(f"\nUnexpected error: {e}")
        if args.verbose:
            import traceback
            traceback.print_exc()
        sys.exit(1)


if __name__ == "__main__":
    main()