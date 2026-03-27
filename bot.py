import asyncio
import sqlite3
import random
import zipfile
import io
from aiogram import Bot, Dispatcher, types, F
from aiogram.types import InlineKeyboardMarkup, InlineKeyboardButton, BufferedInputFile
from aiogram.filters import CommandStart, Command
from aiogram.client.default import DefaultBotProperties

BOT_TOKEN = "8744693542:AAHB_WPcHjbUcyfwa829VleyP7RP40O91tQ"
ADMIN_ID = 7998012491

ALLOWED_EXTENSIONS = (".txt", ".json", ".xml", ".csv", ".log")
MAX_USERS_PER_FILE = 5

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
    referred_counted INTEGER DEFAULT 0
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
    file_id TEXT UNIQUE,
    filename TEXT,
    file_type TEXT,
    sent_count INTEGER DEFAULT 0,
    group_message_id INTEGER,
    group_chat_id TEXT
)
""")

cur.execute("""
CREATE TABLE IF NOT EXISTS user_files (
    user_id INTEGER,
    file_id TEXT,
    PRIMARY KEY (user_id, file_id)
)
""")

cur.execute("""
CREATE TABLE IF NOT EXISTS settings (
    key TEXT PRIMARY KEY,
    value TEXT
)
""")

cur.execute("INSERT OR IGNORE INTO settings (key, value) VALUES ('price', '1')")
cur.execute("INSERT OR IGNORE INTO settings (key, value) VALUES ('file_group', '')")
cur.execute("INSERT OR IGNORE INTO settings (key, value) VALUES ('storage_channel', '')")
conn.commit()

# ---------------- HELPERS ---------------- #
def get_points(uid):
    cur.execute("SELECT points FROM users WHERE user_id=?", (uid,))
    r = cur.fetchone()
    return r[0] if r else 0

def get_price():
    cur.execute("SELECT value FROM settings WHERE key='price'")
    r = cur.fetchone()
    return int(r[0]) if r else 1

def get_file_group():
    cur.execute("SELECT value FROM settings WHERE key='file_group'")
    r = cur.fetchone()
    return r[0] if r and r[0] else None

def get_storage_channel():
    cur.execute("SELECT value FROM settings WHERE key='storage_channel'")
    r = cur.fetchone()
    return r[0] if r and r[0] else None

async def safe_send(uid, text):
    try:
        await bot.send_message(uid, text)
    except:
        pass

async def is_joined(uid, ch):
    try:
        member = await asyncio.wait_for(
            bot.get_chat_member(chat_id=ch, user_id=uid),
            timeout=5
        )
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

def is_allowed_file(name: str) -> bool:
    return any(name.lower().endswith(ext) for ext in ALLOWED_EXTENSIONS)

def is_zip(name: str) -> bool:
    return name.lower().endswith(".zip")

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
    buttons = [[InlineKeyboardButton(text="🔗 Join Channel", url=ch[0])] for ch in channels]
    buttons.append([InlineKeyboardButton(text="✅ I Joined", callback_data="verify")])
    return InlineKeyboardMarkup(inline_keyboard=buttons)

# ---------------- CORE: SAVE FILE TO DB VIA STORAGE CHANNEL ---------------- #
async def save_file_to_db(file_bytes: bytes, filename: str) -> str:
    """
    Upload file bytes to the storage channel to get a stable Telegram file_id.
    Returns 'saved', 'duplicate', or 'error'.
    """
    storage = get_storage_channel()
    if not storage:
        return "error"

    try:
        buf = BufferedInputFile(file_bytes, filename=filename)
        sent = await bot.send_document(
            chat_id=storage,
            document=buf,
            caption=f"🗄 {filename}",
            disable_notification=True
        )
        tg_file_id = sent.document.file_id
    except Exception as e:
        await safe_send(ADMIN_ID, f"❌ Storage upload failed for <code>{filename}</code>: {e}")
        return "error"

    cur.execute("SELECT file_id FROM files WHERE file_id=?", (tg_file_id,))
    if cur.fetchone():
        return "duplicate"

    cur.execute(
        "INSERT OR IGNORE INTO files (file_id, filename, file_type, sent_count) VALUES (?,?,?,0)",
        (tg_file_id, filename, "doc")
    )
    conn.commit()
    return "saved"

# ---------------- START ---------------- #
@dp.message(CommandStart())
async def start(m: types.Message):
    uid = m.from_user.id
    args = m.text.split()
    ref_id = int(args[1]) if len(args) > 1 and args[1].isdigit() else None

    cur.execute("SELECT user_id FROM users WHERE user_id=?", (uid,))
    if not cur.fetchone():
        cur.execute("INSERT INTO users (user_id, referred_by) VALUES (?, ?)", (uid, ref_id))
        conn.commit()

    if not await check_all(uid):
        await m.answer("🔒 Join all channels first:", reply_markup=join_kb())
        return

    cur.execute("SELECT joined FROM users WHERE user_id=?", (uid,))
    if cur.fetchone()[0] == 0:
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
    price = get_price()
    pts = get_points(c.from_user.id)
    price_label = "FREE 🎉" if price == 0 else f"{price} pt/file"
    await c.message.edit_text(
        f"💰 Your Points: <b>{pts}</b>\n🎬 Current Price: <b>{price_label}</b>",
        reply_markup=menu()
    )

@dp.callback_query(lambda c: c.data == "ref")
async def ref(c):
    bot_info = await bot.get_me()
    link = f"https://t.me/{bot_info.username}?start={c.from_user.id}"
    cur.execute("SELECT COUNT(*) FROM users WHERE referred_by=?", (c.from_user.id,))
    n = cur.fetchone()[0]
    await c.message.edit_text(
        f"👥 Your Invite Link:\n<code>{link}</code>\n\nTotal Referrals: <b>{n}</b>",
        reply_markup=menu()
    )

@dp.callback_query(lambda c: c.data == "wd")
async def wd(c):
    price = get_price()
    label = "FREE 🎉" if price == 0 else f"{price} pt"
    desc = "🎉 Files are FREE right now!" if price == 0 else f"Redeem <b>{price}</b> point(s) = 1 file"
    kb = InlineKeyboardMarkup(inline_keyboard=[
        [InlineKeyboardButton(text=f"🎬 Get Netflix File ({label})", callback_data="nf")],
        [InlineKeyboardButton(text="⬅ Back", callback_data="home")]
    ])
    await c.message.edit_text(desc, reply_markup=kb)

@dp.callback_query(lambda c: c.data == "home")
async def home(c):
    await c.message.edit_text(HOME, reply_markup=menu())

# ---------------- FILE REDEEM ---------------- #
@dp.callback_query(lambda c: c.data == "nf")
async def nf(c):
    uid = c.from_user.id
    pts = get_points(uid)
    price = get_price()

    if price > 0 and pts < price:
        await c.answer(f"❌ Need {price} points, you have {pts}", show_alert=True)
        return

    # Only files user hasn't received AND still under max capacity
    cur.execute("""
        SELECT id, file_id, filename, sent_count
        FROM files
        WHERE sent_count < ?
        AND file_id NOT IN (
            SELECT file_id FROM user_files WHERE user_id=?
        )
    """, (MAX_USERS_PER_FILE, uid))
    available = cur.fetchall()

    if not available:
        await c.message.edit_text(
            "😔 No new files available for you right now.\nInvite more friends or check back later!",
            reply_markup=menu()
        )
        return

    file_db_id, file_id, filename, _ = random.choice(available)

    try:
        await bot.send_document(
            uid, file_id,
            caption=f"📄 <b>{filename or 'Netflix File'}</b>\n\nKeep this safe! 🔐"
        )
    except Exception as e:
        await c.answer("❌ Error sending file. Contact admin.", show_alert=True)
        return

    if price > 0:
        cur.execute("UPDATE users SET points = points - ? WHERE user_id=?", (price, uid))
    cur.execute("INSERT OR IGNORE INTO user_files (user_id, file_id) VALUES (?,?)", (uid, file_id))
    cur.execute("UPDATE files SET sent_count = sent_count + 1 WHERE id=?", (file_db_id,))
    conn.commit()

    # Auto-delete from DB when maxed out
    cur.execute("SELECT sent_count FROM files WHERE id=?", (file_db_id,))
    row = cur.fetchone()
    if row and row[0] >= MAX_USERS_PER_FILE:
        cur.execute("DELETE FROM files WHERE id=?", (file_db_id,))
        conn.commit()

    await c.message.edit_text("✅ File sent to your DM!", reply_markup=menu())

# ---------------- DOCUMENT HANDLER ---------------- #
@dp.message(F.document)
async def handle_document(m: types.Message):
    file_group = get_file_group()
    is_from_group = file_group and str(m.chat.id) == str(file_group)
    is_from_admin_private = m.from_user.id == ADMIN_ID and m.chat.type == "private"

    if not (is_from_group or is_from_admin_private):
        return

    filename = (m.document.file_name or "file").strip()

    if is_zip(filename):
        await _handle_zip(m, filename, is_from_group, is_from_admin_private)
    elif is_allowed_file(filename):
        await _handle_single(m, filename, is_from_group, is_from_admin_private)
    elif is_from_admin_private:
        await m.answer(
            f"❌ Unsupported: <code>{filename}</code>\n"
            f"Allowed: {' '.join(ALLOWED_EXTENSIONS)} .zip"
        )


async def _handle_single(m, filename, is_from_group, is_from_admin_private):
    status = await m.answer("⏳ Saving...") if is_from_admin_private else None

    if not get_storage_channel():
        msg = "⚠️ Set storage channel first: /setstorage -100xxx"
        if status:
            await status.edit_text(msg)
        else:
            await safe_send(ADMIN_ID, msg)
        return

    try:
        tg_file = await bot.get_file(m.document.file_id)
        buf = io.BytesIO()
        await bot.download_file(tg_file.file_path, destination=buf)
        file_bytes = buf.getvalue()
    except Exception as e:
        err = f"❌ Download error: {e}"
        if status:
            await status.edit_text(err)
        return

    result = await save_file_to_db(file_bytes, filename)

    if is_from_group:
        try:
            await bot.delete_message(m.chat.id, m.message_id)
        except:
            pass
        if result == "saved":
            await safe_send(ADMIN_ID, f"✅ Saved: <code>{filename}</code>")
        elif result == "duplicate":
            await safe_send(ADMIN_ID, f"⚠️ Duplicate skipped: <code>{filename}</code>")
    else:
        icons = {"saved": "✅", "duplicate": "⚠️ Duplicate", "error": "❌"}
        if status:
            await status.edit_text(f"{icons.get(result, '?')} {filename}")


async def _handle_zip(m, zip_filename, is_from_group, is_from_admin_private):
    if not get_storage_channel():
        msg = "⚠️ Set storage channel first: /setstorage -100xxx"
        if is_from_admin_private:
            await m.answer(msg)
        else:
            await safe_send(ADMIN_ID, msg)
        return

    # Delete from group immediately so it's hidden
    if is_from_group:
        try:
            await bot.delete_message(m.chat.id, m.message_id)
        except:
            pass

    status = await m.answer(f"📦 Unpacking <code>{zip_filename}</code>...") if is_from_admin_private else None
    await safe_send(ADMIN_ID, f"📦 Processing ZIP: <code>{zip_filename}</code>") if not is_from_admin_private else None

    # Download ZIP
    try:
        tg_file = await bot.get_file(m.document.file_id)
        zip_buf = io.BytesIO()
        await bot.download_file(tg_file.file_path, destination=zip_buf)
        zip_buf.seek(0)
    except Exception as e:
        err = f"❌ Failed to download ZIP: {e}"
        if status:
            await status.edit_text(err)
        else:
            await safe_send(ADMIN_ID, err)
        return

    if not zipfile.is_zipfile(zip_buf):
        err = f"❌ Not a valid ZIP: <code>{zip_filename}</code>"
        if status:
            await status.edit_text(err)
        else:
            await safe_send(ADMIN_ID, err)
        return

    zip_buf.seek(0)
    saved = skipped = ignored = 0
    errors = []

    try:
        with zipfile.ZipFile(zip_buf, "r") as zf:
            entries = [
                e for e in zf.namelist()
                if not e.endswith("/") and not e.startswith("__MACOSX") and not e.startswith(".")
            ]

            for entry in entries:
                base = entry.split("/")[-1]
                if not base:
                    continue

                if not is_allowed_file(base):
                    ignored += 1
                    continue

                try:
                    file_bytes = zf.read(entry)
                except Exception as e:
                    errors.append(f"{base}: read error")
                    continue

                result = await save_file_to_db(file_bytes, base)
                if result == "saved":
                    saved += 1
                elif result == "duplicate":
                    skipped += 1
                else:
                    errors.append(f"{base}: upload error")

                await asyncio.sleep(0.35)  # Avoid Telegram flood

    except zipfile.BadZipFile:
        err = f"❌ Corrupt ZIP: <code>{zip_filename}</code>"
        if status:
            await status.edit_text(err)
        else:
            await safe_send(ADMIN_ID, err)
        return

    report = (
        f"📦 <b>{zip_filename}</b>\n\n"
        f"✅ Saved: <b>{saved}</b>\n"
        f"⚠️ Duplicate: <b>{skipped}</b>\n"
        f"🚫 Ignored (wrong type): <b>{ignored}</b>"
    )
    if errors:
        report += f"\n❌ Errors ({len(errors)}):\n" + "\n".join(errors[:5])

    if status:
        await status.edit_text(report)
    await safe_send(ADMIN_ID, report) if not is_from_admin_private else None

# ---------------- ADMIN COMMANDS ---------------- #
@dp.message(Command("setprice"))
async def setprice(m: types.Message):
    if m.from_user.id != ADMIN_ID:
        return
    try:
        price = int(m.text.split()[1])
        if price < 0:
            raise ValueError
        cur.execute("UPDATE settings SET value=? WHERE key='price'", (str(price),))
        conn.commit()
        label = "FREE 🎉" if price == 0 else f"<b>{price} point(s)</b>"
        await m.answer(f"✅ Price set to {label} per file")
    except:
        await m.answer("Usage: /setprice 3\n(0 = free)")

@dp.message(Command("setgroup"))
async def setgroup(m: types.Message):
    if m.from_user.id != ADMIN_ID:
        return
    try:
        gid = m.text.split()[1]
        cur.execute("UPDATE settings SET value=? WHERE key='file_group'", (gid,))
        conn.commit()
        await m.answer(
            f"✅ File source group: <code>{gid}</code>\n"
            "Bot must be admin (delete messages permission)"
        )
    except:
        await m.answer("Usage: /setgroup -100xxxxxxxxxx")

@dp.message(Command("setstorage"))
async def setstorage(m: types.Message):
    if m.from_user.id != ADMIN_ID:
        return
    try:
        gid = m.text.split()[1]
        cur.execute("UPDATE settings SET value=? WHERE key='storage_channel'", (gid,))
        conn.commit()
        await m.answer(
            f"✅ Storage channel: <code>{gid}</code>\n\n"
            "📌 Requirements:\n"
            "• Bot must be admin in that channel\n"
            "• Keep it private — users won't see it\n"
            "• All extracted files are stored here"
        )
    except:
        await m.answer("Usage: /setstorage -100xxxxxxxxxx")

@dp.message(Command("addchannel"))
async def addc(m: types.Message):
    if m.from_user.id != ADMIN_ID:
        return
    try:
        data = m.text.split()
        cur.execute("INSERT INTO channels VALUES (?,?)", (data[1], data[2]))
        conn.commit()
        await m.answer("✅ Join-wall channel added")
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
async def channels_cmd(m: types.Message):
    if m.from_user.id != ADMIN_ID:
        return
    cur.execute("SELECT * FROM channels")
    data = cur.fetchall()
    text = "\n".join([f"{c[0]} | {c[1]}" for c in data])
    await m.answer(text if text else "No channels added")

@dp.message(Command("addpoints"))
async def addpoints(m: types.Message):
    if m.from_user.id != ADMIN_ID:
        return
    try:
        _, uid, pts = m.text.split()
        cur.execute("UPDATE users SET points = points + ? WHERE user_id=?", (pts, uid))
        conn.commit()
        await m.answer(f"✅ Added {pts} points to user {uid}")
    except:
        await m.answer("Usage: /addpoints <user_id> <points>")

@dp.message(Command("stats"))
async def stats(m: types.Message):
    if m.from_user.id != ADMIN_ID:
        return
    cur.execute("SELECT COUNT(*) FROM users")
    users = cur.fetchone()[0]
    cur.execute("SELECT COUNT(*) FROM users WHERE joined=1")
    verified = cur.fetchone()[0]
    cur.execute("SELECT COUNT(*) FROM files")
    files = cur.fetchone()[0]
    price = get_price()
    file_group = get_file_group() or "❌ Not set"
    storage = get_storage_channel() or "❌ Not set"

    await m.answer(f"""
