import asyncio
import sqlite3
import time
import random
from aiogram import Bot, Dispatcher, types
from aiogram.types import InlineKeyboardMarkup, InlineKeyboardButton
from aiogram.filters import CommandStart, Command
from aiogram.client.default import DefaultBotProperties

BOT_TOKEN = "8744693542:AAHB_WPcHjbUcyfwa829VleyP7RP40O91tQ"
ADMIN_ID = 7998012491

HOME = """
🏠 Welcome to Rewards Bot

💰 Earn points by referrals
🎬 Redeem Netflix files
👥 Invite friends to earn more
"""

bot = Bot(token=BOT_TOKEN, default=DefaultBotProperties(parse_mode="HTML"))
dp = Dispatcher()

# ---------------- DATABASE ---------------- #
conn = sqlite3.connect("bot.db", check_same_thread=False)
cur = conn.cursor()

cur.execute("""
CREATE TABLE IF NOT EXISTS users (
    user_id INTEGER PRIMARY KEY,
    points INTEGER DEFAULT 0,
    referred_by INTEGER,
    joined INTEGER DEFAULT 0,
    referred_counted INTEGER DEFAULT 0,
    last_withdraw INTEGER DEFAULT 0
)
""")

cur.execute("""
CREATE TABLE IF NOT EXISTS channels (
    channel_id TEXT,
    channel_link TEXT
)
""")

cur.execute("""
CREATE TABLE IF NOT EXISTS files (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    file_id TEXT,
    file_type TEXT,
    sent_count INTEGER DEFAULT 0
)
""")

conn.commit()

# ---------------- HELPERS ---------------- #
def get_points(uid):
    cur.execute("SELECT points FROM users WHERE user_id=?", (uid,))
    r = cur.fetchone()
    return r[0] if r else 0

async def safe_send(uid, text):
    try:
        await bot.send_message(uid, text)
    except:
        pass

async def is_joined(uid, ch):
    try:
        member = await bot.get_chat_member(chat_id=ch, user_id=uid)
        return member.status in ["member", "administrator", "creator"]
    except:
        return False

async def check_all(uid):
    cur.execute("SELECT channel_id FROM channels")
    channels = cur.fetchall()
    if not channels:
        return True
    for c in channels:
        if not await is_joined(uid, c[0]):
            return False
    return True

# ---------------- UI ---------------- #
def menu():
    return InlineKeyboardMarkup(inline_keyboard=[
        [InlineKeyboardButton(text="💰 Balance", callback_data="bal"),
         InlineKeyboardButton(text="👥 Refer", callback_data="ref")],
        [InlineKeyboardButton(text="🎬 Redeem", callback_data="wd")]
    ])

def join_kb():
    cur.execute("SELECT channel_link FROM channels")
    channels = cur.fetchall()

    buttons = []
    for ch in channels:
        buttons.append([InlineKeyboardButton(
            text="🔗 Join Channel",
            url=ch[0]
        )])

    buttons.append([InlineKeyboardButton(
        text="✅ I Joined",
        callback_data="verify"
    )])

    return InlineKeyboardMarkup(inline_keyboard=buttons)
# ---------------- START ---------------- #
@dp.message(CommandStart())
async def start(m: types.Message):
    uid = m.from_user.id
    args = m.text.split()

    ref_id = None
    if len(args) > 1 and args[1].isdigit():
        ref_id = int(args[1])

    cur.execute("SELECT user_id FROM users WHERE user_id=?", (uid,))
    exists = cur.fetchone()

    if not exists:
        cur.execute(
            "INSERT INTO users (user_id, referred_by) VALUES (?, ?)",
            (uid, ref_id)
        )
        conn.commit()

    if not await check_all(uid):
        await m.answer("🔒 Join all channels first:", reply_markup=join_kb())
        return

    cur.execute("SELECT joined FROM users WHERE user_id=?", (uid,))
    joined = cur.fetchone()[0]

    if joined == 0:
        await m.answer("⚠️ Click verify after joining", reply_markup=join_kb())
        return

    await m.answer(HOME, reply_markup=menu())

# ---------------- VERIFY ---------------- #
@dp.callback_query(lambda c: c.data == "verify")
async def verify(c):
    uid = c.from_user.id

    if not await check_all(uid):
        await c.answer("Join all channels first", show_alert=True)
        return

    cur.execute("UPDATE users SET joined=1 WHERE user_id=?", (uid,))
    conn.commit()

    cur.execute("SELECT referred_by, referred_counted FROM users WHERE user_id=?", (uid,))
    ref_id, counted = cur.fetchone()

    if ref_id and counted == 0:
        cur.execute("UPDATE users SET points = points + 1 WHERE user_id=?", (ref_id,))
        cur.execute("UPDATE users SET referred_counted = 1 WHERE user_id=?", (uid,))
        conn.commit()
        await safe_send(ref_id, "🎉 Referral verified! +1 point")

    await c.message.edit_text("✅ Verified!", reply_markup=menu())

# ---------------- MENU ---------------- #
@dp.callback_query(lambda c: c.data == "bal")
async def bal(c):
    await c.message.edit_text(f"💰 Points: {get_points(c.from_user.id)}", reply_markup=menu())

