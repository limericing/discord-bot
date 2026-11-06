import os
import json
import asyncio
import requests
import discord

from datetime import datetime, timezone
from dotenv import load_dotenv
from discord.ext import commands
from discord.ui import View, Button, Modal, TextInput


# =========================================================
# ENV
# =========================================================

BASE_DIR = os.path.dirname(os.path.abspath(__file__))
ENV_FILE = os.path.join(BASE_DIR, ".env")

load_dotenv(ENV_FILE, override=True)

TOKEN = os.environ.get("DISCORD_TOKEN")
ROBLOX_API_KEY = os.environ.get("ROBLOX_API_KEY")

if not TOKEN:
    raise RuntimeError(
        f"DISCORD_TOKEN was not loaded from {ENV_FILE}"
    )


# =========================================================
# CONFIG
# =========================================================

PREFIX = ","

VERIFICATION_CHANNEL_ID = 1567371316229705898
TICKET_CATEGORY_ID = 1567437889552384030

STAFF_ROLE_ID = 1567435583473582170
ADD_CREW_ROLE_ID = 1567558861475283075
VERIFIED_ROLE_ID = 1567044030359933041

USERNAME_LOG_CHANNEL_ID = 1568255388476903537
TRANSCRIPT_LOG_CHANNEL_ID = 1567418285912367164

MAIN_GROUP_ID = 774188530
MAIN_GROUP_NAME = "Ghost"

GROUP_URL = f"https://www.roblox.com/groups/{MAIN_GROUP_ID}/Ghost"

MIN_ACCOUNT_AGE_DAYS = 90

CREWS_FILE = os.path.join(BASE_DIR, "crews.json")
TICKETS_FILE = os.path.join(BASE_DIR, "tickets.json")


# =========================================================
# BLACKLISTED CREWS
# =========================================================

DEFAULT_CREWS = {
    "103710356": "Deathstar",
    "714622754": "Sworn",
    "977483761": "Snowfall",
    "809253103": "YWL",
    "34641725": "SpectralW",
    "76112202": "Grave",
    "35161823": "Tappers",
}


def load_crews():
    if not os.path.exists(CREWS_FILE):
        save_crews(DEFAULT_CREWS)
        return DEFAULT_CREWS.copy()

    try:
        with open(CREWS_FILE, "r", encoding="utf-8") as file:
            data = json.load(file)

        return {
            str(group_id): str(name)
            for group_id, name in data.items()
        }

    except Exception:
        return DEFAULT_CREWS.copy()


def save_crews(crews):
    with open(CREWS_FILE, "w", encoding="utf-8") as file:
        json.dump(crews, file, indent=4)


CREWS = load_crews()


# =========================================================
# TICKETS
# =========================================================

def load_tickets():
    if not os.path.exists(TICKETS_FILE):
        return {}

    try:
        with open(TICKETS_FILE, "r", encoding="utf-8") as file:
            return json.load(file)

    except Exception:
        return {}


def save_tickets(tickets):
    with open(TICKETS_FILE, "w", encoding="utf-8") as file:
        json.dump(tickets, file, indent=4)


TICKETS = load_tickets()


# =========================================================
# DISCORD
# =========================================================

intents = discord.Intents.default()

intents.guilds = True
intents.members = True
intents.messages = True
intents.message_content = True

bot = commands.Bot(
    command_prefix=PREFIX,
    intents=intents,
    help_command=None
)


# =========================================================
# ROBLOX REQUEST HELPER
# =========================================================

def roblox_request(method, url, **kwargs):
    try:
        return requests.request(
            method,
            url,
            timeout=15,
            **kwargs
        )
    except requests.RequestException:
        return None


# =========================================================
# ROBLOX USER
# =========================================================

def get_roblox_user(username):
    response = roblox_request(
        "POST",
        "https://users.roblox.com/v1/usernames/users",
        json={
            "usernames": [username],
            "excludeBannedUsers": False
        }
    )

    if not response or response.status_code != 200:
        return None

    data = response.json()

    if not data.get("data"):
        return None

    return data["data"][0]


def get_user_details(user_id):
    response = roblox_request(
        "GET",
        f"https://users.roblox.com/v1/users/{user_id}"
    )

    if not response or response.status_code != 200:
        return None

    return response.json()