📊 <b>Bot Statistics</b>

👤 Total Users: {users}
✅ Verified: {verified}
📁 Files in Pool: {files}
💰 Price: {"FREE" if price == 0 else f"{price} pt"}/file

📂 Upload Group: <code>{file_group}</code>
🗄 Storage Channel: <code>{storage}</code>
""")

@dp.message(Command("files"))
async def list_files(m: types.Message):
    if m.from_user.id != ADMIN_ID:
        return
    cur.execute("SELECT id, filename, sent_count FROM files ORDER BY id DESC LIMIT 50")
    data = cur.fetchall()
    if not data:
        await m.answer("📭 No files in DB")
        return
    lines = [f"<code>#{r[0]}</code> {r[1] or 'unknown'} — {r[2]}/{MAX_USERS_PER_FILE} sent" for r in data]
    await m.answer("📁 <b>Files (latest 50):</b>\n\n" + "\n".join(lines))

@dp.message(Command("delfile"))
async def delfile(m: types.Message):
    if m.from_user.id != ADMIN_ID:
        return
    try:
        fid = int(m.text.split()[1])
        cur.execute("SELECT filename FROM files WHERE id=?", (fid,))
        row = cur.fetchone()
        if not row:
            await m.answer("❌ File not found")
            return
        cur.execute("DELETE FROM files WHERE id=?", (fid,))
        conn.commit()
        await m.answer(f"✅ Deleted #{fid}: {row[0]}")
    except:
        await m.answer("Usage: /delfile <id>")

@dp.message(Command("msend"))
async def msend(m: types.Message):
    if m.from_user.id != ADMIN_ID:
        return
    msg = m.text.replace("/msend ", "", 1)
    cur.execute("SELECT user_id FROM users WHERE joined=1")
    users = cur.fetchall()
    sent = 0
    for u in users:
        try:
            await bot.send_message(u[0], msg)
            sent += 1
            await asyncio.sleep(0.05)
        except:
            pass
    await m.answer(f"📢 Sent to {sent} users")

@dp.message(Command("help"))
async def help_cmd(m: types.Message):
    if m.from_user.id != ADMIN_ID:
        return
    await m.answer(f"""
<b>🛠 Admin Commands</b>

<b>⚙️ First-time Setup</b>
/setstorage -100xxx — private storage channel
/setgroup -100xxx — file upload group
/setprice 3 — points per file (0 = free)

<b>📢 Join-wall</b>
/addchannel -100xxx https://t.me/x
/delchannel -100xxx
/channels

<b>📁 Files</b>
/files — list all (latest 50)
/delfile &lt;id&gt; — remove one
Accepted: {" ".join(ALLOWED_EXTENSIONS)} .zip

<b>👥 Users</b>
/addpoints &lt;uid&gt; &lt;pts&gt;
/stats
/msend &lt;text&gt;

<b>📦 How ZIP works</b>
Drop .zip in upload group →
Bot downloads + extracts →
Each allowed file uploaded to storage channel →
file_id saved to DB →
ZIP deleted from group
Max {MAX_USERS_PER_FILE} users/file · No duplicate per user
""")

# ---------------- RUN ---------------- #
async def main():
    print("BOT RUNNING")
    await dp.start_polling(bot)

if __name__ == "__main__":
    asyncio.run(main())
