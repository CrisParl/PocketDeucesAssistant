import os
import disnake
from disnake.ext import commands

# ---- CONFIG ----
TOKEN = os.getenv("DISCORD_TOKEN")  # store your token as env var
ALLOWED_METHODS = ["venmo", "zelle", "cashapp", "crypto"]
ADMIN_ROLES = ["admin", "cashier"]

# Channel ID for public withdrawal announcements
WITHDRAW_CHANNEL_ID = 123456789012345678  # <- replace with your channel ID

# ---- BOT ----
intents = disnake.Intents.default()
intents.members = True
bot = commands.InteractionBot(intents=intents)

# Track queues (in memory)
withdrawals = []
deposits = []


# ---- HELPERS ----
def is_staff(inter):
    return any(r.name.lower() in ADMIN_ROLES for r in inter.author.roles) or inter.author.guild_permissions.manage_guild


# ---- COMMANDS ----

@bot.slash_command(description="Queue a withdrawal request")
async def queue(inter, username: str, method: str, destination: str, amount: float):
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


@bot.slash_command(description="Record a deposit (PENDING until confirmed)")
async def deposit(inter, username: str, method: str, amount: float):
    if not is_staff(inter):
        await inter.response.send_message("❌ Only Admins/Cashiers can use this.", ephemeral=True)
        return
    if method.lower() not in ALLOWED_METHODS:
        await inter.response.send_message("❌ Invalid method.", ephemeral=True)
        return

    deposit_entry = {"username": username, "method": method.lower(), "amount": amount, "status": "pending"}
    deposits.append(deposit_entry)

    await inter.response.send_message(
        f"⏳ Deposit PENDING: {username} — ${amount:.2f} via {method.capitalize()}\n"
        f"Use `/confirm_deposit` once payment is verified."
    )


@bot.slash_command(description="Confirm the last pending deposit and process matches")
async def confirm_deposit(inter):
    if not is_staff(inter):
        await inter.response.send_message("❌ Only Admins/Cashiers can use this.", ephemeral=True)
        return

    # Find the last pending deposit
    pending = None
    for d in reversed(deposits):
        if d["status"] == "pending":
            pending = d
            break

    if not pending:
        await inter.response.send_message("⚠️ No pending deposits to confirm.", ephemeral=True)
        return

    # Confirm it
    pending["status"] = "confirmed"
    username, method, amount = pending["username"], pending["method"], pending["amount"]

    remaining = amount
    messages = []

    # Match to withdrawals
    for w in withdrawals:
        if w["method"] != method or w["amount"] <= 0:
            continue
        if remaining <= 0:
            break

        if remaining >= w["amount"]:  # full match
            messages.append(f"✅ Sent ${w['amount']:.2f} to {w['username']} ({w['destination']}) via {w['method']}")
            remaining -= w["amount"]
            w["amount"] = 0
        else:  # partial match
            messages.append(
                f"✅ Partial: Sent ${remaining:.2f} to {w['username']} ({w['destination']}) via {w['method']}\n"
                f"Remaining withdrawal for {w['username']}: ${w['amount'] - remaining:.2f}"
            )
            w["amount"] -= remaining
            remaining = 0
            break

    # Private response
    if messages:
        if remaining > 0:
            messages.append(f"⚠️ ${remaining:.2f} of {username}'s deposit remains unmatched.")
        await inter.response.send_message("\n".join(messages))
    else:
        await inter.response.send_message("⚠️ Deposit confirmed but no matches found.", ephemeral=True)

    # Public announcement
    channel = bot.get_channel(WITHDRAW_CHANNEL_ID)
    if channel:
        msg = [
            f"📢 **Deposit Confirmed:** {username} (${amount:.2f} via {method.capitalize()})",
        ]
        msg.extend(messages if messages else ["No withdrawals matched."])
        await channel.send("\n".join(msg))


@bot.slash_command(description="Mark oldest withdrawal as filled")
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


