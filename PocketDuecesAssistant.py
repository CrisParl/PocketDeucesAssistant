import os
import sqlite3
import asyncio
from datetime import datetime, timezone
import re

import disnake as discord
from disnake.ext import commands


# --------------- CONFIG ---------------
GUILD_ID = None   # Set to your server ID (int) for faster sync during testing
ADMIN_ROLE_NAMES = {"Admin", "Cashier"}  # Allowed roles
TOKEN = os.getenv("DISCORD_BOT_TOKEN")   # Set in environment variable
DB_PATH = "poker_withdrawals.db"

INTENTS = discord.Intents.default()
INTENTS.members = True
# --------------------------------------

# ---------- UTIL: ADMIN CHECK ----------
def is_admin(interaction: discord.Interaction) -> bool:
    if interaction.user.guild_permissions.manage_guild:
        return True
    user_roles = {r.name for r in getattr(interaction.user, "roles", [])}
    return len(ADMIN_ROLE_NAMES.intersection(user_roles)) > 0

# ---------- DATABASE LAYER ----------
class Store:
    def __init__(self, path: str):
        self.path = path
        self._lock = asyncio.Lock()
        self._init_db()

    def _conn(self):
        return sqlite3.connect(self.path)

    def _init_db(self):
        with self._conn() as c:
            c.execute("""
            CREATE TABLE IF NOT EXISTS withdrawals (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                discord_user_id INTEGER NOT NULL,
                clubgg_username TEXT NOT NULL,
                method TEXT NOT NULL,
                destination TEXT NOT NULL,
                amount REAL NOT NULL,
                status TEXT NOT NULL,        -- 'Queued', 'Filled', 'Completed'
                channel_id INTEGER NOT NULL,
                created_at TEXT NOT NULL,
                updated_at TEXT NOT NULL
            )""")
            c.execute("""
            CREATE INDEX IF NOT EXISTS idx_withdrawals_username_status
            ON withdrawals (clubgg_username, status)
            """)
            c.execute("""
            CREATE TABLE IF NOT EXISTS balances (
                clubgg_username TEXT PRIMARY KEY,
                balance REAL NOT NULL DEFAULT 0
            )""")

    async def add_withdrawal(self, discord_user_id: int, clubgg_username: str,
                             method: str, destination: str, amount: float, channel_id: int) -> int:
        async with self._lock:
            now = datetime.now(timezone.utc).isoformat()
            with self._conn() as c:
                cur = c.execute("""
                    INSERT INTO withdrawals 
                    (discord_user_id, clubgg_username, method, destination, amount, status, channel_id, created_at, updated_at)
                    VALUES (?,?,?,?,?,'Queued',?,?,?)
                """, (discord_user_id, clubgg_username.strip(), method.strip(), destination.strip(),
                      float(amount), channel_id, now, now))
                return cur.lastrowid

    async def get_latest_queued(self, clubgg_username: str):
        async with self._lock:
            with self._conn() as c:
                return c.execute("""
                    SELECT * FROM withdrawals
                    WHERE clubgg_username = ? AND status = 'Queued'
                    ORDER BY id DESC LIMIT 1
                """, (clubgg_username.strip(),)).fetchone()

    async def get_context_latest(self, channel_id: int):
        async with self._lock:
            with self._conn() as c:
                return c.execute("""
                    SELECT * FROM withdrawals
                    WHERE channel_id = ? AND status IN ('Queued','Filled')
                    ORDER BY id DESC LIMIT 1
                """, (channel_id,)).fetchone()

    async def update_withdrawal(self, wid: int, **fields):
        if not fields:
            return
        async with self._lock:
            sets = []
            params = []
            for k, v in fields.items():
                sets.append(f"{k} = ?")
                params.append(v)
            sets.append("updated_at = ?")
            params.append(datetime.now(timezone.utc).isoformat())
            params.append(wid)
            with self._conn() as c:
                c.execute(f"UPDATE withdrawals SET {', '.join(sets)} WHERE id = ?", params)

    async def set_status(self, wid: int, status: str):
        await self.update_withdrawal(wid, status=status)

    async def delete_withdrawal(self, wid: int):
        async with self._lock:
            with self._conn() as c:
                c.execute("DELETE FROM withdrawals WHERE id = ?", (wid,))

    async def get_balance(self, clubgg_username: str) -> float:
        async with self._lock:
            with self._conn() as c:
                row = c.execute("SELECT balance FROM balances WHERE clubgg_username = ?",
                                (clubgg_username.strip(),)).fetchone()
                return float(row[0]) if row else 0.0

    async def set_balance(self, clubgg_username: str, balance: float):
        async with self._lock:
            with self._conn() as c:
                c.execute("""
                    INSERT INTO balances (clubgg_username, balance) VALUES (?,?)
                    ON CONFLICT(clubgg_username) DO UPDATE SET balance=excluded.balance
                """, (clubgg_username.strip(), float(balance)))

