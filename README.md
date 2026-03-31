# AI Git Agent

Automate your Git workflow with AI-powered commit messages and intelligent repository management.

## Features

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

Edit `config.json` to customize agent behavior:

```json
{
  "agent": {
    "auto_push": false,
    "interactive": true
  },
  "ai": {
    "model": "gpt-4"
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
