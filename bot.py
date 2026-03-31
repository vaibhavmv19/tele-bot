import asyncio
import sqlite3
import random
import zipfile
import io
import time
import os
from aiogram import Bot, Dispatcher, types, F
from aiogram.types import InlineKeyboardMarkup, InlineKeyboardButton, BufferedInputFile, FSInputFile
from aiogram.filters import CommandStart, Command
from aiogram.client.default import DefaultBotProperties

BOT_TOKEN = "8744693542:AAHB_WPcHjbUcyfwa829VleyP7RP40O91tQ"
ADMIN_ID = 7998012491

ALLOWED_EXTENSIONS = (".txt", ".json", ".xml", ".csv", ".log")
MAX_USERS_PER_FILE = 3          # Cookie deleted after sent to 3 users
GEN_REQUIRED_INVITES = 5        # Need 5 referrals to use /gen
GEN_COOLDOWN_SECONDS = 6 * 3600 # 6 hours cooldown
GEN_COOLDOWN_VIP = 2 * 3600     # 2 hours (VIP via @aidenzawdx)
UPSELL_HANDLE = "@aidenzawdx"
UPSELL_PRICE = "$5"

# ─────────────────────────── WELCOME TEXT ──────────────────────────── #
HOME = """
🎬 <b>Netflix Cookie Bot</b>

━━━━━━━━━━━━━━━━━━━━━
💎 <b>How it works:</b>
👥 Invite <b>5 friends</b> → unlock <code>/gen</code>
🍪 <code>/gen</code> → receive a fresh Netflix cookie
⏳ Cooldown: <b>6 hours</b> between each gen
━━━━━━━━━━━━━━━━━━━━━

🚀 <i>Reduce cooldown to 2hrs → contact {upsell} ({price})</i>
""".strip().format(upsell=UPSELL_HANDLE, price=UPSELL_PRICE)

bot = Bot(token=BOT_TOKEN, default=DefaultBotProperties(parse_mode="HTML"))
dp = Dispatcher()

# ─────────────────────────── DATABASE ──────────────────────────────── #
conn = sqlite3.connect("bot.db", check_same_thread=False)
cur = conn.cursor()

cur.execute("""
CREATE TABLE IF NOT EXISTS users (
    user_id INTEGER PRIMARY KEY,
    points INTEGER DEFAULT 0,
    referred_by INTEGER,
    joined INTEGER DEFAULT 0,
    referred_counted INTEGER DEFAULT 0,
    is_vip INTEGER DEFAULT 0
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
CREATE TABLE IF NOT EXISTS gen_log (
    user_id INTEGER PRIMARY KEY,
    last_gen INTEGER DEFAULT 0
)
""")

cur.execute("""
CREATE TABLE IF NOT EXISTS settings (
    key TEXT PRIMARY KEY,
    value TEXT
)
""")

cur.execute("INSERT OR IGNORE INTO settings (key, value) VALUES ('price', '0')")
cur.execute("INSERT OR IGNORE INTO settings (key, value) VALUES ('file_group', '')")
cur.execute("INSERT OR IGNORE INTO settings (key, value) VALUES ('storage_channel', '')")
cur.execute("INSERT OR IGNORE INTO settings (key, value) VALUES ('netflix_gif_id', '')")
conn.commit()

# ─────────────────────────── HELPERS ───────────────────────────────── #
def get_points(uid):
    cur.execute("SELECT points FROM users WHERE user_id=?", (uid,))
    r = cur.fetchone()
    return r[0] if r else 0

def get_price():
    cur.execute("SELECT value FROM settings WHERE key='price'")
    r = cur.fetchone()
    return int(r[0]) if r else 0

def get_file_group():
    cur.execute("SELECT value FROM settings WHERE key='file_group'")
    r = cur.fetchone()
    return r[0] if r and r[0] else None

def get_storage_channel():
    cur.execute("SELECT value FROM settings WHERE key='storage_channel'")
    r = cur.fetchone()
    return r[0] if r and r[0] else None

def get_netflix_gif_id():
    cur.execute("SELECT value FROM settings WHERE key='netflix_gif_id'")
    r = cur.fetchone()
    return r[0] if r and r[0] else None

def set_setting(key, value):
    cur.execute("UPDATE settings SET value=? WHERE key=?", (value, key))
    conn.commit()