# ---------- BOT SETUP ----------
class WithdrawBot(commands.Bot):
    def __init__(self):
        super().__init__(command_prefix="!", intents=INTENTS)
        self.store = Store(DB_PATH)
        self.tree = app_commands.CommandTree(self)

    async def setup_hook(self):
        if GUILD_ID:
            guild_obj = discord.Object(id=GUILD_ID)
            self.tree.copy_global_to(guild=guild_obj)
            await self.tree.sync(guild=guild_obj)
        else:
            await self.tree.sync()

bot = WithdrawBot()

# ---------- INPUT VALIDATION ----------
def valid_amount(value: str) -> float:
    if isinstance(value, (int, float)):
        return float(value)
    v = value.strip().replace(",", "")
    if not re.fullmatch(r"-?\d+(\.\d{1,2})?", v):
        raise ValueError("Amount must be a number (up to 2 decimals).")
    return float(v)

# ---------- COMMANDS ----------

@bot.tree.command(name="queue", description="Queue a withdrawal request.")
@app_commands.describe(
    clubgg_username="ClubGG username",
    method_of_payment="Payment method",
    destination="Where to send funds",
    amount="Withdrawal amount"
)
async def queue_cmd(interaction: discord.Interaction,
                    clubgg_username: str,
                    method_of_payment: str,
                    destination: str,
                    amount: str):
    if not is_admin(interaction):
        await interaction.response.send_message("❌ You don’t have permission.", ephemeral=True)
        return
    try:
        amt = valid_amount(amount)
    except ValueError as e:
        await interaction.response.send_message(f"❌ {e}", ephemeral=True)
        return
    wid = await bot.store.add_withdrawal(interaction.user.id, clubgg_username, method_of_payment, destination, amt, interaction.channel_id)
    await interaction.response.send_message(
        f"✅ Queued Withdrawal (ID `{wid}`)\n"
        f"• User: **{clubgg_username}**\n• Method: **{method_of_payment}**\n• Destination: **{destination}**\n• Amount: **${amt:.2f}**",
        ephemeral=False
    )

@bot.tree.command(name="deposit", description="Find a queued user and show details.")
async def deposit_cmd(interaction: discord.Interaction, clubgg_username: str,
                      method_of_payment: str | None = None,
                      destination: str | None = None,
                      amount: str | None = None):
    if not is_admin(interaction):
        await interaction.response.send_message("❌ Admin only.", ephemeral=True)
        return
    row = await bot.store.get_latest_queued(clubgg_username)
    if not row:
        await interaction.response.send_message(f"❌ No queued record for {clubgg_username}.", ephemeral=True)
        return
    (wid, _, u, method, dest, amt, status, _, _, _) = row
    if method_of_payment:
        await bot.store.update_withdrawal(wid, method=method_of_payment)
        method = method_of_payment
    if destination:
        await bot.store.update_withdrawal(wid, destination=destination)
        dest = destination
    if amount:
        amt = valid_amount(amount)
        await bot.store.update_withdrawal(wid, amount=amt)
    await interaction.response.send_message(
        f"🔎 Withdrawal Info (ID `{wid}`)\n• User: **{u}**\n• Method: **{method}**\n• Destination: **{dest}**\n• Amount: **${amt:.2f}**\n• Status: {status}",
        ephemeral=False
    )

@bot.tree.command(name="filled", description="Mark last queued withdrawal as FILLED.")
async def filled_cmd(interaction: discord.Interaction):
    if not is_admin(interaction):
        await interaction.response.send_message("❌ Admin only.", ephemeral=True)
        return
    row = await bot.store.get_context_latest(interaction.channel_id)
    if not row:
        await interaction.response.send_message("❌ Nothing to fill.", ephemeral=True)
        return
    (wid, _, u, _, _, amt, status, _, _, _) = row
    if status == "Queued":
        await bot.store.set_status(wid, "Filled")
        await interaction.response.send_message(f"💰 Marked FILLED (ID `{wid}`) for **{u}**, Amount: ${amt:.2f}", ephemeral=False)
    else:
        await interaction.response.send_message(f"ℹ️ Already {status}.", ephemeral=True)

