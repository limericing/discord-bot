import os
import json
import time
import io
import re
import asyncio
import requests
import discord

from datetime import datetime, timezone, timedelta
from discord.ext import commands
from dotenv import load_dotenv


# ============================================================
# SETTINGS
# ============================================================

BASE_DIR = os.path.dirname(os.path.abspath(__file__))
ENV_PATH = os.path.join(BASE_DIR, ".env")

load_dotenv(ENV_PATH, override=True)

TOKEN = os.getenv("DISCORD_TOKEN")
ROBLOX_API_KEY = os.getenv("ROBLOX_API_KEY")
ROBLOX_GROUP_ID = os.getenv("ROBLOX_GROUP_ID")

print("ENV FILE FOUND:", os.path.isfile(ENV_PATH))
print("DISCORD TOKEN LOADED:", bool(TOKEN))
print("ROBLOX API KEY LOADED:", bool(ROBLOX_API_KEY))
print("ROBLOX GROUP ID LOADED:", bool(ROBLOX_GROUP_ID))

TICKET_PERMS_ROLE_ID = 1567435583473582170
VERIFY_GIVE_ROLE_ID = 1567044030359933041
TICKET_CATEGORY_ID = 1567437889552384030
TICKET_ROLE_ID = 1567435583473582170
REMOVE_ROLE_ID = 1567419664558989392

SPYCHECK_BYPASS_ROLE_ID = 1567437403805982810
SPYCHECK_TARGET_ROLE_ID = 1567044030359933041
COMMAND_ROLE_ID = 1567055696153813072

SPYCHECK_CHANNEL_ID = 1567435325733732403
TRANSCRIPT_CHANNEL_ID = 1567418285912367164
REPORT_CHANNEL_ID = 1567435293811023914

GACCEPT_PERMISSION_ROLE_ID = 1567435583473582170
GROUPCHECK_PERMISSION_ROLE_ID = 1567435583473582170
GROUPCHECK_GROUP_ID = "774188530"

ACCOUNT_MINIMUM_AGE_DAYS = 62
SPYCHECK_VERIFICATION_DAYS = 5


# ============================================================
# DEFAULT ROBLOX CREWS
# ============================================================

DEFAULT_CREWS = {
    "103710356": "Deathstar",
    "714622754": "Sworn",
    "977483761": "Snowfall",
    "809253103": "YWL",
    "34641725": "SpectralW",
    "76112202": "Grave",
    "35161823": "Tappers",
}


# ============================================================
# DATA FILES
# ============================================================

ACTIVITY_FILE = os.path.join(BASE_DIR, "activity_stats.json")
ROBLOX_LINKS_FILE = os.path.join(BASE_DIR, "roblox_links.json")
CREWS_FILE = os.path.join(BASE_DIR, "crews.json")


def load_json(filename, default):
    try:
        with open(filename, "r", encoding="utf-8") as file:
            return json.load(file)
    except (FileNotFoundError, json.JSONDecodeError):
        return default


def save_json(filename, data):
    with open(filename, "w", encoding="utf-8") as file:
        json.dump(data, file, indent=4)


STATS = load_json(ACTIVITY_FILE, {})
ROBLOX_LINKS = load_json(ROBLOX_LINKS_FILE, {})
CREWS = load_json(CREWS_FILE, DEFAULT_CREWS.copy())

VERIFY_LOCKED = False

save_json(CREWS_FILE, CREWS)


# ============================================================
# BOT
# ============================================================

intents = discord.Intents.default()
intents.members = True
intents.message_content = True
intents.voice_states = True

bot = commands.Bot(
    command_prefix=commands.when_mentioned_or(",", "$"),
    intents=intents,
    help_command=None
)


# ============================================================
# EMBED COLOURS
# ============================================================

COLOUR_MAIN = discord.Color.from_rgb(40, 65, 105)
COLOUR_SUCCESS = discord.Color.from_rgb(46, 204, 113)
COLOUR_ERROR = discord.Color.from_rgb(231, 76, 60)
COLOUR_WARNING = discord.Color.from_rgb(241, 196, 15)


# ============================================================
# PERMISSIONS
# ============================================================

def has_role(member, role_id):
    return any(role.id == role_id for role in member.roles)


def ticket_permission(member):
    return (
        TICKET_PERMS_ROLE_ID != 0
        and has_role(member, TICKET_PERMS_ROLE_ID)
    )


def command_permission(member):
    return (
        COMMAND_ROLE_ID != 0
        and has_role(member, COMMAND_ROLE_ID)
    )


def is_ticket_channel(channel):
    return (
        isinstance(channel, discord.TextChannel)
        and channel.name.startswith("verify-")
        and channel.category_id == TICKET_CATEGORY_ID
    )


# ============================================================
# VERIFICATION LOGGING
# ============================================================

async def log_verification(guild, member, moderator):

    report_channel = guild.get_channel(REPORT_CHANNEL_ID)

    if report_channel is None:
        try:
            report_channel = await bot.fetch_channel(REPORT_CHANNEL_ID)
        except (discord.NotFound, discord.Forbidden):
            return False

    embed = discord.Embed(
        title="VERIFICATION COMPLETED",
        description=f"{member.mention} has been verified.",
        color=COLOUR_SUCCESS,
        timestamp=discord.utils.utcnow()
    )

    embed.add_field(
        name="Discord User",
        value=str(member),
        inline=False
    )

    embed.add_field(
        name="Discord ID",
        value=str(member.id),
        inline=True
    )

    embed.add_field(
        name="Verified By",
        value=str(moderator),
        inline=True
    )

    await report_channel.send(embed=embed)
    return True


