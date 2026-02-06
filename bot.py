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
TASKS_PATH = Path("tasks.json")
CONFIG_PATH = Path("config.json")
CHECK_INTERVAL_SECONDS = 30
HOURLY_CHECK_SECONDS = 30


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


@dataclass
class TaskItem:
    id: int
    guild_id: int
    task: str
    urgency: Optional[str] = None
    deadline: Optional[str] = None  # ISO date string YYYY-MM-DD
    created_at: str = ""


class TaskStore:
    def __init__(self, path: Path) -> None:
        self.path = path
        self._items: List[TaskItem] = []
        self._next_id = 1
        self.load()

    def load(self) -> None:
        if not self.path.exists():
            self._items = []
            self._next_id = 1
            return
        data = json.loads(self.path.read_text())
        self._items = [TaskItem(**item) for item in data.get("items", [])]
        self._next_id = data.get("next_id", 1)

    def save(self) -> None:
        data = {
            "next_id": self._next_id,
            "items": [item.__dict__ for item in self._items],
        }
        self.path.write_text(json.dumps(data, indent=2))

    def add(
        self,
        guild_id: int,
        task: str,
        urgency: Optional[str],
        deadline: Optional[str],
    ) -> TaskItem:
        item = TaskItem(
            id=self._next_id,
            guild_id=guild_id,
            task=task,
            urgency=urgency,
            deadline=deadline,
            created_at=datetime.now().isoformat(timespec="seconds"),
        )
        self._next_id += 1
        self._items.append(item)
        self.save()
        return item

    def remove(self, task_id: int) -> bool:
        before = len(self._items)
        self._items = [item for item in self._items if item.id != task_id]
        if len(self._items) == before:
            return False
        self.save()
        return True

    def list_for_guild(self, guild_id: int) -> List[TaskItem]:
        return [item for item in self._items if item.guild_id == guild_id]


class ConfigStore:
    def __init__(self, path: Path) -> None:
        self.path = path
        self._data: Dict[str, Dict[str, Dict[str, Optional[int]]]] = {}
        self.load()

    def load(self) -> None:
        if not self.path.exists():
            self._data = {"hourly_task_list": {}}
            self.save()
            return
        self._data = json.loads(self.path.read_text())
        if "hourly_task_list" not in self._data:
            self._data["hourly_task_list"] = {}

    def save(self) -> None:
        self.path.write_text(json.dumps(self._data, indent=2))

    def set_hourly_task_list(self, guild_id: int, enabled: bool, channel_id: Optional[int]) -> None:
        self._data["hourly_task_list"][str(guild_id)] = {
            "enabled": enabled,
            "channel_id": channel_id,
        }
        self.save()

    def get_hourly_task_list(self, guild_id: int) -> Dict[str, Optional[int]]:
        return self._data.get("hourly_task_list", {}).get(str(guild_id), {"enabled": False, "channel_id": None})


class BotClient(discord.Client):
    def __init__(self, store: ScheduleStore, tasks: TaskStore, config: ConfigStore) -> None:
        intents = discord.Intents.default()
        super().__init__(intents=intents)
        self.tree = app_commands.CommandTree(self)
        self.store = store
        self.tasks = tasks
        self.config = config
        self._scheduler_task: Optional[asyncio.Task] = None
        self._hourly_task: Optional[asyncio.Task] = None

    async def setup_hook(self) -> None:
        await self.tree.sync()
        self._scheduler_task = asyncio.create_task(self._schedule_loop())
        self._hourly_task = asyncio.create_task(self._hourly_loop())

    async def _schedule_loop(self) -> None:
        await self.wait_until_ready()
        while not self.is_closed():
            await self._check_schedules()
            await asyncio.sleep(CHECK_INTERVAL_SECONDS)

    async def _hourly_loop(self) -> None:
        await self.wait_until_ready()
        while not self.is_closed():
            await self._check_hourly_task_list()
            await asyncio.sleep(HOURLY_CHECK_SECONDS)

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

    async def _check_hourly_task_list(self) -> None:
        now = datetime.now()
        if now.minute != 0:
            return
        if now.second > 5:
            return

        for guild in self.guilds:
            settings = self.config.get_hourly_task_list(guild.id)
            if not settings.get("enabled"):
                continue

            channel_id = settings.get("channel_id")
            channel: Optional[discord.abc.Messageable] = None
            if channel_id:
                channel = self.get_channel(channel_id)
                if channel is None:
                    try:
                        channel = await self.fetch_channel(channel_id)
                    except discord.DiscordException:
                        continue
            else:
                channel = guild.system_channel

            if channel is None:
                continue

            items = self.tasks.list_for_guild(guild.id)
            if not items:
                continue

            embed = build_task_embed(items)
            try:
                await channel.send(embed=embed)
            except discord.DiscordException:
                continue


store = ScheduleStore(SCHEDULES_PATH)
tasks = TaskStore(TASKS_PATH)
config = ConfigStore(CONFIG_PATH)
client = BotClient(store, tasks, config)


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

task_group = app_commands.Group(name="task", description="Manage a local checklist")


