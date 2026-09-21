import os
import sqlite3
import threading
import asyncio
from functools import wraps
from flask import Flask, jsonify, request, send_from_directory
from telegram import Update, InlineKeyboardButton, InlineKeyboardMarkup
from telegram.ext import Application, CommandHandler, CallbackQueryHandler, MessageHandler, ConversationHandler, ContextTypes, filters

BOT_TOKEN = os.getenv("BOT_TOKEN", "").strip()
ADMIN_ID = int(os.getenv("ADMIN_ID", "8042982338"))
ADMIN_KEY = os.getenv("ADMIN_KEY", "").strip()
DB_PATH = os.getenv("DB_PATH", "earning_hub.db")
PORT = int(os.getenv("PORT", "10000"))

if not BOT_TOKEN:
    raise RuntimeError("BOT_TOKEN environment variable is required")
if not ADMIN_KEY:
    raise RuntimeError("ADMIN_KEY environment variable is required")

app = Flask(__name__, static_folder="web", static_url_path="")
DB_LOCK = threading.Lock()
SUBMIT, WD_AMOUNT, WD_METHOD, WD_ACCOUNT = range(4)


def db():
    c = sqlite3.connect(DB_PATH, timeout=30, check_same_thread=False)
    c.row_factory = sqlite3.Row
    return c


def init_db():
    with DB_LOCK:
        c = db()
        c.executescript("""
        CREATE TABLE IF NOT EXISTS users(
            user_id INTEGER PRIMARY KEY,
            username TEXT DEFAULT '', first_name TEXT DEFAULT '',
            balance REAL DEFAULT 0, created_at TEXT DEFAULT CURRENT_TIMESTAMP
        );
        CREATE TABLE IF NOT EXISTS settings(key TEXT PRIMARY KEY, value TEXT NOT NULL);
        CREATE TABLE IF NOT EXISTS submissions(
            id INTEGER PRIMARY KEY AUTOINCREMENT, user_id INTEGER NOT NULL,
            identifier TEXT NOT NULL, task_code TEXT NOT NULL,
            reward REAL DEFAULT 0, status TEXT DEFAULT 'pending',
            created_at TEXT DEFAULT CURRENT_TIMESTAMP, reviewed_at TEXT
        );
        CREATE TABLE IF NOT EXISTS withdrawals(
            id INTEGER PRIMARY KEY AUTOINCREMENT, user_id INTEGER NOT NULL,
            amount REAL NOT NULL, method TEXT NOT NULL, account TEXT NOT NULL,
            status TEXT DEFAULT 'pending', created_at TEXT DEFAULT CURRENT_TIMESTAMP,
            reviewed_at TEXT
        );
        """)
        defaults = {"task_code": "SR-001", "reward": "15", "min_withdraw": "100"}
        for k, v in defaults.items():
            c.execute("INSERT OR IGNORE INTO settings(key,value) VALUES(?,?)", (k, v))
        c.commit(); c.close()


def setting(key):
    c = db(); r = c.execute("SELECT value FROM settings WHERE key=?", (key,)).fetchone(); c.close()
    return r["value"] if r else ""


def set_setting(key, value):
    with DB_LOCK:
        c = db(); c.execute("INSERT OR REPLACE INTO settings(key,value) VALUES(?,?)", (key, str(value))); c.commit(); c.close()


def ensure_user(tg_user):
    with DB_LOCK:
        c = db()
        c.execute("INSERT OR IGNORE INTO users(user_id,username,first_name) VALUES(?,?,?)", (tg_user.id, tg_user.username or "", tg_user.first_name or ""))
        c.execute("UPDATE users SET username=?, first_name=? WHERE user_id=?", (tg_user.username or "", tg_user.first_name or "", tg_user.id))
        c.commit(); c.close()


def balance(uid):
    c = db(); r = c.execute("SELECT balance FROM users WHERE user_id=?", (uid,)).fetchone(); c.close()
    return float(r["balance"]) if r else 0.0


