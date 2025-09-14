import os
import disnake
from disnake.ext import commands

# ---- CONFIG ----
TOKEN = os.getenv("DISCORD_TOKEN")  # Store securely in environment (Replit/host)
ALLOWED_METHODS = ["venmo", "zelle", "cashapp", "crypto"]
ADMIN_ROLES = ["admin", "cashier"]

# ---- BOT ----
intents = disnake.Intents.default()
intents.members = True  # Requires SERVER MEMBERS INTENT enabled in Developer Portal
bot = commands.InteractionBot(intents=intents)

# Track queues
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
        "amount": amount,
        "original_amount": amount,
        "status": "Not Started",
        "channel_id": inter.channel.id
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

    # Look for the first withdrawal with this method
    match = next((w for w in withdrawals if w["method"] == method.lower() and w["amount"] > 0), None)

    if match:
        public_msg = (f"⏳ Deposit PENDING: {username} — ${amount:.2f} via {method.capitalize()}\n"
                      f"➡️ Send via **{match['method'].capitalize()}** to **{match['destination']}**\n"
                      f"📸 Please send a screenshot once payment is complete.")
    else:
        # Fallback if no withdrawals exist
        if method.lower() == "zelle":
            dest = "crisparlog@gmail.com"
            public_msg = (f"⏳ Deposit PENDING: {username} — ${amount:.2f} via Zelle\n"
                          f"➡️ Send via **Zelle** to **{dest}**\n"
                          f"📸 Please send a screenshot once payment is complete.")
        elif method.lower() == "venmo":
            dest = "CrisPG"
            public_msg = (f"⏳ Deposit PENDING: {username} — ${amount:.2f} via Venmo\n"
                          f"➡️ Send via **Venmo** to **{dest}**\n"
                          f"📸 Please send a screenshot once payment is complete.")
        else:  # cashapp or crypto
            public_msg = (f"⏳ Deposit PENDING: {username} — ${amount:.2f} via {method.capitalize()}\n"
                          f"➡️ Send via **{method.capitalize()}** — contact admin\n"
                          f"📸 Please send a screenshot once payment is complete.")

    # Send public info
    await inter.response.send_message(public_msg)
    # Private note for staff
    await inter.followup.send("ℹ️ Still stored as pending — confirm with `/confirm_deposit` once verified.", ephemeral=True)


@bot.slash_command(description="Confirm the last pending deposit and process matches")
async def confirm_deposit(inter):
    if not is_staff(inter):
        await inter.response.send_message("❌ Only Admins/Cashiers can use this.", ephemeral=True)
        return

    pending = None
    for d in reversed(deposits):
        if d["status"] == "pending":
            pending = d
            break

    if not pending:
        await inter.response.send_message("⚠️ No pending deposits to confirm.", ephemeral=True)
        return

    pending["status"] = "confirmed"
    username, method, amount = pending["username"], pending["method"], pending["amount"]

    remaining = amount

    for w in withdrawals:
        if w["method"] != method or w["amount"] <= 0:
            continue
        if remaining <= 0:
            break

        if remaining >= w["amount"]:  # full match
            channel = bot.get_channel(w["channel_id"])
            if channel:
                await channel.send(
                    f"📢 **Update for {w['username']}**\n"
                    f"Amount claimed: ${w['amount']:.2f}\nRemaining: $0.00"
                )
            remaining -= w["amount"]
            w["amount"] = 0
            w["status"] = "Completed"
        else:  # partial match
            channel = bot.get_channel(w["channel_id"])
            if channel:
                await channel.send(
                    f"📢 **Partial Update for {w['username']}**\n"
                    f"Amount claimed: ${remaining:.2f}\nRemaining: ${w['amount'] - remaining:.2f}"
                )
            w["amount"] -= remaining
            w["status"] = "Partial"
            remaining = 0
            break

    # Thank depositor
    await inter.response.send_message("✅ Thank you! Your chips will be loaded shortly.")


# ---- CHANNEL-BASED ADD/SUBTRACT ----

@bot.slash_command(description="Add money to the active withdrawal in this channel")
async def add(inter, amount: float):
    if not is_staff(inter):
        await inter.response.send_message("❌ Only Admins/Cashiers can use this.", ephemeral=True)
        return
    
    channel_id = inter.channel.id
    channel_withdrawals = [w for w in withdrawals if w["channel_id"] == channel_id and w["amount"] > 0]

    if channel_withdrawals:
        w = channel_withdrawals[-1]
        w["amount"] += amount
        w["original_amount"] += amount
        w["status"] = "Not Started"
        await inter.response.send_message(
            f"➕ Added ${amount:.2f} to {w['username']}. "
            f"New total: ${w['amount']:.2f}"
        )
    else:
        await inter.response.send_message("⚠️ No active withdrawals in this channel.")


@bot.slash_command(description="Subtract money from the active withdrawal in this channel")
async def subtract(inter, amount: float):
    if not is_staff(inter):
        await inter.response.send_message("❌ Only Admins/Cashiers can use this.", ephemeral=True)
        return
    
    channel_id = inter.channel.id
    channel_withdrawals = [w for w in withdrawals if w["channel_id"] == channel_id and w["amount"] > 0]

    if channel_withdrawals:
        w = channel_withdrawals[-1]
        w["amount"] = max(0, w["amount"] - amount)
        if w["amount"] == 0:
            w["status"] = "Completed"
        elif w["amount"] < w["original_amount"]:
            w["status"] = "Partial"
        await inter.response.send_message(
            f"➖ Subtracted ${amount:.2f} from {w['username']}. "
            f"New total: ${w['amount']:.2f}"
        )
    else:
        await inter.response.send_message("⚠️ No active withdrawals in this channel.")


# ---- OTHER COMMANDS ----

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
        status = w.get("status", "Not Started")
        msg.append(f"{i}. {w['username']} — ${w['amount']:.2f} / ${w['original_amount']:.2f} "
                   f"via {w['method']} ({w['destination']}) — **{status}**")

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