def get_verified_referrals(uid):
    cur.execute(
        "SELECT COUNT(*) FROM users WHERE referred_by=? AND joined=1",
        (uid,)
    )
    return cur.fetchone()[0]

def get_gen_cooldown(uid):
    cur.execute("SELECT last_gen FROM gen_log WHERE user_id=?", (uid,))
    r = cur.fetchone()
    return r[0] if r else 0

def is_vip(uid):
    cur.execute("SELECT is_vip FROM users WHERE user_id=?", (uid,))
    r = cur.fetchone()
    return bool(r and r[0])

def user_cooldown_seconds(uid):
    return GEN_COOLDOWN_VIP if is_vip(uid) else GEN_COOLDOWN_SECONDS

async def safe_send(uid, text, **kwargs):
    try:
        await bot.send_message(uid, text, **kwargs)
    except Exception:
        pass

async def safe_send_animation(uid, gif_id, caption=""):
    try:
        await bot.send_animation(uid, animation=gif_id, caption=caption, parse_mode="HTML")
    except Exception:
        pass

async def is_joined(uid, ch):
    try:
        member = await asyncio.wait_for(
            bot.get_chat_member(chat_id=ch, user_id=uid),
            timeout=5
        )
        return member.status in ["member", "administrator", "creator"]
    except Exception:
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

def fmt_time(seconds: int) -> str:
    h = seconds // 3600
    m = (seconds % 3600) // 60
    s = seconds % 60
    if h:
        return f"{h}h {m}m"
    if m:
        return f"{m}m {s}s"
    return f"{s}s"

# ─────────────────────────── UI KEYBOARDS ──────────────────────────── #
def menu():
    return InlineKeyboardMarkup(inline_keyboard=[
        [
            InlineKeyboardButton(text="🍪 Gen Cookie", callback_data="gen"),
            InlineKeyboardButton(text="👥 Invite", callback_data="ref"),
        ],
        [
            InlineKeyboardButton(text="💰 Balance", callback_data="bal"),
            InlineKeyboardButton(text="ℹ️ Status", callback_data="status"),
        ],
    ])

def join_kb():
    cur.execute("SELECT channel_link FROM channels")
    channels = cur.fetchall()
    buttons = [[InlineKeyboardButton(text="🔗 Join Channel", url=ch[0])] for ch in channels]
    buttons.append([InlineKeyboardButton(text="✅ I Joined", callback_data="verify")])
    return InlineKeyboardMarkup(inline_keyboard=buttons)

def back_kb():
    return InlineKeyboardMarkup(inline_keyboard=[
        [InlineKeyboardButton(text="⬅️ Back", callback_data="home")]
    ])

# ─────────────────────────── GIF UPLOADER ──────────────────────────── #
async def ensure_netflix_gif() -> str | None:
    """Upload Netflix.mp4 to storage on first boot, cache file_id."""
    cached = get_netflix_gif_id()
    if cached:
        return cached

    storage = get_storage_channel()
    if not storage:
        return None

    for fname in ("Netflix.mp4", "netflix.mp4", "netflix.gif", "Netflix.gif"):
        if os.path.exists(fname):
            try:
                f = FSInputFile(fname)
                sent = await bot.send_animation(
                    chat_id=storage,
                    animation=f,
                    caption="🎬 Netflix Intro GIF",
                    disable_notification=True,
                )
                fid = sent.animation.file_id
                cur.execute(
                    "INSERT OR REPLACE INTO settings (key, value) VALUES ('netflix_gif_id', ?)",
                    (fid,)
                )
                conn.commit()
                return fid
            except Exception as e:
                print(f"[GIF] upload failed: {e}")
            break
    return None