async def get_verification_dates(guild):

    report_channel = guild.get_channel(REPORT_CHANNEL_ID)

    if report_channel is None:
        report_channel = await bot.fetch_channel(REPORT_CHANNEL_ID)

    verification_dates = {}

    async for message in report_channel.history(
        limit=None,
        oldest_first=False
    ):

        if message.author.id != bot.user.id:
            continue

        for embed in message.embeds:

            if embed.title != "VERIFICATION COMPLETED":
                continue

            discord_id = None

            for field in embed.fields:
                if field.name == "Discord ID":
                    discord_id = field.value.strip().replace("`", "")
                    break

            if not discord_id or not discord_id.isdigit():
                continue

            if discord_id not in verification_dates:
                verification_dates[discord_id] = (
                    embed.timestamp or message.created_at
                )

    return verification_dates


# ============================================================
# CREW MANAGEMENT
# ============================================================

@bot.command()
async def addcrew(ctx, group_id: str = None, *, crew_name: str = None):

    if not command_permission(ctx.author):
        return

    if not group_id or not crew_name:
        await ctx.send(
            "Use: `,addcrew <roblox_group_id> <crew_name>`"
        )
        return

    group_id = group_id.strip()
    crew_name = crew_name.strip()

    if not group_id.isdigit():
        await ctx.send("The Roblox group ID must only contain numbers.")
        return

    if group_id in CREWS:
        await ctx.send(
            f"That group is already listed as **{CREWS[group_id]}**."
        )
        return

    CREWS[group_id] = crew_name
    save_json(CREWS_FILE, CREWS)

    await ctx.send(
        f"Added **{crew_name}** to the crew blacklist.\n"
        f"Roblox Group ID: `{group_id}`"
    )


@bot.command()
async def removecrew(ctx, group_id: str = None):

    if not command_permission(ctx.author):
        return

    if not group_id:
        await ctx.send("Use: `,removecrew <roblox_group_id>`")
        return

    group_id = group_id.strip()

    if group_id not in CREWS:
        await ctx.send("That Roblox group is not in the crew blacklist.")
        return

    crew_name = CREWS.pop(group_id)
    save_json(CREWS_FILE, CREWS)

    await ctx.send(
        f"Removed **{crew_name}** from the crew blacklist.\n"
        f"Roblox Group ID: `{group_id}`"
    )


@bot.command()
async def listcrews(ctx):

    if not command_permission(ctx.author):
        return

    if not CREWS:
        await ctx.send("There are currently no crews in the blacklist.")
        return

    embed = discord.Embed(
        title="Roblox Crew Blacklist",
        description="These groups are checked during verification.",
        color=COLOUR_MAIN
    )

    for group_id, crew_name in CREWS.items():
        embed.add_field(
            name=crew_name,
            value=f"Group ID: `{group_id}`",
            inline=True
        )

    await ctx.send(embed=embed)


# ============================================================
# ACTIVITY DATA
# ============================================================

def get_stats(user_id):

    user_id = str(user_id)

    if user_id not in STATS:
        STATS[user_id] = {
            "messages": [],
            "vc_sessions": [],
            "active_vc": None
        }

    STATS[user_id].setdefault("messages", [])
    STATS[user_id].setdefault("vc_sessions", [])
    STATS[user_id].setdefault("active_vc", None)

    return STATS[user_id]


def clean_stats(user_id):

    stats = get_stats(user_id)
    cutoff = time.time() - 604800

    stats["messages"] = [
        timestamp
        for timestamp in stats["messages"]
        if timestamp >= cutoff
    ]

    stats["vc_sessions"] = [
        session
        for session in stats["vc_sessions"]
        if len(session) == 2 and session[1] >= cutoff
    ]


def add_message_activity(user_id):

    stats = get_stats(user_id)
    stats["messages"].append(time.time())

    clean_stats(user_id)
    save_json(ACTIVITY_FILE, STATS)


def start_vc(user_id):

    stats = get_stats(user_id)

    if stats["active_vc"] is None:
        stats["active_vc"] = time.time()
        save_json(ACTIVITY_FILE, STATS)


def stop_vc(user_id):

    stats = get_stats(user_id)

    if stats["active_vc"] is None:
        return

    stats["vc_sessions"].append([
        stats["active_vc"],
        time.time()
    ])

    stats["active_vc"] = None

    clean_stats(user_id)
    save_json(ACTIVITY_FILE, STATS)


def message_count(user_id, seconds):

    stats = get_stats(user_id)
    clean_stats(user_id)

    cutoff = time.time() - seconds

    return sum(
        1 for timestamp in stats["messages"]
        if timestamp >= cutoff
    )


def vc_seconds(user_id, seconds):

    stats = get_stats(user_id)
    clean_stats(user_id)

    now = time.time()
    cutoff = now - seconds
    total = 0

    for start, end in stats["vc_sessions"]:

        effective_start = max(start, cutoff)

        if end > effective_start:
            total += end - effective_start

    if stats["active_vc"] is not None:

        effective_start = max(stats["active_vc"], cutoff)

        if now > effective_start:
            total += now - effective_start

    return int(total)


def format_vc(seconds):

    hours = seconds // 3600
    minutes = (seconds % 3600) // 60

    return f"{hours}h {minutes}m"


# ============================================================
# ROBLOX API
# ============================================================

async def roblox_username_to_id(username):

    response = await asyncio.to_thread(
        requests.post,
        "https://users.roblox.com/v1/usernames/users",
        json={
            "usernames": [username],
            "excludeBannedUsers": False
        },
        timeout=30
    )

    if response.status_code != 200:
        raise Exception(
            f"Roblox username lookup failed: HTTP {response.status_code}"
        )

    data = response.json()

    if not data.get("data"):
        return None

    return data["data"][0]["id"]


async def get_roblox_user(user_id):

    response = await asyncio.to_thread(
        requests.get,
        f"https://users.roblox.com/v1/users/{user_id}",
        timeout=30
    )

    if response.status_code != 200:
        raise Exception(
            f"Roblox profile lookup failed: HTTP {response.status_code}"
        )

    return response.json()