def get_avatar_url(user_id):
    response = roblox_request(
        "GET",
        "https://thumbnails.roblox.com/v1/users/avatar",
        params={
            "userIds": user_id,
            "size": "420x420",
            "format": "Png",
            "isCircular": "false"
        }
    )

    if not response or response.status_code != 200:
        return None

    data = response.json()

    if not data.get("data"):
        return None

    return data["data"][0].get("imageUrl")


def get_friend_count(user_id):
    response = roblox_request(
        "GET",
        f"https://friends.roblox.com/v1/users/{user_id}/friends/count"
    )

    if not response or response.status_code != 200:
        return None

    return response.json().get("count")


def get_user_groups(user_id):
    response = roblox_request(
        "GET",
        f"https://groups.roblox.com/v2/users/{user_id}/groups/roles"
    )

    if not response or response.status_code != 200:
        return []

    return response.json().get("data", [])


def get_blacklisted_crews(user_id):
    groups = get_user_groups(user_id)

    found = []

    for group in groups:
        group_info = group.get("group", {})
        group_id = str(group_info.get("id"))

        if group_id in CREWS:
            found.append(CREWS[group_id])

    return found


def is_in_main_group(user_id):
    groups = get_user_groups(user_id)

    for group in groups:
        group_info = group.get("group", {})

        if str(group_info.get("id")) == str(MAIN_GROUP_ID):
            return True

    return False


# =========================================================
# DISCORD ACCOUNT AGE
# =========================================================

def get_discord_account_age(member):
    now = datetime.now(timezone.utc)

    return (now - member.created_at).days


# =========================================================
# STAFF PERMISSIONS
# =========================================================

def has_staff_permission(ctx_or_interaction):
    if isinstance(ctx_or_interaction, commands.Context):
        guild = ctx_or_interaction.guild
        member = ctx_or_interaction.author
    else:
        guild = ctx_or_interaction.guild
        member = ctx_or_interaction.user

    if not guild or not member:
        return False

    if member.guild_permissions.administrator:
        return True

    return any(
        role.id == STAFF_ROLE_ID
        for role in member.roles
    )


def has_add_crew_permission(ctx):
    if not ctx.guild:
        return False

    member = ctx.author

    if member.guild_permissions.administrator:
        return True

    return any(
        role.id == ADD_CREW_ROLE_ID
        for role in member.roles
    )


# =========================================================
# VERIFICATION EMBED
# =========================================================

def verification_embed():
    embed = discord.Embed(
        title="Ghost Staff Verification",
        description=(
            "Welcome to the **Ghost Staff Verification** system.\n\n"
            "To begin your application, click the "
            "**Verify / Create Ticket** button below.\n\n"
            "You will be asked for your Roblox username and "
            "a private verification ticket will be created."
        )
    )

    embed.add_field(
        name="What happens next?",
        value=(
            "Your Roblox account will be checked for account age, "
            "friends, blacklisted crews, groups and other "
            "verification information."
        ),
        inline=False
    )

    embed.add_field(
        name="Ghost",
        value=(
            "If you are accepted, staff will handle your "
            "Ghost group acceptance."
        ),
        inline=False
    )

    return embed


# =========================================================
# TICKET EMBED
# =========================================================

