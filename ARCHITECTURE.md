# Architecture & Design

## Project Overview

AI Git Agent is a modular system for automating Git workflows with AI-powered commit generation. It consists of several independent components that work together through a central orchestrator.

## Core Modules

### `agent.py` - Central Orchestrator

**Responsibility**: Main controller that coordinates all other modules.

**Key Classes**:
- `Agent` - Main orchestrator class
  - Manages repository state
  - Orchestrates commit workflow
  - Handles user interaction modes
  - Manages remote configuration

**Key Methods**:
- `preflight()` - Validates repository and configuration
- `stage_changes()` - Prepares changes for commit
- `generate_commit_message()` - Delegates to AI engine
- `execute_commit()` - Coordinates commit process
- `push_to_remote()` - Manages git push operations

### `daemon.py` - Background Process Management

**Responsibility**: Handles background daemon lifecycle and monitoring.

**Key Classes**:
- `DaemonController` - Manages daemon start/stop/status
  - Process forking and detachment
  - PID file management
  - Log file handling
  - Process health monitoring

**Key Functions**:
- `_is_process_alive()` - Check process status
- `_log_write()` - Append to daemon logs
- `_log_read()` - Retrieve daemon logs

### `RemoteSetup.py` - Remote Configuration

**Responsibility**: Interactive wizard for GitHub/GitLab remote configuration.

**Key Classes**:
- `RemoteSetup` - Interactive remote setup wizard
  - URL validation
  - Git remote configuration
  - Connection testing
  - State persistence

**Key Functions**:
- `load_state()` - Load saved remote configuration
- `save_state()` - Persist remote configuration

### `git_handler.py` - Git Command Interface

**Responsibility**: Low-level Git command execution and parsing.

**Key Functions**:
- `_run()` - Execute git commands with error handling
- `add_all()` - Stage all changes
- `commit()` - Create commits
- `get_branch()` - Get current branch
- `push()` - Push commits to remote

### `ai_engine.py` - AI Integration

**Responsibility**: AI model integration for commit message generation.

**Key Classes**:
- `AIEngine` - Coordinates AI model calls

**Key Methods**:
- `generate_commit_message()` - Generate AI commit message
- `analyze_diff()` - Analyze code changes

### `validator.py` - Validation & Analysis

**Responsibility**: Validates commits and detects project types.

**Key Classes**:
- `Validator` - Commit and change validation
- `ProjectTypeDetector` - Project type inference

**Key Functions**:
- `detect_project_type()` - Identify project type
- `validate_commit()` - Validate commit message

### `watcher.py` - File System Monitoring

**Responsibility**: Monitors file system for changes.

**Key Classes**:
- `Watcher` - Monitors directories for changes
- `TeeLogger` - Dual output logging (console + file)

**Key Methods**:
- `watch()` - Start watching directory
- `wait_for_changes()` - Block until changes detected

### `main.py` - CLI Entry Point

**Responsibility**: Command-line interface and argument parsing.

**Key Functions**:
- `parse_args()` - Parse CLI arguments
- `main()` - CLI main function

## Data Flow

```
User Input (CLI)
        ↓
main.py (argument parsing)
        ↓
Agent.preflight() (validation)
        ↓
Agent.stage_changes() (git add)
        ↓
AIEngine.generate_commit_message() (AI analysis)
        ↓
Agent.execute_commit() (git commit)
        ↓
Agent.push_to_remote() (git push)
```

## Operation Modes

### Interactive Mode
- User confirms each commit
- Prompts for remote setup
- Displays AI-generated messages for review

### Watch Mode
- Monitors directory for changes
- Auto-stages and commits
- Requires confirmation for first commit

### Daemon Mode
- Runs in background
- Continuous monitoring
- Auto-push enabled
- Logs all activity

## Configuration Model

Configuration is managed through `config.json`:

```json
{
  "agent": {
    "auto_push": false,
    "interactive": true
  },
  "ai": {
    "model": "gpt-4",
    "api_key": "${OPENAI_API_KEY}",
    "temperature": 0.7
  },
  "logging": {
    "verbose": false,
    "log_file": ".agent_log.txt"
  },
  "validation": {
    "max_message_length": 72,
    "require_scope": false
  }
}
```

## State Management

### Repository State (`.agent_state.json`)
```json
{
  "remote_url": "https://github.com/user/repo",
  "push_enabled": true,
  "project_type": "python",
  "daemon_pid": 12345
}
```

### Daemon State (`.agent_pid`)
- Stores current daemon process ID
- Used to check if daemon is running
- Cleaned up on daemon stop

## Design Patterns

### Module Composition
- Each module has a single responsibility
- Central `Agent` class composes functionality
- Loose coupling between modules

### Error Handling
- Graceful failure modes
- Comprehensive logging
- User-friendly error messages

### State Persistence
- JSON-based state files
- Automatic .gitignore management
- Recovery from state corruption

## Extension Points

1. **AI Engines**: Implement new `AIEngine` subclass for different models
2. **Project Detectors**: Add project type detection in `validator.py`
3. **Git Workflows**: Extend `git_handler.py` for custom workflows
4. **Monitoring**: Enhance `moniter.py` for health checks

## Dependencies

- Python 3.10+
- GitPython (git operations)
- OpenAI (AI features)
- Additional tools per configuration
