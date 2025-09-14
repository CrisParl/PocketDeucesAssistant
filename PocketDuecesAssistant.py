import disnake
from disnake.ext import commands

# ---- CONFIG ----
TOKEN = "YOUR_DISCORD_BOT_TOKEN"
ALLOWED_METHODS = ["venmo", "zelle", "cashapp", "crypto"]
ADMIN_ROLES = ["admin", "cashier"]

# ---- BOT ----
intents = disnake.Intents.default()
bot = commands.InteractionBot(intents=intents)

# Track queues
withdrawals = []
deposits = []

def is_staff(inter):
    return any(r.name.lower() in ADMIN_ROLES for r in inter.author.roles)

# ---- COMMANDS ----

@bot.slash_command(description="Queue a withdrawal request")
async def queue(
    inter,
    username: str,
    method: str,
    destination: str,
    amount: float
):
    if method.lower() not in ALLOWED_METHODS:
        await inter.response.send_message("❌ Invalid method. Use Venmo, Zelle, CashApp, or Crypto.", ephemeral=True)
        return
    
    withdrawals.append({
        "username": username,
        "method": method.lower(),
        "destination": destination,
        "amount": amount
    })
    await inter.response.send_message(f"✅ Withdrawal queued: {username}, {method}, {amount}")

@bot.slash_command(description="Record a deposit and match to withdrawals")
async def deposit(
    inter,
    username: str,
    method: str,
    amount: float
):
    if not is_staff(inter):
        await inter.response.send_message("❌ Only admins/cashiers can use this command.", ephemeral=True)
        return

    if method.lower() not in ALLOWED_METHODS:
        await inter.response.send_message("❌ Invalid method.", ephemeral=True)
        return

    deposits.append({
        "username": username,
        "method": method.lower(),
        "amount": amount
    })

    # Try to match deposit to withdrawals
    for w in withdrawals:
        if w["method"] == method.lower() and w["amount"] <= amount:
            deposits[-1]["amount"] -= w["amount"]
            msg = (f"💰 Match found!\n"
                   f"Send {w['amount']} to {w['username']} via {w['method']} ({w['destination']})")
            w["amount"] = 0
            await inter.response.send_message(msg)
            return

    await inter.response.send_message("⚠️ No efficient match found. Contact admin.")

@bot.slash_command(description="Mark last withdrawal as filled")
async def filled(inter):
    if not is_staff(inter):
        await inter.response.send_message("❌ Only admins/cashiers can use this command.", ephemeral=True)
        return
    if withdrawals:
        withdrawals.pop(0)
        await inter.response.send_message("✅ Last withdrawal marked as filled.")
    else:
        await inter.response.send_message("⚠️ No withdrawals in queue.")

@bot.slash_command(description="Complete last deposit")
async def complete(inter):
    if not is_staff(inter):
        await inter.response.send_message("❌ Only admins/cashiers can use this command.", ephemeral=True)
        return
    if deposits:
        deposits.pop(0)
        await inter.response.send_message("✅ Last deposit completed.")
    else:
        await inter.response.send_message("⚠️ No deposits in queue.")

# ---- START ----
bot.run(TOKEN)
