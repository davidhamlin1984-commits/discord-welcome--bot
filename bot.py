import os
import re
import discord
from discord.ext import commands

TOKEN = os.getenv("DISCORD_BOT_TOKEN")
ALLOWED_CHANNEL_ID = 0
FRIEND_ROLE_NAME = "friend of 868"
SETUP_COMMAND_NAME = "setup_arrival"

intents = discord.Intents.default()
intents.guilds = True
intents.members = True
intents.message_content = True

bot = commands.Bot(command_prefix="!", intents=intents)


def normalize_value(value: str) -> str:
    return value.strip().lower()


def find_role_case_insensitive(guild: discord.Guild, user_input: str) -> discord.Role | None:
    target = normalize_value(user_input)
    for role in guild.roles:
        if role.is_default() or role.managed:
            continue
        if normalize_value(role.name) == target:
            return role
    return None


def is_rank_role_name(role_name: str) -> bool:
    return re.fullmatch(r"r[0-9]+", role_name.strip().lower()) is not None


def looks_like_state_role_name(role_name: str) -> bool:
    return role_name.strip().isdigit()


def looks_like_alliance_role_name(role_name: str) -> bool:
    stripped = role_name.strip()
    if not stripped:
        return False
    if looks_like_state_role_name(stripped):
        return False
    if is_rank_role_name(stripped):
        return False
    return True


def collect_example_alliance_roles(guild: discord.Guild) -> list[str]:
    names = []
    for role in guild.roles:
        if role.is_default() or role.managed:
            continue
        if normalize_value(role.name) in {normalize_value(FRIEND_ROLE_NAME), "registration bot", "carl-bot"}:
            continue
        if looks_like_alliance_role_name(role.name):
            names.append(role.name)
    return names[:8]


