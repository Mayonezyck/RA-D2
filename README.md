# Discord Scheduler Bot (Local)

A minimal Discord bot built in Python that supports slash commands and scheduled messages. It responds to slash commands and checks a local schedule on a loop; when the time matches, it posts the scheduled message.

## Features
- Slash command `/ping`
- Slash command group `/schedule` with `add`, `list`, `remove`
- Local JSON-backed schedule store (`schedules.json`)
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

## Running
```bash
DISCORD_TOKEN=your_token_here python bot.py
```

If you are using `.env`, you can load it with your preferred method (for example, `python -m dotenv run -- python bot.py` if you install `python-dotenv`).

## Commands
- `/ping` -> responds with `Pong!`
- `/schedule add time:<HH:MM> message:<text> channel:<optional>`
- `/schedule list`
- `/schedule remove schedule_id:<id>`

## Notes
- The schedule loop checks every 30 seconds.
- Times are interpreted using the machine's local time.
- Schedules persist in `schedules.json`.

## Troubleshooting
- Make sure the bot has permission to send messages in the target channel.
- If slash commands do not appear immediately, wait a minute or reinvite the bot with `applications.commands` scope.
