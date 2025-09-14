import os
import disnake
from disnake.ext import commands

# ---- CONFIG ----
TOKEN = os.getenv("DISCORD_TOKEN")
ALLOWED_METHODS = ["venmo", "zelle", "cashapp", "crypto"]
ADMIN_ROLES = ["admin", "cashier"]

# ---- BOT ----
intents = disnake.Intents.default()
bot = commands.InteractionBot(intents=intents)

# Track queues
withdrawals = []
deposits = []


# ---- HELPERS ----
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
    if not is_staff(inter):
        await inter.response.send_message("❌ Only Admins/Cashiers can use this.", ephemeral=True)
        return

    if method.lower() not in ALLOWED_METHODS:
        await inter.response.send_message("❌ Invalid method. Use Venmo, Zelle, CashApp, or Crypto.", ephemeral=True)
        return
    
    withdrawals.append({
        "username": username,
        "method": method.lower(),
        "destination": destination,
        "amount": amount
    })
    await inter.response.send_message(
        f"✅ Withdrawal queued:\n"
        f"User: {username}\nMethod: {method}\nDestination: {destination}\nAmount: ${amount:.2f}"
    )


@bot.slash_command(description="Record a deposit and match it to withdrawals")
async def deposit(
    inter,
    username: str,
    method: str,
    amount: float
):
    if not is_staff(inter):
        await inter.response.send_message("❌ Only Admins/Cashiers can use this.", ephemeral=True)
        return

    if method.lower() not in ALLOWED_METHODS:
        await inter.response.send_message("❌ Invalid method.", ephemeral=True)
        return

    deposit_entry = {
        "username": username,
        "method": method.lower(),
        "amount": amount
    }
    deposits.append(deposit_entry)

    remaining = amount
    messages = []

    # Match deposit against withdrawals (FIFO style)
    for w in withdrawals:
        if w["method"] != method.lower() or w["amount"] <= 0:
            continue

        if remaining <= 0:
            break

        if remaining >= w["amount"]:  # deposit fully covers withdrawal
            messages.append(
                f"💰 Send ${w['amount']:.2f} to {w['username']} via {w['method']} ({w['destination']})"
            )
            remaining -= w["amount"]
            w["amount"] = 0
        else:  # deposit partially covers withdrawal
            messages.append(
                f"💰 Partial match: Send ${remaining:.2f} to {w['username']} via {w['method']} ({w['destination']})\n"
                f"Remaining withdrawal for {w['username']}: ${w['amount'] - remaining:.2f}"
            )
            w["amount"] -= remaining
            remaining = 0
            break

    if messages:
        if remaining > 0:
            messages.append(f"⚠️ ${remaining:.2f} of the deposit remains unmatched.")
        await inter.response.send_message("\n".join(messages))
    else:
        await inter.response.send_message("⚠️ No matching withdrawals found. Contact admin.")


@bot.slash_command(description="Mark the oldest withdrawal as filled (remove from queue)")
async def filled(inter):
    if not is_staff(inter):
        await inter.response.send_message("❌ Only Admins/Cashiers can use this.", ephemeral=True)
        return

    for i, w in enumerate(withdrawals):
        if w["amount"] > 0:
            withdrawals.pop(i)
            await inter.response.send_message("✅ Oldest withdrawal marked as filled.")
            return

    await inter.response.send_message("⚠️ No withdrawals in queue.")


@bot.slash_command(description="Mark the oldest deposit as completed (remove from queue)")
async def complete(inter):
    if not is_staff(inter):
        await inter.response.send_message("❌ Only Admins/Cashiers can use this.", ephemeral=True)
        return

    if deposits:
        deposits.pop(0)
        await inter.response.send_message("✅ Oldest deposit completed.")
    else:
        await inter.response.send_message("⚠️ No deposits in queue.")


# ---- START ----
print("Loaded token?", bool(TOKEN))
bot.run(TOKEN)