@task_group.command(name="add", description="Add a checklist item")
@app_commands.describe(
    task="The task description",
    urgency="Optional urgency label (e.g., low/medium/high)",
    deadline="Optional deadline in YYYY-MM-DD format",
)
async def task_add(
    interaction: discord.Interaction,
    task: str,
    urgency: Optional[str] = None,
    deadline: Optional[str] = None,
) -> None:
    if interaction.guild is None:
        await interaction.response.send_message("Tasks must be created in a server.")
        return

    if deadline and not _is_valid_date(deadline):
        await interaction.response.send_message("Invalid deadline. Use YYYY-MM-DD.")
        return

    item = tasks.add(
        guild_id=interaction.guild.id,
        task=task,
        urgency=urgency,
        deadline=deadline,
    )
    await interaction.response.send_message(f"Added task #{item.id}.")


@task_group.command(name="list", description="List checklist items for this server")
async def task_list(interaction: discord.Interaction) -> None:
    if interaction.guild is None:
        await interaction.response.send_message("No tasks found.")
        return

    items = tasks.list_for_guild(interaction.guild.id)
    if not items:
        await interaction.response.send_message("No tasks found.")
        return

    embed = build_task_embed(items)
    await interaction.response.send_message(embed=embed)


@task_group.command(name="remove", description="Remove a checklist item by id")
@app_commands.describe(task_id="Task id to remove")
async def task_remove(interaction: discord.Interaction, task_id: int) -> None:
    removed = tasks.remove(task_id)
    if removed:
        await interaction.response.send_message(f"Removed task #{task_id}.")
    else:
        await interaction.response.send_message(f"Task #{task_id} not found.")


@task_group.command(name="auto", description="Enable/disable hourly task list at :00")
@app_commands.describe(
    enabled="Turn the hourly task list on or off",
    channel="Channel to post in (defaults to current channel on enable)",
)
async def task_auto(
    interaction: discord.Interaction,
    enabled: bool,
    channel: Optional[discord.TextChannel] = None,
) -> None:
    if interaction.guild is None:
        await interaction.response.send_message("This can only be used in a server.")
        return

    channel_id: Optional[int] = None
    if enabled:
        target_channel = channel or interaction.channel
        if not isinstance(target_channel, discord.TextChannel):
            await interaction.response.send_message("Could not resolve a text channel.")
            return
        channel_id = target_channel.id

    config.set_hourly_task_list(interaction.guild.id, enabled, channel_id)
    if enabled:
        await interaction.response.send_message("Hourly task list enabled.")
    else:
        await interaction.response.send_message("Hourly task list disabled.")


@task_group.command(name="status", description="Show feature flag status")
async def task_status(interaction: discord.Interaction) -> None:
    if interaction.guild is None:
        await interaction.response.send_message("This can only be used in a server.")
        return

    settings = config.get_hourly_task_list(interaction.guild.id)
    enabled = bool(settings.get("enabled"))
    channel_id = settings.get("channel_id")

    embed = discord.Embed(title="Feature Flags", color=discord.Color.blurple())
    status_text = "Enabled" if enabled else "Disabled"
    channel_text = f"<#{channel_id}>" if channel_id else "Not set"
    embed.add_field(name="Hourly Task List", value=f"{status_text}\nChannel: {channel_text}", inline=False)

    await interaction.response.send_message(embed=embed)


client.tree.add_command(task_group)


def _is_valid_time(value: str) -> bool:
    try:
        datetime.strptime(value, "%H:%M")
        return True
    except ValueError:
        return False


def _is_valid_date(value: str) -> bool:
    try:
        datetime.strptime(value, "%Y-%m-%d")
        return True
    except ValueError:
        return False


def build_task_embed(items: List[TaskItem]) -> discord.Embed:
    urgency_rank = {"high": 0, "medium": 1, "low": 2}

    def sort_key(item: TaskItem) -> tuple:
        deadline_sort = item.deadline if item.deadline else "9999-12-31"
        urgency_sort = urgency_rank.get((item.urgency or "").lower(), 3)
        return (deadline_sort, urgency_sort, item.id)

    items_sorted = sorted(items, key=sort_key)

    embed = discord.Embed(title="Checklist", color=discord.Color.blurple())
    for item in items_sorted:
        details = []
        urgency_prefix = ""
        if item.urgency:
            urgency_label = item.urgency.lower()
            if urgency_label == "high":
                urgency_prefix = "🟥 "
            elif urgency_label == "medium":
                urgency_prefix = "🟧 "
            elif urgency_label == "low":
                urgency_prefix = "🟩 "
            else:
                urgency_prefix = "⬜ "
        if item.deadline:
            details.append(f"Deadline: {item.deadline}")
        embed.add_field(
            name=f"#{item.id}",
            value=f"{urgency_prefix}{item.task}" + ("\n" + "\n".join(details) if details else ""),
            inline=False,
        )
    return embed


if __name__ == "__main__":
    token = os.getenv("DISCORD_TOKEN")
    if not token:
        raise RuntimeError("DISCORD_TOKEN is not set")
    client.run(token)
