import asyncio
import sqlite3
import time
import random
from aiogram import Bot, Dispatcher, types, F
from aiogram.types import InlineKeyboardMarkup, InlineKeyboardButton
from aiogram.filters import CommandStart, Command
from aiogram.client.default import DefaultBotProperties

BOT_TOKEN = "8744693542:AAHB_WPcHjbUcyfwa829VleyP7RP40O91tQ"
ADMIN_ID = 7998012491

bot = Bot(token=BOT_TOKEN, default=DefaultBotProperties(parse_mode="HTML"))
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
    last_withdraw INTEGER DEFAULT 0,
    last_earn INTEGER DEFAULT 0,
    device_hash TEXT
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

cur.execute("INSERT OR IGNORE INTO settings VALUES ('cost','1')")
conn.commit()

# ---------------- HELPERS ---------------- #

def get_cost():
    cur.execute("SELECT value FROM settings WHERE key='cost'")
    return int(cur.fetchone()[0])

def get_points(uid):
    cur.execute("SELECT points FROM users WHERE user_id=?", (uid,))
    r = cur.fetchone()
    return r[0] if r else 0

def get_device(user):
    return f"{user.id}_{user.username}_{user.first_name}"

async def safe_send(uid, text):
    try:
        await bot.send_message(uid, text)
    except:
        pass

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

# ---------------- UI ---------------- #

HOME = """
🎬 <b>NETFLIX HUB</b>

Earn → Refer → Redeem
"""

def menu():
    return InlineKeyboardMarkup(inline_keyboard=[
        [InlineKeyboardButton(text="💰 Balance", callback_data="bal"),
         InlineKeyboardButton(text="👥 Refer", callback_data="ref")],
        [InlineKeyboardButton(text="🎬 Redeem", callback_data="wd")],
        [InlineKeyboardButton(text="🔥 Proof", url="https://t.me/zovloo")]
    ])

def join_kb():
    cur.execute("SELECT channel_link FROM channels")
    kb = [[InlineKeyboardButton(text="🔗 Join Channel", url=c[0])] for c in cur.fetchall()]
    kb.append([InlineKeyboardButton(text="✅ I Joined", callback_data="verify")])
    return InlineKeyboardMarkup(inline_keyboard=kb)

# ---------------- START ---------------- #

@dp.message(CommandStart())
async def start(m: types.Message, command: CommandStart):
    uid = m.from_user.id
    ref = command.args
    ref_id = int(ref) if ref and ref.isdigit() else None
    device = get_device(m.from_user)

    cur.execute("SELECT * FROM users WHERE user_id=?", (uid,))
    if not cur.fetchone():
        cur.execute("""
        INSERT INTO users (user_id,referred_by,device_hash)
        VALUES (?,?,?)
        """, (uid, ref_id, device))
        conn.commit()

        if ref_id and ref_id != uid:
            name = f"@{m.from_user.username}" if m.from_user.username else m.from_user.first_name
            await safe_send(ref_id, f"👤 {name} joined\n⏳ Not verified")

    cur.execute("SELECT joined FROM users WHERE user_id=?", (uid,))
    if cur.fetchone()[0] == 0:
        await m.answer("🔒 Join all channels", reply_markup=join_kb())
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

    if ref_id and counted == 0 and ref_id != uid:
        # anti-leech
        cur.execute("SELECT device_hash FROM users WHERE user_id=?", (ref_id,))
        ref_dev = cur.fetchone()[0]
        cur.execute("SELECT device_hash FROM users WHERE user_id=?", (uid,))
        user_dev = cur.fetchone()[0]

        if ref_dev != user_dev:
            cur.execute("UPDATE users SET points=points+1 WHERE user_id=?", (ref_id,))
            cur.execute("UPDATE users SET referred_counted=1 WHERE user_id=?", (uid,))

            name = f"@{c.from_user.username}" if c.from_user.username else c.from_user.first_name
            await safe_send(ref_id, f"🎉 {name} verified +1 point")

    conn.commit()
    await c.message.edit_text("✅ Verified!", reply_markup=menu())

