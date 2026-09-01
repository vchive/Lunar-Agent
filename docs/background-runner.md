# Background runner

Lunar-Agent is a local CLI, not a daemon. `run --detach --json` is the default background mechanism:
it creates the durable run first, starts a new local process group, and returns the run ID. The child
controller writes stdout/stderr to `<run-workspace>/controller.log` and persists its PID/PGID in the
`runs` table. A parent Agent can poll `status --json` and issue `cancel <run-id>` without sharing a
Python process or a Hermes installation.

## macOS launchd (user agent)

For a workstation that should periodically resume unfinished runs, create a user LaunchAgent such
as `~/Library/LaunchAgents/com.vchive.lunar-agent-resume.plist` (replace the paths):

```xml
<?xml version="1.0" encoding="UTF-8"?>
<!DOCTYPE plist PUBLIC "-//Apple//DTD PLIST 1.0//EN" "http://www.apple.com/DTDs/PropertyList-1.0.dtd">
<plist version="1.0"><dict>
  <key>Label</key><string>com.vchive.lunar-agent-resume</string>
  <key>ProgramArguments</key><array>
    <string>/absolute/path/to/.venv/bin/python</string>
    <string>-m</string><string>famou</string>
    <string>resume</string><string>RUN_ID</string>
    <string>--home</string><string>/absolute/path/to/.famou</string>
  </array>
  <key>RunAtLoad</key><true/>
  <key>KeepAlive</key><false/>
  <key>StandardOutPath</key><string>/absolute/path/to/.famou/launchd.log</string>
  <key>StandardErrorPath</key><string>/absolute/path/to/.famou/launchd.err</string>
</dict></plist>
```

Load it for the current user with `launchctl bootstrap gui/$(id -u) ~/Library/LaunchAgents/com.vchive.lunar-agent-resume.plist`.
Use one plist per run, or invoke a small local script that reads pending run IDs from `status` data.

## Linux systemd user service

Create `~/.config/systemd/user/lunar-agent-resume@.service`:

```ini
[Unit]
Description=Resume Lunar-Agent run %i

[Service]
Type=oneshot
ExecStart=%h/path/to/.venv/bin/python -m famou resume %i --home %h/.famou
WorkingDirectory=%h/path/to/Lunar-Agent
```

Start a run with `systemctl --user start lunar-agent-resume@RUN_ID.service`. These examples are
optional conveniences; SQLite recovery through `resume` remains the source of truth after a crash.