def home(uid):
    rows = [
        [InlineKeyboardButton("📥 Submit Task", callback_data="submit")],
        [InlineKeyboardButton("💰 Balance", callback_data="balance"), InlineKeyboardButton("📊 My Tasks", callback_data="history")],
        [InlineKeyboardButton("💸 Withdraw", callback_data="withdraw"), InlineKeyboardButton("🧾 Withdrawals", callback_data="whistory")],
        [InlineKeyboardButton("📜 Rules", callback_data="rules"), InlineKeyboardButton("🆘 Support", callback_data="support")],
    ]
    if uid == ADMIN_ID:
        rows.append([InlineKeyboardButton("👑 Admin Panel", callback_data="admin")])
    return InlineKeyboardMarkup(rows)


def admin_kb():
    return InlineKeyboardMarkup([
        [InlineKeyboardButton("📥 Pending Tasks", callback_data="at"), InlineKeyboardButton("💸 Pending WD", callback_data="aw")],
        [InlineKeyboardButton("👥 Users", callback_data="au"), InlineKeyboardButton("📈 Statistics", callback_data="stats")],
        [InlineKeyboardButton("⚙️ Settings", callback_data="settings")],
        [InlineKeyboardButton("🏠 Main Menu", callback_data="home")],
    ])


def back_kb():
    return InlineKeyboardMarkup([[InlineKeyboardButton("🏠 Main Menu", callback_data="home")]])


async def start(update: Update, context: ContextTypes.DEFAULT_TYPE):
    u = update.effective_user; ensure_user(u)
    text = f"👋 <b>Welcome to SR EARNING HUB</b>\n\nHello, <b>{u.first_name or 'Member'}</b>!\n\n💎 Complete tasks\n💰 Earn rewards\n⚡ Manual admin review\n\n🟢 System: <b>ONLINE</b>\n\nChoose an option below."
    if update.callback_query:
        await update.callback_query.answer(); await update.callback_query.edit_message_text(text, parse_mode="HTML", reply_markup=home(u.id))
    else:
        await update.message.reply_text(text, parse_mode="HTML", reply_markup=home(u.id))


async def submit_start(update: Update, context: ContextTypes.DEFAULT_TYPE):
    q = update.callback_query; await q.answer()
    await q.message.reply_text(
        f"📥 <b>SUBMIT TASK</b>\n\n🔑 Today's Task Code: <code>{setting('task_code')}</code>\n\nSend your Gmail address / task identifier.\n\n⚠️ Never send a Gmail login password, OTP, recovery code, or other login credential.",
        parse_mode="HTML")
    return SUBMIT


async def submit_received(update: Update, context: ContextTypes.DEFAULT_TYPE):
    u = update.effective_user; ensure_user(u)
    identifier = update.message.text.strip()
    if len(identifier) > 200:
        await update.message.reply_text("❌ Input is too long. Please send only the identifier."); return SUBMIT
    with DB_LOCK:
        c = db(); cur = c.execute("INSERT INTO submissions(user_id,identifier,task_code) VALUES(?,?,?)", (u.id, identifier, setting("task_code"))); sid = cur.lastrowid; c.commit(); c.close()
    await update.message.reply_text(f"✅ <b>Task submitted</b>\n\nTask ID: <b>#{sid}</b>\nStatus: ⏳ Pending review\n\nAdmin will manually verify it.", parse_mode="HTML", reply_markup=home(u.id))
    try:
        await context.bot.send_message(ADMIN_ID, f"🔔 <b>NEW TASK #{sid}</b>\nUser: <code>{u.id}</code>\nIdentifier: <code>{identifier}</code>", parse_mode="HTML", reply_markup=InlineKeyboardMarkup([[InlineKeyboardButton("Review", callback_data="at")]]))
    except Exception:
        pass
    return ConversationHandler.END


