# Version: 1.3.1 | Location: /bot.py
import os
from dotenv import load_dotenv

import logging
from telegram import (
    Update,
    InlineKeyboardMarkup,
    InlineKeyboardButton,
    BotCommand
)
from telegram.ext import (
    ApplicationBuilder,
    CommandHandler,
    MessageHandler,
    CallbackQueryHandler,
    ContextTypes,
    filters,
    ConversationHandler,
)
import db
import aiosqlite

# Load environment variables from .env file
load_dotenv()

# ================= CONFIG =================
BOT_TOKEN = os.getenv("BOT_TOKEN")
CHANNEL_USERNAME = os.getenv("CHANNEL_USERNAME")
ADMIN_ID = int(os.getenv("ADMIN_ID", 0)) 
WITHDRAW_MIN = 100.0
REFERRAL_BONUS = 5.0

# ================= LOGGING =================
logging.basicConfig(
    format="%(asctime)s - %(name)s - %(levelname)s - %(message)s", level=logging.INFO
)
logger = logging.getLogger(__name__)

# ================= STATES =================
(WITHDRAW_METHOD, WITHDRAW_NUMBER, WITHDRAW_AMOUNT) = range(3)


# ================ KEYBOARDS =================
def main_menu():
    """Generates the Inline Menu attached directly to the message."""
    return InlineKeyboardMarkup(
        [
            [
                InlineKeyboardButton("💰 Balance", callback_data="menu_balance"),
                # InlineKeyboardButton("🎁 Bonus", callback_data="menu_bonus") # HIDDEN FOR NOW
            ],
            [
                InlineKeyboardButton("👥 Refer", callback_data="menu_refer"),
                InlineKeyboardButton("📋 Tasks", callback_data="menu_tasks")
            ],
            [
                InlineKeyboardButton("💳 Withdraw", callback_data="menu_withdraw"),
                InlineKeyboardButton("🚀 Channel", callback_data="menu_channel")
            ],
        ]
    )

# ================ MIDDLEWARE / CHECKS =================
async def is_joined(user_id: int, bot) -> bool:
    """Verifies if the user is currently in the mandatory channel."""
    try:
        member = await bot.get_chat_member(CHANNEL_USERNAME, user_id)
        return member.status in ["member", "administrator", "creator"]
    except Exception as e:
        logger.error(f"Error checking channel membership for {user_id}: {e}")
        return False