async def get_roblox_groups(user_id):

    response = await asyncio.to_thread(
        requests.get,
        f"https://groups.roblox.com/v2/users/{user_id}/groups/roles",
        timeout=30
    )

    if response.status_code != 200:
        raise Exception(
            f"Roblox group lookup failed: HTTP {response.status_code}"
        )

    data = response.json()
    crews = []

    for item in data.get("data", []):

        group = item.get("group", {})
        group_id = str(group.get("id"))

        if group_id in CREWS:
            crews.append(CREWS[group_id])

    return crews


# ============================================================
# LINKED ROBLOX ACCOUNT LOOKUP
# Used by groupcheck.
# ============================================================

async def get_linked_roblox_id(discord_user_id):

    discord_user_id = str(discord_user_id)

    saved_link = ROBLOX_LINKS.get(discord_user_id)

    if saved_link:
        roblox_id = saved_link.get("roblox_id")
        roblox_username = saved_link.get("roblox_username")

        if roblox_id and roblox_username:
            return str(roblox_id), str(roblox_username)

    channel = bot.get_channel(REPORT_CHANNEL_ID)

    if channel is None:
        channel = await bot.fetch_channel(REPORT_CHANNEL_ID)

    async for message in channel.history(
        limit=None,
        oldest_first=False
    ):

        collected_text = [message.content or ""]

        for embed in message.embeds:

            collected_text.append(embed.title or "")
            collected_text.append(embed.description or "")

            for field in embed.fields:
                collected_text.append(field.name or "")
                collected_text.append(field.value or "")

        text = "\n".join(collected_text)

        if "NEW ROBLOX ACCOUNT LINK" not in text:
            continue

        lines = [line.strip() for line in text.splitlines()]

        logged_discord_id = None
        roblox_id = None
        roblox_username = None

        for index, line in enumerate(lines):

            if line == "Discord ID" and index + 1 < len(lines):
                match = re.search(r"\d{15,22}", lines[index + 1])
                if match:
                    logged_discord_id = match.group(0)

            elif line == "Roblox ID" and index + 1 < len(lines):
                match = re.search(r"\d+", lines[index + 1])
                if match:
                    roblox_id = match.group(0)

            elif line == "Roblox Username" and index + 1 < len(lines):
                roblox_username = lines[index + 1].strip("` ")

        if logged_discord_id == discord_user_id:
            if roblox_id and roblox_username:
                return roblox_id, roblox_username

    return None, None


# ============================================================
# CLEAN SCAN DISPLAY
# ============================================================

def make_scan_embed(username, stage, description, completed=0):

    embed = discord.Embed(
        title="VERIFYING ROBLOX ACCOUNT",
        description=(
            f"**Account:** `{discord.utils.escape_markdown(username)}`\n\n"
            f"**Status:** {stage}\n"
            f"{description}"
        ),
        color=COLOUR_MAIN
    )

    embed.set_footer(text="Verification System")
    return embed


async def update_scan_message(
    message,
    username,
    stage,
    description,
    completed=0
):

    await message.edit(
        embed=make_scan_embed(
            username,
            stage,
            description,
            completed
        )
    )


# ============================================================
# VERIFICATION SCAN
# ============================================================

async def scan_verification(username, progress_message):

    try:

        await update_scan_message(
            progress_message,
            username,
            "Connecting to Roblox",
            "Looking up account..."
        )

        user_id = await roblox_username_to_id(username)

        if user_id is None:
            return {
                "success": False,
                "username": username,
                "reason": "Roblox user could not be found.",
                "crews": [],
                "eligible": False,
                "account_age_days": None
            }

        await update_scan_message(
            progress_message,
            username,
            "Account found",
            "Account located."
        )

        await asyncio.sleep(0.5)

        await update_scan_message(
            progress_message,
            username,
            "Retrieving profile",
            "Loading profile..."
        )

        user = await get_roblox_user(user_id)

        real_username = user.get("name", username)
        created = user.get("created")
        account_age_days = None

        await update_scan_message(
            progress_message,
            real_username,
            "Checking account age",
            "Checking account age..."
        )

        if created:

            created_date = datetime.fromisoformat(
                created.replace("Z", "+00:00")
            )

            account_age_days = int(
                (
                    datetime.now(timezone.utc) - created_date
                ).total_seconds() / 86400
            )

        await asyncio.sleep(0.5)

        await update_scan_message(
            progress_message,
            real_username,
            "Checking group memberships",
            "Checking group memberships..."
        )

        crews = await get_roblox_groups(user_id)

        await asyncio.sleep(0.5)

        await update_scan_message(
            progress_message,
            real_username,
            "Checking crew blacklist",
            "Checking crew blacklist..."
        )

        too_new = (
            account_age_days is not None
            and account_age_days <= ACCOUNT_MINIMUM_AGE_DAYS
        )

        eligible = (
            len(crews) == 0
            and not too_new
        )

        await asyncio.sleep(0.5)

        await update_scan_message(
            progress_message,
            real_username,
            "Finishing scan",
            "Finishing scan..."
        )

        await asyncio.sleep(0.5)

        return {
            "success": True,
            "username": real_username,
            "user_id": str(user_id),
            "crews": crews,
            "eligible": eligible,
            "account_age_days": account_age_days,
            "too_new": too_new
        }

    except requests.RequestException as error:

        return {
            "success": False,
            "username": username,
            "reason": f"Roblox API connection error: {str(error)[:300]}",
            "crews": [],
            "eligible": False,
            "account_age_days": None
        }

    except Exception as error:

        return {
            "success": False,
            "username": username,
            "reason": f"Scan could not be completed: {str(error)[:300]}",
            "crews": [],
            "eligible": False,
            "account_age_days": None
        }