async def balance_view(update: Update, context: ContextTypes.DEFAULT_TYPE):
    q = update.callback_query; await q.answer()
    await q.edit_message_text(f"💰 <b>BALANCE</b>\n\nAvailable: <b>৳{balance(q.from_user.id):.2f}</b>\nReward/task: <b>৳{float(setting('reward')):.2f}</b>\nMinimum withdrawal: <b>৳{float(setting('min_withdraw')):.2f}</b>", parse_mode="HTML", reply_markup=back_kb())


async def history_view(update: Update, context: ContextTypes.DEFAULT_TYPE):
    q = update.callback_query; await q.answer(); c = db(); rows = c.execute("SELECT id,identifier,reward,status FROM submissions WHERE user_id=? ORDER BY id DESC LIMIT 15", (q.from_user.id,)).fetchall(); c.close()
    text = "📊 <b>MY TASKS</b>\n\n" if rows else "📊 <b>MY TASKS</b>\n\nNo submissions yet."
    for r in rows:
        icon = "✅" if r["status"] == "approved" else "❌" if r["status"] == "rejected" else "⏳"
        text += f"{icon} #{r['id']} • {r['status'].upper()} • ৳{float(r['reward']):.2f}\n{r['identifier'][:45]}\n\n"
    await q.edit_message_text(text, parse_mode="HTML", reply_markup=back_kb())


async def rules_view(update: Update, context: ContextTypes.DEFAULT_TYPE):
    q = update.callback_query; await q.answer(); await q.edit_message_text("📜 <b>RULES</b>\n\n1. Complete the assigned task.\n2. Submit the correct identifier/proof.\n3. Admin manually verifies submissions.\n4. Approved tasks add the configured reward.\n5. Never send passwords, OTPs, or login credentials.", parse_mode="HTML", reply_markup=back_kb())


async def support_view(update: Update, context: ContextTypes.DEFAULT_TYPE):
    q = update.callback_query; await q.answer(); await q.edit_message_text("🆘 <b>SUPPORT</b>\n\nFor task or withdrawal issues, contact the administrator through Telegram.", parse_mode="HTML", reply_markup=back_kb())


async def withdraw_start(update: Update, context: ContextTypes.DEFAULT_TYPE):
    q = update.callback_query; await q.answer(); b = balance(q.from_user.id); minimum = float(setting("min_withdraw"))
    if b < minimum:
        await q.edit_message_text(f"❌ <b>Withdrawal unavailable</b>\n\nBalance: ৳{b:.2f}\nMinimum: ৳{minimum:.2f}", parse_mode="HTML", reply_markup=back_kb()); return ConversationHandler.END
    await q.message.reply_text(f"💸 <b>WITHDRAW</b>\n\nAvailable: ৳{b:.2f}\nMinimum: ৳{minimum:.2f}\n\nEnter amount:", parse_mode="HTML")
    return WD_AMOUNT


async def withdraw_amount(update: Update, context: ContextTypes.DEFAULT_TYPE):
    try: amount = float(update.message.text.strip())
    except ValueError:
        await update.message.reply_text("❌ Enter a valid amount."); return WD_AMOUNT
    if amount < float(setting("min_withdraw")):
        await update.message.reply_text(f"❌ Minimum withdrawal is ৳{float(setting('min_withdraw')):.2f}"); return WD_AMOUNT
    if amount > balance(update.effective_user.id):
        await update.message.reply_text("❌ Insufficient balance."); return WD_AMOUNT
    context.user_data["wd_amount"] = amount
    await update.message.reply_text("💳 <b>Select withdrawal method</b>", parse_mode="HTML", reply_markup=InlineKeyboardMarkup([[InlineKeyboardButton("📱 bKash", callback_data="wd_bkash")], [InlineKeyboardButton("₮ USDT BEP20", callback_data="wd_usdt")]]))
    return WD_METHOD