# ─────────────────────────── STORAGE WITH RETRY ────────────────────── #
async def save_file_to_db(file_bytes: bytes, filename: str, retries=3) -> str:
    storage = get_storage_channel()
    if not storage:
        return "error"

    for attempt in range(retries):
        try:
            buf = BufferedInputFile(file_bytes, filename=filename)
            sent = await bot.send_document(
                chat_id=storage,
                document=buf,
                caption=f"🗄 {filename}",
                disable_notification=True,
            )
            tg_file_id = sent.document.file_id
            break
        except Exception as e:
            err_str = str(e)
            if "retry after" in err_str.lower():
                # Parse retry-after seconds from error
                try:
                    retry_secs = int([w for w in err_str.split() if w.isdigit()][-1]) + 1
                except Exception:
                    retry_secs = 10
                await asyncio.sleep(retry_secs)
                continue
            await safe_send(ADMIN_ID, f"❌ Storage upload failed for <code>{filename}</code>: {e}")
            return "error"
    else:
        await safe_send(ADMIN_ID, f"❌ Storage upload failed after {retries} retries: <code>{filename}</code>")
        return "error"

    cur.execute("SELECT file_id FROM files WHERE file_id=?", (tg_file_id,))
    if cur.fetchone():
        return "duplicate"

    cur.execute(
        "INSERT OR IGNORE INTO files (file_id, filename, file_type, sent_count) VALUES (?,?,?,0)",
        (tg_file_id, filename, "doc"),
    )
    conn.commit()
    return "saved"

# ─────────────────────────── /START ────────────────────────────────── #
@dp.message(CommandStart())
async def start(m: types.Message):
    uid = m.from_user.id
    args = m.text.split()
    ref_id = int(args[1]) if len(args) > 1 and args[1].isdigit() else None

    cur.execute("SELECT user_id FROM users WHERE user_id=?", (uid,))
    if not cur.fetchone():
        cur.execute(
            "INSERT INTO users (user_id, referred_by) VALUES (?, ?)",
            (uid, ref_id),
        )
        conn.commit()

    if not await check_all(uid):
        await m.answer("🔒 <b>Join all channels first to continue:</b>", reply_markup=join_kb())
        return

    cur.execute("SELECT joined FROM users WHERE user_id=?", (uid,))
    if cur.fetchone()[0] == 0:
        await m.answer(
            "⚠️ <b>Please join the channel then tap ✅ I Joined</b>",
            reply_markup=join_kb()
        )
        return

    # Send Netflix GIF welcome
    gif_id = await ensure_netflix_gif()
    if gif_id:
        try:
            await bot.send_animation(
                uid,
                animation=gif_id,
                caption=HOME,
                reply_markup=menu(),
                parse_mode="HTML",
            )
        except Exception:
            await m.answer(HOME, reply_markup=menu())
    else:
        await m.answer(HOME, reply_markup=menu())

# ─────────────────────────── VERIFY ────────────────────────────────── #
@dp.callback_query(lambda c: c.data == "verify")
async def verify(c: types.CallbackQuery):
    uid = c.from_user.id
    if not await check_all(uid):
        await c.answer("❌ Join all channels first!", show_alert=True)
        return

    cur.execute("UPDATE users SET joined=1 WHERE user_id=?", (uid,))
    conn.commit()

    cur.execute("SELECT referred_by, referred_counted FROM users WHERE user_id=?", (uid,))
    ref_id, counted = cur.fetchone()
    if ref_id and counted == 0:
        cur.execute("UPDATE users SET points = points + 1 WHERE user_id=?", (ref_id,))
        cur.execute("UPDATE users SET referred_counted = 1 WHERE user_id=?", (uid,))
        conn.commit()
        refs = get_verified_referrals(ref_id)
        bonus = ""
        if refs >= GEN_REQUIRED_INVITES:
            bonus = f"\n\n🍪 You now have <b>{refs}</b> invites — use /gen to get a cookie!"
        await safe_send(ref_id, f"🎉 <b>New referral verified!</b> +1 point{bonus}")

    gif_id = await ensure_netflix_gif()
    if gif_id:
        try:
            await c.message.delete()
        except Exception:
            pass
        await bot.send_animation(
            uid, animation=gif_id, caption="✅ <b>Verified! Welcome aboard.</b>\n\n" + HOME,
            reply_markup=menu(), parse_mode="HTML"
        )
    else:
        await c.message.edit_text("✅ <b>Verified! Welcome.</b>\n\n" + HOME, reply_markup=menu())

# ─────────────────────────── HOME ──────────────────────────────────── #
@dp.callback_query(lambda c: c.data == "home")
async def home_cb(c: types.CallbackQuery):
    gif_id = await ensure_netflix_gif()
    if gif_id:
        try:
            await c.message.delete()
        except Exception:
            pass
        await bot.send_animation(
            c.from_user.id, animation=gif_id, caption=HOME,
            reply_markup=menu(), parse_mode="HTML"
        )
    else:
        await c.message.edit_text(HOME, reply_markup=menu())