def build_member_info_embed(
    member,
    username,
    user_data,
    details,
    blacklisted
):
    user_id = user_data["id"]

    avatar_url = get_avatar_url(user_id)
    friend_count = get_friend_count(user_id)

    created_string = details.get("created")

    try:
        created = datetime.fromisoformat(
            created_string.replace("Z", "+00:00")
        )

        account_age = (
            datetime.now(timezone.utc) - created
        ).days

    except Exception:
        account_age = 0

    discord_age = get_discord_account_age(member)

    # Account age
    if account_age >= MIN_ACCOUNT_AGE_DAYS:
        account_age_text = (
            f"Passed — {account_age} days"
        )
    else:
        account_age_text = (
            f"Failed — {account_age} days"
        )

    # Friends
    if friend_count is None:
        friends_text = "Unable to check"
    else:
        friends_text = str(friend_count)

    # Blacklist
    if blacklisted:
        blacklist_text = ", ".join(blacklisted)
    else:
        blacklist_text = "None"

    # Discord age
    if discord_age >= MIN_ACCOUNT_AGE_DAYS:
        discord_age_text = (
            f"Passed — {discord_age} days"
        )
    else:
        discord_age_text = (
            f"Failed — {discord_age} days"
        )

    # Ghost group
    if is_in_main_group(user_id):
        ghost_group_text = "Already in Ghost"
    else:
        ghost_group_text = "Not in Ghost"

    embed = discord.Embed(
        title="Ghost Staff Verification",
        description=(
            f"Verification information for "
            f"**{username}**"
        )
    )

    # =====================================================
    # MEMBER INFORMATION
    # =====================================================

    embed.add_field(
        name="Member Information",
        value=(
            f"**Discord:** {member.mention}\n"
            f"**Discord ID:** `{member.id}`\n"
            f"**Roblox:** [{username}]"
            f"(https://www.roblox.com/users/{user_id}/profile)\n"
            f"**Roblox ID:** `{user_id}`"
        ),
        inline=False
    )

    # =====================================================
    # VERIFICATION CHECKS
    # =====================================================

    embed.add_field(
        name="Account Age",
        value=account_age_text,
        inline=True
    )

    embed.add_field(
        name="Friends",
        value=friends_text,
        inline=True
    )

    embed.add_field(
        name="Blacklisted Crews",
        value=blacklist_text,
        inline=False
    )

    embed.add_field(
        name="Discord Account Age",
        value=discord_age_text,
        inline=True
    )

    embed.add_field(
        name="Ghost Group",
        value=ghost_group_text,
        inline=True
    )

    if avatar_url:
        embed.set_thumbnail(
            url=avatar_url
        )

    embed.set_footer(
        text=f"Roblox ID: {user_id}"
    )

    return embed


# =========================================================
# VERIFICATION MODAL
# =========================================================

class VerificationModal(
    Modal,
    title="Ghost Verification"
):

    username = TextInput(
        label="Roblox Username",
        placeholder="Enter your Roblox username",
        required=True,
        max_length=20
    )

    async def on_submit(
        self,
        interaction: discord.Interaction
    ):
        await interaction.response.defer(
            ephemeral=True
        )

        username = self.username.value.strip()

        user_data = await asyncio.to_thread(
            get_roblox_user,
            username
        )

        if not user_data:
            await interaction.followup.send(
                "That Roblox username could not be found.",
                ephemeral=True
            )
            return

        user_id = user_data["id"]

        details = await asyncio.to_thread(
            get_user_details,
            user_id
        )

        if not details:
            await interaction.followup.send(
                "Could not retrieve the Roblox account.",
                ephemeral=True
            )
            return

        blacklisted = await asyncio.to_thread(
            get_blacklisted_crews,
            user_id
        )

        guild = interaction.guild

        category = guild.get_channel(
            TICKET_CATEGORY_ID
        )

        if not category:
            await interaction.followup.send(
                "The ticket category could not be found.",
                ephemeral=True
            )
            return

        # Prevent duplicate tickets.
        for channel_id, ticket in TICKETS.items():

            if str(ticket.get("discord_id")) != str(
                interaction.user.id
            ):
                continue

            existing = guild.get_channel(
                int(channel_id)
            )

            if existing:
                await interaction.followup.send(
                    f"You already have an open ticket: "
                    f"{existing.mention}",
                    ephemeral=True
                )
                return

        overwrites = {
            guild.default_role: discord.PermissionOverwrite(
                view_channel=False
            ),

            interaction.user: discord.PermissionOverwrite(
                view_channel=True,
                send_messages=True,
                read_message_history=True,
                attach_files=True
            )
        }

        staff_role = guild.get_role(
            STAFF_ROLE_ID
        )

        if staff_role:
            overwrites[staff_role] = discord.PermissionOverwrite(
                view_channel=True,
                send_messages=True,
                read_message_history=True,
                manage_messages=True
            )

        safe_username = "".join(
            character
            for character in username.lower()
            if character.isalnum() or character in "-_"
        )

        channel_name = f"verify-{safe_username}"

        ticket_channel = await guild.create_text_channel(
            channel_name,
            category=category,
            overwrites=overwrites,
            reason="Ghost verification ticket"
        )

        created = details.get("created")

        if not created:
            created = datetime.now(
                timezone.utc
            ).isoformat()

        ticket_data = {
            "discord_id": interaction.user.id,
            "discord_name": str(interaction.user),
            "roblox_username": username,
            "roblox_id": user_id,
            "created": created,
            "blacklisted": blacklisted,
            "claimed_by": None
        }

        TICKETS[str(ticket_channel.id)] = ticket_data

        save_tickets(TICKETS)

        # =================================================
        # USERNAME LOG
        # =================================================

        username_log = guild.get_channel(
            USERNAME_LOG_CHANNEL_ID
        )

        if username_log:
            await username_log.send(
                f"Roblox username submitted: **{username}**\n"
                f"Discord user: {interaction.user.mention}\n"
                f"Roblox ID: `{user_id}`"
            )

        # =================================================
        # TICKET EMBED
        # =================================================

        ticket_embed = await asyncio.to_thread(
            build_member_info_embed,
            interaction.user,
            username,
            user_data,
            details,
            blacklisted
        )

        # =================================================
        # TICKET MESSAGE
        # =================================================

        await ticket_channel.send(
            content=(
                f"<@&{STAFF_ROLE_ID}>\n\n"
                f"Thanks for applying to **{MAIN_GROUP_NAME}**!\n"
                f"Please wait for a staff member to review "
                f"your application."
            ),
            embed=ticket_embed,
            view=TicketView()
        )

        await interaction.followup.send(
            f"Your verification ticket has been created: "
            f"{ticket_channel.mention}",
            ephemeral=True
        )