async def withdraw_method(update: Update, context: ContextTypes.DEFAULT_TYPE):
    q = update.callback_query; await q.answer(); context.user_data["wd_method"] = "bKash" if q.data == "wd_bkash" else "USDT BEP20"
    await q.message.reply_text(f"💳 Selected: <b>{context.user_data['wd_method']}</b>\n\nSend your payment number/address:", parse_mode="HTML")
    return WD_ACCOUNT


async def withdraw_account(update: Update, context: ContextTypes.DEFAULT_TYPE):
    uid = update.effective_user.id; amount = float(context.user_data.get("wd_amount", 0)); method = context.user_data.get("wd_method", ""); account = update.message.text.strip()
    if not account or len(account) > 150:
        await update.message.reply_text("❌ Invalid payment account."); return WD_ACCOUNT
    with DB_LOCK:
        c = db(); row = c.execute("SELECT balance FROM users WHERE user_id=?", (uid,)).fetchone()
        if not row or float(row["balance"]) < amount:
            c.close(); await update.message.reply_text("❌ Insufficient balance."); return ConversationHandler.END
        c.execute("UPDATE users SET balance=balance-? WHERE user_id=?", (amount, uid))
        cur = c.execute("INSERT INTO withdrawals(user_id,amount,method,account) VALUES(?,?,?,?)", (uid, amount, method, account)); wid = cur.lastrowid; c.commit(); c.close()
    context.user_data.clear()
    await update.message.reply_text(f"✅ <b>Withdrawal requested</b>\n\nID: #{wid}\nAmount: ৳{amount:.2f}\nMethod: {method}\nStatus: ⏳ Pending", parse_mode="HTML", reply_markup=home(uid))
    try:
        await context.bot.send_message(ADMIN_ID, f"💸 <b>NEW WITHDRAWAL #{wid}</b>\nUser: <code>{uid}</code>\nAmount: ৳{amount:.2f}\nMethod: {method}\nAccount: <code>{account}</code>", parse_mode="HTML", reply_markup=InlineKeyboardMarkup([[InlineKeyboardButton("Review withdrawals", callback_data="aw")]]))
    except Exception:
        pass
    return ConversationHandler.END


async def withdrawals_view(update: Update, context: ContextTypes.DEFAULT_TYPE):
    q = update.callback_query; await q.answer(); c = db(); rows = c.execute("SELECT id,amount,method,status FROM withdrawals WHERE user_id=? ORDER BY id DESC LIMIT 15", (q.from_user.id,)).fetchall(); c.close()
    text = "🧾 <b>WITHDRAWALS</b>\n\n" if rows else "🧾 <b>WITHDRAWALS</b>\n\nNo requests yet."
    for r in rows:
        icon = "✅" if r["status"] == "paid" else "❌" if r["status"] == "rejected" else "⏳"
        text += f"{icon} #{r['id']} • ৳{float(r['amount']):.2f} • {r['method']} • {r['status'].upper()}\n"
    await q.edit_message_text(text, parse_mode="HTML", reply_markup=back_kb())


def is_admin(update):
    return bool(update.effective_user and update.effective_user.id == ADMIN_ID)


async def admin_view(update: Update, context: ContextTypes.DEFAULT_TYPE):
    if not is_admin(update):
        if update.callback_query: await update.callback_query.answer("Not authorized", show_alert=True)
        return
    if update.callback_query: await update.callback_query.answer()
    text = f"👑 <b>ADMIN PANEL</b>\n\n🟢 Bot: ONLINE\n🔑 Task code: <code>{setting('task_code')}</code>\n💵 Reward: ৳{float(setting('reward')):.2f}\n💸 Minimum WD: ৳{float(setting('min_withdraw')):.2f}\n\nChoose an option:"
    if update.callback_query: await update.callback_query.edit_message_text(text, parse_mode="HTML", reply_markup=admin_kb())
    else: await update.message.reply_text(text, parse_mode="HTML", reply_markup=admin_kb())