# ─────────────────────────── BALANCE ───────────────────────────────── #
@dp.callback_query(lambda c: c.data == "bal")
async def bal(c: types.CallbackQuery):
    uid = c.from_user.id
    pts = get_points(uid)
    refs = get_verified_referrals(uid)
    last_gen = get_gen_cooldown(uid)
    cooldown = user_cooldown_seconds(uid)
    now = int(time.time())
    elapsed = now - last_gen
    if elapsed >= cooldown or last_gen == 0:
        cd_str = "✅ Ready"
    else:
        cd_str = f"⏳ {fmt_time(cooldown - elapsed)} left"

    vip_line = "👑 <b>VIP</b> — 2hr cooldown\n" if is_vip(uid) else ""
    await c.message.edit_text(
        f"💰 <b>Your Account</b>\n"
        f"━━━━━━━━━━━━━━━━\n"
        f"{vip_line}"
        f"💎 Points: <b>{pts}</b>\n"
        f"👥 Verified Invites: <b>{refs}</b> / {GEN_REQUIRED_INVITES}\n"
        f"🍪 /gen Status: <b>{cd_str}</b>\n"
        f"━━━━━━━━━━━━━━━━\n"
        f"<i>Get {GEN_REQUIRED_INVITES} invites to unlock /gen</i>",
        reply_markup=menu()
    )

# ─────────────────────────── STATUS ────────────────────────────────── #
@dp.callback_query(lambda c: c.data == "status")
async def status_cb(c: types.CallbackQuery):
    uid = c.from_user.id
    refs = get_verified_referrals(uid)
    cooldown = user_cooldown_seconds(uid)
    last_gen = get_gen_cooldown(uid)
    now = int(time.time())
    elapsed = now - last_gen
    remaining = cooldown - elapsed

    invite_bar = "🟢" * min(refs, GEN_REQUIRED_INVITES) + "⬜" * max(0, GEN_REQUIRED_INVITES - refs)
    gen_status = "✅ <b>Ready to gen!</b>" if remaining <= 0 or last_gen == 0 else f"⏳ Next gen in <b>{fmt_time(remaining)}</b>"
    vip_badge = "👑 VIP Member\n" if is_vip(uid) else ""

    kb = InlineKeyboardMarkup(inline_keyboard=[
        [InlineKeyboardButton(text=f"💬 Get VIP ({UPSELL_PRICE})", url=f"https://t.me/{UPSELL_HANDLE.lstrip('@')}")],
        [InlineKeyboardButton(text="⬅️ Back", callback_data="home")]
    ])

    await c.message.edit_text(
        f"📊 <b>Your Status</b>\n"
        f"━━━━━━━━━━━━━━━━\n"
        f"{vip_badge}"
        f"👥 Invites: {invite_bar} <b>{refs}/{GEN_REQUIRED_INVITES}</b>\n"
        f"🍪 Gen: {gen_status}\n"
        f"⏱ Cooldown: <b>{'2hr (VIP)' if is_vip(uid) else '6hr'}</b>\n"
        f"━━━━━━━━━━━━━━━━\n"
        f"🚀 Reduce to <b>2hr cooldown</b> → {UPSELL_HANDLE} ({UPSELL_PRICE})",
        reply_markup=kb
    )

# ─────────────────────────── REFER ─────────────────────────────────── #
@dp.callback_query(lambda c: c.data == "ref")
async def ref(c: types.CallbackQuery):
    bot_info = await bot.get_me()
    link = f"https://t.me/{bot_info.username}?start={c.from_user.id}"
    refs = get_verified_referrals(c.from_user.id)
    need = max(0, GEN_REQUIRED_INVITES - refs)
    bar = "🟢" * min(refs, GEN_REQUIRED_INVITES) + "⬜" * need

    kb = InlineKeyboardMarkup(inline_keyboard=[
        [InlineKeyboardButton(text="📤 Share Invite Link", url=f"https://t.me/share/url?url={link}")],
        [InlineKeyboardButton(text="⬅️ Back", callback_data="home")]
    ])
    await c.message.edit_text(
        f"👥 <b>Invite Friends</b>\n"
        f"━━━━━━━━━━━━━━━━\n"
        f"Progress: {bar}\n"
        f"✅ Verified: <b>{refs}</b> | Need: <b>{GEN_REQUIRED_INVITES}</b>\n\n"
        f"🔗 Your link:\n<code>{link}</code>\n\n"
        f"{'✅ <b>Unlocked!</b> Use /gen to get a cookie.' if refs >= GEN_REQUIRED_INVITES else f'⚠️ Invite <b>{need}</b> more friends to unlock /gen'}",
        reply_markup=kb
    )