# =========================================================
# VERIFICATION PANEL
# =========================================================

class VerifyPanelView(View):

    def __init__(self):
        super().__init__(
            timeout=None
        )

        self.add_item(
            Button(
                label="Join Ghost",
                style=discord.ButtonStyle.link,
                url=GROUP_URL,
                row=0
            )
        )

    @discord.ui.button(
        label="Verify / Create Ticket",
        style=discord.ButtonStyle.primary,
        custom_id="ghost_verify",
        row=0
    )
    async def verify_button(
        self,
        interaction: discord.Interaction,
        button: Button
    ):
        await interaction.response.send_modal(
            VerificationModal()
        )


# =========================================================
# TICKET PANEL
# =========================================================

class TicketView(View):

    def __init__(self):
        super().__init__(
            timeout=None
        )

        self.add_item(
            Button(
                label="Join Ghost",
                style=discord.ButtonStyle.link,
                url=GROUP_URL,
                row=1
            )
        )

    # -----------------------------------------------------
    # CLAIM
    # -----------------------------------------------------

    @discord.ui.button(
        label="Claim",
        style=discord.ButtonStyle.secondary,
        custom_id="ghost_ticket_claim",
        row=0
    )
    async def claim(
        self,
        interaction: discord.Interaction,
        button: Button
    ):
        if not has_staff_permission(interaction):
            await interaction.response.send_message(
                "You do not have permission to claim tickets.",
                ephemeral=True
            )
            return

        channel_id = str(
            interaction.channel.id
        )

        if channel_id not in TICKETS:
            await interaction.response.send_message(
                "This is not a tracked ticket.",
                ephemeral=True
            )
            return

        TICKETS[channel_id]["claimed_by"] = (
            interaction.user.id
        )

        save_tickets(TICKETS)

        await interaction.response.send_message(
            f"This ticket has been claimed by "
            f"{interaction.user.mention}."
        )

    # -----------------------------------------------------
    # RE-SCAN
    # -----------------------------------------------------

    @discord.ui.button(
        label="Re-scan",
        style=discord.ButtonStyle.secondary,
        custom_id="ghost_ticket_rescan",
        row=0
    )
    async def rescan(
        self,
        interaction: discord.Interaction,
        button: Button
    ):
        if not has_staff_permission(interaction):
            await interaction.response.send_message(
                "You do not have permission to re-scan tickets.",
                ephemeral=True
            )
            return

        ticket = TICKETS.get(
            str(interaction.channel.id)
        )

        if not ticket:
            await interaction.response.send_message(
                "This is not a tracked ticket.",
                ephemeral=True
            )
            return

        await interaction.response.defer()

        user_id = ticket["roblox_id"]
        username = ticket["roblox_username"]

        user_data = await asyncio.to_thread(
            get_roblox_user,
            username
        )

        details = await asyncio.to_thread(
            get_user_details,
            user_id
        )

        blacklisted = await asyncio.to_thread(
            get_blacklisted_crews,
            user_id
        )

        if not user_data or not details:
            await interaction.followup.send(
                "Could not re-scan the Roblox account."
            )
            return

        ticket["blacklisted"] = blacklisted

        save_tickets(TICKETS)

        member = interaction.guild.get_member(
            ticket["discord_id"]
        )

        if not member:
            await interaction.followup.send(
                "Could not find the Discord member."
            )
            return

        embed = await asyncio.to_thread(
            build_member_info_embed,
            member,
            username,
            user_data,
            details,
            blacklisted
        )

        await interaction.followup.send(
            "Verification re-scanned.",
            embed=embed
        )

    # -----------------------------------------------------
    # ALL GROUPS
    # -----------------------------------------------------

    @discord.ui.button(
        label="All Groups",
        style=discord.ButtonStyle.secondary,
        custom_id="ghost_ticket_groups",
        row=0
    )
    async def all_groups(
        self,
        interaction: discord.Interaction,
        button: Button
    ):
        if not has_staff_permission(interaction):
            await interaction.response.send_message(
                "You do not have permission to view groups.",
                ephemeral=True
            )
            return

        ticket = TICKETS.get(
            str(interaction.channel.id)
        )

        if not ticket:
            await interaction.response.send_message(
                "This is not a tracked ticket.",
                ephemeral=True
            )
            return

        await interaction.response.defer(
            ephemeral=True
        )

        groups = await asyncio.to_thread(
            get_user_groups,
            ticket["roblox_id"]
        )

        if not groups:
            await interaction.followup.send(
                "No groups detected.",
                ephemeral=True
            )
            return

        lines = []

        for group in groups:
            group_info = group.get(
                "group",
                {}
            )

            role_info = group.get(
                "role",
                {}
            )

            group_name = group_info.get(
                "name",
                "Unknown"
            )

            group_id = group_info.get(
                "id",
                "Unknown"
            )

            role_name = role_info.get(
                "name",
                "Unknown"
            )

            lines.append(
                f"**{group_name}** (`{group_id}`) - "
                f"{role_name}"
            )

        output = "\n".join(lines)

        if len(output) > 1900:
            output = output[:1900] + "\n..."

        await interaction.followup.send(
            output,
            ephemeral=True
        )

    # -----------------------------------------------------
    # CLOSE
    # -----------------------------------------------------

    @discord.ui.button(
        label="Close",
        style=discord.ButtonStyle.danger,
        custom_id="ghost_ticket_close",
        row=1
    )
    async def close(
        self,
        interaction: discord.Interaction,
        button: Button
    ):
        if not has_staff_permission(interaction):
            await interaction.response.send_message(
                "You do not have permission to close tickets.",
                ephemeral=True
            )
            return

        await interaction.response.send_message(
            "Creating transcript and closing ticket..."
        )

        await asyncio.sleep(1)

        await create_transcript(
            interaction.channel
        )

        channel_id = str(
            interaction.channel.id
        )

        if channel_id in TICKETS:
            del TICKETS[channel_id]
            save_tickets(TICKETS)

        await interaction.channel.delete(
            reason="Ghost verification ticket closed"
        )


