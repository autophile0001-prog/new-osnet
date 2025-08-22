
from telegram import Update
from telegram.ext import Application, CommandHandler, MessageHandler, filters, ContextTypes
import sqlite3, requests

# --- CONFIG ---
API_URL = "http://xploide.site/Api.php"
BOT_TOKEN = "8481154557:AAG4RKO8FM0kDjYpVx-DcWF9SoIReb4x7VI"   # <- put your token
ADMIN_ID = 1218938666               # <- put your Telegram numeric ID

# --- DATABASE SETUP ---
conn = sqlite3.connect("credits.db", check_same_thread=False)
cursor = conn.cursor()
# Create table (new installs get username column)
cursor.execute("""
    CREATE TABLE IF NOT EXISTS users (
        user_id INTEGER PRIMARY KEY,
        username TEXT,
        credits INTEGER
    )
""")
conn.commit()
# Migrate old DBs that may lack `username`
cursor.execute("PRAGMA table_info(users)")
cols = {row[1] for row in cursor.fetchall()}
if "username" not in cols:
    cursor.execute("ALTER TABLE users ADD COLUMN username TEXT")
    conn.commit()

# --- HELPERS ---
def normalize_username(username: str | None) -> str | None:
    """Store usernames without @ and in lowercase."""
    return username.lstrip("@").lower() if username else None

def get_user_by_username(username: str):
    """Find a user by username (with/without @, case-insensitive)."""
    uname = normalize_username(username)
    cursor.execute("SELECT user_id, username, credits FROM users WHERE LOWER(username)=?", (uname,))
    return cursor.fetchone()

def get_credits(user_id: int) -> int:
    cursor.execute("SELECT credits FROM users WHERE user_id=?", (user_id,))
    row = cursor.fetchone()
    return row[0] if row else 0

def ensure_user(user_id: int, username: str | None):
    """Ensure a row exists; keep username up to date."""
    uname = normalize_username(username)
    cursor.execute("SELECT user_id FROM users WHERE user_id=?", (user_id,))
    if cursor.fetchone():
        cursor.execute("UPDATE users SET username=? WHERE user_id=?", (uname, user_id))
    else:
        cursor.execute("INSERT INTO users (user_id, username, credits) VALUES (?, ?, ?)", (user_id, uname, 0))
    conn.commit()

def add_credits(user_id: int, amount: int):
    cursor.execute("UPDATE users SET credits = COALESCE(credits, 0) + ? WHERE user_id=?", (amount, user_id))
    if cursor.rowcount == 0:
        # If not present, create with that balance
        cursor.execute("INSERT INTO users (user_id, credits) VALUES (?, ?)", (user_id, amount))
    conn.commit()

def remove_credits(user_id: int, amount: int):
    cursor.execute("UPDATE users SET credits = MAX(COALESCE(credits,0) - ?, 0) WHERE user_id=?", (amount, user_id))
    conn.commit()

def set_credits(user_id: int, amount: int):
    cursor.execute("UPDATE users SET credits=? WHERE user_id=?", (amount, user_id))
    if cursor.rowcount == 0:
        cursor.execute("INSERT INTO users (user_id, credits) VALUES (?, ?)", (user_id, amount))
    conn.commit()

def deduct_credit(user_id: int):
    cursor.execute("UPDATE users SET credits = credits - 1 WHERE user_id=? AND credits > 0", (user_id,))
    conn.commit()

def resolve_target(target: str):
    """
    Accepts: numeric ID, '@username', or 'username'.
    Returns: (user_id, username_or_None) or (None, None) if not found for username case.
    """
    target = target.strip()
    if target.isdigit():
        uid = int(target)
        cursor.execute("SELECT username FROM users WHERE user_id=?", (uid,))
        row = cursor.fetchone()
        return uid, (row[0] if row else None)
    else:
        user = get_user_by_username(target)
        if not user:
            return None, None
        uid, uname, _credits = user
        return uid, uname

def disp_user(uid: int, uname: str | None) -> str:
    return f"ID {uid}" + (f" (@{uname})" if uname else "")

async def admin_only(update: Update) -> bool:
    if update.message.from_user.id != ADMIN_ID:
        await update.message.reply_text("❌ Only admin can use this command.")
        return False
    return True

# --- COMMANDS ---
async def start(update: Update, context: ContextTypes.DEFAULT_TYPE):
    u = update.message.from_user
    ensure_user(u.id, u.username)
    credits = get_credits(u.id)
    uname = f"@{u.username}" if u.username else "N/A"
    await update.message.reply_text(
        f"👋 Welcome {u.first_name}!\n\n"
        f"🆔 Telegram ID: {u.id}\n"
        f"👤 Username: {uname}\n"
        f"💳 Credits: {credits}\n\n"
        "➡️ Contact admin to get credits."
    )

async def mycredits(update: Update, context: ContextTypes.DEFAULT_TYPE):
    u = update.message.from_user
    credits = get_credits(u.id)
    await update.message.reply_text(f"💰 You have {credits} credits left.")

async def whoami(update: Update, context: ContextTypes.DEFAULT_TYPE):
    u = update.message.from_user
    uname = f"@{u.username}" if u.username else "N/A"
    is_admin = "YES ✅" if u.id == ADMIN_ID else "NO ❌"
    await update.message.reply_text(
        f"🔎 Your details:\n"
        f"🆔 ID: {u.id}\n"
        f"👤 Username: {uname}\n"
        f"👑 Admin: {is_admin}"
    )

