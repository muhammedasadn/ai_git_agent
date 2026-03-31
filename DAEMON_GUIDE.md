# Daemon Mode Guide

## Overview

The AI Git Agent can run as a persistent background daemon, continuously monitoring your repository and auto-committing changes even after you close the terminal.

## How It Works

1. **Start**: `python main.py --daemon start /path/to/repo`
   - Forks a background process
   - Writes PID to `.agent_pid` file
   - Redirects output to `.agent_log.txt`

2. **Monitor**: The daemon watches for file changes and generates commits

3. **Stop**: `python main.py --daemon stop /path/to/repo`
   - Sends SIGTERM to the background process
   - Cleans up PID file

## Commands

### Start Daemon

```bash
python main.py --daemon start /path/to/repo
```

**Output:**
```
[>>] Starting AI Git Agent daemon...
[Repository]  : /path/to/repo
[Log file]    : /path/to/repo/.agent_log.txt
[>>] Daemon started! (PID: 12345)
```

### Check Status

```bash
python main.py --daemon status /path/to/repo
```

**Output:**
```
[>>] Daemon Status: /path/to/repo
    PID:          12345
    Running:      Yes
    Uptime:       2h 15m
    Last commit:  5 minutes ago
```

### View Logs

```bash
python main.py --daemon logs /path/to/repo
```

Shows the last 50 lines of daemon activity logged to `.agent_log.txt`.

### Stop Daemon

```bash
python main.py --daemon stop /path/to/repo
```

**Output:**
```
[>>] Stopping daemon (PID: 12345)...
[✓] Daemon stopped successfully
```

## Configuration for Daemon Mode

In `config.json`, set daemon-specific settings:

```json
{
  "agent": {
    "auto_push": true,
    "interactive": false
  },
  "logging": {
    "verbose": true
  },
  "daemon": {
    "watch_interval": 5,
    "log_retention_days": 7
  }
}
```

## Hidden Files

The daemon creates and maintains these files:

- `.agent_pid` - Current daemon process ID
- `.agent_log.txt` - Daemon activity log with timestamps
- `.agent_state.json` - Persistent daemon state (remote URL, settings)

These files are automatically added to `.gitignore`.

## Troubleshooting

### Daemon won't start

```bash
# Check if already running
python main.py --daemon status /path/to/repo

# View error logs
tail -f /path/to/repo/.agent_log.txt
```

### High CPU usage

- Check `.agent_log.txt` for errors
- Reduce watch interval in `config.json`
- Stop and restart: `python main.py --daemon stop /path/to/repo`
- Then start again: `python main.py --daemon start /path/to/repo`

### Manual cleanup

If daemon doesn't stop cleanly:

```bash
# Find the PID
cat /path/to/repo/.agent_pid

# Kill manually if needed
kill -9 <PID>

# Remove state files
rm /path/to/repo/.agent_pid
```

## Best Practices

1. **Enable Auto-Push**: Set `auto_push: true` in `config.json` for daemon mode
2. **Monitor Logs**: Periodically check `.agent_log.txt` for issues
3. **Test First**: Run in watch mode before enabling daemon
4. **Remote Setup**: Configure remote URL before starting daemon
5. **Backups**: Ensure you have backups before enabling auto-commit

## Advanced

### Running Multiple Daemons

You can run separate daemons for different repositories:

```bash
python main.py --daemon start /path/to/repo1
python main.py --daemon start /path/to/repo2
```

Each maintains its own PID and log files.

### Monitoring Daemon Health

```bash
# List all agent daemons
ps aux | grep "main.py.*--watch-forever"

# Check specific daemon status
python main.py --daemon status /path/to/repo
```