@dp.callback_query(lambda c: c.data == "ref")
async def ref(c):
    bot_info = await bot.get_me()
    link = f"https://t.me/{bot_info.username}?start={c.from_user.id}"

    cur.execute("SELECT COUNT(*) FROM users WHERE referred_by=?", (c.from_user.id,))
    n = cur.fetchone()[0]

    await c.message.edit_text(f"👥 Invite:\n<code>{link}</code>\nUsers: {n}", reply_markup=menu())

@dp.callback_query(lambda c: c.data == "wd")
async def wd(c):
    kb = InlineKeyboardMarkup(inline_keyboard=[
        [InlineKeyboardButton(text="🎬 Netflix File", callback_data="nf")],
        [InlineKeyboardButton(text="⬅ Back", callback_data="home")]
    ])
    await c.message.edit_text("Redeem 1 point = 1 file", reply_markup=kb)

@dp.callback_query(lambda c: c.data == "home")
async def home(c):
    await c.message.edit_text(HOME, reply_markup=menu())

# ---------------- FILE REDEEM ---------------- #
@dp.callback_query(lambda c: c.data == "nf")
async def nf(c):
    uid = c.from_user.id
    pts = get_points(uid)

    if pts < 1:
        await c.message.edit_text("Not enough points", reply_markup=menu())
        return

    cur.execute("SELECT * FROM files")
    files = cur.fetchall()

    if not files:
        await c.message.edit_text("No files available", reply_markup=menu())
        return

    file = random.choice(files)
    file_db_id, file_id, ftype, sent_count = file

    await bot.send_document(uid, file_id, caption="📄 File")

    # Update sent count
    cur.execute("UPDATE files SET sent_count = sent_count + 1 WHERE id=?", (file_db_id,))
    cur.execute("UPDATE users SET points = points - 1 WHERE user_id=?", (uid,))
    conn.commit()

    # Auto delete after 5 users
    cur.execute("SELECT sent_count FROM files WHERE id=?", (file_db_id,))
    count = cur.fetchone()[0]

    if count >= 5:
        cur.execute("DELETE FROM files WHERE id=?", (file_db_id,))
        conn.commit()

    await c.message.edit_text("✅ File sent", reply_markup=menu())
# auto save
@dp.message()
async def auto_add_files(m: types.Message):
    if m.from_user.id != ADMIN_ID:
        return

    if not m.document:
        return

    filename = m.document.file_name.lower()

    # Allow only txt and json
    if not (filename.endswith(".txt") or filename.endswith(".json")):
        return

    file_id = m.document.file_id

    # Check duplicate
    cur.execute("SELECT file_id FROM files WHERE file_id=?", (file_id,))
    if cur.fetchone():
        await m.answer("⚠️ File already exists")
        return

    cur.execute(
        "INSERT INTO files (file_id, file_type, sent_count) VALUES (?, ?, 0)",
        (file_id, "doc")
    )
    conn.commit()

    await m.answer(f"✅ Added: {filename}")
# ---------------- ADMIN ---------------- #
@dp.message(Command("addchannel"))
async def addc(m: types.Message):
    if m.from_user.id != ADMIN_ID:
        return

    try:
        data = m.text.split()
        cid = data[1]
        link = data[2]

        cur.execute("INSERT INTO channels VALUES (?,?)", (cid, link))
        conn.commit()

        await m.answer("✅ Channel added")

    except:
        await m.answer("Usage:\n/addchannel -100xxxx https://t.me/channel")
        
@dp.message(Command("delchannel"))
async def delc(m: types.Message):
    if m.from_user.id != ADMIN_ID:
        return

    try:
        cid = m.text.split()[1]
        cur.execute("DELETE FROM channels WHERE channel_id=?", (cid,))
        conn.commit()
        await m.answer("✅ Channel removed")
    except:
        await m.answer("Usage:\n/delchannel -100xxxx")
        

@dp.message(Command("channels"))
async def channels(m):
    if m.from_user.id != ADMIN_ID: return
    cur.execute("SELECT * FROM channels")
    data = cur.fetchall()
    text = "\n".join([f"{c[0]} | {c[1]}" for c in data])
    await m.answer(text if text else "No channels")

@dp.message(Command("addpoints"))
async def addpoints(m):
    if m.from_user.id != ADMIN_ID: return
    _, uid, pts = m.text.split()
    cur.execute("UPDATE users SET points = points + ? WHERE user_id=?", (pts, uid))
    conn.commit()
    await m.answer("Points added")

@dp.message(Command("stats"))
async def stats(m):
    if m.from_user.id != ADMIN_ID: return
    cur.execute("SELECT COUNT(*) FROM users")
    users = cur.fetchone()[0]
    await m.answer(f"Users: {users}")

@dp.message(Command("msend"))
async def msend(m):
    if m.from_user.id != ADMIN_ID: return
    msg = m.text.replace("/msend ", "")
    cur.execute("SELECT user_id FROM users")
    users = cur.fetchall()
    for u in users:
        await safe_send(u[0], msg)
    await m.answer("Broadcast sent")

# Add file by forwarding file to bot with caption /addfile
@dp.message(Command("addfile"))
async def addfile(m):
    if m.from_user.id != ADMIN_ID: return
    if m.reply_to_message.document:
        file_id = m.reply_to_message.document.file_id
        cur.execute("INSERT INTO files (file_id, file_type) VALUES (?,?)",(file_id,"doc"))
        conn.commit()
        await m.answer("File added")

# ---------------- RUN ---------------- #
async def main():
    print("BOT RUNNING")
    await dp.start_polling(bot)

if __name__ == "__main__":
    asyncio.run(main())