@bot.slash_command(description="Mark oldest deposit as completed")
async def complete(inter):
    if not is_staff(inter):
        await inter.response.send_message("❌ Only Admins/Cashiers can use this.", ephemeral=True)
        return
    if deposits:
        deposits.pop(0)
        await inter.response.send_message("✅ Oldest deposit completed.")
    else:
        await inter.response.send_message("⚠️ No deposits in queue.")


@bot.slash_command(description="Show withdrawal queue")
async def queue_list(inter):
    if not is_staff(inter):
        await inter.response.send_message("❌ Only Admins/Cashiers can use this.", ephemeral=True)
        return
    if not withdrawals:
        await inter.response.send_message("⚠️ No withdrawals queued.")
        return
    msg = ["📋 **Withdrawal Queue:**"]
    for i, w in enumerate(withdrawals, start=1):
        if w["amount"] > 0:
            msg.append(f"{i}. {w['username']} — ${w['amount']:.2f} via {w['method']} ({w['destination']})")
    await inter.response.send_message("\n".join(msg))


@bot.slash_command(description="Show deposit queue")
async def deposit_list(inter):
    if not is_staff(inter):
        await inter.response.send_message("❌ Only Admins/Cashiers can use this.", ephemeral=True)
        return
    if not deposits:
        await inter.response.send_message("⚠️ No deposits queued.")
        return
    msg = ["📋 **Deposit Queue:**"]
    for i, d in enumerate(deposits, start=1):
        msg.append(f"{i}. {d['username']} — ${d['amount']:.2f} via {d['method']} [{d['status'].upper()}]")
    await inter.response.send_message("\n".join(msg))


@bot.slash_command(description="Delete the last withdrawal")
async def delete(inter):
    if not is_staff(inter):
        await inter.response.send_message("❌ Only Admins/Cashiers can use this.", ephemeral=True)
        return
    if withdrawals:
        removed = withdrawals.pop()
        await inter.response.send_message(f"🗑️ Deleted {removed['username']}'s withdrawal (${removed['amount']:.2f}).")
    else:
        await inter.response.send_message("⚠️ No withdrawals to delete.")


@bot.slash_command(description="Add money to last withdrawal")
async def add(inter, amount: float):
    if not is_staff(inter):
        await inter.response.send_message("❌ Only Admins/Cashiers can use this.", ephemeral=True)
        return
    if withdrawals:
        withdrawals[-1]["amount"] += amount
        await inter.response.send_message(
            f"➕ Added ${amount:.2f} to {withdrawals[-1]['username']}. "
            f"New total: ${withdrawals[-1]['amount']:.2f}"
        )
    else:
        await inter.response.send_message("⚠️ No withdrawals to modify.")


@bot.slash_command(description="Subtract money from last withdrawal")
async def subtract(inter, amount: float):
    if not is_staff(inter):
        await inter.response.send_message("❌ Only Admins/Cashiers can use this.", ephemeral=True)
        return
    if withdrawals:
        withdrawals[-1]["amount"] -= amount
        if withdrawals[-1]["amount"] < 0:
            withdrawals[-1]["amount"] = 0
        await inter.response.send_message(
            f"➖ Subtracted ${amount:.2f} from {withdrawals[-1]['username']}. "
            f"New total: ${withdrawals[-1]['amount']:.2f}"
        )
    else:
        await inter.response.send_message("⚠️ No withdrawals to modify.")


@bot.slash_command(description="Grant someone Admin or Cashier role")
async def make(inter, user: disnake.Member, role: str):
    if not is_staff(inter):
        await inter.response.send_message("❌ Only Admins/Cashiers can use this.", ephemeral=True)
        return
    role = role.capitalize()
    if role not in {"Admin", "Cashier"}:
        await inter.response.send_message("❌ Role must be Admin or Cashier.", ephemeral=True)
        return
    guild = inter.guild
    target_role = disnake.utils.get(guild.roles, name=role)
    if target_role is None:
        target_role = await guild.create_role(name=role)
    await user.add_roles(target_role)
    await inter.response.send_message(f"✅ {user.mention} is now a **{role}**.")


# ---- START ----
print("Loaded token?", bool(TOKEN))
bot.run(TOKEN)