async def force_join(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Triggers the force join UI."""
    keyboard = InlineKeyboardMarkup(
        [
            [InlineKeyboardButton("🚀 Join Channel", url=f"https://t.me/{CHANNEL_USERNAME.replace('@', '')}")],
            [InlineKeyboardButton("✅ I've Joined", callback_data="check_join")]
        ]
    )
    msg = "❌ You must join our official channel to use this bot and withdraw earnings!"
    if update.message:
        await update.message.reply_text(msg, reply_markup=keyboard)
    elif update.callback_query:
        await update.callback_query.message.reply_text(msg, reply_markup=keyboard)

# ================ CORE LOGIC =================
async def start(update: Update, context: ContextTypes.DEFAULT_TYPE):
    user = update.effective_user

    # Parse referral ID from deep link
    referrer_id = None
    if context.args and context.args[0].isdigit():
        referrer_id = int(context.args[0])
        if referrer_id == user.id:
            referrer_id = None  

    await db.create_user(user.id, referrer_id)

    if not await is_joined(user.id, context.bot):
        return await force_join(update, context)

    await process_referral_reward(user.id, context)
    
    # Send main menu attached to the message
    await update.message.reply_text(
        "🔥 <b>Welcome back! Choose an option:</b>", 
        reply_markup=main_menu(),
        parse_mode="HTML"
    )

async def process_referral_reward(user_id: int, context: ContextTypes.DEFAULT_TYPE):
    user_data = await db.get_user(user_id)
    if user_data:
        _, ref_id, claimed = user_data
        if ref_id and not claimed:
            await db.update_balance(ref_id, REFERRAL_BONUS)
            await db.mark_reward_claimed(user_id)
            try:
                await context.bot.send_message(
                    ref_id,
                    f"🎉 <b>New Referral!</b>\nSomeone joined using your link. You earned {REFERRAL_BONUS} BDT!",
                    parse_mode="HTML",
                )
            except Exception:
                pass  

async def button_handler(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Handles all inline keyboard callbacks (Menu & Admin actions)."""
    query = update.callback_query
    await query.answer()
    data = query.data
    user_id = query.from_user.id

    # 1. Join Verification
    if data == "check_join":
        if await is_joined(user_id, context.bot):
            await process_referral_reward(user_id, context)
            await query.message.delete()
            await query.message.reply_text(
                "✅ Access Granted! Welcome to the system.", reply_markup=main_menu()
            )
        else:
            await query.message.reply_text("❌ You still haven't joined the channel. Please join first.")

    # 2. Main Menu Routing
    elif data.startswith("menu_"):
        if not await is_joined(user_id, context.bot):
            return await force_join(update, context)

        if data == "menu_balance":
            user_data = await db.get_user(user_id)
            bal = user_data[0] if user_data else 0.0
            await query.edit_message_text(f"💰 <b>Your Balance:</b> {bal:.2f} BDT", parse_mode="HTML", reply_markup=main_menu())

        elif data == "menu_refer":
            link = f"https://t.me/{context.bot.username}?start={user_id}"
            await query.edit_message_text(
                f"👥 <b>Invite & Earn {REFERRAL_BONUS} BDT per user!</b>\n\nShare your link:\n<code>{link}</code>",
                parse_mode="HTML", reply_markup=main_menu()
            )

        elif data == "menu_tasks":
            await query.edit_message_text("📋 Available Tasks:\n1. 👥 Invite Friends (5 BDT per valid invite)\nMore coming soon!", reply_markup=main_menu())

        # DAILY BONUS HIDDEN FOR NOW
        # elif data == "menu_bonus":
        #     await query.edit_message_text("🎁 Daily bonus feature is under construction for optimization.", reply_markup=main_menu())

        elif data == "menu_channel":
            await query.edit_message_text(f"Join our official updates: https://t.me/{CHANNEL_USERNAME.replace('@', '')}", reply_markup=main_menu())

    # 3. Admin Withdrawal Approval/Rejection
    elif data.startswith("wd_"):
        if user_id != ADMIN_ID:
            return await query.message.reply_text("⛔ Unauthorized.")

        action, wd_id = data.split("_")[1], int(data.split("_")[2])
        wd_data = await db.get_withdrawal(wd_id)

        if not wd_data or wd_data[2] != "pending":
            return await query.edit_message_text("⚠️ This withdrawal has already been processed.")

        target_user, amount, _ = wd_data

        if action == "approve":
            await db.update_withdrawal_status(wd_id, "approved")
            await query.edit_message_text(f"{query.message.text}\n\n✅ <b>STATUS: APPROVED</b>", parse_mode="HTML")
            try:
                await context.bot.send_message(target_user, f"✅ Your withdrawal of {amount} BDT has been APPROVED and sent!")
            except: pass

        elif action == "reject":
            await db.update_withdrawal_status(wd_id, "rejected")
            await db.update_balance(target_user, amount)  # Refund balance
            await query.edit_message_text(f"{query.message.text}\n\n❌ <b>STATUS: REJECTED (Refunded)</b>", parse_mode="HTML")
            try:
                await context.bot.send_message(target_user, f"❌ Your withdrawal of {amount} BDT was REJECTED. Funds returned to balance.")
            except: pass


# ================ WITHDRAWAL SYSTEM (Conversation) =================
async def withdraw_start(update: Update, context: ContextTypes.DEFAULT_TYPE):
    query = update.callback_query
    await query.answer()
    user_id = query.from_user.id
    
    if not await is_joined(user_id, context.bot):
        await force_join(update, context)
        return ConversationHandler.END

    data = await db.get_user(user_id)
    bal = data[0] if data else 0.0

    if bal < WITHDRAW_MIN:
        await query.edit_message_text(f"❌ Minimum withdrawal is {WITHDRAW_MIN} BDT. Your balance: {bal:.2f} BDT.", reply_markup=main_menu())
        return ConversationHandler.END

    # Inline Keyboard for method selection
    keyboard = InlineKeyboardMarkup([
        [InlineKeyboardButton("Bkash", callback_data="wdmethod_Bkash"),
         InlineKeyboardButton("Nagad", callback_data="wdmethod_Nagad")],
        [InlineKeyboardButton("Cancel", callback_data="wdmethod_Cancel")]
    ])
    
    await query.edit_message_text("💳 Select your payment method:", reply_markup=keyboard)
    return WITHDRAW_METHOD

async def withdraw_method(update: Update, context: ContextTypes.DEFAULT_TYPE):
    query = update.callback_query
    await query.answer()
    method = query.data.split("_")[1] # Extracts "Bkash", "Nagad", or "Cancel"

    if method == "Cancel":
        await query.edit_message_text("❌ Withdrawal cancelled.", reply_markup=main_menu())
        return ConversationHandler.END

    context.user_data["wd_method"] = method
    await query.edit_message_text(f"📱 Enter your {method} number:")
    return WITHDRAW_NUMBER

async def withdraw_number(update: Update, context: ContextTypes.DEFAULT_TYPE):
    text = update.message.text
    if text.lower() == "cancel":
        await update.message.reply_text("❌ Withdrawal cancelled.", reply_markup=main_menu())
        return ConversationHandler.END

    context.user_data["wd_number"] = text
    data = await db.get_user(update.effective_user.id)
    max_bal = data[0]

    await update.message.reply_text(f"💵 Enter amount to withdraw (Max: {max_bal:.2f} BDT):")
    return WITHDRAW_AMOUNT

async def withdraw_amount(update: Update, context: ContextTypes.DEFAULT_TYPE):
    text = update.message.text
    user_id = update.effective_user.id

    if text.lower() == "cancel":
        await update.message.reply_text("❌ Withdrawal cancelled.", reply_markup=main_menu())
        return ConversationHandler.END

    try:
        amount = float(text)
    except ValueError:
        await update.message.reply_text("❌ Please enter a valid number.")
        return WITHDRAW_AMOUNT

    data = await db.get_user(user_id)
    max_bal = data[0]

    if amount < WITHDRAW_MIN or amount > max_bal:
        await update.message.reply_text(f"❌ Invalid amount. Min: {WITHDRAW_MIN}, Max: {max_bal:.2f}.")
        return WITHDRAW_AMOUNT

    method = context.user_data["wd_method"]
    phone = context.user_data["wd_number"]

    await db.update_balance(user_id, -amount)
    await db.create_withdrawal(user_id, amount, method, phone)

    async with aiosqlite.connect(db.DB_PATH) as conn:
        async with conn.execute("SELECT seq FROM sqlite_sequence WHERE name='withdrawals'") as cursor:
            wd_id = (await cursor.fetchone())[0]

    await update.message.reply_text("✅ Withdrawal request submitted! Pending admin approval.", reply_markup=main_menu())

    # Notify Admin
    admin_text = (
        f"🚨 <b>NEW WITHDRAWAL REQUEST</b>\n"
        f"User ID: <code>{user_id}</code>\n"
        f"Method: {method}\n"
        f"Number: <code>{phone}</code>\n"
        f"Amount: {amount} BDT"
    )
    admin_kb = InlineKeyboardMarkup(
        [
            [
                InlineKeyboardButton("✅ Approve", callback_data=f"wd_approve_{wd_id}"),
                InlineKeyboardButton("❌ Reject", callback_data=f"wd_reject_{wd_id}"),
            ]
        ]
    )
    try:
        await context.bot.send_message(ADMIN_ID, admin_text, reply_markup=admin_kb, parse_mode="HTML")
    except Exception as e:
        logger.error(f"Failed to notify admin: {e}")

    context.user_data.clear()
    return ConversationHandler.END


# ================ MAIN BOOTSTRAP =================
async def post_init(application: ApplicationBuilder):
    await db.init_db()
    
    # This creates the command suggestions menu in the text field
    await application.bot.set_my_commands([
        BotCommand("start", "Restart the bot and show menu")
    ])

def main():
    app = ApplicationBuilder().token(BOT_TOKEN).post_init(post_init).build()

    # Handlers
    app.add_handler(CommandHandler("start", start))
    
    # Withdrawal Conversation handles specific callback logic
    withdraw_conv = ConversationHandler(
        entry_points=[CallbackQueryHandler(withdraw_start, pattern="^menu_withdraw$")],
        states={
            WITHDRAW_METHOD: [
                CallbackQueryHandler(withdraw_method, pattern="^wdmethod_")
            ],
            WITHDRAW_NUMBER: [
                MessageHandler(filters.TEXT & ~filters.COMMAND, withdraw_number)
            ],
            WITHDRAW_AMOUNT: [
                MessageHandler(filters.TEXT & ~filters.COMMAND, withdraw_amount)
            ],
        },
        fallbacks=[CommandHandler("start", start)],
        per_message=False # Explicitly stating intent to silence PTB ambiguity
    )
    app.add_handler(withdraw_conv)
    
    # Main callback handler catches all other button presses
    app.add_handler(CallbackQueryHandler(button_handler))

    logger.info("🚀 Bot Architecture v1.3.1 Initialized & Running...")
    app.run_polling()


if __name__ == "__main__":
    main()

