import os
import discord
from discord.ext import commands

# Intents
intents = discord.Intents.default()
intents.message_content = True
intents.guilds = True

# Bot setup
bot = commands.Bot(command_prefix="/", intents=intents)

# Data
withdrawals = []  # list of {id, username, method, destination, amount}
roles = {}        # {user_id: "Admin" | "Cashier"}

# Allowed payment methods
ALLOWED_METHODS = ["Venmo", "Zelle", "CashApp", "Crypto"]

# Track active matches for deposits
active_deposits = {}  # {depositor_id: {withdrawal, amount}}

# --------------------
# Helpers
# --------------------
def has_permission(user_id):
    return roles.get(user_id) in ["Admin", "Cashier"]


def find_best_match(method, deposit_amount):
    """
    Find the first withdrawal with same method and amount >= deposit.
    If first withdrawal is too small, keep scanning until a suitable match.
    """
    for idx, w in enumerate(withdrawals):
        if w["method"] == method and w["amount"] >= deposit_amount:
            return idx, w
    return None, None


# --------------------
# Events
# --------------------
@bot.event
async def on_ready():
    print(f"✅ Logged in as {bot.user} (id: {bot.user.id})")
    print("------")


# --------------------
# Commands
# --------------------
@bot.slash_command(name="make", description="Make a user an Admin or Cashier")
async def make(ctx, member: discord.Member, role: str):
    if ctx.author.id not in roles or roles[ctx.author.id] != "Admin":
        await ctx.respond("❌ Only Admins can assign roles.", ephemeral=True)
        return
    if role not in ["Admin", "Cashier"]:
        await ctx.respond("❌ Role must be Admin or Cashier.", ephemeral=True)
        return

    roles[member.id] = role
    await ctx.respond(f"✅ {member.mention} is now a {role}.")


@bot.slash_command(name="queue", description="Queue a withdrawal request")
async def queue(ctx, clubgg_username: str, method: str, destination: str, amount: float):
    if not has_permission(ctx.author.id):
        await ctx.respond("❌ You don’t have permission to use this command.", ephemeral=True)
        return

    if method.capitalize() not in ALLOWED_METHODS:
        await ctx.respond("⚠️ Invalid payment method. Contact an Admin.", ephemeral=True)
        return

    withdrawal = {
        "id": ctx.author.id,
        "username": clubgg_username,
        "method": method.capitalize(),
        "destination": destination,
        "amount": amount,
    }
    withdrawals.append(withdrawal)

    await ctx.respond(
        f"💰 Queued withdrawal: {clubgg_username} requests ${amount} via {method.capitalize()} → {destination}"
    )


@bot.slash_command(name="deposit", description="Match a deposit to a withdrawal")
async def deposit(ctx, method: str, amount: float):
    if not has_permission(ctx.author.id):
        await ctx.respond("❌ You don’t have permission to use this command.", ephemeral=True)
        return

    method = method.capitalize()
    if method not in ALLOWED_METHODS:
        await ctx.respond("⚠️ Invalid payment method. Contact an Admin.", ephemeral=True)
        return

    idx, match = find_best_match(method, amount)
    if not match:
        await ctx.respond("⚠️ No suitable withdrawal found. Contact an Admin.", ephemeral=True)
        return

    # Track the match
    active_deposits[ctx.author.id] = {
        "withdrawal": match,
        "amount": amount,
    }

    # Update withdrawal amount
    if match["amount"] > amount:
        match["amount"] -= amount
        msg = (
            f"💵 Deposit of ${amount} matched with withdrawal for {match['username']} "
            f"via {match['method']} → {match['destination']}.\n"
            f"Remaining withdrawal: ${match['amount']}"
        )
    elif match["amount"] == amount:
        withdrawals.pop(idx)  # remove fully filled
        msg = (
            f"💵 Deposit of ${amount} fully matched withdrawal for {match['username']} "
            f"via {match['method']} → {match['destination']}.\n"
            f"✅ Withdrawal completed."
        )
    else:
        msg = "⚠️ Unexpected error in matching logic. Contact Admin."

    await ctx.respond(msg)


@bot.slash_command(name="complete", description="Complete a deposit transaction")
async def complete(ctx):
    if not has_permission(ctx.author.id):
        await ctx.respond("❌ You don’t have permission to use this command.", ephemeral=True)
        return

    if ctx.author.id not in active_deposits:
        await ctx.respond("⚠️ You have no active deposits in progress.", ephemeral=True)
        return

    match_info = active_deposits.pop(ctx.author.id)
    withdrawal = match_info["withdrawal"]
    amount = match_info["amount"]

    await ctx.respond(
        f"✅ Deposit of ${amount} confirmed for {withdrawal['username']} via {withdrawal['method']}."
    )


@bot.slash_command(name="filled", description="Mark a withdrawal as filled manually")
async def filled(ctx, clubgg_username: str):
    if not has_permission(ctx.author.id):
        await ctx.respond("❌ You don’t have permission to use this command.", ephemeral=True)
        return

    for idx, w in enumerate(withdrawals):
        if w["username"] == clubgg_username:
            withdrawals.pop(idx)
            await ctx.respond(f"✅ Withdrawal for {clubgg_username} marked as filled.")
            return

    await ctx.respond("⚠️ No matching withdrawal found.")


# --------------------
# Run the bot
# --------------------
if __name__ == "__main__":
    token = os.getenv("DISCORD_BOT_TOKEN")
    if not token:
        raise ValueError("❌ DISCORD_BOT_TOKEN not set in environment variables")
    bot.run(token)
