#!/usr/bin/env python3
"""
main.py
=======
CLI entry point for the AI Git Agent.

Usage:
  python main.py                           Run once in current directory
  python main.py /path/to/repo            Run in specified repo
  python main.py --watch                  Auto-watch mode
  python main.py --push                   Run and auto-push to remote
  python main.py --dry-run                Plan commits without executing
  python main.py --interactive            Ask before each commit
  python main.py --undo                   Undo last commit (keeps changes)
  python main.py --branch auto            Create AI-named branch
  python main.py --branch my-branch       Create named branch
  python main.py --dashboard              Show repo status dashboard
  python main.py --status                 Show raw git status (no AI)
  python main.py --no-validate            Skip build/test validation
  python main.py --no-init               Disable auto git init
  python main.py --unicode               Use unicode symbols (modern terminals)
  python main.py --verbose               Verbose debug logging
  python main.py --model codellama       Use a different Ollama model
  python main.py --help                  Full help
"""

import sys
import os
import json
import argparse


# ─────────────────────────────────────────────
# Config Loader
# ─────────────────────────────────────────────

def load_config(config_path=None):
    default_path = os.path.join(os.path.dirname(__file__), "config.json")
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
        "git": {
            "default_branch": "main",
            "sign_commits": False
        },
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
            print(f"Warning: config.json is invalid ({e}). Using defaults.")

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
        print("  Remote : (none configured)")

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
# CLI Argument Parsing
# ─────────────────────────────────────────────

def parse_args():
    parser = argparse.ArgumentParser(
        prog="ai-git-agent",
        description="Autonomous AI-powered Git agent (local Ollama LLM)",
        formatter_class=argparse.RawDescriptionHelpFormatter,
        epilog="""
COMMANDS:
  python main.py                     Analyze changes and commit
  python main.py --watch             Auto-watch: commit on every save
  python main.py --push              Commit + push to remote
  python main.py --dry-run           Show what WOULD happen (no commits)
  python main.py --interactive       Ask for confirmation at each step
  python main.py --undo              Undo last commit (keeps your changes)
  python main.py --branch auto       Create an AI-named branch
  python main.py --branch NAME       Create a specific branch
  python main.py --dashboard         Show repo status dashboard
  python main.py --status            Show git status (no AI required)

SETUP:
  1. Install Ollama:   https://ollama.ai
  2. Pull model:       ollama pull qwen2.5-coder:1.5b
  3. Start Ollama:     ollama serve
  4. Run agent:        python main.py

TIPS:
  - Use --unicode on modern terminals (iTerm2, GNOME Terminal, Windows Terminal)
  - Use --no-validate to skip build checks on the first run
  - Use --dry-run to preview what the AI plans without committing
  - Edit config.json to customize model, timeouts, watch intervals
        """
    )

    parser.add_argument("path", nargs="?", default=".",
                        help="Git repository path (default: current directory)")

    # Modes
    parser.add_argument("--watch",       "-w", action="store_true",
                        help="Auto-watch mode: commit automatically on changes")
    parser.add_argument("--push",        "-p", action="store_true",
                        help="Auto-push after committing")
    parser.add_argument("--dry-run",     "-n", action="store_true",
                        help="Plan commits without executing them")
    parser.add_argument("--interactive", "-i", action="store_true",
                        help="Ask for confirmation before each commit")
    parser.add_argument("--undo",              action="store_true",
                        help="Undo last commit (changes kept in working tree)")
    parser.add_argument("--branch",            nargs="?", const="auto",
                        metavar="NAME",
                        help="Create branch (use 'auto' for AI-generated name)")
    parser.add_argument("--dashboard",         action="store_true",
                        help="Show rich status dashboard")
    parser.add_argument("--status",      "-s", action="store_true",
                        help="Show git status only (no AI required)")

    # Options
    parser.add_argument("--no-validate",       action="store_true",
                        help="Skip build/test validation")
    parser.add_argument("--no-init",           action="store_true",
                        help="Disable automatic git init")
    parser.add_argument("--unicode",           action="store_true",
                        help="Use unicode symbols (for modern terminals)")
    parser.add_argument("--verbose",     "-v", action="store_true",
                        help="Verbose/debug logging")
    parser.add_argument("--model",             default=None,
                        help="Override Ollama model (e.g. codellama, llama3.2)")
    parser.add_argument("--config",            default=None,
                        help="Path to custom config.json")
    parser.add_argument("--version",           action="version",
                        version="ai-git-agent v2.0")

    return parser.parse_args()


# ─────────────────────────────────────────────
# Main
# ─────────────────────────────────────────────

def main():
    args = parse_args()

    # Fast path: --status needs no AI
    if args.status:
        show_status(args.path)
        sys.exit(0)

    # Load config
    config = load_config(args.config)

    # Apply CLI overrides
    if args.push:           config["agent"]["auto_push"]   = True
    if args.verbose:        config["logging"]["verbose"]   = True
    if args.unicode:        config["logging"]["unicode_symbols"] = True
    if args.no_validate:    config["validation"]["enabled"] = False
    if args.no_init:        config["agent"]["auto_init"]   = False
    if args.dry_run:        config["agent"]["dry_run"]     = True
    if args.interactive:    config["agent"]["interactive"] = True
    if args.model:          config["ollama"]["model"]      = args.model

    from agent import Agent
    agent = Agent(config)

    try:
        if args.undo:
            agent.undo_last_commit(args.path)

        elif args.branch is not None:
            agent.create_branch(args.path, args.branch)

        elif args.dashboard:
            agent.show_dashboard(args.path)

        elif args.watch:
            agent.watch(args.path)

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