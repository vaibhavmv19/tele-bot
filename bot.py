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
    file_type TEXT
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

def menu():
    return InlineKeyboardMarkup(inline_keyboard=[
        [InlineKeyboardButton(text="💰 Balance", callback_data="bal"),
         InlineKeyboardButton(text="👥 Refer", callback_data="ref")],
        [InlineKeyboardButton(text="🎬 Redeem", callback_data="wd")],
        [InlineKeyboardButton(text="🔥 Proof", url="https://t.me/zovloo")]
    ])

def join_kb():
    cur.execute("SELECT channel_link FROM channels")
    kb = [[InlineKeyboardButton(text="🔗 Join", url=c[0])] for c in cur.fetchall()]
    kb.append([InlineKeyboardButton(text="✅ I Joined", callback_data="verify")])
    return InlineKeyboardMarkup(inline_keyboard=kb)


# ---------------- START ---------------- #
@dp.message(CommandStart())
async def start(m: types.Message):
    uid = m.from_user.id
    args = m.text.split()

    ref_id = None
    if len(args) > 1:
        if args[1].isdigit():
            ref_id = int(args[1])

    # check if user exists
    cur.execute("SELECT user_id FROM users WHERE user_id=?", (uid,))
    exists = cur.fetchone()

    if not exists:
        cur.execute(
            "INSERT INTO users (user_id, referred_by, joined, referred_counted) VALUES (?, ?, 0, 0)",
            (uid, ref_id)
        )
        conn.commit()

        if ref_id and ref_id != uid:
            name = f"@{m.from_user.username}" if m.from_user.username else m.from_user.first_name
            await safe_send(ref_id, f"👤 {name} joined via your link\n⏳ Not verified yet")

    # Force join
    if not await check_all(uid):
        await m.answer("🔒 Join all channels first:", reply_markup=join_kb())
        return

    # check verified
    cur.execute("SELECT joined FROM users WHERE user_id=?", (uid,))
    joined = cur.fetchone()[0]

    if joined == 0:
        await m.answer("⚠️ Click '✅ Joined' after joining channels", reply_markup=join_kb())
        return

    await m.answer(HOME, reply_markup=menu())
# ---------------- VERIFY ---------------- #
@dp.callback_query(lambda c: c.data == "verify")
async def verify(c):
    uid = c.from_user.id

    if not await check_all(uid):
        await c.answer("❌ Join all channels first", show_alert=True)
        return

    # mark user as verified
    cur.execute("UPDATE users SET joined=1 WHERE user_id=?", (uid,))
    conn.commit()

    # give referral points
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
    await c.answer()
    await c.message.edit_text(f"💰 Points: {get_points(c.from_user.id)}", reply_markup=menu())

@dp.callback_query(lambda c: c.data == "ref")
async def ref(c):
    await c.answer()
    bot_info = await bot.get_me()
    link = f"https://t.me/{bot_info.username}?start={c.from_user.id}"

    cur.execute("SELECT COUNT(*) FROM users WHERE referred_by=?", (c.from_user.id,))
    n = cur.fetchone()[0]

    await c.message.edit_text(f"👥 Invite:\n<code>{link}</code>\nUsers: {n}", reply_markup=menu())

# ---------------- REDEEM ---------------- #

@dp.callback_query(lambda c: c.data == "wd")
async def wd(c):
    await c.answer()
    kb = InlineKeyboardMarkup(inline_keyboard=[
        [InlineKeyboardButton(text="🎬 Netflix [1]", callback_data="nf")],
        [InlineKeyboardButton(text="⬅ Back", callback_data="home")]
    ])
    await c.message.edit_text("🎬 Redeem\n1 Point = 1 File", reply_markup=kb)

