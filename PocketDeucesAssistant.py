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
withdrawals = []
deposits = []


# ---- HELPERS ----
def is_staff(inter):
    return any(r.name.lower() in ADMIN_ROLES for r in inter.author.roles) or inter.author.guild_permissions.manage_guild


@bot.event
async def on_ready():
    print(f"Logged in as {bot.user} (guilds: {[g.name for g in bot.guilds]})")
    # Force sync commands so /help appears immediately
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
    if method.lower() not in ALLOWED_METHODS:
        await inter.response.send_message("❌ Invalid method. Use Venmo, Zelle, CashApp, or Crypto.", ephemeral=True)
        return

    # Zelle validation (must be 10-digit phone OR an email)
    if method.lower() == "zelle":
        if not (destination.isdigit() and len(destination) == 10) and "@" not in destination:
            await inter.response.send_message(
                "❌ Invalid Zelle destination. Must be a 10-digit phone number or an email.",
                ephemeral=True
            )
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

    # Show where to send: first open withdrawal of same method if any; otherwise fallback
    match = next((w for w in withdrawals if w["method"] == method.lower() and w["amount"] > 0), None)

    if match:
        public_msg = (f"⏳ Deposit PENDING: {username} — ${amount:.2f} via {method.capitalize()}\n"
                      f"➡️ Send via **{match['method'].capitalize()}** to **{match['destination']}**\n"
                      f"📸 Please send a screenshot once payment is complete.")
    else:
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

    await inter.response.send_message(public_msg)  # public
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
        ret