# =========================================================
# TRANSCRIPTS
# =========================================================

async def create_transcript(channel):

    messages = []

    async for message in channel.history(
        limit=None,
        oldest_first=True
    ):
        messages.append({
            "id": message.id,
            "author_id": message.author.id,
            "author": str(message.author),
            "content": message.content,
            "created_at": message.created_at.isoformat(),
            "attachments": [
                attachment.url
                for attachment in message.attachments
            ]
        })

    transcript = {
        "channel_id": channel.id,
        "channel_name": channel.name,
        "created_at": datetime.now(
            timezone.utc
        ).isoformat(),
        "messages": messages
    }

    transcript_folder = os.path.join(
        BASE_DIR,
        "transcripts"
    )

    os.makedirs(
        transcript_folder,
        exist_ok=True
    )

    file_path = os.path.join(
        transcript_folder,
        f"{channel.id}.json"
    )

    with open(
        file_path,
        "w",
        encoding="utf-8"
    ) as file:
        json.dump(
            transcript,
            file,
            indent=4,
            ensure_ascii=False
        )

    log_channel = channel.guild.get_channel(
        TRANSCRIPT_LOG_CHANNEL_ID
    )

    if log_channel:
        await log_channel.send(
            content=(
                f"Transcript created for "
                f"`{channel.name}`."
            ),
            file=discord.File(
                file_path,
                filename=f"{channel.id}.json"
            )
        )