# ============================================================
# VERIFICATION RESULT
# ============================================================

def verification_embed(result):

    if not result.get("success"):

        embed = discord.Embed(
            title="SCAN COULD NOT BE COMPLETED",
            description=(
                "The verification scan encountered an error.\n\n"
                f"**Reason:** {result.get('reason', 'Unknown error')}"
            ),
            color=COLOUR_WARNING
        )

        embed.set_footer(text="Verification System")
        return embed

    eligible = result["eligible"]

    embed = discord.Embed(
        title=(
            "VERIFICATION PASSED"
            if eligible
            else "VERIFICATION FLAGGED"
        ),
        description=(
            "The account passed all configured checks."
            if eligible
            else "The account did not pass all configured checks."
        ),
        color=COLOUR_SUCCESS if eligible else COLOUR_ERROR
    )

    embed.add_field(
        name="Roblox Account",
        value=(
            f"**Username:** {result['username']}\n"
            f"**User ID:** `{result['user_id']}`"
        ),
        inline=False
    )

    if result["account_age_days"] is not None:

        days = result["account_age_days"]

        embed.add_field(
            name="Account Age",
            value=f"**{days} days** ({days / 30.44:.1f} months)",
            inline=True
        )

    else:

        embed.add_field(
            name="Account Age",
            value="Unavailable",
            inline=True
        )

    crew_text = (
        "\n".join(f"FLAGGED: {crew}" for crew in result["crews"])
        if result["crews"]
        else "No blacklisted crews detected."
    )

    embed.add_field(
        name="Crew Memberships",
        value=crew_text,
        inline=False
    )

    if result.get("too_new"):

        eligibility_text = (
            f"Not eligible: account is {ACCOUNT_MINIMUM_AGE_DAYS} "
            "days old or younger."
        )

    elif result["crews"]:

        eligibility_text = (
            "Not eligible: blacklisted crew membership detected."
        )

    else:

        eligibility_text = "Account passed the configured checks."

    embed.add_field(
        name="Eligibility",
        value=eligibility_text,
        inline=False
    )

    embed.set_footer(text="Verification System")
    return embed


# ============================================================
# VERIFY MODAL
# ============================================================

class VerifyTicketModal(discord.ui.Modal):

    def __init__(self):

        super().__init__(title="Roblox Verification")

        self.roblox_username = discord.ui.TextInput(
            label="Roblox username",
            placeholder="Enter your Roblox username",
            required=True,
            max_length=100
        )

        self.activity = discord.ui.TextInput(
            label="What are you active in?",
            placeholder="Enter: vc, raids, or chat",
            required=True,
            max_length=20
        )

        self.add_item(self.roblox_username)
        self.add_item(self.activity)

    async def on_submit(self, interaction):

        if VERIFY_LOCKED:
            await interaction.response.send_message(
                "Verification is currently locked.",
                ephemeral=True
            )
            return

        guild = interaction.guild

        if guild is None:
            return

        activity = self.activity.value.strip().lower()

        if activity not in {"vc", "raids", "chat"}:
            await interaction.response.send_message(
                "Please enter only `vc`, `raids`, or `chat` for your activity.",
                ephemeral=True
            )
            return

        category = guild.get_channel(TICKET_CATEGORY_ID)

        if category is None:
            await interaction.response.send_message(
                "The verification category could not be found. Please contact staff.",
                ephemeral=True
            )
            return

        safe_name = interaction.user.name.lower()

        safe_name = "".join(
            character
            if character.isalnum() or character in "-_"
            else "-"
            for character in safe_name
        )

        channel_name = f"verify-{safe_name}"

        existing = discord.utils.find(
            lambda channel:
                channel.name == channel_name
                and channel.category_id == TICKET_CATEGORY_ID,
            guild.text_channels
        )

        if existing:
            await interaction.response.send_message(
                f"You already have a verification ticket: {existing.mention}",
                ephemeral=True
            )
            return

        await interaction.response.defer(ephemeral=True)

        ticket_role = guild.get_role(TICKET_ROLE_ID)
        bot_member = guild.me

        overwrites = {
            guild.default_role: discord.PermissionOverwrite(
                view_channel=False
            ),
            interaction.user: discord.PermissionOverwrite(
                view_channel=True,
                send_messages=True,
                read_message_history=True
            ),
            bot_member: discord.PermissionOverwrite(
                view_channel=True,
                send_messages=True,
                read_message_history=True,
                manage_channels=True,
                manage_messages=True
            )
        }

        if ticket_role:
            overwrites[ticket_role] = discord.PermissionOverwrite(
                view_channel=True,
                send_messages=True,
                read_message_history=True
            )

        channel = await guild.create_text_channel(
            channel_name,
            category=category,
            overwrites=overwrites,
            reason=f"Verification ticket for {interaction.user}"
        )

        await interaction.followup.send(
            f"Your verification ticket has been created: {channel.mention}",
            ephemeral=True
        )

        welcome = discord.Embed(
            title="VERIFICATION",
            description=(
                f"Welcome {interaction.user.mention}.\n\n"
                "Your Roblox account is being checked. "
                "Please wait for the result."
            ),
            color=COLOUR_MAIN
        )

        welcome.add_field(
            name="SUBMISSION",
            value=(
                f"Roblox: `{discord.utils.escape_markdown(self.roblox_username.value.strip())}`\n"
                f"Activity: `{activity.upper()}`"
            ),
            inline=False
        )

        await channel.send(embed=welcome)

        progress_message = await channel.send(
            embed=make_scan_embed(
                self.roblox_username.value.strip(),
                "Starting",
                "Preparing account check..."
            )
        )

        result = await scan_verification(
            self.roblox_username.value.strip(),
            progress_message
        )

        if result.get("success"):

            ROBLOX_LINKS[str(interaction.user.id)] = {
                "discord_id": str(interaction.user.id),
                "discord_username": str(interaction.user),
                "roblox_id": result.get("user_id"),
                "roblox_username": result.get("username"),
                "activity": activity
            }

            save_json(ROBLOX_LINKS_FILE, ROBLOX_LINKS)

            report_channel = guild.get_channel(REPORT_CHANNEL_ID)

            if report_channel is None:
                try:
                    report_channel = await bot.fetch_channel(
                        REPORT_CHANNEL_ID
                    )
                except (discord.NotFound, discord.Forbidden):
                    report_channel = None

            if report_channel is not None:

                report = discord.Embed(
                    title="NEW ROBLOX ACCOUNT LINK",
                    color=COLOUR_MAIN
                )

                report.add_field(
                    name="Discord User",
                    value=interaction.user.mention,
                    inline=False
                )

                report.add_field(
                    name="Discord ID",
                    value=f"`{interaction.user.id}`",
                    inline=True
                )

                report.add_field(
                    name="Roblox Username",
                    value=result["username"],
                    inline=True
                )

                report.add_field(
                    name="Roblox ID",
                    value=f"`{result['user_id']}`",
                    inline=False
                )

                report.add_field(
                    name="Activity",
                    value=activity.upper(),
                    inline=True
                )

                await report_channel.send(embed=report)

            else:
                print(
                    f"REPORT CHANNEL NOT FOUND: {REPORT_CHANNEL_ID}"
                )

        await channel.send(
            content=interaction.user.mention,
            embed=verification_embed(result)
        )

        if result.get("success") and result["eligible"]:

            await channel.send(
                "Your account passed the automated checks. "
                "Please wait for staff to complete verification."
            )

        elif result.get("success"):

            await channel.send(
                "Your account was flagged. A staff member can review it."
            )

        else:

            await channel.send(
                "The scan could not be completed. Please contact staff."
            )


