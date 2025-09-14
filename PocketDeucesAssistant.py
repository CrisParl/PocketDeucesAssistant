import os
import disnake
from disnake.ext import commands

# ---- CONFIG ----
TOKEN = os.getenv("DISCORD_TOKEN")  # Store securely (Replit/host)
ALLOWED_METHODS = ["venmo", "zelle", "cashapp", "crypto"]
ADMIN_ROLES = ["admin", "cashier"]

# Test guilds for instant slash command registration (comma-separated IDs)
def _parse_test_guilds():
    raw = os.getenv("TEST_GUILD_IDS", "").replace(" ", "")
    if not raw:
        return []
    ids = []
    for piece in raw.split(","):
        try:
            ids.append(int(piece))
        except Exception:
            pass
    return ids

TEST_GUILD_IDS = _parse_test_guilds()

# ---- BOT ----
intents = disnake.Intents.default()
intents.members = True  # Enable SERVER MEMBERS INTENT in Dev Portal
bot = commands.InteractionBot(
    intents=intents,
    test_guilds=TEST_GUILD_IDS if TEST_GUILD_IDS else None
)

# Track queues
withdrawals = []  # list of dicts
deposits = []     # list of dicts


# ---- HELPERS ----
def is_staff(inter):
    return any(r.name.lower() in ADMIN_ROLES for r in inter.author.roles) or inter.author.guild_permissions.manage_guild


@bot.event
async def on_ready():
    print(f"Logged in as {bot.user} (guilds: {[g.name for g in bot.guilds]})")
    try:
        await bot.sync_commands()
        print("Slash commands synced.")
    except Exception as e:
        print("Failed to sync slash commands:", e)


# ---- COMMANDS ----

@bot.slash_command(description="Queue a withdrawal request")
async def queue(inter, username: str, method: str, destination: str, amount: float):
    if not is_staff(inter):
        await inter.response.send_message("❌ Only Admins/Cashiers can use this.", ephemeral=True)
        return

    method_l = method.lower()
    if method_l not in ALLOWED_METHODS:
        await inter.response.send_message("❌ Invalid method. Use Venmo, Zelle, CashApp, or Crypto.", ephemeral=True)
        return

    # Zelle validation (must be 10-digit phone OR an email)
    if method_l == "zelle":
        if not (destination.isdigit() and len(destination) == 10) and "@" not in destination:
            await inter.response.send_message(
                "❌ Invalid Zelle destination. Must be a 10-digit phone number or an email.",
                ephemeral=True
            )
            return

    withdrawals.append({
        "username": username,
        "method": method_l,
        "destination": destination,
        "amount": amount,
        "original_amount": amount,
        "status": "Not Started",
        "channel_id": inter.channel.id
    })

    await inter.response.send_message(
        f"✅ Withdrawal queued:\n"
        f"User: {username}\nMethod: {method_l}\nDestination: {destination}\nAmount: ${amount:.2f}"
    )


@bot.slash_command(description="Record a deposit (PENDING until confirmed)")
async def deposit(inter, username: str, method: str, amount: float):
    if not is_staff(inter):
        await inter.response.send_message("❌ Only Admins/Cashiers can use this.", ephemeral=True)
        return

    method_l = method.lower()
    if method_l not in ALLOWED_METHODS:
        await inter.response.send_message("❌ Invalid method.", ephemeral=True)
        return

    # Store the pending deposit
    deposit_entry = {"username": username, "method": method_l, "amount": amount, "status": "pending"}
    deposits.append(deposit_entry)

    # IMPORTANT: Use the same rule as confirm_deposit
    # Find the FIRST withdrawal of the same method that can accept the FULL deposit (no splitting)
    match = next((w for w in withdrawals if w["method"] == method_l and w["amount"] >= amount), None)

    if match:
        public_msg = (
            f"⏳ Deposit PENDING: {username} — ${amount:.2f} via {method_l.capitalize()}\n"
            f"➡️ Send via **{match['method'].capitalize()}** to **{match['destination']}**\n"
            f"📸 Please send a screenshot once payment is complete."
        )
    else:
        # Fallback if no eligible withdrawal exists
        if method_l == "zelle":
            dest = "crisparlog@gmail.com"
        elif method_l == "venmo":
            dest = "CrisPG"
        else:  # cashapp or crypto
            dest = "Contact admin"

        public_msg = (
            f"⏳ Deposit PENDING: {username} — ${amount:.2f} via {method_l.capitalize()}\n"
            f"➡️ Send via **{method_l.capitalize()}** to **{dest}**\n"
            f"📸 Please send a screenshot once payment is complete."
        )

    # Send public info
    await inter.response.send_message(public_msg)
    # Private note for staff
    await inter.followup.send("ℹ️ Still stored as pending — confirm with `/confirm_deposit` once verified.", ephemeral=True)


