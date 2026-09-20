import os
import sqlite3
import threading
from flask import Flask, request, jsonify, send_from_directory
from telegram import Update, InlineKeyboardButton, InlineKeyboardMarkup, WebAppInfo, MenuButtonWebApp
from telegram.ext import Application, CommandHandler, CallbackQueryHandler, ContextTypes

BOT_TOKEN = os.getenv("BOT_TOKEN", "").strip()
ADMIN_ID = int(os.getenv("ADMIN_ID", "8042982338"))
# Render provides this automatically after deployment.
PUBLIC_URL = os.getenv("WEBAPP_URL", "").strip().rstrip("/")
if not PUBLIC_URL:
    PUBLIC_URL = os.getenv("RENDER_EXTERNAL_URL", "").strip().rstrip("/")
DB = os.getenv("DB_PATH", "earning_hub.db")

if not BOT_TOKEN:
    raise RuntimeError("BOT_TOKEN environment variable is required.")
if not PUBLIC_URL.startswith("https://"):
    raise RuntimeError("WEBAPP_URL/RENDER_EXTERNAL_URL must be an HTTPS URL.")

app = Flask(__name__, static_folder="web", static_url_path="")

def db():
    c = sqlite3.connect(DB, timeout=30)
    c.row_factory = sqlite3.Row
    return c

def init_db():
    c = db()
    c.executescript("""
    CREATE TABLE IF NOT EXISTS users(
      tg_id INTEGER PRIMARY KEY,
      username TEXT DEFAULT '',
      balance REAL DEFAULT 0,
      completed INTEGER DEFAULT 0,
      created_at TEXT DEFAULT CURRENT_TIMESTAMP
    );
    CREATE TABLE IF NOT EXISTS settings(
      key TEXT PRIMARY KEY,
      value TEXT NOT NULL
    );
    CREATE TABLE IF NOT EXISTS submissions(
      id INTEGER PRIMARY KEY AUTOINCREMENT,
      tg_id INTEGER NOT NULL,
      identifier TEXT NOT NULL,
      task_code TEXT NOT NULL,
      status TEXT DEFAULT 'pending',
      reward REAL DEFAULT 0,
      created_at TEXT DEFAULT CURRENT_TIMESTAMP
    );
    CREATE TABLE IF NOT EXISTS withdrawals(
      id INTEGER PRIMARY KEY AUTOINCREMENT,
      tg_id INTEGER NOT NULL,
      amount REAL NOT NULL,
      method TEXT NOT NULL,
      account TEXT NOT NULL,
      status TEXT DEFAULT 'pending',
      created_at TEXT DEFAULT CURRENT_TIMESTAMP
    );
    """)
    defaults = {"task_code":"SR-002", "reward":"15", "min_withdraw":"100"}
    for k, v in defaults.items():
        c.execute("INSERT OR IGNORE INTO settings(key,value) VALUES(?,?)", (k,v))
    c.commit()
    c.close()

def setting(key):
    c=db()
    r=c.execute("SELECT value FROM settings WHERE key=?", (key,)).fetchone()
    c.close()
    return r["value"] if r else ""

def ensure_user(tg_id, username=""):
    c=db()
    c.execute("INSERT OR IGNORE INTO users(tg_id,username) VALUES(?,?)", (tg_id, username or ""))
    c.execute("UPDATE users SET username=? WHERE tg_id=?", (username or "", tg_id))
    c.commit()
    c.close()

def is_admin(tg_id):
    return tg_id == ADMIN_ID

async def start(update: Update, context: ContextTypes.DEFAULT_TYPE):
    u = update.effective_user
    ensure_user(u.id, u.username)
    buttons = [[InlineKeyboardButton("🚀 OPEN EARNING HUB", web_app=WebAppInfo(url=PUBLIC_URL))]]
    if is_admin(u.id):
        buttons.append([InlineKeyboardButton("🛠️ Admin Help", callback_data="admin")])
    await update.message.reply_text(
        "💎 SR EARNING HUB\n\nWelcome! Complete verified tasks and manage your balance.",
        reply_markup=InlineKeyboardMarkup(buttons)
    )

