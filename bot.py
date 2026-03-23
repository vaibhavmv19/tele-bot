
import asyncio
import sqlite3
import time
import random
from aiogram import Bot, Dispatcher, types, F
from aiogram.types import InlineKeyboardMarkup, InlineKeyboardButton
from aiogram.filters import CommandStart, Command

BOT_TOKEN = "8744693542:AAHB_WPcHjbUcyfwa829VleyP7RP40O91tQ"
ADMIN_ID = 7998012491

from aiogram.client.default import DefaultBotProperties

bot = Bot(
    token=BOT_TOKEN,
    default=DefaultBotProperties(parse_mode="HTML")
)
dp = Dispatcher()

# ---------------- DATABASE ---------------- #
conn = sqlite3.connect("bot.db", check_same_thread=False)
cur = conn.cursor()

cur.execute("""CREATE TABLE IF NOT EXISTS users (
    user_id INTEGER PRIMARY KEY,
    points INTEGER DEFAULT 0,
    referred_by INTEGER,
    joined INTEGER DEFAULT 0,
    referred_counted INTEGER DEFAULT 0,
    last_withdraw INTEGER DEFAULT 0
)""")

cur.execute("""CREATE TABLE IF NOT EXISTS channels (
    channel_id TEXT,
    channel_link TEXT
)""")

cur.execute("""CREATE TABLE IF NOT EXISTS settings (
    key TEXT PRIMARY KEY,
    value TEXT
)""")

cur.execute("""CREATE TABLE IF NOT EXISTS files (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    file_id TEXT
)""")

cur.execute("INSERT OR IGNORE INTO settings VALUES ('cost','')")
conn.commit()

# ---------------- HELPERS ---------------- #

def get_cost():
    cur.execute("SELECT value FROM settings WHERE key='cost'")
    return int(cur.fetchone()[0])

def get_points(uid):
    cur.execute("SELECT points FROM users WHERE user_id=?", (uid,))
    r = cur.fetchone()
    return r[0] if r else 0

async def safe_send(uid, text):
    try:
        await bot.send_message(uid, text)
    except:
        pass

async def check_access(uid):
    cur.execute("SELECT joined FROM users WHERE user_id=?", (uid,))
    r = cur.fetchone()
    return r and r[0] == 1

async def is_joined(uid, ch):
    try:
        m = await bot.get_chat_member(ch, uid)
        return m.status in ["member","administrator","creator"]
    except:
        return False

async def check_all(uid):
    cur.execute("SELECT channel_id FROM channels")
    for c in cur.fetchall():
        if not await is_joined(uid, c[0]):
            return False
    return True

async def edit(call, text, kb=None):
    try:
        await call.message.edit_text(text, reply_markup=kb)
    except:
        await call.message.answer(text, reply_markup=kb)

# ---------------- UI ---------------- #

HOME = """
🎬 <b>NETFLIX HUB</b>

Earn points → Redeem files

⚡ Fast • Secure • Premium
"""

def menu():
    return InlineKeyboardMarkup(inline_keyboard=[
        [InlineKeyboardButton(text="💰 Balance", callback_data="bal"),
         InlineKeyboardButton(text="👥 Refer", callback_data="ref")],
        [InlineKeyboardButton(text="🎬 Redeem", callback_data="wd")],
        [InlineKeyboardButton(text="📖 Guide", url="https://t.me/nfbotz/405")],
        [InlineKeyboardButton(text="🔥 Proof", url="https://t.me/netflixgiveawayx")]
    ])

def back():
    return InlineKeyboardMarkup(inline_keyboard=[
        [InlineKeyboardButton(text="⬅ Back", callback_data="home")]
    ])

def join_kb():
    cur.execute("SELECT channel_link FROM channels")
    kb = [[InlineKeyboardButton(text="🔗 Join", url=c[0])] for c in cur.fetchall()]
    kb.append([InlineKeyboardButton(text="✅ Done", callback_data="verify")])
    return InlineKeyboardMarkup(inline_keyboard=kb)

# ---------------- START ---------------- #

@dp.message(CommandStart())
async def start(m: types.Message, command: CommandStart):
    uid = m.from_user.id
    ref = command.args
    ref_id = int(ref) if ref and ref.isdigit() else None

    cur.execute("SELECT user_id FROM users WHERE user_id=?", (uid,))
    if not cur.fetchone():
        cur.execute("INSERT INTO users (user_id,referred_by) VALUES (?,?)", (uid, ref_id))
        conn.commit()

        if ref_id and ref_id != uid:
            name = f"@{m.from_user.username}" if m.from_user.username else m.from_user.first_name
            await safe_send(ref_id, f"👤 {name} joined\n⏳ Not verified")

    if not await check_access(uid):
        await m.answer("🔒 Join channels", reply_markup=join_kb())
        return

    await m.answer(HOME, reply_markup=menu())

# ---------------- VERIFY ---------------- #

@dp.callback_query(lambda c: c.data == "verify")
async def verify(c: types.CallbackQuery):
    await c.answer()

    uid = c.from_user.id

    if not await check_all(uid):
        await c.answer("Join all first", True)
        return

    cur.execute("SELECT referred_by,referred_counted FROM users WHERE user_id=?", (uid,))
    ref_id, counted = cur.fetchone()

    cur.execute("UPDATE users SET joined=1 WHERE user_id=?", (uid,))

    if ref_id and ref_id != uid and counted == 0:
        cur.execute("SELECT joined FROM users WHERE user_id=?", (ref_id,))
        if cur.fetchone()[0] == 1:
            cur.execute("UPDATE users SET points=points+1 WHERE user_id=?", (ref_id,))
            cur.execute("UPDATE users SET referred_counted=1 WHERE user_id=?", (uid,))

            name = f"@{c.from_user.username}" if c.from_user.username else c.from_user.first_name
            await safe_send(ref_id, f"🎉 {name} verified +1")

    conn.commit()
    await edit(c, "✅ Verified!", menu())

