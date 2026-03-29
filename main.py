#!/usr/bin/env python3
"""
main.py
=======
CLI entry point for the AI Git Agent.

Usage:
  python main.py                          # Run once in current directory
  python main.py /path/to/repo           # Run once in specified repo
  python main.py --watch                 # Auto-watch current directory
  python main.py --watch /path/to/repo   # Auto-watch specified repo
  python main.py --push                  # Run and auto-push
  python main.py --status                # Show repo status only (no AI)
  python main.py --verbose               # Verbose logging
  python main.py --help                  # Show help

Environment:
  Requires Ollama running locally with qwen2.5-coder:1.5b model.
  See README.md for setup instructions.
"""

import sys
import os
import json
import argparse

# ─────────────────────────────────────────────
# Load config
# ─────────────────────────────────────────────

def load_config(config_path: str = None) -> dict:
    """
    Load configuration from config.json.
    Falls back to defaults if the file doesn't exist.
    """
    default_config_path = os.path.join(os.path.dirname(__file__), "config.json")
    path = config_path or default_config_path

    defaults = {
        "ollama": {
            "base_url": "http://localhost:11434",
            "model": "qwen2.5-coder:1.5b",
            "timeout": 120,
            "temperature": 0.3
        },
        "agent": {
            "auto_push": False,
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
            "log_to_file": False,
            "log_file": "agent.log"
        }
    }

    if os.path.exists(path):
        try:
            with open(path) as f:
                loaded = json.load(f)
            # Merge loaded config over defaults
            for key, val in loaded.items():
                if isinstance(val, dict) and key in defaults:
                    defaults[key].update(val)
                else:
                    defaults[key] = val
        except json.JSONDecodeError as e:
            print(f"Warning: config.json is invalid JSON: {e}")
            print("Using default configuration.")

    return defaults


# ─────────────────────────────────────────────
# Status-only mode (no AI needed)
# ─────────────────────────────────────────────

def show_status(path: str):
    """
    Print a human-readable repo status without using AI.
    Useful for quick checks.
    """
    import git_handler

    path = os.path.abspath(path)

    if not git_handler.is_git_repo(path):
        print(f"ERROR: '{path}' is not a Git repository.")
        sys.exit(1)

    print(f"\n── Repository Status: {path} ──\n")

    branch = git_handler.get_current_branch(path)
    print(f"  Branch : {branch}")

    remotes = git_handler.get_remotes(path)
    for name, url in remotes.items():
        print(f"  Remote : {name} → {url}")

    if not remotes:
        print("  Remote : (none configured)")

    status = git_handler.get_status(path)
    print()

    modified = status.get("modified", [])
    added = status.get("added", [])
    deleted = status.get("deleted", [])
    staged = status.get("staged", [])

    total = len(modified) + len(added) + len(deleted)

    if total == 0 and not staged:
        print("  ✓ Working tree is clean — nothing to commit")
    else:
        if modified:
            print(f"  Modified  ({len(modified)}):")
            for f in modified:
                print(f"    M {f}")
        if added:
            print(f"  New files ({len(added)}):")
            for f in added:
                print(f"    A {f}")
        if deleted:
            print(f"  Deleted   ({len(deleted)}):")
            for f in deleted:
                print(f"    D {f}")
        if staged:
            print(f"  Staged    ({len(staged)}):")
            for f in staged:
                print(f"    S {f}")

    commits = git_handler.get_commit_log(path, n=3)
    if commits:
        print()
        print("  Recent commits:")
        for c in commits:
            print(f"    [{c['hash']}] {c['message']}")

    print()


# ─────────────────────────────────────────────
# CLI Argument Parsing
# ─────────────────────────────────────────────

def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(
        prog="ai-git-agent",
        description="Autonomous AI-powered Git agent using local Ollama LLM",
        formatter_class=argparse.RawDescriptionHelpFormatter,
        epilog="""
Examples:
  python main.py                         Run agent in current directory
  python main.py /path/to/repo           Run agent in specified directory
  python main.py --watch                 Watch mode (auto-commit on changes)
  python main.py --push                  Run and push to remote
  python main.py --status                Show repo status (no AI needed)
  python main.py --no-validate           Skip build/test validation
  python main.py --verbose               Enable verbose debug logging
  python main.py --model llama3.2        Use a different Ollama model

Setup:
  1. Install Ollama: https://ollama.ai
  2. Pull model: ollama pull qwen2.5-coder:1.5b
  3. Start Ollama: ollama serve
  4. Run this agent!
        """
    )

    parser.add_argument(
        "path",
        nargs="?",
        default=".",
        help="Path to the Git repository (default: current directory)"
    )

    parser.add_argument(
        "--watch", "-w",
        action="store_true",
        help="Auto-watch mode: monitor for changes and commit automatically"
    )

    parser.add_argument(
        "--push", "-p",
        action="store_true",
        help="Automatically push commits to remote after creating them"
    )

    parser.add_argument(
        "--status", "-s",
        action="store_true",
        help="Show repository status only (does not use AI)"
    )

    parser.add_argument(
        "--no-validate",
        action="store_true",
        help="Skip build/test validation before committing"
    )

    parser.add_argument(
        "--verbose", "-v",
        action="store_true",
        help="Enable verbose/debug logging"
    )

    parser.add_argument(
        "--model",
        default=None,
        help="Override Ollama model (e.g. llama3.2, codellama)"
    )

    parser.add_argument(
        "--config",
        default=None,
        help="Path to custom config.json file"
    )

    parser.add_argument(
        "--version",
        action="version",
        version="ai-git-agent 1.0.0"
    )

    return parser.parse_args()


# ─────────────────────────────────────────────
# Main Entry Point
# ─────────────────────────────────────────────

def main():
    args = parse_args()

    # ── Status-only mode (fast, no AI) ──
    if args.status:
        show_status(args.path)
        sys.exit(0)

    # ── Load configuration ──
    config = load_config(args.config)

    # ── Apply CLI overrides ──
    if args.push:
        config["agent"]["auto_push"] = True

    if args.verbose:
        config["logging"]["verbose"] = True

    if args.no_validate:
        config["validation"]["enabled"] = False

    if args.model:
        config["ollama"]["model"] = args.model

    # ── Import and create agent ──
    # (imported here to allow --status to work without Ollama)
    from agent import Agent
    agent = Agent(config)

    # ── Run in watch mode or single run ──
    try:
        if args.watch:
            agent.watch(args.path)
        else:
            success = agent.run(args.path)
            sys.exit(0 if success else 1)

    except KeyboardInterrupt:
        print("\n\nInterrupted by user.")
        sys.exit(0)
    except Exception as e:
        print(f"\nUnexpected error: {e}")
        if args.verbose:
            import traceback
            traceback.print_exc()
        sys.exit(1)


if __name__ == "__main__":
    main()