async def pending_tasks(update: Update, context: ContextTypes.DEFAULT_TYPE):
    if not is_admin(update): return
    q = update.callback_query; await q.answer(); c = db(); rows = c.execute("SELECT id,user_id,identifier FROM submissions WHERE status='pending' ORDER BY id LIMIT 20").fetchall(); c.close()
    if not rows:
        await q.edit_message_text("📥 <b>PENDING TASKS</b>\n\nNothing pending.", parse_mode="HTML", reply_markup=admin_kb()); return
    await q.edit_message_text(f"📥 <b>PENDING TASKS</b>\n\n{len(rows)} pending submission(s).", parse_mode="HTML", reply_markup=admin_kb())
    for r in rows:
        await q.message.reply_text(f"📩 <b>Task #{r['id']}</b>\nUser: <code>{r['user_id']}</code>\nIdentifier: <code>{r['identifier']}</code>\nReward: ৳{float(setting('reward')):.2f}", parse_mode="HTML", reply_markup=InlineKeyboardMarkup([[InlineKeyboardButton("✅ Approve", callback_data=f"approve:{r['id']}"), InlineKeyboardButton("❌ Reject", callback_data=f"reject:{r['id']}")]]))


async def pending_withdrawals(update: Update, context: ContextTypes.DEFAULT_TYPE):
    if not is_admin(update): return
    q = update.callback_query; await q.answer(); c = db(); rows = c.execute("SELECT id,user_id,amount,method,account FROM withdrawals WHERE status='pending' ORDER BY id LIMIT 20").fetchall(); c.close()
    if not rows:
        await q.edit_message_text("💸 <b>PENDING WITHDRAWALS</b>\n\nNothing pending.", parse_mode="HTML", reply_markup=admin_kb()); return
    await q.edit_message_text(f"💸 <b>PENDING WITHDRAWALS</b>\n\n{len(rows)} pending request(s).", parse_mode="HTML", reply_markup=admin_kb())
    for r in rows:
        await q.message.reply_text(f"💸 <b>Withdrawal #{r['id']}</b>\nUser: <code>{r['user_id']}</code>\nAmount: ৳{float(r['amount']):.2f}\nMethod: {r['method']}\nAccount: <code>{r['account']}</code>", parse_mode="HTML", reply_markup=InlineKeyboardMarkup([[InlineKeyboardButton("✅ Mark Paid", callback_data=f"paid:{r['id']}"), InlineKeyboardButton("❌ Reject", callback_data=f"wdreject:{r['id']}")]]))


async def users_view(update: Update, context: ContextTypes.DEFAULT_TYPE):
    if not is_admin(update): return
    q = update.callback_query; await q.answer(); c = db(); total = c.execute("SELECT COUNT(*) n FROM users").fetchone()["n"]; rows = c.execute("SELECT user_id,username,balance FROM users ORDER BY balance DESC LIMIT 15").fetchall(); c.close()
    text = f"👥 <b>USERS</b>\n\nTotal: <b>{total}</b>\n\n" + "".join(f"<code>{r['user_id']}</code> @{r['username'] or 'N/A'} — ৳{float(r['balance']):.2f}\n" for r in rows)
    await q.edit_message_text(text, parse_mode="HTML", reply_markup=admin_kb())


async def stats_view(update: Update, context: ContextTypes.DEFAULT_TYPE):
    if not is_admin(update): return
    q = update.callback_query; await q.answer(); c = db()
    users = c.execute("SELECT COUNT(*) n FROM users").fetchone()["n"]
    pending = c.execute("SELECT COUNT(*) n FROM submissions WHERE status='pending'").fetchone()["n"]
    approved = c.execute("SELECT COUNT(*) n FROM submissions WHERE status='approved'").fetchone()["n"]
    rewards = c.execute("SELECT COALESCE(SUM(reward),0) n FROM submissions WHERE status='approved'").fetchone()["n"]
    paid = c.execute("SELECT COALESCE(SUM(amount),0) n FROM withdrawals WHERE status='paid'").fetchone()["n"]
    c.close()
    await q.edit_message_text(f"📈 <b>STATISTICS</b>\n\n👥 Users: {users}\n⏳ Pending tasks: {pending}\n✅ Approved tasks: {approved}\n💰 Rewards credited: ৳{float(rewards):.2f}\n💸 Withdrawals paid: ৳{float(paid):.2f}", parse_mode="HTML", reply_markup=admin_kb())