# ============================================================
# VERIFY BUTTON
# ============================================================

class VerifyTicketView(discord.ui.View):

    def __init__(self):
        super().__init__(timeout=None)

    @discord.ui.button(
        label="Start Verification",
        style=discord.ButtonStyle.primary,
        custom_id="verify_ticket_button"
    )
    async def verify_button(self, interaction, button):

        if VERIFY_LOCKED:
            await interaction.response.send_message(
                "Verification is currently locked.",
                ephemeral=True
            )
            return

        await interaction.response.send_modal(VerifyTicketModal())


# ============================================================
# START VERIFY TICKET
# ============================================================

@bot.command()
async def startverifyticket(ctx):

    if not ticket_permission(ctx.author):
        return

    embed = discord.Embed(
        title="SERVER VERIFICATION",
        description=(
            "All members must complete Roblox account verification "
            "before accessing the server.\n\n"
            "Click the button below to begin."
        ),
        color=COLOUR_MAIN
    )

    embed.add_field(
        name="ACCOUNT CHECKS",
        value=(
            "Roblox account identity\n"
            "Account creation date\n"
            "Public group memberships\n"
            "Blacklisted crew memberships"
        ),
        inline=False
    )

    embed.set_footer(text="Verification Centre")

    await ctx.send(
        embed=embed,
        view=VerifyTicketView()
    )


# ============================================================
# LOCK VERIFY
# ============================================================

@bot.command()
async def lockverify(ctx):

    global VERIFY_LOCKED

    if not ticket_permission(ctx.author):
        return

    VERIFY_LOCKED = True

    embed = discord.Embed(
        title="VERIFICATION LOCKED",
        description="New verification tickets are temporarily disabled.",
        color=COLOUR_ERROR
    )

    await ctx.send(embed=embed)


# ============================================================
# UNLOCK VERIFY
# ============================================================

@bot.command()
async def unlockverify(ctx):

    global VERIFY_LOCKED

    if not ticket_permission(ctx.author):
        return

    VERIFY_LOCKED = False

    embed = discord.Embed(
        title="VERIFICATION UNLOCKED",
        description="Members can now create verification tickets again.",
        color=COLOUR_SUCCESS
    )

    await ctx.send(embed=embed)


# ============================================================
# TRANSCRIPTS
# ============================================================

async def create_transcript(channel):

    lines = []

    async for message in channel.history(
        limit=None,
        oldest_first=True
    ):

        timestamp = message.created_at.strftime(
            "%Y-%m-%d %H:%M:%S"
        )

        content = message.content or "[embed/button/attachment]"

        lines.append(
            f"[{timestamp}] "
            f"{message.author} "
            f"({message.author.id}): "
            f"{content}"
        )

        for embed in message.embeds:
            lines.append(f"Embed title: {embed.title or 'No title'}")
            if embed.description:
                lines.append(embed.description)

            for field in embed.fields:
                lines.append(f"{field.name}: {field.value}")

        for attachment in message.attachments:
            lines.append(f"Attachment: {attachment.url}")

    return "\n".join(lines)


async def save_transcript(channel):

    transcript_channel = channel.guild.get_channel(
        TRANSCRIPT_CHANNEL_ID
    )

    if transcript_channel is None:
        try:
            transcript_channel = await bot.fetch_channel(
                TRANSCRIPT_CHANNEL_ID
            )
        except (discord.NotFound, discord.Forbidden):
            return False

    transcript = await create_transcript(channel)

    file_data = io.BytesIO(transcript.encode("utf-8"))

    file = discord.File(
        file_data,
        filename=f"{channel.name}.txt"
    )

    await transcript_channel.send(
        content=f"Transcript for {channel.name}",
        file=file
    )

    return True


# ============================================================
# DELETE TICKET
# ============================================================

@bot.command()
async def delete(ctx):

    if not ticket_permission(ctx.author):
        return

    if not is_ticket_channel(ctx.channel):
        return

    await save_transcript(ctx.channel)

    await ctx.channel.delete(
        reason=f"Ticket deleted by {ctx.author}"
    )


