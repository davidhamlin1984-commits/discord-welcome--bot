import os
import asyncio
import re
import discord
from discord.ext import commands

# -------- CONFIG --------
# Put your bot token in an environment variable named DISCORD_BOT_TOKEN
TOKEN = os.getenv("DISCORD_BOT_TOKEN")

# Channel ID where users are allowed to use the command.
# Set to 0 to allow it in any channel.
ALLOWED_CHANNEL_ID = 0

# Command users type to begin registration
COMMAND_NAME = "register"

# Optional: remove any existing roles that look like state/alliance/rank roles
# before assigning the newly selected ones.
REMOVE_OLD_CATEGORY_ROLES = True

# Prompt timeout in seconds
PROMPT_TIMEOUT = 60

# -------- BOT SETUP --------
intents = discord.Intents.default()
intents.message_content = True
intents.guilds = True
intents.members = True

bot = commands.Bot(command_prefix="!", intents=intents)


def normalize_value(value: str) -> str:
    return value.strip().lower()


def find_role_case_insensitive(guild: discord.Guild, user_input: str) -> discord.Role | None:
    target = normalize_value(user_input)
    for role in guild.roles:
        if normalize_value(role.name) == target:
            return role
    return None


def is_rank_role_name(role_name: str) -> bool:
    return re.fullmatch(r"r\d+", role_name.strip().lower()) is not None


def looks_like_state_role_name(role_name: str) -> bool:
    return role_name.strip().isdigit()


def collect_known_alliance_roles(guild: discord.Guild) -> list[discord.Role]:
    return [
        role for role in guild.roles
        if not role.is_default()
        and not looks_like_state_role_name(role.name)
        and not is_rank_role_name(role.name)
    ]


async def ask_question(ctx: commands.Context, question: str) -> str | None:
    await ctx.reply(question)

    def check(message: discord.Message) -> bool:
        return message.author == ctx.author and message.channel == ctx.channel

    try:
        msg = await bot.wait_for("message", check=check, timeout=PROMPT_TIMEOUT)
        return msg.content.strip()
    except asyncio.TimeoutError:
        await ctx.reply("Registration timed out. Please run `!register` again.")
        return None


async def ask_for_existing_role(ctx: commands.Context, label: str, helper_text: str = "") -> discord.Role | None:
    while True:
        prompt = f"Enter your **{label}** exactly as the role exists in this server."
        if helper_text:
            prompt += f"
{helper_text}"

        answer = await ask_question(ctx, prompt)
        if answer is None:
            return None

        role = find_role_case_insensitive(ctx.guild, answer)
        if role is not None:
            return role

        await ctx.reply(f"I couldn't find a server role named `{answer}`. Try again.")


async def ask_for_nickname(ctx: commands.Context) -> str | None:
    while True:
        answer = await ask_question(ctx, "Enter your **player name**.")
        if answer is None:
            return None

        nickname = answer.strip()
        if not nickname:
            await ctx.reply("Player name cannot be empty.")
            continue

        if len(nickname) > 32:
            await ctx.reply("Player name must be 32 characters or fewer.")
            continue

        return nickname


@bot.event
async def on_ready():
    print(f"Logged in as {bot.user} (ID: {bot.user.id})")
    print("Bot is ready.")


@bot.command(name=COMMAND_NAME)
@commands.guild_only()
async def register(ctx: commands.Context):
    if ALLOWED_CHANNEL_ID and ctx.channel.id != ALLOWED_CHANNEL_ID:
        await ctx.reply("You can only use this command in the registration channel.")
        return

    me = ctx.guild.me
    if me is None:
        await ctx.reply("I couldn't access my server member profile.")
        return

    if not me.guild_permissions.manage_roles:
        await ctx.reply("I need the **Manage Roles** permission.")
        return

    if not me.guild_permissions.manage_nicknames:
        await ctx.reply("I need the **Manage Nicknames** permission.")
        return

    alliance_examples = collect_known_alliance_roles(ctx.guild)
    alliance_hint = ""
    if alliance_examples:
        sample_names = ", ".join(f"`{role.name}`" for role in alliance_examples[:10])
        alliance_hint = f"Examples I found: {sample_names}"

    await ctx.reply(
        "Let's get you set up. I'll ask for your state role, alliance role, rank role, and player name."
    )

    state_role = await ask_for_existing_role(
        ctx,
        "state role",
        "Example: `868`"
    )
    if state_role is None:
        return

    # If state is NOT 868, assign 'friend of 868' instead
    if state_role.name.strip() != "868":
        friend_role = discord.utils.get(ctx.guild.roles, name="friend of 868")
        if friend_role is None:
            await ctx.reply("I couldn't find the role `friend of 868` in this server.")
            return
        state_role = friend_role

    alliance_role = await ask_for_existing_role(
        ctx,
        "alliance role",
        alliance_hint or "Example: `zrh`"
    )
    if alliance_role is None:
        return

    rank_role = await ask_for_existing_role(
        ctx,
        "rank role",
        "Example: `r4`"
    )
    if rank_role is None:
        return

    nickname = await ask_for_nickname(ctx)
    if nickname is None:
        return

    target_roles = [state_role, alliance_role, rank_role]

    for role in target_roles:
        if role >= me.top_role:
            await ctx.reply(
                f"My role must be above `{role.name}` in Server Settings -> Roles."
            )
            return

    member = ctx.author

    try:
        if REMOVE_OLD_CATEGORY_ROLES:
            roles_to_remove = []
            for role in member.roles:
                if role in target_roles:
                    continue
                if looks_like_state_role_name(role.name) or is_rank_role_name(role.name):
                    roles_to_remove.append(role)

            if alliance_role not in member.roles:
                for role in member.roles:
                    if role in target_roles or role in roles_to_remove or role.is_default():
                        continue
                    if not looks_like_state_role_name(role.name) and not is_rank_role_name(role.name):
                        if role < me.top_role:
                            roles_to_remove.append(role)

            if roles_to_remove:
                await member.remove_roles(*roles_to_remove, reason="Refreshing registration roles")

        roles_to_add = [r for r in target_roles if r not in member.roles]
        if roles_to_add:
            await member.add_roles(*roles_to_add, reason="User registration")

        if member != ctx.guild.owner and member.top_role >= me.top_role:
            added_names = ", ".join(r.name for r in roles_to_add) if roles_to_add else "no new roles"
            await ctx.reply(
                f"I assigned your roles ({added_names}), but I can't change your nickname because my role is not high enough."
            )
            return

        await member.edit(nick=nickname, reason="User registration nickname update")

        role_names = ", ".join(r.name for r in target_roles)
        await ctx.reply(
            f"Done. Nickname set to **{nickname}** and roles assigned: **{role_names}**"
        )

    except discord.Forbidden:
        await ctx.reply(
            "I don't have enough permissions. Make sure my bot role is above the target roles and I have Manage Roles and Manage Nicknames."
        )
    except discord.HTTPException as e:
        await ctx.reply(f"Discord returned an error: `{e}`")


if __name__ == "__main__":
    if not TOKEN:
        raise RuntimeError("Set the DISCORD_BOT_TOKEN environment variable before starting the bot.")
    bot.run(TOKEN)