async def settings_view(update: Update, context: ContextTypes.DEFAULT_TYPE):
    if not is_admin(update): return
    q = update.callback_query; await q.answer(); await q.edit_message_text(f"⚙️ <b>SETTINGS</b>\n\n🔑 Code: <code>{setting('task_code')}</code>\n💵 Reward: ৳{float(setting('reward')):.2f}\n💸 Minimum WD: ৳{float(setting('min_withdraw')):.2f}\n\nCommands:\n<code>/setcode SR-002</code>\n<code>/setreward 15</code>\n<code>/setmin 100</code>", parse_mode="HTML", reply_markup=admin_kb())


async def admin_action(update: Update, context: ContextTypes.DEFAULT_TYPE):
    if not is_admin(update): return
    q = update.callback_query; await q.answer(); data = q.data
    with DB_LOCK:
        c = db()
        if data.startswith("approve:"):
            sid = int(data.split(":")[1]); r = c.execute("SELECT user_id,status FROM submissions WHERE id=?", (sid,)).fetchone()
            if r and r["status"] == "pending":
                reward = float(setting("reward")); c.execute("UPDATE submissions SET status='approved',reward=?,reviewed_at=CURRENT_TIMESTAMP WHERE id=?", (reward, sid)); c.execute("UPDATE users SET balance=balance+? WHERE user_id=?", (reward, r["user_id"])); c.commit(); msg = f"✅ Task #{sid} approved. +৳{reward:.2f}"
            else: msg = "Already reviewed."
        elif data.startswith("reject:"):
            sid = int(data.split(":")[1]); c.execute("UPDATE submissions SET status='rejected',reviewed_at=CURRENT_TIMESTAMP WHERE id=? AND status='pending'", (sid,)); c.commit(); msg = f"❌ Task #{sid} rejected."
        elif data.startswith("paid:"):
            wid = int(data.split(":")[1]); c.execute("UPDATE withdrawals SET status='paid',reviewed_at=CURRENT_TIMESTAMP WHERE id=? AND status='pending'", (wid,)); c.commit(); msg = f"✅ Withdrawal #{wid} marked paid."
        elif data.startswith("wdreject:"):
            wid = int(data.split(":")[1]); r = c.execute("SELECT user_id,amount,status FROM withdrawals WHERE id=?", (wid,)).fetchone()
            if r and r["status"] == "pending":
                c.execute("UPDATE withdrawals SET status='rejected',reviewed_at=CURRENT_TIMESTAMP WHERE id=?", (wid,)); c.execute("UPDATE users SET balance=balance+? WHERE user_id=?", (r["amount"], r["user_id"])); c.commit(); msg = f"❌ Withdrawal #{wid} rejected; ৳{float(r['amount']):.2f} returned."
            else: msg = "Already reviewed."
        else: msg = "Unknown action."
        c.close()
    await q.edit_message_text(msg, reply_markup=admin_kb())


async def setcode(update: Update, context: ContextTypes.DEFAULT_TYPE):
    if is_admin(update) and context.args:
        set_setting("task_code", " ".join(context.args)); await update.message.reply_text("✅ Task code updated.")

async def setreward(update: Update, context: ContextTypes.DEFAULT_TYPE):
    if is_admin(update) and context.args:
        try: set_setting("reward", float(context.args[0])); await update.message.reply_text("✅ Reward updated.")
        except ValueError: await update.message.reply_text("❌ Invalid number.")

async def setmin(update: Update, context: ContextTypes.DEFAULT_TYPE):
    if is_admin(update) and context.args:
        try: set_setting("min_withdraw", float(context.args[0])); await update.message.reply_text("✅ Minimum withdrawal updated.")
        except ValueError: await update.message.reply_text("❌ Invalid number.")