# =========================================================
# VERIFY COMMAND
# =========================================================

@bot.command()
async def verify(ctx):

    if ctx.channel.id != VERIFICATION_CHANNEL_ID:
        await ctx.send(
            "This command can only be used in the verification channel."
        )
        return

    await ctx.send(
        embed=verification_embed(),
        view=VerifyPanelView()
    )


# =========================================================
# SCAN
# =========================================================

@bot.command()
async def scan(
    ctx,
    username: str
):

    user_data = await asyncio.to_thread(
        get_roblox_user,
        username
    )

    if not user_data:
        await ctx.send(
            "Roblox user not found."
        )
        return

    blacklisted = await asyncio.to_thread(
        get_blacklisted_crews,
        user_data["id"]
    )

    if not blacklisted:
        await ctx.send(
            "No crew detected."
        )
        return

    await ctx.send(
        "Crew detected: "
        + ", ".join(blacklisted)
    )


# =========================================================
# ADD CREW
# =========================================================

@bot.command()
async def addcrew(
    ctx,
    group_id: str,
    *,
    name: str
):

    if not has_add_crew_permission(ctx):
        await ctx.send(
            "You do not have permission to add crews."
        )
        return

    if not group_id.isdigit():
        await ctx.send(
            "The group ID must be a number."
        )
        return

    CREWS[group_id] = name

    save_crews(CREWS)

    await ctx.send(
        f"Added crew **{name}** (`{group_id}`)."
    )


# =========================================================
# REMOVE CREW
# =========================================================

@bot.command()
async def removecrew(
    ctx,
    group_id: str
):

    if not has_add_crew_permission(ctx):
        await ctx.send(
            "You do not have permission to remove crews."
        )
        return

    if group_id not in CREWS:
        await ctx.send(
            "That crew is not on the blacklist."
        )
        return

    name = CREWS.pop(group_id)

    save_crews(CREWS)

    await ctx.send(
        f"Removed crew **{name}** (`{group_id}`)."
    )


# =========================================================
# LIST CREWS
# =========================================================

@bot.command()
async def listcrews(ctx):

    if not CREWS:
        await ctx.send(
            "No crews are currently configured."
        )
        return

    lines = []

    for group_id, name in CREWS.items():
        lines.append(
            f"**{name}** — `{group_id}`"
        )

    await ctx.send(
        "\n".join(lines)
    )


# =========================================================
# GACCEPT
# =========================================================

def find_join_request(user_id):
    if not ROBLOX_API_KEY:
        return None

    url = (
        f"https://apis.roblox.com/cloud/v2/groups/"
        f"{MAIN_GROUP_ID}/join-requests"
    )

    headers = {
        "x-api-key": ROBLOX_API_KEY
    }

    page_token = None

    for _ in range(10):

        params = {
            "maxPageSize": 100
        }

        if page_token:
            params["pageToken"] = page_token

        response = roblox_request(
            "GET",
            url,
            headers=headers,
            params=params
        )

        if not response or response.status_code != 200:
            return None

        data = response.json()

        for request in data.get(
            "groupJoinRequests",
            []
        ):
            user = request.get(
                "user",
                {}
            )

            request_user_id = (
                user.get("userId")
                or user.get("id")
            )

            if str(request_user_id) == str(user_id):
                return request

        page_token = data.get(
            "nextPageToken"
        )

        if not page_token:
            break

    return None