@bot.slash_command(description="Confirm the last pending deposit and process matches")
async def confirm_deposit(inter):
    if not is_staff(inter):
        await inter.response.send_message("❌ Only Admins/Cashiers can use this.", ephemeral=True)
        return

    # Find last pending deposit
    pending = None
    for d in reversed(deposits):
        if d["status"] == "pending":
            pending = d
            break

    if not pending:
        await inter.response.send_message("⚠️ No pending deposits to confirm.", ephemeral=True)
        return

    pending["status"] = "confirmed"
    username, method_l, amount = pending["username"], pending["method"], pending["amount"]

    # EXACT SAME RULE as /deposit: the deposit must fit fully into a single withdrawal
    target = next((w for w in withdrawals if w["method"] == method_l and w["amount"] >= amount), None)

    if not target:
        # Extremely rare now (since /deposit already guided to fallback), but keep safety:
        if method_l == "zelle":
            dest = "crisparlog@gmail.com"
        elif method_l == "venmo":
            dest = "CrisPG"
        else:
            dest = "Contact admin"

        await inter.response.send_message(
            f"⚠️ No eligible withdrawal found for ${amount:.2f}.\n"
            f"➡️ Send via {method_l.capitalize()} to **{dest}**"
        )
        return

    # Apply FULL deposit to that ONE withdrawal (no splitting)
    target["amount"] -= amount
    if target["amount"] == 0:
        target["status"] = "Completed"
    else:
        # Still less than original -> Partial
        target["status"] = "Partial"

    # Announce in the withdrawal's channel
    channel = bot.get_channel(target["channel_id"])
    if channel:
        if target["amount"] == 0:
            await channel.send(
                f"📢 **Update for {target['username']}**\n"
                f"Amount claimed: ${amount:.2f}\n"
                f"Remaining: $0.00 / ${target['original_amount']:.2f}"
            )
        else:
            await channel.send(
                f"📢 **Partial Update for {target['username']}**\n"
                f"Amount claimed: ${amount:.2f}\n"
                f"Remaining: ${target['amount']:.2f} / ${target['original_amount']:.2f}"
            )

    # Thank depositor (staff sees this)
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
        w["original_amount"] += amount  # reflect manual increase in the "original" total
        # If someone adds after a partial, we can reset to Not Started if no amount was ever claimed;
        # but simplest: leave status alone unless it hits zero.
        await inter.response.send_message(
            f"➕ Added ${amount:.2f} to {w['username']}. New total: ${w['amount']:.2f}"
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
            f"➖ Subtracted ${amount:.2f} from {w['username']}. New total: ${w['amount']:.2f}"
        )
    else:
        await inter.response.send_message("⚠️ No active withdrawals in this channel.")


# ---- LIST / ADMIN COMMANDS ----

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
        msg.append(
            f"{i}. {w['username']} — ${w['amount']:.2f} / ${w['original_amount']:.2f} "
            f"via {w['method']} ({w['destination']}) — **{status}**"
        )
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
    role_cap = role.capitalize()
    if role_cap not in {"Admin", "Cashier"}:
        await inter.response.send_message("❌ Role must be Admin or Cashier.", ephemeral=True)
        return
    guild = inter.guild
    target_role = disnake.utils.get(guild.roles, name=role_cap)
    if target_role is None:
        target_role = await guild.create_role(name=role_cap)
    await user.add_roles(target_role)
    await inter.response.send_message(f"✅ {user.mention} is now a **{role_cap}**.")


# Name function differently to avoid collisions; command name stays "help"
@bot.slash_command(name="help", description="Show all available commands and their uses")
async def help_cmd(inter):
    if not is_staff(inter):
        await inter.response.send_message("❌ Only Admins/Cashiers can use this bot.", ephemeral=True)
        return

    help_text = """
📖 **Pocket Deuces Assistant Commands**

**Withdrawals**
- `/queue username method destination amount`
   → Queue a new withdrawal request. (Zelle must be a 10-digit phone or email.)
- `/queue_list`
   → Show all withdrawals with status (Not Started / Partial / Completed).
- `/add amount`
   → Add money to the active withdrawal in this channel.
- `/subtract amount`
   → Subtract money from the active withdrawal in this channel.

**Deposits**
- `/deposit username method amount`
   → Record a deposit (PENDING). Shows the FIRST withdrawal that can accept the FULL amount.
   → If no withdrawal can accept it, shows fallback destination (Zelle email / Venmo user / contact admin).
- `/confirm_deposit`
   → Confirms the last pending deposit. Applies it to exactly ONE withdrawal (no splitting),
     posts an update in that withdrawal's channel: `Remaining: $X / $Original`.
- `/deposit_list`
   → Show all deposits with their status (PENDING/CONFIRMED).
- `/complete`
   → Mark the oldest deposit as completed.

**Roles**
- `/make @user role`
   → Grant a user the Admin or Cashier role.

**Notes**
- Only users with Admin/Cashier roles can use these commands.
- Updates for withdrawals are posted directly in the channel where they were queued.
"""
    await inter.response.send_message(help_text, ephemeral=True)


# ---- START ----
print("Loaded token?", bool(TOKEN))
if TEST_GUILD_IDS:
    print("Registering commands to test guilds:", TEST_GUILD_IDS)
else:
    print("No TEST_GUILD_IDS set; registering commands globally (may take a while to appear).")
bot.run(TOKEN)