# ---------------- NAV ---------------- #

@dp.callback_query(lambda c: c.data == "home")
async def home(c):
    await c.answer()
    await edit(c, HOME, menu())

@dp.callback_query(lambda c: c.data == "bal")
async def bal(c):
    await c.answer()
    if not await check_access(c.from_user.id):
        await edit(c, "🔒 Join first", join_kb())
        return
    await edit(c, f"💰 Points: {get_points(c.from_user.id)}", menu())

@dp.callback_query(lambda c: c.data == "ref")
async def ref(c):
    await c.answer()
    bot_info = await bot.get_me()
    link = f"https://t.me/{bot_info.username}?start={c.from_user.id}"

    cur.execute("SELECT COUNT(*) FROM users WHERE referred_by=?", (c.from_user.id,))
    n = cur.fetchone()[0]

    await edit(c, f"👥 Invite:\n<code>{link}</code>\nUsers: {n}", menu())

# ---------------- WITHDRAW ---------------- #

@dp.callback_query(lambda c: c.data == "wd")
async def wd(c):
    await c.answer()

    cost = get_cost()

    kb = InlineKeyboardMarkup(inline_keyboard=[
        [InlineKeyboardButton(text=f"🎬 Netflix [{cost}]", callback_data="nf")],
        [InlineKeyboardButton(text="⬅ Back", callback_data="home")]
    ])

    await edit(c, f"""
🎬 <b>Redeem</b>

Netflix File = <b>{cost}</b> Points
""", kb)
    await edit(c, "🎬 Redeem", kb)

@dp.callback_query(lambda c: c.data == "nf")
async def nf(c):
    await c.answer("⏳ Processing...")

    uid = c.from_user.id
    pts = get_points(uid)
    cost = get_cost()

    cur.execute("SELECT last_withdraw FROM users WHERE user_id=?", (uid,))
    row = cur.fetchone()
    last = row[0] if row else 0

    # ❌ Not enough points
    if pts < cost:
        await edit(c, f"❌ You need {cost} points", menu())
        return

    # ⏳ Cooldown
    if time.time() - last < 60:
        await edit(c, "⏳ Wait 1 minute", menu())
        return

    # 📂 Get files
    cur.execute("SELECT file_id FROM files")
    files = cur.fetchall()

    if not files:
        await edit(c, "⚠️ No files uploaded", menu())
        return

    file_id = random.choice(files)[0]

    # 📤 Send file
    await bot.send_document(uid, file_id)

    # 💰 Deduct points
    cur.execute(
        "UPDATE users SET points = points - ?, last_withdraw = ? WHERE user_id=?",
        (cost, int(time.time()), uid)
    )
    conn.commit()

    await edit(c, "✅ File sent successfully!", menu())

# ---------------- ADMIN ---------------- #

@dp.message(Command("addchannel"))
async def addc(m):
    if m.from_user.id != ADMIN_ID: return
    _, cid, link = m.text.split()
    cur.execute("INSERT INTO channels VALUES (?,?)",(cid,link))
    conn.commit()
    await m.answer("Added")

@dp.message(Command("delchannel"))
async def delc(m):
    if m.from_user.id != ADMIN_ID: return
    cur.execute("DELETE FROM channels WHERE channel_id=?", (m.text.split()[1],))
    conn.commit()
    await m.answer("Deleted")

@dp.message(Command("setcost"))
async def setcost(m):
    if m.from_user.id != ADMIN_ID:
        return

    try:
        value = int(m.text.split()[1])
    except:
        await m.answer("Usage: /setcost 1")
        return

    cur.execute("UPDATE settings SET value=? WHERE key='cost'", (value,))
    conn.commit()

    await m.answer(f"✅ Cost set to {value}")

@dp.message(F.document)
async def upload(m):
    if m.from_user.id != ADMIN_ID: return
    cur.execute("INSERT INTO files (file_id) VALUES (?)", (m.document.file_id,))
    conn.commit()
    await m.answer("File added")

@dp.message(Command("stats"))
async def stats(m):
    if m.from_user.id != ADMIN_ID: return
    cur.execute("SELECT COUNT(*) FROM users")
    u = cur.fetchone()[0]
    cur.execute("SELECT COUNT(*) FROM users WHERE joined=1")
    v = cur.fetchone()[0]
    cur.execute("SELECT COUNT(*) FROM files")
    f = cur.fetchone()[0]

    await m.answer(f"Users:{u}\nVerified:{v}\nFiles:{f}")

@dp.message(Command("msend"))
async def msend(m):
    if m.from_user.id != ADMIN_ID: return
    txt = m.text.replace("/msend ","")
    cur.execute("SELECT user_id FROM users WHERE joined=1")
    for u in cur.fetchall():
        await safe_send(u[0], txt)
    await m.answer("Done")

# ---------------- RUN ---------------- #

async def main():
    print("🔥 GOD TIER BOT RUNNING")
    await dp.start_polling(bot)

if __name__ == "__main__":
    asyncio.run(main())