async def cancel(update: Update, context: ContextTypes.DEFAULT_TYPE):
    context.user_data.clear(); await update.message.reply_text("❌ Cancelled.", reply_markup=home(update.effective_user.id)); return ConversationHandler.END


async def callback_router(update: Update, context: ContextTypes.DEFAULT_TYPE):
    d = update.callback_query.data
    if d == "home": await start(update, context)
    elif d == "balance": await balance_view(update, context)
    elif d == "history": await history_view(update, context)
    elif d == "rules": await rules_view(update, context)
    elif d == "support": await support_view(update, context)
    elif d == "whistory": await withdrawals_view(update, context)
    elif d == "admin": await admin_view(update, context)
    elif d == "at": await pending_tasks(update, context)
    elif d == "aw": await pending_withdrawals(update, context)
    elif d == "au": await users_view(update, context)
    elif d == "stats": await stats_view(update, context)
    elif d == "settings": await settings_view(update, context)
    elif d.startswith(("approve:", "reject:", "paid:", "wdreject:")): await admin_action(update, context)


# ---------- Web / admin API ----------
def require_admin(fn):
    @wraps(fn)
    def wrapper(*args, **kwargs):
        key = request.headers.get("X-Admin-Key") or request.args.get("key") or request.form.get("key")
        if key != ADMIN_KEY:
            return jsonify({"ok": False, "error": "Unauthorized"}), 401
        return fn(*args, **kwargs)
    return wrapper


@app.get("/")
def index():
    return send_from_directory("web", "index.html")

@app.get("/admin")
def admin_page():
    return send_from_directory("web", "admin.html")

@app.get("/api/config")
def api_config():
    return jsonify({"ok": True, "reward": float(setting("reward")), "min_withdraw": float(setting("min_withdraw")), "task_code": setting("task_code")})

@app.get("/api/admin/overview")
@require_admin
def admin_overview():
    c = db(); users = c.execute("SELECT COUNT(*) n FROM users").fetchone()["n"]; tasks = c.execute("SELECT COUNT(*) n FROM submissions WHERE status='pending'").fetchone()["n"]; wds = c.execute("SELECT COUNT(*) n FROM withdrawals WHERE status='pending'").fetchone()["n"]; c.close()
    return jsonify({"ok": True, "users": users, "pending_tasks": tasks, "pending_withdrawals": wds, "reward": float(setting("reward")), "min_withdraw": float(setting("min_withdraw")), "task_code": setting("task_code")})

@app.get("/api/admin/tasks")
@require_admin
def admin_tasks():
    c = db(); rows = c.execute("SELECT id,user_id,identifier,task_code,reward,status,created_at FROM submissions ORDER BY id DESC LIMIT 100").fetchall(); c.close(); return jsonify({"ok": True, "items": [dict(r) for r in rows]})

@app.get("/api/admin/withdrawals")
@require_admin
def admin_withdrawals():
    c = db(); rows = c.execute("SELECT id,user_id,amount,method,account,status,created_at FROM withdrawals ORDER BY id DESC LIMIT 100").fetchall(); c.close(); return jsonify({"ok": True, "items": [dict(r) for r in rows]})

@app.post("/api/admin/settings")
@require_admin
def admin_settings():
    data = request.get_json(silent=True) or {}
    if "task_code" in data: set_setting("task_code", str(data["task_code"]).strip()[:100])
    if "reward" in data: set_setting("reward", float(data["reward"]))
    if "min_withdraw" in data: set_setting("min_withdraw", float(data["min_withdraw"]))
    return jsonify({"ok": True})