# ─────────────────────────── /GEN COMMAND ──────────────────────────── #
@dp.message(Command("gen"))
async def gen_cmd(m: types.Message):
    uid = m.from_user.id

    # Must be verified
    cur.execute("SELECT joined FROM users WHERE user_id=?", (uid,))
    row = cur.fetchone()
    if not row or row[0] == 0:
        await m.answer("❌ <b>Please /start and join the required channels first.</b>")
        return

    # Check 5 invites
    refs = get_verified_referrals(uid)
    if refs < GEN_REQUIRED_INVITES:
        bot_info = await bot.get_me()
        link = f"https://t.me/{bot_info.username}?start={uid}"
        need = GEN_REQUIRED_INVITES - refs
        bar = "🟢" * refs + "⬜" * need
        await m.answer(
            f"🔒 <b>Gen Locked</b>\n"
            f"━━━━━━━━━━━━━━━━\n"
            f"Progress: {bar}\n"
            f"You need <b>{need}</b> more verified invite(s).\n\n"
            f"🔗 Your link:\n<code>{link}</code>",
            reply_markup=InlineKeyboardMarkup(inline_keyboard=[
                [InlineKeyboardButton(text="📤 Share Link", url=f"https://t.me/share/url?url={link}")]
            ])
        )
        return

    # Check cooldown
    now = int(time.time())
    last_gen = get_gen_cooldown(uid)
    cooldown = user_cooldown_seconds(uid)
    elapsed = now - last_gen

    if last_gen > 0 and elapsed < cooldown:
        remaining = cooldown - elapsed
        kb = InlineKeyboardMarkup(inline_keyboard=[
            [InlineKeyboardButton(
                text=f"⚡ Reduce to 2hr — {UPSELL_PRICE}",
                url=f"https://t.me/{UPSELL_HANDLE.lstrip('@')}"
            )]
        ])
        await m.answer(
            f"⏳ <b>Cooldown Active</b>\n"
            f"━━━━━━━━━━━━━━━━\n"
            f"Next cookie in: <b>{fmt_time(remaining)}</b>\n\n"
            f"🚀 Want <b>2hr cooldown</b> instead of 6hr?\n"
            f"Contact {UPSELL_HANDLE} — only {UPSELL_PRICE}!",
            reply_markup=kb
        )
        return

    # Pick a cookie not yet sent to this user, under max capacity
    cur.execute("""
        SELECT id, file_id, filename, sent_count
        FROM files
        WHERE sent_count < ?
        AND file_id NOT IN (
            SELECT file_id FROM user_files WHERE user_id=?
        )
        ORDER BY RANDOM()
        LIMIT 1
    """, (MAX_USERS_PER_FILE, uid))
    cookie = cur.fetchone()

    if not cookie:
        await m.answer(
            "😔 <b>No cookies available right now.</b>\n"
            "New stock is being added — check back soon! 🔄"
        )
        return

    file_db_id, file_id, filename, sent_count = cookie

    # Send the cookie as animation (GIF) + document
    gif_id = await ensure_netflix_gif()
    try:
        if gif_id:
            await bot.send_animation(
                uid,
                animation=gif_id,
                caption=(
                    f"🍪 <b>Your Netflix Cookie</b>\n"
                    f"━━━━━━━━━━━━━━━━\n"
                    f"📄 File: <code>{filename or 'cookie'}</code>\n"
                    f"🔐 Keep this private!\n"
                    f"⏱ Next gen in: <b>{fmt_time(cooldown)}</b>"
                ),
                parse_mode="HTML"
            )
        await bot.send_document(
            uid,
            document=file_id,
            caption=(
                f"🍪 <b>{filename or 'Netflix Cookie'}</b>\n\n"
                f"✅ Import this cookie to access Netflix\n"
                f"🔐 Do not share with others!\n\n"
                f"<i>Next gen unlocks in {fmt_time(cooldown)}</i>"
            )
        )
    except Exception as e:
        await m.answer("❌ Error sending cookie. Please contact admin.")
        return

    # Update records
    cur.execute(
        "INSERT OR IGNORE INTO user_files (user_id, file_id) VALUES (?,?)",
        (uid, file_id)
    )
    cur.execute(
        "UPDATE files SET sent_count = sent_count + 1 WHERE id=?",
        (file_db_id,)
    )
    cur.execute(
        "INSERT OR REPLACE INTO gen_log (user_id, last_gen) VALUES (?,?)",
        (uid, now)
    )
    conn.commit()

    # Auto-delete cookie from pool after MAX_USERS_PER_FILE
    cur.execute("SELECT sent_count FROM files WHERE id=?", (file_db_id,))
    row = cur.fetchone()
    if row and row[0] >= MAX_USERS_PER_FILE:
        cur.execute("DELETE FROM files WHERE id=?", (file_db_id,))
        conn.commit()

    await m.answer(
        f"✅ <b>Cookie sent to your DM!</b>\n"
        f"⏳ Next gen unlocks in <b>{fmt_time(cooldown)}</b>\n\n"
        f"🚀 Reduce to 2hr → {UPSELL_HANDLE} ({UPSELL_PRICE})",
        reply_markup=InlineKeyboardMarkup(inline_keyboard=[
            [InlineKeyboardButton(text=f"⚡ Get VIP ({UPSELL_PRICE})",
                                  url=f"https://t.me/{UPSELL_HANDLE.lstrip('@')}")]
        ])
    )