async def addcredits_cmd(update: Update, context: ContextTypes.DEFAULT_TYPE):
    if not await admin_only(update): return
    if len(context.args) != 2:
        await update.message.reply_text("⚠️ Usage: /addcredits <user_id|@username|username> <amount>")
        return
    target, amount = context.args
    try:
        amount = int(amount)
        if amount <= 0: raise ValueError
    except:
        await update.message.reply_text("⚠️ Amount must be a positive number.")
        return

    uid, uname = resolve_target(target)
    if uid is None:
        await update.message.reply_text("❌ User not found in database. Ask them to /start first.")
        return

    add_credits(uid, amount)
    new_balance = get_credits(uid)
    await update.message.reply_text(f"✅ Added {amount} credits to {disp_user(uid, uname)}\n💳 New balance: {new_balance}")

async def removecredits_cmd(update: Update, context: ContextTypes.DEFAULT_TYPE):
    if not await admin_only(update): return
    if len(context.args) != 2:
        await update.message.reply_text("⚠️ Usage: /removecredits <user_id|@username|username> <amount>")
        return
    target, amount = context.args
    try:
        amount = int(amount)
        if amount <= 0: raise ValueError
    except:
        await update.message.reply_text("⚠️ Amount must be a positive number.")
        return

    uid, uname = resolve_target(target)
    if uid is None:
        await update.message.reply_text("❌ User not found in database. Ask them to /start first.")
        return

    remove_credits(uid, amount)
    new_balance = get_credits(uid)
    await update.message.reply_text(f"✅ Removed {amount} credits from {disp_user(uid, uname)}\n💳 New balance: {new_balance}")

async def setcredits_cmd(update: Update, context: ContextTypes.DEFAULT_TYPE):
    if not await admin_only(update): return
    if len(context.args) != 2:
        await update.message.reply_text("⚠️ Usage: /setcredits <user_id|@username|username> <amount>")
        return
    target, amount = context.args
    try:
        amount = int(amount)
        if amount < 0: raise ValueError
    except:
        await update.message.reply_text("⚠️ Amount must be a non-negative number.")
        return

    uid, uname = resolve_target(target)
    if uid is None:
        await update.message.reply_text("❌ User not found in database. Ask them to /start first.")
        return

    set_credits(uid, amount)
    await update.message.reply_text(f"✅ Set {disp_user(uid, uname)} credits to {amount}")

async def list_users(update: Update, context: ContextTypes.DEFAULT_TYPE):
    if not await admin_only(update): return
    cursor.execute("SELECT user_id, username, credits FROM users ORDER BY credits DESC, user_id ASC")
    rows = cursor.fetchall()
    if not rows:
        await update.message.reply_text("⚠️ No users registered yet.")
        return
    reply = "👥 Registered Users & Credits:\n\n"
    for uid, uname, credits in rows:
        uname_str = f"@{uname}" if uname else "N/A"
        reply += f"🆔 {uid} | {uname_str} → 💳 {credits}\n"
    await update.message.reply_text(reply)

# --- SEARCH HANDLER ---
async def handle_text(update: Update, context: ContextTypes.DEFAULT_TYPE):
    u = update.message.from_user
    ensure_user(u.id, u.username)

    credits = get_credits(u.id)
    if credits <= 0:
        await update.message.reply_text("❌ You have no credits left. Contact admin.")
        return

    user_input = update.message.text.strip()
    if not user_input.isdigit():
        await update.message.reply_text("❌ Please enter digits only.")
        return

    try:
        response = requests.get(API_URL, params={"num": user_input}, timeout=15)
        if response.status_code == 200:
            data = response.json()
            if isinstance(data, list) and len(data) > 0:
                record = data[0]
                reply = (
                    f"📱 Mobile: {record.get('mobile', 'N/A')}\n"
                    f"👤 Name: {record.get('name', 'N/A')}\n"
                    f"👨‍👩 Father: {record.get('father_name', 'N/A')}\n"
                    f"🏠 Address: {record.get('address', 'N/A')}\n"
                    f"📞 Alt Mobile: {record.get('alt_mobile', 'N/A')}\n"
                    f"🌐 Circle: {record.get('circle', 'N/A')}\n"
                    f"🆔 ID Number: {record.get('id_number', 'N/A')}\n"
                    f"📧 Email: {record.get('email', 'N/A')}"
                )
                deduct_credit(u.id)
                left = get_credits(u.id)
                await update.message.reply_text(reply + f"\n\n💳 Credits left: {left}")
            else:
                await update.message.reply_text("⚠️ No records found.")
        else:
            await update.message.reply_text("❌ API error — please try again later.")
    except Exception as e:
        await update.message.reply_text(f"⚠️ Exception: {e}")

# --- MAIN ---
def main():
    app = Application.builder().token(BOT_TOKEN).build()
    app.add_handler(CommandHandler("start", start))
    app.add_handler(CommandHandler("mycredits", mycredits))
    app.add_handler(CommandHandler("whoami", whoami))
    app.add_handler(CommandHandler("addcredits", addcredits_cmd))
    app.add_handler(CommandHandler("removecredits", removecredits_cmd))
    app.add_handler(CommandHandler("setcredits", setcredits_cmd))
    app.add_handler(CommandHandler("users", list_users))
    app.add_handler(MessageHandler(filters.TEXT & ~filters.COMMAND, handle_text))

    print("🤖 Bot running with credit system...")
    app.run_polling()

if __name__ == "__main__":
    main()