@dp.callback_query(lambda c: c.data == "nf")
async def nf(c):
    await c.answer("⏳ Processing...")

    uid = c.from_user.id
    pts = get_points(uid)

    if pts < 1:
        await c.message.edit_text("❌ Not enough points", reply_markup=menu())
        return

    cur.execute("SELECT last_withdraw FROM users WHERE user_id=?", (uid,))
    last = cur.fetchone()[0]

    if time.time() - last < 10:
        await c.message.edit_text("⏳ Wait 10 sec", reply_markup=menu())
        return

    cur.execute("SELECT file_id, file_type FROM files")
    files = cur.fetchall()

    if not files:
        await c.message.edit_text("⚠️ No files available", reply_markup=menu())
        return

    file_id, ftype = random.choice(files)

    # 📤 Send file
    if ftype == "txt":
        await bot.send_document(uid, file_id, caption="📄 TXT File")
    elif ftype == "json":
        await bot.send_document(uid, file_id, caption="🧾 JSON File")

    # 💰 Deduct points
    cur.execute(
        "UPDATE users SET points = points - 1, last_withdraw=? WHERE user_id=?",
        (int(time.time()), uid)
    )
    conn.commit()

    await c.message.edit_text("✅ File sent!", reply_markup=menu())

# ---------------- ADMIN ---------------- #

@dp.message(Command("addchannel"))
async def addc(m):
    if m.from_user.id != ADMIN_ID: return
    _, cid, link = m.text.split()
    cur.execute("INSERT INTO channels VALUES (?,?)",(cid,link))
    conn.commit()
    await m.answer("✅ Added")

@dp.message(Command("delchannel"))
async def delc(m):
    if m.from_user.id != ADMIN_ID: return
    cur.execute("DELETE FROM channels WHERE channel_id=?", (m.text.split()[1],))
    conn.commit()
    await m.answer("✅ Deleted")

@dp.message(Command("channels"))
async def list_channels(m):
    if m.from_user.id != ADMIN_ID: return
    cur.execute("SELECT * FROM channels")
    data = cur.fetchall()
    text = "\n".join([f"{c[0]} | {c[1]}" for c in data])
    await m.answer(text if text else "No channels")

@dp.message(F.document)
async def upload(m):
    if m.from_user.id != ADMIN_ID:
        return

    file_name = m.document.file_name.lower()

    if file_name.endswith(".txt"):
        ftype = "txt"
    elif file_name.endswith(".json"):
        ftype = "json"
    else:
        await m.answer("❌ Only TXT or JSON allowed")
        return

    cur.execute("INSERT INTO files (file_id, file_type) VALUES (?, ?)",
                (m.document.file_id, ftype))
    conn.commit()

    await m.answer(f"✅ {ftype.upper()} file added")

@dp.message(Command("stats"))
async def stats(m):
    if m.from_user.id != ADMIN_ID: return

    cur.execute("SELECT COUNT(*) FROM users")
    u = cur.fetchone()[0]
    cur.execute("SELECT COUNT(*) FROM users WHERE joined=1")
    v = cur.fetchone()[0]
    cur.execute("SELECT COUNT(*) FROM files")
    f = cur.fetchone()[0]

    await m.answer(f"👥 Users: {u}\n✅ Verified: {v}\n📂 Files: {f}")

@dp.message(Command("msend"))
async def msend(m):
    if m.from_user.id != ADMIN_ID: return
    txt = m.text.replace("/msend ","")

    cur.execute("SELECT user_id FROM users WHERE joined=1")
    for u in cur.fetchall():
        await safe_send(u[0], txt)

    await m.answer("✅ Broadcast sent")
@dp.message(Command("addpoints"))
async def add_points(m: types.Message):
    if m.from_user.id != ADMIN_ID:
        return

    args = m.text.split()

    if len(args) != 3:
        await m.answer("Usage:\n/addpoints USER_ID AMOUNT")
        return

    try:
        user_id = int(args[1])
        amount = int(args[2])
    except:
        await m.answer("❌ Invalid input")
        return

    # check user exists
    cur.execute("SELECT user_id FROM users WHERE user_id=?", (user_id,))
    if not cur.fetchone():
        await m.answer("❌ User not found")
        return

    # add points
    cur.execute("UPDATE users SET points = points + ? WHERE user_id=?", (amount, user_id))
    conn.commit()

    await m.answer(f"✅ Added {amount} points to {user_id}")

    # notify user
    try:
        await bot.send_message(user_id, f"🎁 You received {amount} points from admin")
    except:
        pass

# ---------------- RUN ---------------- #

async def main():
    print("🔥 ULTIMATE BOT RUNNING")
    await dp.start_polling(bot)

if __name__ == "__main__":
    asyncio.run(main())