# ---------------- NAV ---------------- #

@dp.callback_query(lambda c: c.data == "bal")
async def bal(c):
    await c.answer()
    if not await check_all(c.from_user.id):
        await c.message.edit_text("🔒 Join first", reply_markup=join_kb())
        return
    await c.message.edit_text(f"💰 Points: {get_points(c.from_user.id)}", reply_markup=menu())

@dp.callback_query(lambda c: c.data == "ref")
async def ref(c):
    await c.answer()
    bot_info = await bot.get_me()
    link = f"https://t.me/{bot_info.username}?start={c.from_user.id}"

    cur.execute("SELECT COUNT(*) FROM users WHERE referred_by=?", (c.from_user.id,))
    n = cur.fetchone()[0]

    await c.message.edit_text(f"👥 Invite:\n<code>{link}</code>\nUsers: {n}", reply_markup=menu())

# ---------------- WITHDRAW ---------------- #

@dp.callback_query(lambda c: c.data == "wd")
async def wd(c):
    await c.answer()
    cost = get_cost()

    kb = InlineKeyboardMarkup(inline_keyboard=[
        [InlineKeyboardButton(text=f"🎬 Netflix [{cost}]", callback_data="nf")],
        [InlineKeyboardButton(text="⬅ Back", callback_data="bal")]
    ])

    await c.message.edit_text(f"🎬 Redeem\nCost: {cost} points", reply_markup=kb)

@dp.callback_query(lambda c: c.data == "nf")
async def nf(c):
    await c.answer("Processing...")

    uid = c.from_user.id
    pts = get_points(uid)
    cost = get_cost()

    if pts < cost:
        await c.message.edit_text("❌ Not enough points", reply_markup=menu())
        return

    cur.execute("SELECT file_id FROM files")
    files = cur.fetchall()

    if not files:
        await c.message.edit_text("⚠️ No files", reply_markup=menu())
        return

    file_id = random.choice(files)[0]
    await bot.send_document(uid, file_id)

    cur.execute("UPDATE users SET points=points-? WHERE user_id=?", (cost, uid))
    conn.commit()

    await c.message.edit_text("✅ Sent!", reply_markup=menu())

# ---------------- AUTO SYSTEMS ---------------- #

async def anti_leave():
    while True:
        cur.execute("SELECT user_id FROM users WHERE joined=1")
        for (uid,) in cur.fetchall():
            if not await check_all(uid):
                cur.execute("UPDATE users SET joined=0 WHERE user_id=?", (uid,))
                conn.commit()
                await safe_send(uid, "❌ You left channel. Access removed.")
        await asyncio.sleep(60)

async def auto_earn():
    while True:
        now = int(time.time())
        cur.execute("SELECT user_id,last_earn FROM users WHERE joined=1")
        for uid,last in cur.fetchall():
            if now - last > 300:
                cur.execute("UPDATE users SET points=points+1,last_earn=? WHERE user_id=?", (now, uid))
        conn.commit()
        await asyncio.sleep(60)

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
    if m.from_user.id != ADMIN_ID: return
    cur.execute("UPDATE settings SET value=? WHERE key='cost'", (m.text.split()[1],))
    conn.commit()
    await m.answer("Updated")

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

    await m.answer(f"Users: {u}\nVerified: {v}\nFiles: {f}")

@dp.message(Command("msend"))
async def msend(m):
    if m.from_user.id != ADMIN_ID: return
    text = m.text.replace("/msend ","")
    cur.execute("SELECT user_id FROM users WHERE joined=1")
    for (uid,) in cur.fetchall():
        await safe_send(uid, text)
    await m.answer("Broadcast done")

# ---------------- RUN ---------------- #

async def main():
    print("🔥 ULTIMATE BOT RUNNING")
    asyncio.create_task(anti_leave())
    asyncio.create_task(auto_earn())
    await dp.start_polling(bot)

if __name__ == "__main__":
    asyncio.run(main())