def accept_join_request(request_id):
    if not ROBLOX_API_KEY:
        return False

    url = (
        f"https://apis.roblox.com/cloud/v2/groups/"
        f"{MAIN_GROUP_ID}/join-requests/"
        f"{request_id}:accept"
    )

    response = roblox_request(
        "POST",
        url,
        headers={
            "x-api-key": ROBLOX_API_KEY
        }
    )

    if not response:
        return False

    return response.status_code in (
        200,
        201,
        204
    )


@bot.command()
async def gaccept(
    ctx,
    username: str
):

    if not has_staff_permission(ctx):
        await ctx.send(
            "You do not have permission to use this command."
        )
        return

    user_data = await asyncio.to_thread(
        get_roblox_user,
        username
    )

    if not user_data:
        await ctx.send(
            "Could not accept into the Roblox group."
        )
        return

    user_id = user_data["id"]

    already_member = await asyncio.to_thread(
        is_in_main_group,
        user_id
    )

    if already_member:
        await ctx.send(
            "Person is already in the Roblox group."
        )
        return

    if not ROBLOX_API_KEY:
        await ctx.send(
            "Could not accept into the Roblox group."
        )
        return

    join_request = await asyncio.to_thread(
        find_join_request,
        user_id
    )

    if not join_request:
        await ctx.send(
            "Person did not request the Roblox group."
        )
        return

    request_id = (
        join_request.get(
            "path",
            ""
        )
        .rstrip("/")
        .split("/")[-1]
    )

    if not request_id:
        request_id = join_request.get(
            "id"
        )

    if not request_id:
        await ctx.send(
            "Could not accept into the Roblox group."
        )
        return

    success = await asyncio.to_thread(
        accept_join_request,
        request_id
    )

    if not success:
        await ctx.send(
            "Could not accept into the Roblox group."
        )
        return

    await ctx.send(
        "Person is accepted into the Roblox group."
    )


# =========================================================
# TRANSCRIPT COMMAND
# =========================================================

@bot.command(
    name="transcript"
)
async def transcript_command(ctx):

    if not has_staff_permission(ctx):
        await ctx.send(
            "You do not have permission to use this command."
        )
        return

    if str(ctx.channel.id) not in TICKETS:
        await ctx.send(
            "This is not a tracked ticket."
        )
        return

    await create_transcript(
        ctx.channel
    )

    await ctx.send(
        "Transcript saved and logged."
    )


# =========================================================
# DELETE COMMAND
# =========================================================

@bot.command(
    name="delete"
)
async def delete_command(ctx):

    if not has_staff_permission(ctx):
        await ctx.send(
            "You do not have permission to use this command."
        )
        return

    channel_id = str(
        ctx.channel.id
    )

    if channel_id not in TICKETS:
        await ctx.send(
            "This is not a tracked ticket."
        )
        return

    await create_transcript(
        ctx.channel
    )

    del TICKETS[channel_id]

    save_tickets(TICKETS)

    await ctx.channel.delete(
        reason="Ghost ticket deleted"
    )


# =========================================================
# READY
# =========================================================

@bot.event
async def on_ready():

    bot.add_view(
        VerifyPanelView()
    )

    bot.add_view(
        TicketView()
    )

    print("Ghost configuration loaded.")
    print(f"Logged in as {bot.user}")
    print(f"Prefix: {PREFIX}")
    print(
        f"Main group: "
        f"{MAIN_GROUP_NAME} ({MAIN_GROUP_ID})"
    )


# =========================================================
# COMMAND ERRORS
# =========================================================

@bot.event
async def on_command_error(
    ctx,
    error
):

    if isinstance(
        error,
        commands.CommandNotFound
    ):
        return

    if isinstance(
        error,
        commands.MissingRequiredArgument
    ):
        await ctx.send(
            "Missing required argument."
        )
        return

    if isinstance(
        error,
        commands.BadArgument
    ):
        await ctx.send(
            "Invalid argument."
        )
        return

    print(
        f"Command error: {error}"
    )


# =========================================================
# START
# =========================================================

bot.run(TOKEN)
