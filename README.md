# Discord Scheduler Bot (Local)

A minimal Discord bot built in Python that supports slash commands and scheduled messages. It responds to slash commands and checks a local schedule on a loop; when the time matches, it posts the scheduled message.

## Features
- Slash command `/ping`
- Slash command group `/schedule` with `add`, `list`, `remove`
- Slash command group `/task` with `add`, `list`, `remove`
- Local JSON-backed schedule store (`schedules.json`)
- Local JSON-backed checklist store (`tasks.json`)
- Local JSON config for feature flags (`config.json`)
- Local time matching (HH:MM, 24-hour)

## Requirements
- Python 3.10+
- A Discord application + bot token

## Setup
1. Create and activate a virtual environment (optional but recommended).
2. Install dependencies:

```bash
pip install -r requirements.txt
```

3. Set your bot token in a `.env` file:

```bash
cp .env.example .env
```

Then edit `.env` and set `DISCORD_TOKEN`.
Optionally set `DISCORD_GUILD_ID` to sync commands instantly to a specific server.

## Running
```bash
DISCORD_TOKEN=your_token_here DISCORD_GUILD_ID=your_server_id python bot.py
```

If you are using `.env`, you can load it with your preferred method (for example, `python -m dotenv run -- python bot.py` if you install `python-dotenv`).

## Commands
- `/ping` -> responds with `Pong!`
- `/schedule add time:<HH:MM> message:<text> channel:<optional>`
- `/schedule list`
- `/schedule remove schedule_id:<id>`
- `/task add task:<text> urgency:<optional> deadline:<YYYY-MM-DD optional>`
- `/task list`
- `/task remove task_id:<id>`
- `/task auto enabled:<true|false> channel:<optional>`
- `/task status`
- `/channel clear confirm:<true|false>`
- `/glossary add word:<text> note:<text>`
- `/glossary set word:<text> note:<text>`
- `/glossary get word:<text>`
- `/glossary list`
- `/glossary remove word:<text>`

## Notes
- The schedule loop checks every 30 seconds.
- Times are interpreted using the machine's local time.
- Schedules persist in `schedules.json`.
- The hourly task list posts at `HH:00` when enabled.

## Troubleshooting
- Make sure the bot has permission to send messages in the target channel.
- If slash commands do not appear immediately, wait a minute or reinvite the bot with `applications.commands` scope.