# Callback alias for gen from inline button
@dp.callback_query(lambda c: c.data == "gen")
async def gen_cb(c: types.CallbackQuery):
    # Simulate message for gen_cmd
    await gen_cmd(c.message)

# ─────────────────────────── DOCUMENT HANDLER ──────────────────────── #
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
    status = await m.answer("⏳ Saving cookie...") if is_from_admin_private else None

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
        except Exception:
            pass
        if result == "saved":
            await safe_send(ADMIN_ID, f"✅ Cookie saved: <code>{filename}</code>")
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

    if is_from_group:
        try:
            await bot.delete_message(m.chat.id, m.message_id)
        except Exception:
            pass

    status = await m.answer(f"📦 Unpacking <code>{zip_filename}</code>...") if is_from_admin_private else None
    if not is_from_admin_private:
        await safe_send(ADMIN_ID, f"📦 Processing ZIP: <code>{zip_filename}</code>")

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
                if not e.endswith("/")
                and not e.startswith("__MACOSX")
                and not e.startswith(".")
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
                except Exception:
                    errors.append(f"{base}: read error")
                    continue

                result = await save_file_to_db(file_bytes, base)
                if result == "saved":
                    saved += 1
                elif result == "duplicate":
                    skipped += 1
                else:
                    errors.append(f"{base}: upload error")

                await asyncio.sleep(1.0)  # Respect Telegram flood limits

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
    if not is_from_admin_private:
        await safe_send(ADMIN_ID, report)

# ─────────────────────────── ADMIN COMMANDS ────────────────────────── #
@dp.message(Command("setprice"))
async def setprice(m: types.Message):
    if m.from_user.id != ADMIN_ID:
        return
    try:
        price = int(m.text.split()[1])
        if price < 0:
            raise ValueError
        set_setting("price", str(price))
        label = "FREE 🎉" if price == 0 else f"<b>{price} point(s)</b>"
        await m.answer(f"✅ Price set to {label} per file")
    except Exception:
        await m.answer("Usage: /setprice 3\n(0 = free)")

@dp.message(Command("setgroup"))
async def setgroup(m: types.Message):
    if m.from_user.id != ADMIN_ID:
        return
    try:
        gid = m.text.split()[1]
        set_setting("file_group", gid)
        await m.answer(
            f"✅ File source group: <code>{gid}</code>\n"
            "Bot must be admin (delete messages permission)"
        )
    except Exception:
        await m.answer("Usage: /setgroup -100xxxxxxxxxx")