async def admin_help(update: Update, context: ContextTypes.DEFAULT_TYPE):
    q=update.callback_query
    await q.answer()
    if is_admin(q.from_user.id):
        await q.message.reply_text(
            "🛠️ ADMIN COMMANDS\n\n"
            "/setcode SR-003\n"
            "/setreward 15\n"
            "/setmin 100\n"
            "/pending"
        )

async def setcode(update, context):
    if not is_admin(update.effective_user.id): return
    if not context.args:
        return await update.message.reply_text("Usage: /setcode SR-003")
    value=" ".join(context.args)
    c=db(); c.execute("UPDATE settings SET value=? WHERE key='task_code'",(value,)); c.commit(); c.close()
    await update.message.reply_text("✅ Today's task code updated.")

async def setreward(update, context):
    if not is_admin(update.effective_user.id): return
    if not context.args: return await update.message.reply_text("Usage: /setreward 15")
    try: float(context.args[0])
    except: return await update.message.reply_text("Reward must be a number.")
    c=db(); c.execute("UPDATE settings SET value=? WHERE key='reward'",(context.args[0],)); c.commit(); c.close()
    await update.message.reply_text("✅ Reward updated.")

async def setmin(update, context):
    if not is_admin(update.effective_user.id): return
    if not context.args: return await update.message.reply_text("Usage: /setmin 100")
    try: float(context.args[0])
    except: return await update.message.reply_text("Minimum must be a number.")
    c=db(); c.execute("UPDATE settings SET value=? WHERE key='min_withdraw'",(context.args[0],)); c.commit(); c.close()
    await update.message.reply_text("✅ Minimum withdrawal updated.")

async def pending(update, context):
    if not is_admin(update.effective_user.id): return
    c=db()
    rows=c.execute("SELECT * FROM submissions WHERE status='pending' ORDER BY id DESC LIMIT 30").fetchall()
    c.close()
    if not rows:
        return await update.message.reply_text("No pending submissions.")
    for r in rows:
        kb=InlineKeyboardMarkup([[
            InlineKeyboardButton("✅ Approve",callback_data=f"approve:{r['id']}"),
            InlineKeyboardButton("❌ Reject",callback_data=f"reject:{r['id']}")
        ]])
        await update.message.reply_text(
            f"#{r['id']} • User {r['tg_id']}\n"
            f"Identifier: {r['identifier']}\n"
            f"Code: {r['task_code']}",
            reply_markup=kb
        )

async def review(update, context):
    q=update.callback_query
    await q.answer()
    if not is_admin(q.from_user.id): return
    action,sid=q.data.split(":")
    sid=int(sid)
    c=db()
    r=c.execute("SELECT * FROM submissions WHERE id=? AND status='pending'",(sid,)).fetchone()
    if not r:
        c.close()
        return await q.message.reply_text("Already reviewed.")
    if action=="approve":
        reward=float(setting("reward"))
        c.execute("UPDATE submissions SET status='approved',reward=? WHERE id=?",(reward,sid))
        c.execute("UPDATE users SET balance=balance+?,completed=completed+1 WHERE tg_id=?",(reward,r["tg_id"]))
        msg=f"✅ Submission #{sid} approved. ৳{reward:.2f} added."
    else:
        c.execute("UPDATE submissions SET status='rejected' WHERE id=?",(sid,))
        msg=f"❌ Submission #{sid} rejected."
    c.commit(); c.close()
    await q.message.reply_text(msg)

@app.get("/")
def home():
    return send_from_directory("web","index.html")

@app.get("/health")
def health():
    return jsonify(ok=True)

@app.get("/api/config")
def api_config():
    return jsonify(
        task_code=setting("task_code"),
        reward=float(setting("reward")),
        min_withdraw=float(setting("min_withdraw"))
    )

@app.post("/api/user")
def api_user():
    data=request.get_json(force=True) or {}
    try: tg_id=int(data.get("tg_id",0))
    except: tg_id=0
    username=str(data.get("username",""))
    if not tg_id: return jsonify(error="Telegram user required"),400
    ensure_user(tg_id,username)
    c=db(); r=c.execute("SELECT * FROM users WHERE tg_id=?",(tg_id,)).fetchone(); c.close()
    return jsonify(tg_id=r["tg_id"],username=r["username"],balance=r["balance"],completed=r["completed"])