# ============================================================
# VERIFY USER
# ============================================================

@bot.command()
async def verify(ctx, member: discord.Member = None):

    if not ticket_permission(ctx.author):
        return

    if not is_ticket_channel(ctx.channel):
        return

    if member is None:
        await ctx.send("Use: `,verify @user`")
        return

    give_role = ctx.guild.get_role(VERIFY_GIVE_ROLE_ID)
    remove_role = ctx.guild.get_role(REMOVE_ROLE_ID)

    if give_role is None:
        await ctx.send("The verification role could not be found.")
        return

    try:

        await member.add_roles(
            give_role,
            reason=f"Verified by {ctx.author}"
        )

        if remove_role:
            await member.remove_roles(
                remove_role,
                reason=f"Verified by {ctx.author}"
            )

        logged = await log_verification(
            ctx.guild,
            member,
            ctx.author
        )

        if not logged:
            await ctx.send(
                "The member received the verification role, "
                "but the verification log could not be sent. "
                "Please check the report channel permissions."
            )
            return

        await ctx.send(f"{member.mention} has been verified.")

        await save_transcript(ctx.channel)

        await ctx.channel.delete(
            reason=f"Verified by {ctx.author}"
        )

    except discord.Forbidden:
        await ctx.send(
            "The bot does not have permission to manage these roles "
            "or send the verification log."
        )

    except Exception as error:
        print("VERIFY ERROR:", repr(error))
        await ctx.send(
            "An error occurred while verifying this member."
        )


@verify.error
async def verify_error(ctx, error):

    if isinstance(error, commands.MissingRequiredArgument):
        if ticket_permission(ctx.author):
            await ctx.send("Use: `,verify @user`")


# ============================================================
# STATS
# ============================================================

@bot.command()
async def stats(ctx, member: discord.Member = None):

    if not command_permission(ctx.author):
        return

    if member is None:
        member = ctx.author

    user_id = str(member.id)

    clean_stats(user_id)

    daily_messages = message_count(user_id, 86400)
    weekly_messages = message_count(user_id, 604800)

    daily_vc = vc_seconds(user_id, 86400)
    weekly_vc = vc_seconds(user_id, 604800)

    roblox_data = ROBLOX_LINKS.get(user_id)

    output = {
        "discord_user": str(member),
        "discord_id": member.id,
        "roblox_username": (
            roblox_data.get("roblox_username")
            if roblox_data
            else None
        ),
        "messages": {
            "24h": daily_messages,
            "7d": weekly_messages
        },
        "vc": {
            "24h_seconds": daily_vc,
            "24h": format_vc(daily_vc),
            "7d_seconds": weekly_vc,
            "7d": format_vc(weekly_vc)
        }
    }

    await ctx.send(
        f"```json\n{json.dumps(output, indent=4)}\n```"
    )


# ============================================================
# SPYCHECK
# ============================================================

@bot.command()
async def spycheck(ctx):

    if not command_permission(ctx.author):
        return

    if ctx.channel.id != SPYCHECK_CHANNEL_ID:
        return

    status = await ctx.send(
        embed=discord.Embed(
            title="SPYCHECK RUNNING",
            description="Checking verification dates and activity...",
            color=COLOUR_MAIN
        )
    )

    try:
        verification_dates = await get_verification_dates(ctx.guild)

    except discord.Forbidden:
        await status.edit(
            embed=discord.Embed(
                title="SPYCHECK ERROR",
                description=(
                    "The bot cannot read the verification log channel. "
                    "Give it View Channel and Read Message History permissions."
                ),
                color=COLOUR_ERROR
            )
        )
        return

    except Exception as error:
        print("SPYCHECK LOG ERROR:", repr(error))

        await status.edit(
            embed=discord.Embed(
                title="SPYCHECK ERROR",
                description="Could not retrieve verification records.",
                color=COLOUR_ERROR
            )
        )
        return

    failures = []
    scanned = 0
    waiting = 0
    missing_records = 0

    now = discord.utils.utcnow()
    waiting_period = timedelta(days=SPYCHECK_VERIFICATION_DAYS)

    for member in ctx.guild.members:

        if member.bot:
            continue

        if not has_role(member, SPYCHECK_TARGET_ROLE_ID):
            continue

        if has_role(member, SPYCHECK_BYPASS_ROLE_ID):
            continue

        user_id = str(member.id)
        verified_at = verification_dates.get(user_id)

        if verified_at is None:
            missing_records += 1
            continue

        if now - verified_at < waiting_period:
            waiting += 1
            continue

        scanned += 1

        msgs = message_count(user_id, 604800)
        vc = vc_seconds(user_id, 604800)

        if msgs >= 200 and vc >= 10 * 3600:
            continue

        roblox_data = ROBLOX_LINKS.get(user_id)

        roblox_username = (
            roblox_data.get("roblox_username")
            if roblox_data
            else "Unknown"
        )

        failures.append(
            f"{member.mention} | "
            f"Discord ID: `{member.id}` | "
            f"Roblox: **{roblox_username}** | "
            f"Messages: **{msgs}** | "
            f"VC: **{format_vc(vc)}**"
        )

    if not failures:

        embed = discord.Embed(
            title="SPYCHECK COMPLETE",
            description=(
                "No members were flagged.\n\n"
                f"Members scanned: **{scanned}**\n"
                f"Members waiting for 5 days: **{waiting}**\n"
                f"Members without a verification record: **{missing_records}**"
            ),
            color=COLOUR_SUCCESS
        )

        await status.edit(embed=embed)
        return

    embed = discord.Embed(
        title="SPYCHECK RESULTS",
        description=(
            f"Members scanned: **{scanned}**\n"
            f"Members flagged: **{len(failures)}**\n"
            f"Members waiting for 5 days: **{waiting}**\n"
            f"Members without a verification record: **{missing_records}**"
        ),
        color=COLOUR_ERROR
    )

    await status.edit(embed=embed)

    current = ""

    for line in failures:

        if len(current) + len(line) + 1 > 1900:
            await ctx.send(current)
            current = line
        else:
            if current:
                current += "\n"
            current += line

    if current:
        await ctx.send(current)