@dp.message(Command("setstorage"))
async def setstorage(m: types.Message):
    if m.from_user.id != ADMIN_ID:
        return
    try:
        gid = m.text.split()[1]
        set_setting("storage_channel", gid)
        await m.answer(
            f"✅ Storage channel: <code>{gid}</code>\n\n"
            "📌 Requirements:\n"
            "• Bot must be admin in that channel\n"
            "• Keep it private — users won't see it\n"
            "• All cookies stored here\n\n"
            "💡 Place <code>Netflix.mp4</code> in bot folder → auto-uploaded as GIF on next /start"
        )
    except Exception:
        await m.answer("Usage: /setstorage -100xxxxxxxxxx")

@dp.message(Command("setgif"))
async def setgif(m: types.Message):
    """Admin: manually set Netflix GIF file_id"""
    if m.from_user.id != ADMIN_ID:
        return
    try:
        fid = m.text.split()[1]
        cur.execute(
            "INSERT OR REPLACE INTO settings (key, value) VALUES ('netflix_gif_id', ?)",
            (fid,)
        )
        conn.commit()
        await m.answer(f"✅ Netflix GIF set: <code>{fid}</code>")
    except Exception:
        await m.answer("Usage: /setgif <file_id>\nOr place Netflix.mp4 in bot folder — auto-detected on startup.")

@dp.message(Command("setvip"))
async def setvip(m: types.Message):
    """Admin: grant VIP (2hr cooldown) to a user"""
    if m.from_user.id != ADMIN_ID:
        return
    try:
        uid = int(m.text.split()[1])
        cur.execute("UPDATE users SET is_vip=1 WHERE user_id=?", (uid,))
        conn.commit()
        await m.answer(f"✅ User <code>{uid}</code> is now VIP (2hr cooldown)")
        await safe_send(uid, "👑 <b>You're now VIP!</b> Your /gen cooldown is reduced to <b>2 hours</b>!")
    except Exception:
        await m.answer("Usage: /setvip <user_id>")

@dp.message(Command("revokevip"))
async def revokevip(m: types.Message):
    if m.from_user.id != ADMIN_ID:
        return
    try:
        uid = int(m.text.split()[1])
        cur.execute("UPDATE users SET is_vip=0 WHERE user_id=?", (uid,))
        conn.commit()
        await m.answer(f"✅ VIP revoked for <code>{uid}</code>")
    except Exception:
        await m.answer("Usage: /revokevip <user_id>")

@dp.message(Command("resetgen"))
async def resetgen(m: types.Message):
    """Admin: reset a user's gen cooldown"""
    if m.from_user.id != ADMIN_ID:
        return
    try:
        uid = int(m.text.split()[1])
        cur.execute("DELETE FROM gen_log WHERE user_id=?", (uid,))
        conn.commit()
        await m.answer(f"✅ Gen cooldown reset for <code>{uid}</code>")
        await safe_send(uid, "✅ Your /gen cooldown has been reset by admin! Use /gen now.")
    except Exception:
        await m.answer("Usage: /resetgen <user_id>")

@dp.message(Command("addchannel"))
async def addc(m: types.Message):
    if m.from_user.id != ADMIN_ID:
        return
    try:
        data = m.text.split()
        cur.execute("INSERT INTO channels VALUES (?,?)", (data[1], data[2]))
        conn.commit()
        await m.answer("✅ Join-wall channel added")
    except Exception:
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
    except Exception:
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
    except Exception:
        await m.answer("Usage: /addpoints <user_id> <points>")

