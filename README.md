# AI Git Agent

Automate your Git workflow with AI-powered commit messages and intelligent repository management.

## Features

- **Dual AI Backends**: Gemini API (free, Google AI) or Ollama (local) for commit message generation
- **Intelligent Batch Processing**: Collect file changes over a 5-minute window before creating commits
- **AI-Powered Commits**: Generates meaningful commit messages using AI analysis
- **Background Daemon Mode**: Run the agent continuously in the background
- **Interactive Remote Setup**: Wizard-based GitHub/GitLab remote configuration
- **Auto Push**: Automatically push commits to remote repositories
- **Project Type Detection**: Identifies and adapts to different project types
- **Watch Mode**: Monitor directories for changes and auto-commit

## Installation

```bash
git clone <repository-url>
cd ai-git-agent
pip install -r requirements.txt
```

## Quick Start

### Basic Usage

```bash
# Initialize agent for a repository
python main.py /path/to/repo

# Enable auto-push
python main.py --push /path/to/repo

# Verbose logging
python main.py --verbose /path/to/repo
```

### Watch Mode

```bash
# Watch a directory and auto-commit changes
python main.py --watch /path/to/repo

# Run forever in watch mode (interactive)
python main.py --watch-forever /path/to/repo
```

### Daemon Mode

```bash
# Start background daemon
python main.py --daemon start /path/to/repo

# Check daemon status
python main.py --daemon status /path/to/repo

# View daemon logs
python main.py --daemon logs /path/to/repo

# Stop daemon
python main.py --daemon stop /path/to/repo
```

## Configuration

### AI Backend: Gemini API vs Ollama

**Gemini API (Recommended - Free)**

The agent now uses Google's Gemini API by default (free tier with no credit card required):

1. Get your free API key: https://aistudio.google.com/app/apikey
2. Set via CLI:
```bash
python main.py --gemini-key "AIza..." --watch /path/to/repo
```

Or in `config.json`:
```json
{
  "gemini": {
    "api_key": "AIza...",
    "model": "gemini-1.5-flash",
    "temperature": 0.2
  }
}
```

Or via environment variable:
```bash
export GEMINI_API_KEY="AIza..."
```

**Ollama (Local Alternative)**

If Gemini is not configured, the agent automatically falls back to Ollama:
```bash
python main.py --model qwen2.5-coder:1.5b --watch /path/to/repo
```

### Batch Window Configuration

By default, the agent collects file changes over a 5-minute window before creating a commit:

```bash
# Use default 5-minute batch window
python main.py --watch /path/to/repo

# Use 1-minute batch window
python main.py --batch-window 60 --watch /path/to/repo

# Disable batching (commit immediately)
python main.py --batch-window 0 --watch /path/to/repo
```

Or in `config.json`:
```json
{
  "agent": {
    "batch_window_seconds": 300
  }
}
```

### Advanced Configuration

Edit `config.json` to customize agent behavior:

```json
{
  "agent": {
    "auto_push": false,
    "interactive": true,
    "batch_window_seconds": 300,
    "watch_interval_seconds": 5
  },
  "ollama": {
    "base_url": "http://localhost:11434",
    "model": "qwen2.5-coder:1.5b",
    "temperature": 0.2
  },
  "logging": {
    "verbose": false
  }
}
```

## Project Structure

- `agent.py` - Main agent logic and orchestration
- `daemon.py` - Background process management
- `RemoteSetup.py` - GitHub/GitLab remote configuration
- `git_handler.py` - Git command utilities
- `ai_engine.py` - AI commit message generation
- `validator.py` - Commit and project validation
- `watcher.py` - File system monitoring

## Contributing

See CONTRIBUTING.md for development guidelines.

## License

See LICENSE file for details.