# ============================================================
# MESSAGE TRACKING
# ============================================================

@bot.event
async def on_message(message):

    if not message.author.bot and message.guild:
        add_message_activity(message.author.id)

    await bot.process_commands(message)


# ============================================================
# VOICE TRACKING
# ============================================================

@bot.event
async def on_voice_state_update(member, before, after):

    if member.bot:
        return

    user_id = str(member.id)

    was_in_vc = before.channel is not None
    is_in_vc = after.channel is not None

    if not was_in_vc and is_in_vc:
        start_vc(user_id)

    elif was_in_vc and not is_in_vc:
        stop_vc(user_id)

    elif (
        was_in_vc
        and is_in_vc
        and before.channel != after.channel
    ):

        stats = get_stats(user_id)
        stats["active_vc"] = time.time()
        save_json(ACTIVITY_FILE, STATS)


# ============================================================
# ROBLOX GROUP ACCEPT
# Usage: ,gaccept RobloxUsername
# ============================================================

async def get_pending_roblox_requests():

    if not ROBLOX_API_KEY or not ROBLOX_GROUP_ID:
        raise Exception("Roblox API key or group ID is missing.")

    headers = {
        "x-api-key": ROBLOX_API_KEY
    }

    all_requests = []
    page_token = None

    while True:

        params = {
            "maxPageSize": 100
        }

        if page_token:
            params["pageToken"] = page_token

        response = await asyncio.to_thread(
            requests.get,
            f"https://apis.roblox.com/cloud/v2/groups/"
            f"{ROBLOX_GROUP_ID}/join-requests",
            headers=headers,
            params=params,
            timeout=30
        )

        if response.status_code != 200:
            raise Exception(
                f"Roblox API error {response.status_code}: "
                f"{response.text[:1000]}"
            )

        data = response.json()

        requests_list = data.get(
            "groupJoinRequests",
            data.get("joinRequests", [])
        )

        all_requests.extend(requests_list)

        page_token = data.get("nextPageToken")

        if not page_token:
            break

    return all_requests


@bot.command(name="gaccept")
async def gaccept(ctx, *, roblox_username: str = None):

    if not has_role(ctx.author, GACCEPT_PERMISSION_ROLE_ID):
        await ctx.send("You do not have permission to use this command.")
        return

    if not ROBLOX_API_KEY or not ROBLOX_GROUP_ID:
        await ctx.send("Roblox API key or group ID is missing.")
        return

    if not roblox_username:
        await ctx.send("Usage: `,gaccept RobloxUsername`")
        return

    roblox_username = roblox_username.strip()

    try:

        await ctx.send(
            f"Looking up Roblox account **{roblox_username}**..."
        )

        # Convert the typed username into a Roblox user ID.
        roblox_id = await roblox_username_to_id(roblox_username)

        if roblox_id is None:
            await ctx.send(
                f"Roblox user **{roblox_username}** could not be found."
            )
            return

        # Get the account's current username.
        user_data = await get_roblox_user(roblox_id)
        real_username = user_data.get("name", roblox_username)

        await ctx.send(
            f"Found **{real_username}** (`{roblox_id}`). "
            "Checking pending group requests..."
        )

        # Find the user's pending join request.
        join_requests = await get_pending_roblox_requests()

        request = None

        for item in join_requests:

            user = item.get("user", "")

            if isinstance(user, dict):
                user = user.get("path", "")

            if user == f"users/{roblox_id}":
                request = item
                break

        if request is None:
            await ctx.send(
                f"**{real_username}** has no pending join request "
                f"in group `{ROBLOX_GROUP_ID}`."
            )
            return

        # Extract the request resource path.
        request_path = request.get("path", "")

        if not request_path:
            await ctx.send(
                "Roblox returned a join request without a resource path."
            )
            return

        # Accept the request with an explicit JSON content type.
        accept_url = (
            f"https://apis.roblox.com/cloud/v2/"
            f"{request_path}:accept"
        )

        response = await asyncio.to_thread(
            requests.post,
            accept_url,
            headers={
                "x-api-key": ROBLOX_API_KEY,
                "Content-Type": "application/json"
            },
            data="{}",
            timeout=30
        )

        print("GACCEPT STATUS:", response.status_code)
        print("GACCEPT RESPONSE:", response.text[:1000])

        if response.status_code in (200, 201, 202, 204):

            await ctx.send(
                "**ROBLOX JOIN REQUEST ACCEPTED**\n"
                f"Roblox username: **{real_username}**\n"
                f"Roblox ID: `{roblox_id}`\n"
                f"Group ID: `{ROBLOX_GROUP_ID}`"
            )

        else:

            await ctx.send(
                "**ROBLOX ACCEPT FAILED**\n"
                f"Status: `{response.status_code}`\n"
                f"Response: `{response.text[:1000]}`"
            )

    except Exception as error:

        print("GACCEPT ERROR:", repr(error))

        await ctx.send(
            f"GACCEPT ERROR: `{str(error)[:1000]}`"
        )


@gaccept.error
async def gaccept_error(ctx, error):

    if isinstance(error, commands.MissingRequiredArgument):
        await ctx.send("Usage: `,gaccept RobloxUsername`")
    else:
        print("GACCEPT COMMAND ERROR:", repr(error))
        await ctx.send(
            f"Command error: `{str(error)[:1000]}`"
        )


# ============================================================
# ROBLOX GROUP CHECK
# Usage: ,groupcheck @DiscordUser
# ============================================================