@dp.message(Command("stats"))
async def stats(m: types.Message):
    if m.from_user.id != ADMIN_ID:
        return
    cur.execute("SELECT COUNT(*) FROM users")
    users = cur.fetchone()[0]
    cur.execute("SELECT COUNT(*) FROM users WHERE joined=1")
    verified = cur.fetchone()[0]
    cur.execute("SELECT COUNT(*) FROM users WHERE is_vip=1")
    vips = cur.fetchone()[0]
    cur.execute("SELECT COUNT(*) FROM files")
    files = cur.fetchone()[0]
    cur.execute("SELECT COUNT(*) FROM gen_log")
    gens = cur.fetchone()[0]
    price = get_price()
    file_group = get_file_group() or "❌ Not set"
    storage = get_storage_channel() or "❌ Not set"

    await m.answer(
        f"📊 <b>Bot Statistics</b>\n"
        f"━━━━━━━━━━━━━━━━\n"
        f"👤 Total Users: <b>{users}</b>\n"
        f"✅ Verified: <b>{verified}</b>\n"
        f"👑 VIPs: <b>{vips}</b>\n"
        f"🍪 Cookies in Pool: <b>{files}</b>\n"
        f"📤 Total Gens: <b>{gens}</b>\n"
        f"💰 Price: <b>{'FREE' if price == 0 else f'{price} pt'}/cookie</b>\n"
        f"━━━━━━━━━━━━━━━━\n"
        f"📂 Upload Group: <code>{file_group}</code>\n"
        f"🗄 Storage: <code>{storage}</code>"
    )

@dp.message(Command("files"))
async def list_files(m: types.Message):
    if m.from_user.id != ADMIN_ID:
        return
    cur.execute("SELECT id, filename, sent_count FROM files ORDER BY id DESC LIMIT 50")
    data = cur.fetchall()
    if not data:
        await m.answer("📭 No cookies in DB")
        return
    lines = [
        f"<code>#{r[0]}</code> {r[1] or 'unknown'} — {r[2]}/{MAX_USERS_PER_FILE} sent"
        for r in data
    ]
    await m.answer("🍪 <b>Cookies (latest 50):</b>\n\n" + "\n".join(lines))

@dp.message(Command("delfile"))
async def delfile(m: types.Message):
    if m.from_user.id != ADMIN_ID:
        return
    try:
        fid = int(m.text.split()[1])
        cur.execute("SELECT filename FROM files WHERE id=?", (fid,))
        row = cur.fetchone()
        if not row:
            await m.answer("❌ Cookie not found")
            return
        cur.execute("DELETE FROM files WHERE id=?", (fid,))
        conn.commit()
        await m.answer(f"✅ Deleted #{fid}: {row[0]}")
    except Exception:
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
        except Exception:
            pass
    await m.answer(f"📢 Sent to {sent} users")

@dp.message(Command("help"))
async def help_cmd(m: types.Message):
    if m.from_user.id != ADMIN_ID:
        return
    await m.answer(
        f"<b>🛠 Admin Commands</b>\n\n"
        f"<b>⚙️ Setup</b>\n"
        f"/setstorage -100xxx — storage channel\n"
        f"/setgroup -100xxx — file upload group\n"
        f"/setprice 0 — price per cookie (0=free)\n"
        f"/setgif &lt;file_id&gt; — set Netflix GIF manually\n\n"
        f"<b>🍪 Cookies</b>\n"
        f"/files — list all (latest 50)\n"
        f"/delfile &lt;id&gt; — remove one\n"
        f"Accepted: {' '.join(ALLOWED_EXTENSIONS)} .zip\n"
        f"Max users per cookie: <b>{MAX_USERS_PER_FILE}</b> → auto-deleted\n\n"
        f"<b>👥 Users</b>\n"
        f"/addpoints &lt;uid&gt; &lt;pts&gt;\n"
        f"/setvip &lt;uid&gt; — grant 2hr cooldown\n"
        f"/revokevip &lt;uid&gt; — remove VIP\n"
        f"/resetgen &lt;uid&gt; — reset gen cooldown\n"
        f"/stats — bot statistics\n"
        f"/msend &lt;text&gt; — broadcast\n\n"
        f"<b>📢 Join-wall</b>\n"
        f"/addchannel -100xxx https://t.me/x\n"
        f"/delchannel -100xxx\n"
        f"/channels\n\n"
        f"<b>📦 How ZIP works</b>\n"
        f"Drop .zip in upload group →\n"
        f"Bot extracts + uploads each file to storage →\n"
        f"file_id saved to DB → ZIP deleted from group\n"
        f"Flood control: 1s delay between uploads"
    )

# ─────────────────────────── RUN ───────────────────────────────────── #
async def main():
    print("🎬 Netflix Cookie Bot RUNNING")
    await dp.start_polling(bot)

if __name__ == "__main__":
    asyncio.run(main())