@app.post("/api/admin/task/<int:sid>/<action>")
@require_admin
def admin_task_action(sid, action):
    with DB_LOCK:
        c = db(); r = c.execute("SELECT user_id,status FROM submissions WHERE id=?", (sid,)).fetchone()
        if not r or r["status"] != "pending": c.close(); return jsonify({"ok": False, "error": "Already reviewed or missing"}), 400
        if action == "approve":
            reward = float(setting("reward")); c.execute("UPDATE submissions SET status='approved',reward=?,reviewed_at=CURRENT_TIMESTAMP WHERE id=?", (reward, sid)); c.execute("UPDATE users SET balance=balance+? WHERE user_id=?", (reward, r["user_id"]))
        elif action == "reject":
            c.execute("UPDATE submissions SET status='rejected',reviewed_at=CURRENT_TIMESTAMP WHERE id=?", (sid,))
        else: c.close(); return jsonify({"ok": False, "error": "Invalid action"}), 400
        c.commit(); c.close()
    return jsonify({"ok": True})

@app.post("/api/admin/withdrawal/<int:wid>/<action>")
@require_admin
def admin_withdrawal_action(wid, action):
    with DB_LOCK:
        c = db(); r = c.execute("SELECT user_id,amount,status FROM withdrawals WHERE id=?", (wid,)).fetchone()
        if not r or r["status"] != "pending": c.close(); return jsonify({"ok": False, "error": "Already reviewed or missing"}), 400
        if action == "paid":
            c.execute("UPDATE withdrawals SET status='paid',reviewed_at=CURRENT_TIMESTAMP WHERE id=?", (wid,))
        elif action == "reject":
            c.execute("UPDATE withdrawals SET status='rejected',reviewed_at=CURRENT_TIMESTAMP WHERE id=?", (wid,)); c.execute("UPDATE users SET balance=balance+? WHERE user_id=?", (r["amount"], r["user_id"]))
        else: c.close(); return jsonify({"ok": False, "error": "Invalid action"}), 400
        c.commit(); c.close()
    return jsonify({"ok": True})


def run_web():
    # The web server lives in a daemon thread; Telegram polling owns the main asyncio loop.
    app.run(host="0.0.0.0", port=PORT, debug=False, use_reloader=False, threaded=True)


def build_bot():
    application = Application.builder().token(BOT_TOKEN).build()
    submit_conv = ConversationHandler(
        entry_points=[CallbackQueryHandler(submit_start, pattern=r"^submit$")],
        states={SUBMIT: [MessageHandler(filters.TEXT & ~filters.COMMAND, submit_received)]},
        fallbacks=[CommandHandler("cancel", cancel)],
        allow_reentry=True,
    )
    withdraw_conv = ConversationHandler(
        entry_points=[CallbackQueryHandler(withdraw_start, pattern=r"^withdraw$")],
        states={
            WD_AMOUNT: [MessageHandler(filters.TEXT & ~filters.COMMAND, withdraw_amount)],
            WD_METHOD: [CallbackQueryHandler(withdraw_method, pattern=r"^wd_(bkash|usdt)$")],
            WD_ACCOUNT: [MessageHandler(filters.TEXT & ~filters.COMMAND, withdraw_account)],
        },
        fallbacks=[CommandHandler("cancel", cancel)],
        allow_reentry=True,
    )
    application.add_handler(CommandHandler("start", start))
    application.add_handler(CommandHandler("admin", admin_view))
    application.add_handler(CommandHandler("setcode", setcode))
    application.add_handler(CommandHandler("setreward", setreward))
    application.add_handler(CommandHandler("setmin", setmin))
    application.add_handler(submit_conv)
    application.add_handler(withdraw_conv)
    application.add_handler(CallbackQueryHandler(callback_router))
    return application


def main():
    init_db()
    threading.Thread(target=run_web, daemon=True, name="web-server").start()
    application = build_bot()
    print(f"SR EARNING HUB V4 online | web port={PORT}")
    # Python 3.13+ may not create a default event loop automatically.
    # Create and register one before python-telegram-bot starts polling.
    loop = asyncio.new_event_loop()
    asyncio.set_event_loop(loop)
    application.run_polling(drop_pending_updates=True, close_loop=True)


if __name__ == "__main__":
    main()