@bot.tree.command(name="complete", description="Complete withdrawal and deduct balance.")
async def complete_cmd(interaction: discord.Interaction):
    if not is_admin(interaction):
        await interaction.response.send_message("❌ Admin only.", ephemeral=True)
        return
    row = await bot.store.get_context_latest(interaction.channel_id)
    if not row:
        await interaction.response.send_message("❌ Nothing to complete.", ephemeral=True)
        return
    (wid, _, u, _, _, amt, _, _, _, _) = row
    current_balance = await bot.store.get_balance(u)
    new_balance = current_balance - float(amt)
    await bot.store.set_balance(u, new_balance)
    await bot.store.set_status(wid, "Completed")
    await interaction.response.send_message(
        f"✅ COMPLETED (ID `{wid}`)\n• User: **{u}**\n• Amount: ${amt:.2f}\n• Remaining Balance: ${new_balance:.2f}",
        ephemeral=False
    )

@bot.tree.command(name="delete", description="Delete the last queued/filled withdrawal.")
async def delete_cmd(interaction: discord.Interaction):
    if not is_admin(interaction):
        await interaction.response.send_message("❌ Admin only.", ephemeral=True)
        return
    row = await bot.store.get_context_latest(interaction.channel_id)
    if not row:
        await interaction.response.send_message("❌ Nothing to delete.", ephemeral=True)
        return
    (wid, _, u, _, _, amt, status, _, _, _) = row
    await bot.store.delete_withdrawal(wid)
    await interaction.response.send_message(f"🗑️ Deleted withdrawal ID `{wid}` for **{u}** (Amount: ${amt:.2f}, Status: {status})", ephemeral=False)

@bot.tree.command(name="add", description="Add money to last queued/filled request.")
async def add_cmd(interaction: discord.Interaction, amount: str):
    if not is_admin(interaction):
        await interaction.response.send_message("❌ Admin only.", ephemeral=True)
        return
    delta = valid_amount(amount)
    row = await bot.store.get_context_latest(interaction.channel_id)
    if not row:
        await interaction.response.send_message("❌ Nothing to modify.", ephemeral=True)
        return
    (wid, _, u, _, _, amt, _, _, _, _) = row
    new_amt = amt + delta
    await bot.store.update_withdrawal(wid, amount=new_amt)
    await interaction.response.send_message(f"➕ Updated withdrawal (ID `{wid}`) for **{u}**\nPrevious: ${amt:.2f}\nAdded: +${delta:.2f}\nNew: ${new_amt:.2f}", ephemeral=False)

@bot.tree.command(name="subtract", description="Subtract money from last queued/filled request.")
async def subtract_cmd(interaction: discord.Interaction, amount: str):
    if not is_admin(interaction):
        await interaction.response.send_message("❌ Admin only.", ephemeral=True)
        return
    delta = valid_amount(amount)
    row = await bot.store.get_context_latest(interaction.channel_id)
    if not row:
        await interaction.response.send_message("❌ Nothing to modify.", ephemeral=True)
        return
    (wid, _, u, _, _, amt, _, _, _, _) = row
    new_amt = amt - delta
    if new_amt < 0:
        await interaction.response.send_message("❌ Cannot go negative.", ephemeral=True)
        return
    await bot.store.update_withdrawal(wid, amount=new_amt)
    await interaction.response.send_message(f"➖ Updated withdrawal (ID `{wid}`) for **{u}**\nPrevious: ${amt:.2f}\nSubtracted: -${delta:.2f}\nNew: ${new_amt:.2f}", ephemeral=False)

@bot.tree.command(name="make", description="Grant someone Admin or Cashier role.")
@app_commands.describe(user="User to promote", role="Role to assign (Admin or Cashier)")
async def make_cmd(interaction: discord.Interaction, user: discord.Member, role: str):
    if not is_admin(interaction):
        await interaction.response.send_message("❌ You don’t have permission.", ephemeral=True)
        return
    role = role.capitalize()
    if role not in {"Admin", "Cashier"}:
        await interaction.response.send_message("❌ Role must be Admin or Cashier.", ephemeral=True)
        return
    guild = interaction.guild
    target_role = discord.utils.get(guild.roles, name=role)
    if target_role is None:
        target_role = await guild.create_role(name=role)
        await interaction.response.send_message(f"ℹ️ Created new role **{role}**.", ephemeral=True)
    await user.add_roles(target_role)
    await interaction.followup.send(f"✅ {user.mention} is now a **{role}**.", ephemeral=False)

# ---------- LIFECYCLE ----------
@bot.event
async def on_ready():
    print(f"Logged in as {bot.user} (id={bot.user.id})")
    try:
        if GUILD_ID:
            await bot.tree.sync(guild=discord.Object(id=GUILD_ID))
        else:
            await bot.tree.sync()
        print("Slash commands synced.")
    except Exception as e:
        print("Command sync failed:", e)

# ---------- MAIN ----------
def main():
    if not TOKEN:
        raise RuntimeError("Set your token in the DISCORD_BOT_TOKEN environment variable.")
    bot.run(TOKEN)

if __name__ == "__main__":
    main()