@app.post("/api/submit")
def api_submit():
    data=request.get_json(force=True) or {}
    try: tg_id=int(data.get("tg_id",0))
    except: tg_id=0
    identifier=str(data.get("identifier","")).strip()
    code=str(data.get("task_code","")).strip()
    if not tg_id or not identifier or not code:
        return jsonify(error="Missing fields"),400
    if code != setting("task_code"):
        return jsonify(error="Invalid task code"),400
    ensure_user(tg_id)
    c=db()
    c.execute("INSERT INTO submissions(tg_id,identifier,task_code) VALUES(?,?,?)",(tg_id,identifier,code))
    c.commit(); c.close()
    return jsonify(ok=True,message="Submitted for admin review.")

@app.get("/api/submissions")
def api_submissions():
    try: tg_id=int(request.args.get("tg_id","0"))
    except: tg_id=0
    c=db()
    rows=c.execute("SELECT id,identifier,status,reward,created_at FROM submissions WHERE tg_id=? ORDER BY id DESC LIMIT 50",(tg_id,)).fetchall()
    c.close()
    return jsonify(items=[dict(r) for r in rows])

@app.post("/api/withdraw")
def api_withdraw():
    data=request.get_json(force=True) or {}
    try:
        tg_id=int(data.get("tg_id",0)); amount=float(data.get("amount",0))
    except:
        return jsonify(error="Invalid amount"),400
    method=str(data.get("method","")).strip()
    account=str(data.get("account","")).strip()
    minimum=float(setting("min_withdraw"))
    if amount < minimum: return jsonify(error=f"Minimum withdrawal is ৳{minimum:.0f}"),400
    if method not in ("bKash","USDT BEP20") or not account:
        return jsonify(error="Invalid withdrawal details"),400
    c=db()
    r=c.execute("SELECT balance FROM users WHERE tg_id=?",(tg_id,)).fetchone()
    if not r or r["balance"] < amount:
        c.close()
        return jsonify(error="Insufficient balance"),400
    c.execute("UPDATE users SET balance=balance-? WHERE tg_id=?",(amount,tg_id))
    c.execute("INSERT INTO withdrawals(tg_id,amount,method,account) VALUES(?,?,?,?)",(tg_id,amount,method,account))
    c.commit(); c.close()
    return jsonify(ok=True,message="Withdrawal request sent for manual admin payment.")

@app.get("/api/withdrawals")
def api_withdrawals():
    try: tg_id=int(request.args.get("tg_id","0"))
    except: tg_id=0
    c=db()
    rows=c.execute("SELECT id,amount,method,status,created_at FROM withdrawals WHERE tg_id=? ORDER BY id DESC LIMIT 50",(tg_id,)).fetchall()
    c.close()
    return jsonify(items=[dict(r) for r in rows])

def run_web():
    port=int(os.getenv("PORT","8080"))
    app.run(host="0.0.0.0",port=port,debug=False,use_reloader=False)

async def post_init(application):
    # Makes the Mini App available from the bot's menu automatically.
    await application.bot.set_chat_menu_button(
        menu_button=MenuButtonWebApp(text="💎 Earning Hub", web_app=WebAppInfo(url=PUBLIC_URL))
    )

def main():
    init_db()
    threading.Thread(target=run_web,daemon=True).start()
    application=Application.builder().token(BOT_TOKEN).post_init(post_init).build()
    application.add_handler(CommandHandler("start",start))
    application.add_handler(CommandHandler("setcode",setcode))
    application.add_handler(CommandHandler("setreward",setreward))
    application.add_handler(CommandHandler("setmin",setmin))
    application.add_handler(CommandHandler("pending",pending))
    application.add_handler(CallbackQueryHandler(review,pattern=r"^(approve|reject):\d+$"))
    application.add_handler(CallbackQueryHandler(admin_help,pattern=r"^admin$"))
    application.run_polling(drop_pending_updates=True)

if __name__=="__main__":
    main()