class RegistrationModal(discord.ui.Modal, title="Server Registration"):
    state = discord.ui.TextInput(
        label="State role",
        placeholder="Example: 868",
        required=True,
        max_length=32,
    )
    alliance = discord.ui.TextInput(
        label="Alliance role",
        placeholder="Example: zrh",
        required=True,
        max_length=32,
    )
    rank = discord.ui.TextInput(
        label="Rank role",
        placeholder="Example: r4",
        required=True,
        max_length=32,
    )
    player_name = discord.ui.TextInput(
        label="Player name",
        placeholder="Example: Seph",
        required=True,
        max_length=32,
    )

    async def on_submit(self, interaction: discord.Interaction):
        guild = interaction.guild
        if guild is None:
            await interaction.response.send_message(
                "This can only be used inside a server.",
                ephemeral=True,
            )
            return

        me = guild.me
        if me is None:
            await interaction.response.send_message(
                "I couldn't access my server member profile.",
                ephemeral=True,
            )
            return

        if not me.guild_permissions.manage_roles:
            await interaction.response.send_message(
                "I need the Manage Roles permission.",
                ephemeral=True,
            )
            return

        if not me.guild_permissions.manage_nicknames:
            await interaction.response.send_message(
                "I need the Manage Nicknames permission.",
                ephemeral=True,
            )
            return

        state_input = str(self.state).strip()
        alliance_input = str(self.alliance).strip()
        rank_input = str(self.rank).strip()
        nickname = str(self.player_name).strip()

        state_role = find_role_case_insensitive(guild, state_input)
        if state_role is None:
            await interaction.response.send_message(
                f"I couldn't find a server role named `{state_input}` for state.",
                ephemeral=True,
            )
            return

        if state_role.name.strip() != "868":
            friend_role = discord.utils.get(guild.roles, name=FRIEND_ROLE_NAME)
            if friend_role is None:
                await interaction.response.send_message(
                    f"I couldn't find the role `{FRIEND_ROLE_NAME}` in this server.",
                    ephemeral=True,
                )
                return
            state_role = friend_role

        alliance_role = find_role_case_insensitive(guild, alliance_input)
        if alliance_role is None:
            examples = collect_example_alliance_roles(guild)
            extra = ""
            if examples:
                extra = " Example alliance roles: " + ", ".join(f"`{name}`" for name in examples)
            await interaction.response.send_message(
                f"I couldn't find a server role named `{alliance_input}` for alliance.{extra}",
                ephemeral=True,
            )
            return

        rank_role = find_role_case_insensitive(guild, rank_input)
        if rank_role is None:
            await interaction.response.send_message(
                f"I couldn't find a server role named `{rank_input}` for rank.",
                ephemeral=True,
            )
            return

        target_roles = [state_role, alliance_role, rank_role]
        for role in target_roles:
            if role >= me.top_role:
                await interaction.response.send_message(
                    f"My role must be above `{role.name}` in Server Settings and Roles.",
                    ephemeral=True,
                )
                return

        member = interaction.user
        if not isinstance(member, discord.Member):
            await interaction.response.send_message(
                "I couldn't resolve your server member profile.",
                ephemeral=True,
            )
            return

        roles_to_remove = []
        for role in member.roles:
            if role.is_default() or role in target_roles:
                continue
            if (
                looks_like_state_role_name(role.name)
                or is_rank_role_name(role.name)
                or looks_like_alliance_role_name(role.name)
            ):
                if role < me.top_role:
                    roles_to_remove.append(role)

        roles_to_add = [role for role in target_roles if role not in member.roles]

        try:
            if roles_to_remove:
                await member.remove_roles(*roles_to_remove, reason="Refreshing registration roles")

            if roles_to_add:
                await member.add_roles(*roles_to_add, reason="User registration")

            nickname_updated = False
            if member != guild.owner and member.top_role < me.top_role:
                await member.edit(nick=nickname, reason="User registration nickname update")
                nickname_updated = True

            role_names = ", ".join(role.name for role in target_roles)
            if nickname_updated:
                message = f"Done. Nickname set to **{nickname}** and roles assigned: **{role_names}**"
            else:
                message = (
                    f"Roles assigned: **{role_names}**. "
                    f"I could not update your nickname. Make sure my bot role is above yours."
                )

            await interaction.response.send_message(message, ephemeral=True)

        except discord.Forbidden:
            await interaction.response.send_message(
                "I don't have enough permissions. Make sure my bot role is above the target roles and I have Manage Roles and Manage Nicknames.",
                ephemeral=True,
            )
        except discord.HTTPException as e:
            await interaction.response.send_message(
                f"Discord returned an error: `{e}`",
                ephemeral=True,
            )


class ArrivalView(discord.ui.View):
    def __init__(self):
        super().__init__(timeout=None)

    @discord.ui.button(
        label="Start Registration",
        style=discord.ButtonStyle.primary,
        custom_id="start_registration_button",
    )
    async def start_registration(self, interaction: discord.Interaction, button: discord.ui.Button):
        await interaction.response.send_modal(RegistrationModal())


@bot.event
async def on_ready():
    bot.add_view(ArrivalView())
    print(f"Logged in as {bot.user} (ID: {bot.user.id})")
    print("Bot is ready.")


@bot.command(name=SETUP_COMMAND_NAME)
@commands.guild_only()
@commands.has_permissions(manage_guild=True)
async def setup_arrival(ctx: commands.Context):
    if ALLOWED_CHANNEL_ID and ctx.channel.id != ALLOWED_CHANNEL_ID:
        await ctx.reply("You can only use this setup command in the arrival channel.")
        return

    embed = discord.Embed(
        title="Welcome",
        description=(
            "Click the button below to register.\n\n"
            "You will be asked for your state role, alliance role, rank role, and player name."
        ),
    )

    await ctx.send(embed=embed, view=ArrivalView())
    await ctx.reply("Arrival registration button posted.")


@setup_arrival.error
async def setup_arrival_error(ctx: commands.Context, error: commands.CommandError):
    if isinstance(error, commands.MissingPermissions):
        await ctx.reply("You need the Manage Server permission to post the arrival button.")
    else:
        await ctx.reply(f"Setup failed: `{error}`")


if __name__ == "__main__":
    if not TOKEN:
        raise RuntimeError("Set the DISCORD_BOT_TOKEN environment variable before starting the bot.")
    bot.run(TOKEN)
