import asyncio
import json
import os
from dataclasses import dataclass
from datetime import datetime, date
from pathlib import Path
from typing import Dict, List, Optional

import discord
from discord import app_commands

SCHEDULES_PATH = Path("schedules.json")
CHECK_INTERVAL_SECONDS = 30


@dataclass
class ScheduleItem:
    id: int
    guild_id: int
    channel_id: int
    time: str  # "HH:MM" in local time
    message: str
    last_run_date: Optional[str] = None  # ISO date string


class ScheduleStore:
    def __init__(self, path: Path) -> None:
        self.path = path
        self._items: List[ScheduleItem] = []
        self._next_id = 1
        self.load()

    def load(self) -> None:
        if not self.path.exists():
            self._items = []
            self._next_id = 1
            return
        data = json.loads(self.path.read_text())
        self._items = [ScheduleItem(**item) for item in data.get("items", [])]
        self._next_id = data.get("next_id", 1)

    def save(self) -> None:
        data = {
            "next_id": self._next_id,
            "items": [item.__dict__ for item in self._items],
        }
        self.path.write_text(json.dumps(data, indent=2))

    def add(self, guild_id: int, channel_id: int, time: str, message: str) -> ScheduleItem:
        item = ScheduleItem(
            id=self._next_id,
            guild_id=guild_id,
            channel_id=channel_id,
            time=time,
            message=message,
            last_run_date=None,
        )
        self._next_id += 1
        self._items.append(item)
        self.save()
        return item

    def remove(self, schedule_id: int) -> bool:
        before = len(self._items)
        self._items = [item for item in self._items if item.id != schedule_id]
        if len(self._items) == before:
            return False
        self.save()
        return True

    def list_for_guild(self, guild_id: int) -> List[ScheduleItem]:
        return [item for item in self._items if item.guild_id == guild_id]

    def all(self) -> List[ScheduleItem]:
        return list(self._items)

    def update_last_run(self, schedule_id: int, run_date: date) -> None:
        for item in self._items:
            if item.id == schedule_id:
                item.last_run_date = run_date.isoformat()
                break
        self.save()


class BotClient(discord.Client):
    def __init__(self, store: ScheduleStore) -> None:
        intents = discord.Intents.default()
        super().__init__(intents=intents)
        self.tree = app_commands.CommandTree(self)
        self.store = store
        self._scheduler_task: Optional[asyncio.Task] = None

    async def setup_hook(self) -> None:
        await self.tree.sync()
        self._scheduler_task = asyncio.create_task(self._schedule_loop())

    async def _schedule_loop(self) -> None:
        await self.wait_until_ready()
        while not self.is_closed():
            await self._check_schedules()
            await asyncio.sleep(CHECK_INTERVAL_SECONDS)

    async def _check_schedules(self) -> None:
        now = datetime.now()
        now_time = now.strftime("%H:%M")
        today = now.date()

        for item in self.store.all():
            if item.time != now_time:
                continue
            if item.last_run_date == today.isoformat():
                continue

            try:
                channel = self.get_channel(item.channel_id)
                if channel is None:
                    # Channel not found or bot not cached it yet
                    channel = await self.fetch_channel(item.channel_id)
                if isinstance(channel, discord.TextChannel):
                    await channel.send(item.message)
                    self.store.update_last_run(item.id, today)
            except discord.DiscordException:
                # Skip failures but keep the scheduler alive
                continue


store = ScheduleStore(SCHEDULES_PATH)
client = BotClient(store)


@client.tree.command(name="ping", description="Check if the bot is alive")
async def ping(interaction: discord.Interaction) -> None:
    await interaction.response.send_message("Pong!")


schedule_group = app_commands.Group(name="schedule", description="Manage scheduled messages")


@schedule_group.command(name="add", description="Add a scheduled message")
@app_commands.describe(
    time="Local time in HH:MM (24h) format",
    message="Message to send",
    channel="Channel to send to (defaults to current channel)",
)
async def schedule_add(
    interaction: discord.Interaction,
    time: str,
    message: str,
    channel: Optional[discord.TextChannel] = None,
) -> None:
    if interaction.guild is None:
        await interaction.response.send_message("Schedules must be created in a server.")
        return

    if not _is_valid_time(time):
        await interaction.response.send_message("Invalid time. Use HH:MM in 24h format.")
        return

    target_channel = channel or interaction.channel
    if not isinstance(target_channel, discord.TextChannel):
        await interaction.response.send_message("Could not resolve a text channel.")
        return

    item = store.add(
        guild_id=interaction.guild.id,
        channel_id=target_channel.id,
        time=time,
        message=message,
    )
    await interaction.response.send_message(
        f"Scheduled #{item.id} at {item.time} in #{target_channel.name}."
    )


@schedule_group.command(name="list", description="List schedules for this server")
async def schedule_list(interaction: discord.Interaction) -> None:
    if interaction.guild is None:
        await interaction.response.send_message("No schedules found.")
        return

    items = store.list_for_guild(interaction.guild.id)
    if not items:
        await interaction.response.send_message("No schedules found.")
        return

    lines = []
    for item in items:
        channel = interaction.guild.get_channel(item.channel_id)
        channel_name = channel.name if isinstance(channel, discord.TextChannel) else str(item.channel_id)
        lines.append(f"#{item.id}: {item.time} in #{channel_name} -> {item.message}")

    await interaction.response.send_message("\n".join(lines))


@schedule_group.command(name="remove", description="Remove a schedule by id")
@app_commands.describe(schedule_id="Schedule id to remove")
async def schedule_remove(interaction: discord.Interaction, schedule_id: int) -> None:
    removed = store.remove(schedule_id)
    if removed:
        await interaction.response.send_message(f"Removed schedule #{schedule_id}.")
    else:
        await interaction.response.send_message(f"Schedule #{schedule_id} not found.")


client.tree.add_command(schedule_group)


def _is_valid_time(value: str) -> bool:
    try:
        datetime.strptime(value, "%H:%M")
        return True
    except ValueError:
        return False


if __name__ == "__main__":
    token = os.getenv("DISCORD_TOKEN")
    if not token:
        raise RuntimeError("DISCORD_TOKEN is not set")
    client.run(token)