@bot.command(name="groupcheck")
async def groupcheck(ctx, member: discord.Member = None):

    if not has_role(ctx.author, GROUPCHECK_PERMISSION_ROLE_ID):
        await ctx.send("You do not have permission to use this command.")
        return

    if member is None:
        await ctx.send("Usage: `,groupcheck @user`")
        return

    if not ROBLOX_API_KEY:
        await ctx.send("Roblox API key is missing.")
        return

    try:

        await ctx.send(
            f"Checking {member.mention}'s Roblox group membership..."
        )

        roblox_id, roblox_username = await get_linked_roblox_id(
            member.id
        )

        if not roblox_id:
            await ctx.send(
                f"No linked Roblox account found for {member.mention}."
            )
            return

        response = await asyncio.to_thread(
            requests.get,
            f"https://apis.roblox.com/cloud/v2/groups/"
            f"{GROUPCHECK_GROUP_ID}/memberships",
            headers={
                "x-api-key": ROBLOX_API_KEY
            },
            params={
                "filter": f"user == 'users/{roblox_id}'",
                "maxPageSize": 10
            },
            timeout=30
        )

        if response.status_code != 200:
            await ctx.send(
                f"Roblox API error: `{response.status_code}`\n"
                f"`{response.text[:1000]}`"
            )
            return

        memberships = response.json().get(
            "groupMemberships", []
        )

        is_member = any(
            (
                item.get("user", {}).get("path")
                if isinstance(item.get("user"), dict)
                else item.get("user")
            ) == f"users/{roblox_id}"
            for item in memberships
        )

        if is_member:

            await ctx.send(
                "**GROUP CHECK: MEMBER**\n"
                f"Discord: {member.mention}\n"
                f"Roblox: **{roblox_username}**\n"
                f"Roblox ID: `{roblox_id}`\n"
                f"Group ID: `{GROUPCHECK_GROUP_ID}`"
            )

        else:

            await ctx.send(
                "**GROUP CHECK: NOT A MEMBER**\n"
                f"Discord: {member.mention}\n"
                f"Roblox: **{roblox_username}**\n"
                f"Roblox ID: `{roblox_id}`\n"
                f"Group ID: `{GROUPCHECK_GROUP_ID}`"
            )

    except Exception as error:

        print("GROUPCHECK ERROR:", repr(error))

        await ctx.send(
            f"Something went wrong while checking group membership: "
            f"`{str(error)[:500]}`"
        )


@groupcheck.error
async def groupcheck_error(ctx, error):

    if isinstance(error, commands.MissingRequiredArgument):
        await ctx.send("Usage: `,groupcheck @user`")

    elif isinstance(error, commands.MemberNotFound):
        await ctx.send("I could not find that Discord member.")

    else:
        print("GROUPCHECK COMMAND ERROR:", repr(error))
        await ctx.send(
            f"Command error: `{str(error)[:500]}`"
        )


# ============================================================
# COMMANDS LIST
# ============================================================

@bot.command(name="commands")
async def commands_list(ctx):

    embed = discord.Embed(
        title="BOT COMMANDS",
        description="Here is a list of the available bot commands.",
        color=COLOUR_MAIN
    )

    embed.add_field(
        name="VERIFICATION",
        value=(
            "`,startverifyticket` - Sends the verification panel.\n"
            "`,verify @user` - Verifies a member and removes their old role.\n"
            "`,lockverify` - Disables new verification tickets.\n"
            "`,unlockverify` - Enables new verification tickets.\n"
            "`,delete` - Saves the ticket transcript and deletes the ticket."
        ),
        inline=False
    )

    embed.add_field(
        name="SPYCHECK & ACTIVITY",
        value=(
            "`,spycheck` - Checks eligible members' weekly activity.\n"
            "`,stats` - Shows your activity statistics.\n"
            "`,stats @user` - Shows another member's statistics."
        ),
        inline=False
    )

    embed.add_field(
        name="CREW MANAGEMENT",
        value=(
            "`,addcrew <group_id> <name>` - Adds a Roblox crew.\n"
            "`,removecrew <group_id>` - Removes a Roblox crew.\n"
            "`,listcrews` - Shows the blacklisted crews."
        ),
        inline=False
    )

    embed.add_field(
        name="ROBLOX",
        value=(
            "`,gaccept <roblox_username>` - Accepts a Roblox group join request.\n"
            "`,groupcheck @user` - Checks a linked Roblox account's group membership."
        ),
        inline=False
    )

    embed.add_field(
        name="OTHER",
        value="`,commands` - Shows this command list.",
        inline=False
    )

    embed.set_footer(
        text="Some commands require specific roles or channels."
    )

    await ctx.send(embed=embed)


# ============================================================
# BOT READY
# ============================================================

@bot.event
async def on_ready():

    print(f"Online as {bot.user}")

    bot.add_view(VerifyTicketView())

    for guild in bot.guilds:

        for member in guild.members:

            if member.bot:
                continue

            user_id = str(member.id)
            stats = get_stats(user_id)

            if member.voice and member.voice.channel:

                if stats["active_vc"] is None:
                    stats["active_vc"] = time.time()

            else:

                if stats["active_vc"] is not None:

                    stats["vc_sessions"].append([
                        stats["active_vc"],
                        time.time()
                    ])

                    stats["active_vc"] = None

    save_json(ACTIVITY_FILE, STATS)


# ============================================================
# START
# ============================================================

if not TOKEN:
    raise RuntimeError("DISCORD_TOKEN is missing from .env")

if not ROBLOX_API_KEY:
    print("WARNING: ROBLOX_API_KEY is missing from .env")

if not ROBLOX_GROUP_ID:
    print("WARNING: ROBLOX_GROUP_ID is missing from .env")

bot.run(TOKEN)
