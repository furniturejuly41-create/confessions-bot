import os
import logging
import re
import sqlite3
import time
import asyncio
import warnings
from telegram import Update, InlineKeyboardButton, InlineKeyboardMarkup, ReplyKeyboardMarkup
from telegram.error import BadRequest, TimedOut, NetworkError
from telegram.ext import (
    Application, CommandHandler, MessageHandler, ContextTypes,
    CallbackQueryHandler, filters, ConversationHandler
)
import google.generativeai as genai
from dotenv import load_dotenv
from database import *

# Suppress harmless PTBUserWarning about per_message=False
warnings.filterwarnings("ignore", category=UserWarning, module="telegram.ext._handlers.conversationhandler")

load_dotenv()
BOT_TOKEN = os.getenv("BOT_TOKEN")
GEMINI_API_KEY = os.getenv("GEMINI_API_KEY", "").strip()
ADMIN_USER_ID = int(os.getenv("ADMIN_USER_ID", 0))
CONFESS_CHANNEL = os.getenv("CONFESS_CHANNEL")
BOT_USERNAME = os.getenv("BOT_USERNAME", "").strip().replace("@", "")

logging.basicConfig(level=logging.INFO, format='%(asctime)s - %(name)s - %(levelname)s - %(message)s')
logger = logging.getLogger(__name__)

if GEMINI_API_KEY and len(GEMINI_API_KEY) > 10 and GEMINI_API_KEY.lower() != "your_gemini_api_key_here":
    genai.configure(api_key=GEMINI_API_KEY)
else:
    logger.warning("⚠️ Gemini API Key is missing or invalid. AI Enhance disabled.")

# --- STATES ---
(
    AWAIT_POLICY, MAIN_MENU, SUBMIT_TEXT, PREVIEW_CONF, EDIT_CONF, SELECT_CATEGORIES, 
    AWAIT_COMMENT, AWAIT_REPLY, SET_NICKNAME, SET_BIO, SET_EMOJI, 
    SETTINGS_MENU, PENDING_EDIT, VIEWING, AWAIT_REPORT_REASON, AWAIT_REPORT_CUSTOM_REASON,
    AWAIT_MEDIA_TEXT, AWAIT_ADMIN_REASON, AWAIT_BROADCAST, AWAIT_AD_REQUEST, AWAIT_PROFILE_DETAIL
) = range(21)

init_db()

CATEGORIES = ["Relationship", "Family", "School", "Religion", "Addiction", "Crush", "Trauma", "Exam", "Friendship", "Mental", "Harassment", "Health", "Sexual", "Other"]
MENU_BUTTONS = {"📖 Browse Feed", "📨 Confess", "👤 Profile", "⚙️ Settings", "🏆 Leaderboard", "ℹ️ Help", "📢 Advertise", "❌ Cancel", "📜 My Confessions"}

# --- PROFILE DETAILS DEFINITIONS ---
DETAIL_FIELDS = [
    ("gender", "👤 Gender", "gender_visible"),
    ("job", "💼 Job", "job_visible"),
    ("age", "🎂 Age", "age_visible"),
    ("work", "🏢 Work", "work_visible"),
    ("marital_status", "💍 Status", "marital_status_visible"),
    ("country", "🌍 Country", "country_visible"),
    ("region", "📍 Region", "region_visible"),
]

# --- PROFESSIONAL TEXT TEMPLATES ---
WELCOME_RULES_TEXT = (
    "📜 *Bot Rules & Regulations*\n\n"
    "To keep the community safe, respectful, and meaningful, please follow these guidelines:\n\n"
    "1. *Stay Relevant:* Mainly for sharing confessions, experiences, and thoughts.\n"
    "2. *Respectful Communication:* Sensitive topics allowed but must be discussed with respect.\n"
    "3. *No Harmful Content:* Mentioning names is at your own risk. Removal requests will be honored.\n"
    "4. *Names & Responsibility:* Do not share personal identifying information.\n"
    "5. *Anonymity & Privacy:* Don't reveal private details of others without consent.\n"
    "6. *Constructive Environment:* Keep confessions genuine. Avoid spam, trolling, or repeated submissions.\n\n"
    "Use this space to connect, share, and learn, not to spread misinformation or cause unnecessary drama."
)

HELP_TEXT = (
    "📘 *Welcome to Abyssinia Confessions!*\n\n"
    "This is your ultimate guide to using the bot, connecting with peers, and making the most of our community features.\n\n"
    
    "🛠️ *1. Core Commands*\n"
    "• /start - Launch the bot and view the main menu.\n"
    "• /confess - Submit a new anonymous confession (Text, Photo, or Video).\n"
    "• /profile - View your profile, stats, and manage your details.\n"
    "• /help - Display this help guide.\n"
    "• /privacy - Read our comprehensive Privacy Policy.\n\n"
    
    "📝 *2. Sharing Confessions*\n"
    "• Submit text, photos, or videos completely anonymously.\n"
    "• *AI Enhance:* Use the ✨ AI Enhance button to let our AI improve your grammar and flow before submitting.\n"
    "• *Categories:* Tag your confession with up to 3 categories to help others find it.\n\n"
    
    "💬 *3. Comments & Interactions*\n"
    "• Comment using text, voice notes, stickers, or GIFs!\n"
    "• React with 👍 (Like) or 👎 (Dislike) to show your opinion.\n"
    "• *Highlight:* Spend 5 ⭐️ Stars to highlight your comment, making it stand out at the top of the thread!\n\n"
    
    "👤 *4. Profile & Networking*\n"
    "• *Profile Details:* Set your gender, age, job, etc. Use the 👁️/🙈 toggles to control exactly what is visible to others.\n"
    "• *Network:* Follow other users to see their new posts in your Activity Feed. Send 💬 Chat Requests to connect privately.\n\n"
    
    "✨ *5. Aura Points & Stars (Gamification)*\n"
    "• *Aura Points:* Earn +1 Aura for commenting, and earn more when your comments get liked or you get followed!\n"
    "• *Stars:* Automatically earn 1 ⭐️ Star for every 10 Aura Points. Claim your free daily Stars using the 🎁 Daily Reward button in your profile.\n"
    "• *Leaderboard:* Check the 🏆 Leaderboard to see the top contributors in the community.\n\n"
    
    "🛡️ *6. Safety & Moderation*\n"
    "• *Report:* Use the 🚩 Report button on any user's profile to report spam, harassment, or rule violations.\n"
    "• *Admin Actions:* Admins can issue ⚠️ Warnings, ⏳ 24-Hour Blocks, or 🚫 Permanent Bans to keep the community safe.\n\n"
    
    "📩 *Need Help?*\n"
    "If you need assistance, want to request the deletion of a published confession, or want to reach the admin directly, please use the connection features or reply to this message!\n\n"
    
    "_Share anonymously. Connect privately. Earn rewards. Welcome to the community!_"
)

PRIVACY_TEXT = (
    "🔒 *Privacy Policy & Data Protection*\n\n"
    "Welcome to the Abyssinia Confessions Bot. Your privacy, anonymity, and data security are our highest priorities. This policy explains what information we collect, how we use it, and how we protect you.\n\n"
    "📊 *1. Information We Collect*\n"
    "• *Telegram User ID:* Collected automatically to enable bot functionality, track Aura/Star points, and manage your account.\n"
    "• *Optional Profile Data:* Nickname, bio, and demographic details (gender, age, job, marital status, country, region). *Note: You have full control over the visibility of these details via the Profile Settings.*\n"
    "• *User-Generated Content:* Confessions, comments, replies, and reactions you make within the bot.\n\n"
    "🛡️ *2. Anonymity & Privacy Guarantees*\n"
    "• *Public Anonymity:* All confessions posted to the public channel are 100% anonymous. Other users cannot see your Telegram username, phone number, or real identity.\n"
    "• *Admin Access:* Administrators can view your Telegram User ID *solely* for moderation purposes (e.g., processing reports, enforcing warnings/bans, or fulfilling deletion requests). Admins cannot access your phone number or private Telegram data.\n"
    "• *No Third-Party Sharing:* We do not sell, rent, or share your personal data with any third parties, advertisers, or external organizations.\n\n"
    "🤖 *3. Third-Party Services (AI Enhancement)*\n"
    "If you use the 'AI Enhance' feature, the text of your confession is temporarily sent to Google's Gemini API for grammar and flow improvement. This text is processed securely and is not used to identify you.\n\n"
    "🗑️ *4. Data Retention & Your Rights*\n"
    "• *Right to Delete:* You can request the permanent deletion of any of your pending confessions via the 'My Confessions' menu. For published confessions or profile data, please contact the administration.\n"
    "• *Data Retention:* Your data is stored securely on our servers only for as long as the bot is active. If the bot is discontinued, all user data will be permanently erased.\n\n"
    "📩 *5. Contact Us*\n"
    "If you have any questions, concerns, or requests regarding your privacy or data, please use the `/help` command to contact the bot administration directly.\n\n"
    "_By using this bot, you acknowledge that you have read and agree to this Privacy Policy and our Community Rules._"
)

# --- BULLETPROOF HELPER FUNCTIONS ---
def get_aura_title(aura):
    if aura >= 500: return "👑 Legend"
    if aura >= 200: return "🌟 Influencer"
    if aura >= 50: return "✨ Regular"
    return "🌱 Novice"

def save_user(user):
    create_user(user.id)
    if user.username:
        current = get_user(user.id)
        if current and current['telegram_username'] is None:
            update_user(user.id, telegram_username=f"@{user.username}")

async def safe_admin_update(q, text):
    try:
        if q.message.text:
            await q.message.edit_text(text, parse_mode="Markdown")
        else:
            await q.message.edit_caption(text, parse_mode="Markdown")
    except (BadRequest, TimedOut, NetworkError):
        try:
            await q.message.reply_text(text, parse_mode="Markdown")
        except:
            pass

async def send_menu(update):
    kb = [
        ["📖 Browse Feed", "📨 Confess"],
        ["👤 Profile", "⚙️ Settings"],
        ["🏆 Leaderboard", "ℹ️ Help"],
        ["📢 Advertise", "❌ Cancel"]
    ]
    text = "✨ *Abyssinia Confessions*\n\nShare anonymously. Connect privately. Earn rewards."
    reply_markup = ReplyKeyboardMarkup(kb, resize_keyboard=True)
    
    try:
        if update.message:
            await update.message.reply_text(text, parse_mode="Markdown", reply_markup=reply_markup)
        elif update.callback_query:
            await update.callback_query.message.reply_text(text, parse_mode="Markdown", reply_markup=reply_markup)
    except (BadRequest, TimedOut, NetworkError):
        pass

async def handle_menu_buttons(update: Update, context: ContextTypes.DEFAULT_TYPE):
    text = update.message.text.strip()
    context.user_data.clear()
    if text == "📖 Browse Feed":
        channel_username = CONFESS_CHANNEL.replace("@", "")
        await update.message.reply_text("📢 *Public Channel*\n\nJoin there to read, comment, and earn Stars!", parse_mode="Markdown", reply_markup=InlineKeyboardMarkup([[InlineKeyboardButton("📢 Open Channel", url=f"https://t.me/{channel_username}")]]))
        return MAIN_MENU
    elif text == "📨 Confess":
        await update.message.reply_text("🤫 *Submit Confession*\n\nPlease send your anonymous confession (Text, Photo, or Video).", parse_mode="Markdown")
        return SUBMIT_TEXT
    elif text == "👤 Profile": return await show_profile(update, context)
    elif text == "⚙️ Settings": return await show_settings(update, context)
    elif text == "🏆 Leaderboard": return await show_leaderboard(update, context)
    elif text == "📜 My Confessions": return await show_my_confessions(update, context)
    elif text == "📢 Advertise":
        await update.message.reply_text("📢 *Request Advertisement*\n\nPlease send the details of your advertisement (Text, Photo, or Video) along with your offer. The admin will review it.", parse_mode="Markdown")
        return AWAIT_AD_REQUEST
    elif text == "ℹ️ Help": return await show_help(update, context)
    elif text == "❌ Cancel":
        await update.message.reply_text("🛑 *Action Cancelled*", parse_mode="Markdown", reply_markup=ReplyKeyboardMarkup([["📖 Browse Feed", "📨 Confess"]], resize_keyboard=True))
        return MAIN_MENU
    return MAIN_MENU

# --- GLOBAL MENU INTERCEPTOR (Functional at ANY time) ---
async def global_menu_interceptor(update: Update, context: ContextTypes.DEFAULT_TYPE):
    text = update.message.text.strip()
    if text in MENU_BUTTONS:
        context.user_data.clear()
        return await handle_menu_buttons(update, context)
    return ConversationHandler.END

async def update_channel(context, conf_id):
    conf = get_confession(conf_id)
    if not conf or not conf['approved'] or not conf['channel_msg_id']: return
    stats = get_confession_stats(conf_id)
    try:
        btn = InlineKeyboardButton(f"💬 Read & Add Comments ({stats['comments']})", url=f"https://t.me/{BOT_USERNAME}?start=conf_{conf_id}")
        await context.bot.edit_message_reply_markup(chat_id=CONFESS_CHANNEL, message_id=conf['channel_msg_id'], reply_markup=InlineKeyboardMarkup([[btn]]))
    except (BadRequest, TimedOut, NetworkError) as e:
        if "Message is not modified" not in str(e): logger.warning(f"Channel button update failed: {e}")

def build_comment_markup(comment, current_user_id, is_reply=False):
    like_btn = InlineKeyboardButton(f"👍 {comment['likes']}", callback_data=f"l_{comment['id']}")
    dis_btn = InlineKeyboardButton(f"👎 {comment['dislikes']}", callback_data=f"d_{comment['id']}")
    rep_btn = InlineKeyboardButton("↪️ Reply", callback_data=f"r_{comment['id']}")
    prof_btn = InlineKeyboardButton("👤 Profile", callback_data=f"vprof_{comment['user_id']}")
    if is_reply: return InlineKeyboardMarkup([[like_btn, dis_btn, rep_btn], [prof_btn]])
    else:
        chat_btn = InlineKeyboardButton("🤝 Connect", callback_data=f"chat_{comment['user_id']}_{comment['confession_id']}_{comment['id']}")
        star_btn = InlineKeyboardButton("⭐️ Highlight (5)", callback_data=f"star_{comment['id']}") if not comment.get('is_highlighted') else InlineKeyboardButton("🌟 Highlighted", callback_data="noop")
        return InlineKeyboardMarkup([[like_btn, dis_btn, rep_btn], [prof_btn, chat_btn], [star_btn]])

# --- Start & Exact Rules Flow ---
async def start(update: Update, context: ContextTypes.DEFAULT_TYPE):
    user = update.effective_user
    save_user(user)
    u = get_user(user.id)
    
    if context.args and context.args[0].startswith("accept_"):
        req_id = int(context.args[0].split("_")[1])
        req = get_chat_request(req_id)
        if req and req['to_user_id'] == user.id and req['status'] == 'pending':
            update_chat_request(req_id, 'accepted')
            from_u = get_user(req['from_user_id']); to_u = get_user(user.id)
            from_un = from_u['telegram_username'] or "Anonymous"; to_un = to_u['telegram_username'] or "Anonymous"
            try: await context.bot.send_message(req['from_user_id'], f"✅ *Request Accepted!*\n\nContact: {to_un}", parse_mode="Markdown")
            except: pass
            if update.message: await update.message.reply_text(f"✅ *Request Accepted!*\n\nContact: {from_un}", parse_mode="Markdown")
            return MAIN_MENU

    if context.args and context.args[0].startswith("conf_"):
        if not u.get('accepted_policy'):
            context.user_data['pending_conf_id'] = int(context.args[0].split("_")[1])
            return await _show_policy(update)
        cid = int(context.args[0].split("_")[1])
        conf = get_confession(cid)
        if conf and conf['approved']:
            context.user_data['conf_id'] = cid
            await show_confession_intro(update, context)
            return VIEWING

    if not u.get('accepted_policy'): return await _show_policy(update)
    await send_menu(update)
    return MAIN_MENU

async def _show_policy(update):
    kb = [[InlineKeyboardButton("✅ I Accept the Rules", callback_data="accept_policy")], [InlineKeyboardButton("❌ Decline", callback_data="decline_policy")]]
    try:
        if update.message: await update.message.reply_text(WELCOME_RULES_TEXT, parse_mode="Markdown", reply_markup=InlineKeyboardMarkup(kb))
        elif update.callback_query: await update.callback_query.message.reply_text(WELCOME_RULES_TEXT, parse_mode="Markdown", reply_markup=InlineKeyboardMarkup(kb))
    except (BadRequest, TimedOut, NetworkError): pass
    return AWAIT_POLICY

async def handle_policy(update: Update, context: ContextTypes.DEFAULT_TYPE):
    query = update.callback_query; await query.answer()
    if query.data == "accept_policy":
        accept_privacy_policy(query.from_user.id)
        try: await query.message.edit_text("✅ *Welcome to the Community!*\n\nYou have accepted the rules. You now have full access to all features.", parse_mode="Markdown")
        except: pass
        pending_cid = context.user_data.get('pending_conf_id'); context.user_data.pop('pending_conf_id', None)
        if pending_cid and get_confession(pending_cid):
            context.user_data['conf_id'] = pending_cid; await show_confession_intro(update, context); return VIEWING
        await send_menu(query); return MAIN_MENU
    else:
        try: await query.message.edit_text("❌ *Access Denied*\n\nYou must accept the rules to use this bot.", parse_mode="Markdown")
        except: pass
        return ConversationHandler.END

# --- AI Enhance (ROBUST) ---
async def ai_enhance_text(text):
    if not GEMINI_API_KEY or len(GEMINI_API_KEY) < 10 or GEMINI_API_KEY.lower() == "your_gemini_api_key_here":
        return None, "API key is missing or invalid in .env file."
    try:
        model = genai.GenerativeModel('gemini-3.8-flash')
        resp = await model.generate_content_async(
            f"Improve the grammar, flow, and emotional impact of this text while keeping the original meaning, tone, and anonymity intact. Do not add fake details. Return ONLY the improved text.\n\nText:\n{text}"
        )
        if resp.text:
            return resp.text.strip().strip('"').strip("'").strip(), None
        return None, "AI returned an empty response."
    except Exception as e:
        return None, str(e)

# --- Submission Flow ---
async def submit_receive(update: Update, context: ContextTypes.DEFAULT_TYPE):
    if update.message.text and update.message.text.strip() in MENU_BUTTONS: return await global_menu_interceptor(update, context)
    user_id = update.effective_user.id
    is_blocked, block_type = is_user_blocked(user_id)
    if is_blocked:
        await update.message.reply_text("🚫 *Access Restricted*", parse_mode="Markdown")
        return MAIN_MENU

    media_type = None; media_file_id = None; text = ""
    if update.message.photo:
        media_type = "photo"; media_file_id = update.message.photo[-1].file_id; text = update.message.caption or ""
    elif update.message.video:
        media_type = "video"; media_file_id = update.message.video.file_id; text = update.message.caption or ""
    elif update.message.text:
        text = update.message.text.strip()

    if len(text) < 10:
        if media_type:
            context.user_data['draft_media_type'] = media_type; context.user_data['draft_media_file_id'] = media_file_id; context.user_data['draft_text'] = text
            await update.message.reply_text("📝 *Caption Required*\n\nPlease send the text for your media (min 10 chars).", parse_mode="Markdown")
            return AWAIT_MEDIA_TEXT
        await update.message.reply_text("❌ *Message Too Short*\n\nMinimum 10 characters required.", parse_mode="Markdown")
        return SUBMIT_TEXT

    context.user_data['draft_confession'] = text; context.user_data['draft_media_type'] = media_type; context.user_data['draft_media_file_id'] = media_file_id; context.user_data['draft_categories'] = []
    await show_preview(update, context)
    return PREVIEW_CONF

async def await_media_text_receive(update: Update, context: ContextTypes.DEFAULT_TYPE):
    if update.message.text and update.message.text.strip() in MENU_BUTTONS: return await global_menu_interceptor(update, context)
    text = update.message.text.strip()
    if len(text) < 10:
        await update.message.reply_text("❌ *Message Too Short*", parse_mode="Markdown")
        return AWAIT_MEDIA_TEXT
    context.user_data['draft_confession'] = text; context.user_data['draft_categories'] = []
    await show_preview(update, context)
    return PREVIEW_CONF

async def show_preview(update: Update, context: ContextTypes.DEFAULT_TYPE):
    text = context.user_data.get('draft_confession', '')
    media_type = context.user_data.get('draft_media_type')
    media_file_id = context.user_data.get('draft_media_file_id')
    kb = [
        [InlineKeyboardButton("✏️ Edit", callback_data="prev_edit"), InlineKeyboardButton("✨ AI Enhance", callback_data="prev_ai")],
        [InlineKeyboardButton("🚀 Submit", callback_data="prev_submit")], 
        [InlineKeyboardButton("❌ Cancel", callback_data="prev_cancel")]
    ]
    try:
        if media_type == "photo": 
            await update.effective_message.reply_photo(photo=media_file_id, caption=f"👀 *Preview*\n\n{text}", parse_mode="Markdown", reply_markup=InlineKeyboardMarkup(kb))
        elif media_type == "video": 
            await update.effective_message.reply_video(video=media_file_id, caption=f"👀 *Preview*\n\n{text}", parse_mode="Markdown", reply_markup=InlineKeyboardMarkup(kb), supports_streaming=True)
        else: 
            await update.effective_message.reply_text(f"👀 *Preview*\n\n{text}", parse_mode="Markdown", reply_markup=InlineKeyboardMarkup(kb))
    except (BadRequest, TimedOut, NetworkError) as e:
        logger.error(f"Preview send failed: {e}")
        await update.effective_message.reply_text("⚠️ *Network error or invalid media.* Please try submitting again.", parse_mode="Markdown")
        context.user_data.clear()
        return MAIN_MENU

async def preview_callback(update: Update, context: ContextTypes.DEFAULT_TYPE):
    q = update.callback_query
    await q.answer()
    if q.data == "prev_edit": 
        await q.message.reply_text("✏️ *Edit*\n\nSend updated text:", parse_mode="Markdown")
        return EDIT_CONF
    elif q.data == "prev_ai":
        await q.answer("⏳ Processing with AI...")
        try:
            await q.message.edit_text("⏳ *AI is enhancing your text... Please wait.*", parse_mode="Markdown")
        except (BadRequest, TimedOut, NetworkError):
            pass
            
        enhanced, error = await ai_enhance_text(context.user_data['draft_confession'])
        if enhanced:
            context.user_data['draft_confession'] = enhanced
            await q.message.reply_text("✅ *AI Enhancement Successful!* Your text has been improved.", parse_mode="Markdown")
            await show_preview(update, context)
        else:
            await q.message.reply_text(f"⚠️ *AI Enhance Failed*\n\nReason: `{error}`", parse_mode="Markdown")
            await show_preview(update, context)
        return PREVIEW_CONF
    elif q.data == "prev_submit": await show_category_selection(q.message, context); return SELECT_CATEGORIES
    elif q.data == "prev_cancel":
        await q.message.reply_text("🛑 *Cancelled*", parse_mode="Markdown")
        context.user_data.clear(); await send_menu(q); return MAIN_MENU
    return PREVIEW_CONF

async def edit_conf_receive(update: Update, context: ContextTypes.DEFAULT_TYPE):
    if update.message.text and update.message.text.strip() in MENU_BUTTONS: return await global_menu_interceptor(update, context)
    context.user_data['draft_confession'] = update.message.text.strip()
    await show_preview(update, context); return PREVIEW_CONF

async def show_category_selection(message, context):
    cats = context.user_data.get('draft_categories', [])
    kb, row = [], []
    for c in CATEGORIES:
        row.append(InlineKeyboardButton(f"✅ {c}" if c in cats else c, callback_data=f"cat_{c}"))
        if len(row) == 2: kb.append(row); row = []
    if row: kb.append(row)
    kb.append([InlineKeyboardButton(f"✅ Done ({len(cats)}/3)", callback_data="cat_done"), InlineKeyboardButton("❌ Cancel", callback_data="cat_cancel")])
    try:
        await message.reply_text("🏷️ *Great! Now, please choose categories for your confession.*", parse_mode="Markdown", reply_markup=InlineKeyboardMarkup(kb))
    except (BadRequest, TimedOut, NetworkError): pass

async def category_callback(update: Update, context: ContextTypes.DEFAULT_TYPE):
    q = update.callback_query; await q.answer()
    if q.data.startswith("cat_") and q.data not in ["cat_done", "cat_cancel"]:
        cat = q.data[4:]; cats = context.user_data.get('draft_categories', [])
        if cat in cats: cats.remove(cat)
        elif len(cats) < 3: cats.append(cat)
        else: await q.answer("Max 3!", show_alert=True); return SELECT_CATEGORIES
        context.user_data['draft_categories'] = cats
        kb, row = [], []
        for c in CATEGORIES:
            row.append(InlineKeyboardButton(f"✅ {c}" if c in cats else c, callback_data=f"cat_{c}"))
            if len(row) == 2: kb.append(row); row = []
        if row: kb.append(row)
        kb.append([InlineKeyboardButton(f"✅ Done ({len(cats)}/3)", callback_data="cat_done"), InlineKeyboardButton("❌ Cancel", callback_data="cat_cancel")])
        try: await q.message.edit_text("🏷️ *Great! Now, please choose categories for your confession.*", parse_mode="Markdown", reply_markup=InlineKeyboardMarkup(kb))
        except (BadRequest, TimedOut, NetworkError): pass
        return SELECT_CATEGORIES
    elif q.data == "cat_done":
        cats = context.user_data.get('draft_categories', [])
        cat_str = " ".join([f"#{c}" for c in cats]) if cats else "#General"
        cid = save_confession(q.from_user.id, context.user_data['draft_confession'], context.user_data.get('draft_media_type'), context.user_data.get('draft_media_file_id'), cat_str)
        try: await q.message.delete()
        except: pass
        await context.bot.send_message(q.from_user.id, "📤 *Submitted!*\n\nAwaiting admin review.", parse_mode="Markdown")
        admin_msg = f"🆕 *New Submission #{cid}*\n\n🏷️ {cat_str}\n\n{context.user_data['draft_confession']}"
        try:
            if context.user_data.get('draft_media_type') == "photo":
                await context.bot.send_photo(ADMIN_USER_ID, context.user_data['draft_media_file_id'], caption=admin_msg, parse_mode="Markdown", reply_markup=InlineKeyboardMarkup([[InlineKeyboardButton("✅ Approve", callback_data=f"aok_{cid}"), InlineKeyboardButton("❌ Reject", callback_data=f"ano_{cid}")]]))
            elif context.user_data.get('draft_media_type') == "video":
                await context.bot.send_video(ADMIN_USER_ID, context.user_data['draft_media_file_id'], caption=admin_msg, parse_mode="Markdown", reply_markup=InlineKeyboardMarkup([[InlineKeyboardButton("✅ Approve", callback_data=f"aok_{cid}"), InlineKeyboardButton("❌ Reject", callback_data=f"ano_{cid}")]]), supports_streaming=True)
            else:
                await context.bot.send_message(ADMIN_USER_ID, admin_msg, parse_mode="Markdown", reply_markup=InlineKeyboardMarkup([[InlineKeyboardButton("✅ Approve", callback_data=f"aok_{cid}"), InlineKeyboardButton("❌ Reject", callback_data=f"ano_{cid}")]]))
        except (BadRequest, TimedOut, NetworkError) as e:
            logger.error(f"Admin submission failed: {e}")
            await q.message.reply_text("⚠️ *Network error.* Please try submitting again.", parse_mode="Markdown")
            return MAIN_MENU
        context.user_data.clear(); await send_menu(q); return MAIN_MENU
    elif q.data == "cat_cancel":
        try: await q.message.delete()
        except: pass
        context.user_data.clear(); await send_menu(q); return MAIN_MENU
    return SELECT_CATEGORIES

# --- PREMIUM PROFILE UI ---
async def show_profile(update: Update, context: ContextTypes.DEFAULT_TYPE):
    user_id = update.effective_user.id
    u = get_user(user_id)
    title = get_aura_title(u['aura_points'])
    bio_text = u['bio'] if u['bio'] and u['bio'] != "No bio set" else "_Tap 'Customize Profile' to add a bio._"
    
    text = (
        f"👤 *{u['nickname']}*  •  {u['emoji']}\n"
        f"🏅 *Rank:* {title}\n"
        f"━━━━━━━━━━━━━━━━━━━━\n"
        f"✨ *Aura Points:* `{u['aura_points']}`   ⭐️ *Stars:* `{u['star_balance']}`\n"
        f"👥 *Followers:* `{u['followers_count']}`   🫂 *Following:* `{u['following_count']}`\n"
        f"━━━━━━━━━━━━━━━━━━━━\n"
        f"📝 *Bio:*\n{bio_text}\n"
    )
    kb = [
        [InlineKeyboardButton("🎁 Claim Daily Reward", callback_data="daily_reward")],
        [InlineKeyboardButton("✏️ Customize Profile", callback_data="prof_edit")],
        [InlineKeyboardButton("📝 Profile Details", callback_data="prof_details")],
        [InlineKeyboardButton("📜 My Confessions", callback_data="prof_confs")],
        [InlineKeyboardButton("📢 Activity", callback_data="prof_activity"), InlineKeyboardButton("👥 Network", callback_data="prof_network")],
        [InlineKeyboardButton("⚙️ Preferences", callback_data="prof_settings"), InlineKeyboardButton("💌 Connections", callback_data="prof_chats")]
    ]
    try:
        if update.message: await update.message.reply_text(text, parse_mode="Markdown", reply_markup=InlineKeyboardMarkup(kb))
        else: await update.callback_query.message.edit_text(text, parse_mode="Markdown", reply_markup=InlineKeyboardMarkup(kb))
    except (BadRequest, TimedOut, NetworkError): pass
    return MAIN_MENU

# --- ADVANCED PROFILE DETAILS & VISIBILITY ---
async def show_profile_details_view(update: Update, context: ContextTypes.DEFAULT_TYPE):
    user_id = update.effective_user.id
    user = get_user(user_id)
    
    text = "📝 *Profile Details & Visibility*\n\n"
    text += "Manage what others see on your public profile.\n"
    text += "👁️ = Visible to others | 🙈 = Hidden\n\n"
    
    kb = []
    for field_key, label, vis_key in DETAIL_FIELDS:
        val = user.get(field_key)
        if val in [None, '', 0]:
            display_val = "Not Set"
        else:
            display_val = str(val)
            
        is_visible = user.get(vis_key, 0)
        vis_icon = "👁️" if is_visible else "🙈"
        
        text += f"{label}: {display_val} {vis_icon}\n"
        
        kb.append([
            InlineKeyboardButton("✏️ Edit", callback_data=f"det_edit:{field_key}"),
            InlineKeyboardButton(f"{vis_icon} Toggle", callback_data=f"det_vis:{field_key}")
        ])
        
    kb.append([InlineKeyboardButton("🔙 Back to Profile", callback_data="prof_back")])
    
    try:
        if update.callback_query:
            await update.callback_query.message.edit_text(text, parse_mode="Markdown", reply_markup=InlineKeyboardMarkup(kb))
        else:
            await update.message.reply_text(text, parse_mode="Markdown", reply_markup=InlineKeyboardMarkup(kb))
    except (BadRequest, TimedOut, NetworkError): pass
    return MAIN_MENU

async def handle_profile_detail_callback(update: Update, context: ContextTypes.DEFAULT_TYPE):
    q = update.callback_query
    data = q.data
    
    if data.startswith("det_edit:"):
        field_key = data.split(":")[1]
        context.user_data['editing_detail'] = field_key
        
        if field_key == "gender":
            kb = [
                [InlineKeyboardButton("Male", callback_data="det_val:gender:Male"), InlineKeyboardButton("Female", callback_data="det_val:gender:Female")],
                [InlineKeyboardButton("Prefer not to say", callback_data="det_val:gender:")]
            ]
            await q.message.reply_text("Select your gender:", reply_markup=InlineKeyboardMarkup(kb))
        elif field_key == "marital_status":
            kb = [
                [InlineKeyboardButton("Single", callback_data="det_val:marital_status:Single"), InlineKeyboardButton("Married", callback_data="det_val:marital_status:Married")],
                [InlineKeyboardButton("Divorced", callback_data="det_val:marital_status:Divorced"), InlineKeyboardButton("Widowed", callback_data="det_val:marital_status:Widowed")],
                [InlineKeyboardButton("Prefer not to say", callback_data="det_val:marital_status:")]
            ]
            await q.message.reply_text("Select your marital status:", reply_markup=InlineKeyboardMarkup(kb))
        else:
            await q.message.reply_text(f"Please enter your {field_key.replace('_', ' ').title()}:")
            return AWAIT_PROFILE_DETAIL
            
    elif data.startswith("det_val:"):
        parts = data.split(":", 2)
        if len(parts) >= 3:
            field_key = parts[1]
            val = parts[2]
            update_user(q.from_user.id, **{field_key: val})
            await q.message.reply_text(f"✅ Updated {field_key.replace('_', ' ').title()}!")
        return await show_profile_details_view(update, context)
        
    elif data.startswith("det_vis:"):
        field_key = data.split(":")[1]
        vis_key = f"{field_key}_visible"
        user = get_user(q.from_user.id)
        current_val = user.get(vis_key, 0)
        update_user(q.from_user.id, **{vis_key: not current_val})
        await q.answer("Visibility toggled!")
        return await show_profile_details_view(update, context)
        
    return MAIN_MENU

async def handle_profile_detail_text(update: Update, context: ContextTypes.DEFAULT_TYPE):
    if update.message.text and update.message.text.strip() in MENU_BUTTONS: return await global_menu_interceptor(update, context)
    field_key = context.user_data.get('editing_detail')
    if not field_key:
        return MAIN_MENU
        
    text = update.message.text.strip()
    if field_key == "age":
        if not text.isdigit():
            await update.message.reply_text("❌ Please enter a valid number for age.")
            return AWAIT_PROFILE_DETAIL
        val = int(text)
    else:
        val = text
        
    update_user(update.effective_user.id, **{field_key: val})
    await update.message.reply_text(f"✅ Updated {field_key.replace('_', ' ').title()}!")
    context.user_data.pop('editing_detail', None)
    return await show_profile_details_view(update, context)

async def handle_daily_reward(update: Update, context: ContextTypes.DEFAULT_TYPE):
    q = update.callback_query; await q.answer()
    success, message = claim_daily_reward(q.from_user.id)
    await q.message.reply_text(message, parse_mode="Markdown")
    return MAIN_MENU

# --- ADVANCED PAGINATED NETWORK MANAGEMENT ---
async def show_network(update: Update, context: ContextTypes.DEFAULT_TYPE):
    q = update.callback_query; await q.answer()
    user_id = q.from_user.id
    u = get_user(user_id)
    
    kb = [
        [InlineKeyboardButton(f"🫂 Followers ({u['followers_count']})", callback_data="net_view_fol_0")],
        [InlineKeyboardButton(f"👣 Following ({u['following_count']})", callback_data="net_view_fing_0")],
        [InlineKeyboardButton("🔙 Back to Profile", callback_data="prof_back")]
    ]
    try: await q.message.edit_text("👥 *Network Management*\n\nSelect a list to view and manage:", parse_mode="Markdown", reply_markup=InlineKeyboardMarkup(kb))
    except (BadRequest, TimedOut, NetworkError): pass
    return MAIN_MENU

async def show_list_page(update: Update, context: ContextTypes.DEFAULT_TYPE, list_type: str, page: int):
    q = update.callback_query
    await q.answer()
    user_id = q.from_user.id
    
    limit = 5
    if list_type == 'fol':
        items, total = get_followers_paginated(user_id, page, limit)
        title = "🫂 *Your Followers*"
    else:
        items, total = get_following_paginated(user_id, page, limit)
        title = "👣 *Users You Follow*"
        
    total_pages = max(1, (total + limit - 1) // limit)
    
    text = f"{title}\n\n*Total:* {total} | *Page:* {page + 1}/{total_pages}\n\n"
    kb = []
    
    for target_id in items:
        target_user = get_user(target_id)
        if target_user:
            name = target_user['nickname']
            if list_type == 'fing':
                kb.append([
                    InlineKeyboardButton(f"💬 Chat {name}", callback_data=f"net_req_{target_id}"),
                    InlineKeyboardButton(f"❌ Unfollow", callback_data=f"net_unf_{target_id}_{page}")
                ])
            else:
                kb.append([
                    InlineKeyboardButton(f"💬 Chat {name}", callback_data=f"net_req_{target_id}"),
                    InlineKeyboardButton(f"👤 Profile", callback_data=f"vprof_{target_id}")
                ])
            
    nav_row = []
    if page > 0:
        nav_row.append(InlineKeyboardButton("⬅️ Prev", callback_data=f"net_view_{list_type}_{page-1}"))
    if (page + 1) * limit < total:
        nav_row.append(InlineKeyboardButton("Next ➡️", callback_data=f"net_view_{list_type}_{page+1}"))
    
    if nav_row:
        kb.append(nav_row)
        
    kb.append([InlineKeyboardButton("🔙 Back to Network", callback_data="prof_network")])
    
    if not items:
        text += "_This list is empty._"
        
    try:
        await q.message.edit_text(text, parse_mode="Markdown", reply_markup=InlineKeyboardMarkup(kb))
    except (BadRequest, TimedOut, NetworkError):
        await q.message.reply_text(text, parse_mode="Markdown", reply_markup=InlineKeyboardMarkup(kb))
    return MAIN_MENU

# --- DELETION REQUEST FLOW ---
async def show_my_confessions(update: Update, context: ContextTypes.DEFAULT_TYPE):
    user_id = update.effective_user.id; u = get_user(user_id); confs = get_user_confessions(user_id)
    approved_count = sum(1 for c in confs if c['approved']); pending_count = sum(1 for c in confs if not c['approved'])
    text = f"📜 *Your Confessions*\n✨ Aura: {u['aura_points']}\n📊 ✅ {approved_count} Live | ⏳ {pending_count} Pending\n\n"
    kb = []
    if not confs: text += "_None yet._"
    else:
        for c in confs[:10]:
            status = "✅ Live" if c['approved'] else "⏳ Pending"
            preview = c['text'][:60] + "..." if len(c['text']) > 60 else c['text']
            text += f"🆔 *#{c['id']}* ({status})\n_{preview}_\n\n"
            if not c['approved']: kb.append([InlineKeyboardButton(f"🗑️ Request Deletion #{c['id']}", callback_data=f"req_del_{c['id']}")])
    kb.append([InlineKeyboardButton("🔙 Back", callback_data="prof_back")])
    try:
        if update.message: await update.message.reply_text(text, parse_mode="Markdown", reply_markup=InlineKeyboardMarkup(kb))
        else: await update.callback_query.message.edit_text(text, parse_mode="Markdown", reply_markup=InlineKeyboardMarkup(kb))
    except (BadRequest, TimedOut, NetworkError): pass
    return MAIN_MENU

async def handle_request_deletion(update: Update, context: ContextTypes.DEFAULT_TYPE):
    q = update.callback_query; await q.answer()
    conf_id = int(q.data.split("_")[2]); user_id = q.from_user.id
    conf = get_confession(conf_id)
    if not conf or conf['user_id'] != user_id: await q.message.reply_text("❌ Not found."); return MAIN_MENU
    if conf['approved']: await q.message.reply_text("❌ *Cannot Delete*\n\nAlready live. Use /help to contact admin.", parse_mode="Markdown"); return MAIN_MENU
    
    admin_msg = f"🗑️ *Deletion Request*\n\n🆔 #{conf_id}\n👤 `{user_id}`\n\n_{conf['text'][:150]}_"
    kb = [[InlineKeyboardButton("🗑️ Delete Permanently", callback_data=f"del_perm_{conf_id}")], [InlineKeyboardButton("✅ Approve Anyway", callback_data=f"aok_{conf_id}")]]
    try:
        await context.bot.send_message(ADMIN_USER_ID, admin_msg, parse_mode="Markdown", reply_markup=InlineKeyboardMarkup(kb))
        await q.message.reply_text("✅ *Request Sent*\n\nThe admin has been notified.", parse_mode="Markdown")
    except (BadRequest, TimedOut, NetworkError):
        await q.message.reply_text("⚠️ *Network error.* Please try again.", parse_mode="Markdown")
    return MAIN_MENU

async def show_my_chats(update: Update, context: ContextTypes.DEFAULT_TYPE):
    user_id = update.effective_user.id; requests = get_user_chat_requests(user_id)
    text = "💌 *My Chats*\n\n"
    if not requests: text += "_No requests._"
    else:
        for req in requests[:5]:
            status_emoji = "⏳" if req['status'] == 'pending' else ("✅" if req['status'] == 'accepted' else "❌")
            other_party = req['to_nick'] if req['from_user_id'] == user_id else req['from_nick']
            text += f"{status_emoji} *{other_party}*\n"
    kb = [[InlineKeyboardButton("🔙 Back", callback_data="prof_back")]]
    try:
        if update.message: await update.message.reply_text(text, parse_mode="Markdown", reply_markup=InlineKeyboardMarkup(kb))
        else: await update.callback_query.message.edit_text(text, parse_mode="Markdown", reply_markup=InlineKeyboardMarkup(kb))
    except (BadRequest, TimedOut, NetworkError): pass
    return MAIN_MENU

async def show_leaderboard(update: Update, context: ContextTypes.DEFAULT_TYPE):
    top_users = get_leaderboard(10)
    if not top_users: await update.message.reply_text("🏆 *Leaderboard*\n\n_No points yet._", parse_mode="Markdown"); return MAIN_MENU
    text = "🏆 *Top Leaders*\n\n"; medals = ["🥇", "🥈", "🥉"]
    for i, u in enumerate(top_users):
        medal = medals[i] if i < 3 else f"#{i+1}"
        text += f"{medal} *{u['nickname']}* • {u['aura_points']}✨ | ⭐️ {u['star_balance']}\n"
    await update.message.reply_text(text, parse_mode="Markdown"); return MAIN_MENU

# --- Profile Editing ---
async def profile_edit_menu(update: Update, context: ContextTypes.DEFAULT_TYPE):
    q = update.callback_query; await q.answer()
    kb = [[InlineKeyboardButton("😀 Emoji", callback_data="edit_emoji")], [InlineKeyboardButton("📝 Nickname", callback_data="edit_nick")],
          [InlineKeyboardButton("📖 Bio", callback_data="edit_bio")], [InlineKeyboardButton("🔙 Back", callback_data="prof_back")]]
    try: await q.message.edit_text("✏️ *Customization*", parse_mode="Markdown", reply_markup=InlineKeyboardMarkup(kb))
    except (BadRequest, TimedOut, NetworkError): pass
    return MAIN_MENU

async def handle_profile_edit(update: Update, context: ContextTypes.DEFAULT_TYPE):
    q = update.callback_query; await q.answer()
    if q.data == "edit_emoji": await q.message.reply_text("😀 Send emoji:"); return SET_EMOJI
    elif q.data == "edit_nick": await q.message.reply_text("📝 Send nickname:"); return SET_NICKNAME
    elif q.data == "edit_bio": await q.message.reply_text("📖 Send bio:"); return SET_BIO
    elif q.data == "prof_back": await show_profile(update, context); return MAIN_MENU
    return MAIN_MENU

async def set_emoji(update: Update, context: ContextTypes.DEFAULT_TYPE):
    if update.message.text.strip() in MENU_BUTTONS: return await global_menu_interceptor(update, context)
    e = update.message.text.strip()
    if len(e) > 2: await update.message.reply_text("❌ Single emoji only."); return SET_EMOJI
    update_user(update.effective_user.id, emoji=e)
    await update.message.reply_text(f"✅ {e}"); await show_profile(update, context)
    return MAIN_MENU

async def set_nickname(update: Update, context: ContextTypes.DEFAULT_TYPE):
    if update.message.text.strip() in MENU_BUTTONS: return await global_menu_interceptor(update, context)
    n = update.message.text.strip()
    if len(n) > 30: await update.message.reply_text("❌ Max 30."); return SET_NICKNAME
    update_user(update.effective_user.id, nickname=n)
    await update.message.reply_text(f"✅ {n}"); await show_profile(update, context)
    return MAIN_MENU

async def set_bio(update: Update, context: ContextTypes.DEFAULT_TYPE):
    if update.message.text.strip() in MENU_BUTTONS: return await global_menu_interceptor(update, context)
    b = update.message.text.strip()
    if len(b) > 150: await update.message.reply_text("❌ Max 150."); return SET_BIO
    update_user(update.effective_user.id, bio=b)
    await update.message.reply_text("✅ Updated!"); await show_profile(update, context)
    return MAIN_MENU

# --- PREMIUM SETTINGS UI & NOTIFICATION CENTER ---
async def _send_settings_menu(message, user_id):
    user = get_user(user_id)
    voice_display = user['voice_effect']
    if voice_display != 'Original': voice_display = f"{voice_display} 🎙️"
    text = (
        f"⚙️ *Bot Preferences*\n\n"
        f"🗂 *Display Settings*\n└ 📄 *Comments per page:* `{user['comments_per_page']}`\n\n"
        f"🔒 *Privacy & Social*\n└ 💬 *Allow Chat Requests:* {'✅ Enabled' if user['allow_chats'] else '❌ Disabled'}\n\n"
        f"🎙️ *Audio Settings*\n└ 🎛️ *Voice Effect:* `{voice_display}`\n"
    )
    kb = [
        [InlineKeyboardButton(f"📄 Change Page Size ({user['comments_per_page']})", callback_data="set_cpp")],
        [InlineKeyboardButton(f"💬 {'Disable' if user['allow_chats'] else 'Enable'} Chat Requests", callback_data="set_chat_req")],
        [InlineKeyboardButton("🎛️ Configure Voice Effect", callback_data="set_voice")],
        [InlineKeyboardButton("🔔 Notification Center", callback_data="set_notif")],
        [InlineKeyboardButton("🔙 Back to Profile", callback_data="prof_back")]
    ]
    try: await message.edit_text(text, parse_mode="Markdown", reply_markup=InlineKeyboardMarkup(kb))
    except (BadRequest, TimedOut, NetworkError): pass

async def show_settings(update: Update, context: ContextTypes.DEFAULT_TYPE):
    if update.callback_query: await _send_settings_menu(update.callback_query.message, update.effective_user.id)
    else: 
        try:
            msg = await update.message.reply_text("Loading...")
            await _send_settings_menu(msg, update.effective_user.id)
        except (BadRequest, TimedOut, NetworkError): pass
    return SETTINGS_MENU

async def settings_callback(update: Update, context: ContextTypes.DEFAULT_TYPE):
    q = update.callback_query; await q.answer(); user_id = q.from_user.id; user = get_user(user_id)
    if q.data == "set_chat_req": update_user(user_id, allow_chats=not user['allow_chats']); await q.answer("Updated")
    elif q.data == "set_voice":
        try:
            await q.message.edit_text("🎤 *Voice Effect*\n\nSaved & displayed as a badge!", parse_mode="Markdown", reply_markup=InlineKeyboardMarkup([
                [InlineKeyboardButton("Original", callback_data="voice_Original"), InlineKeyboardButton("Manly", callback_data="voice_Manly")],
                [InlineKeyboardButton("Female", callback_data="voice_Female"), InlineKeyboardButton("Chipmunk", callback_data="voice_Chipmunk")], [InlineKeyboardButton("🔙 Back", callback_data="prof_settings")]]))
        except (BadRequest, TimedOut, NetworkError): pass
        return SETTINGS_MENU
    elif q.data.startswith("voice_"): update_user(user_id, voice_effect=q.data.split("_")[1]); await q.answer("Set")
    elif q.data == "set_notif":
        kb = [
            [InlineKeyboardButton(f"💬 Comment: {'On' if user['notify_comment'] else 'Off'}", callback_data="notif_comment")],
            [InlineKeyboardButton(f"↪️ Reply: {'On' if user['notify_reply'] else 'Off'}", callback_data="notif_reply")],
            [InlineKeyboardButton(f"👍 Like: {'On' if user['notify_like'] else 'Off'}", callback_data="notif_like")],
            [InlineKeyboardButton(f"👥 Follow: {'On' if user['notify_follow'] else 'Off'}", callback_data="notif_follow")],
            [InlineKeyboardButton(f"📢 Activity: {'On' if user.get('notify_activity', 1) else 'Off'}", callback_data="notif_activity")],
            [InlineKeyboardButton("🔙 Back", callback_data="prof_settings")]
        ]
        try: await q.message.edit_text("🔔 *Notification Center*\n\nManage your alerts:", parse_mode="Markdown", reply_markup=InlineKeyboardMarkup(kb))
        except (BadRequest, TimedOut, NetworkError): pass
        return SETTINGS_MENU
    elif q.data.startswith("notif_"):
        field = q.data.split("_")[1]
        map_field = {
            "comment": "notify_comment", "reply": "notify_reply", "like": "notify_like", 
            "follow": "notify_follow", "activity": "notify_activity"
        }
        if field in map_field:
            db_field = map_field[field]
            current_val = user.get(db_field, 1)
            update_user(user_id, **{db_field: not current_val})
            await q.answer("Updated")
            user = get_user(user_id)
            kb = [
                [InlineKeyboardButton(f"💬 Comment: {'On' if user['notify_comment'] else 'Off'}", callback_data="notif_comment")],
                [InlineKeyboardButton(f"↪️ Reply: {'On' if user['notify_reply'] else 'Off'}", callback_data="notif_reply")],
                [InlineKeyboardButton(f"👍 Like: {'On' if user['notify_like'] else 'Off'}", callback_data="notif_like")],
                [InlineKeyboardButton(f"👥 Follow: {'On' if user['notify_follow'] else 'Off'}", callback_data="notif_follow")],
                [InlineKeyboardButton(f"📢 Activity: {'On' if user.get('notify_activity', 1) else 'Off'}", callback_data="notif_activity")],
                [InlineKeyboardButton("🔙 Back", callback_data="prof_settings")]
            ]
            try: await q.message.edit_text("🔔 *Notification Center*\n\nManage your alerts:", parse_mode="Markdown", reply_markup=InlineKeyboardMarkup(kb))
            except (BadRequest, TimedOut, NetworkError): pass
            return SETTINGS_MENU
    elif q.data == "set_cpp":
        options = [10, 15, 20, 30]; idx = options.index(user['comments_per_page']) if user['comments_per_page'] in options else 1
        update_user(user_id, comments_per_page=options[(idx + 1) % len(options)]); await q.answer("Updated")
    elif q.data == "prof_back": await show_profile(update, context); return MAIN_MENU
    if q.data not in ["set_notif", "set_voice", "prof_back"]: await _send_settings_menu(q.message, user_id)
    return SETTINGS_MENU

# --- Menu Router ---
async def menu_router(update: Update, context: ContextTypes.DEFAULT_TYPE):
    t = update.message.text.strip()
    if t in MENU_BUTTONS: return await global_menu_interceptor(update, context)
    await send_menu(update); return MAIN_MENU

# --- FUNCTIONAL /help & /privacy COMMANDS ---
async def show_help(update: Update, context: ContextTypes.DEFAULT_TYPE):
    try:
        if update.message: await update.message.reply_text(HELP_TEXT, parse_mode="Markdown")
        elif update.callback_query and update.callback_query.message: await update.callback_query.message.reply_text(HELP_TEXT, parse_mode="Markdown")
    except (BadRequest, TimedOut, NetworkError): pass

async def show_privacy(update: Update, context: ContextTypes.DEFAULT_TYPE):
    try:
        if update.message: await update.message.reply_text(PRIVACY_TEXT, parse_mode="Markdown")
        elif update.callback_query and update.callback_query.message: await update.callback_query.message.reply_text(PRIVACY_TEXT, parse_mode="Markdown")
    except (BadRequest, TimedOut, NetworkError): pass

# --- View Confession Flow ---
async def show_confession_intro(update: Update, context: ContextTypes.DEFAULT_TYPE):
    cid = context.user_data.get('conf_id')
    if not cid: return MAIN_MENU
    conf = get_confession(cid)
    if not conf or not conf['approved']: return MAIN_MENU
    
    stats = get_confession_stats(cid)
    header = f"🪪 *Confession #{cid}*\n\n{conf['text']}\n\n🏷️ {conf.get('categories') or '#General'}"
    if update.callback_query:
        await update.callback_query.answer()
        try: await update.callback_query.message.delete()
        except: pass

    try:
        if conf.get('media_type') == 'photo': 
            await update.effective_message.reply_photo(photo=conf['media_file_id'], caption=header, parse_mode='Markdown')
        elif conf.get('media_type') == 'video': 
            await update.effective_message.reply_video(video=conf['media_file_id'], caption=header, parse_mode='Markdown', supports_streaming=True)
        else: 
            await update.effective_message.reply_text(header, parse_mode='Markdown')

        await update.effective_message.reply_text(
            f"💬 *Total Comments:* {stats['comments']}\n\n"
            "👇 *What would you like to do?*", 
            parse_mode="Markdown",
            reply_markup=InlineKeyboardMarkup([
                [InlineKeyboardButton("➕ Add Comment", callback_data=f"c_{cid}")],
                [InlineKeyboardButton("🔄 Browse Comments", callback_data=f"browse_{cid}")]
            ])
        )
    except (BadRequest, TimedOut, NetworkError): pass
    return VIEWING

async def show_confession_comments(update: Update, context: ContextTypes.DEFAULT_TYPE):
    cid = context.user_data.get('conf_id')
    if not cid: return MAIN_MENU
    
    limit = get_user(update.effective_user.id)['comments_per_page']
    comments = get_comments(cid, limit=limit)
    
    # --- FORCE SORT BY LIKES (MOST LIKED AT THE TOP) ---
    comments.sort(key=lambda x: x.get('likes', 0), reverse=True)
    for c in comments:
        if c.get('replies'):
            c['replies'].sort(key=lambda x: x.get('likes', 0), reverse=True)
            
    current_user = update.effective_user.id
    
    if not comments: 
        await update.effective_message.reply_text("💬 _No comments yet. Be the first!_", parse_mode="Markdown")
    else:
        for c in comments:
            user_display = c['nickname'] or "Anonymous"
            aura_badge = f" [{get_aura_title(c['aura_points'])} | {c['aura_points']}✨]" if c['aura_points'] > 0 else ""
            markup = build_comment_markup(c, current_user, is_reply=False)
            
            try:
                if c['media_type'] == 'voice':
                    effect_tag = f" 🎙️ *[{c.get('voice_effect', 'Original').upper()}]*" if c.get('voice_effect') != 'Original' else " 🎙️"
                    await context.bot.send_voice(chat_id=update.effective_chat.id, voice=c['media_file_id'], caption=f"{c['emoji']} *{user_display}*{aura_badge}{effect_tag}", parse_mode="Markdown", reply_markup=markup)
                elif c['media_type'] == 'sticker':
                    await context.bot.send_sticker(chat_id=update.effective_chat.id, sticker=c['media_file_id'])
                    await update.effective_message.reply_text(f"{c['emoji']} *{user_display}*{aura_badge}", parse_mode="Markdown", reply_markup=markup)
                elif c['media_type'] == 'animation':
                    await context.bot.send_animation(chat_id=update.effective_chat.id, animation=c['media_file_id'], caption=f"{c['emoji']} *{user_display}*{aura_badge}", parse_mode="Markdown", reply_markup=markup)
                else:
                    await update.effective_message.reply_text(f"{c['emoji']} *{user_display}*{aura_badge}:\n_{c['text']}_", parse_mode='Markdown', reply_markup=markup)
                    
                for r in c.get('replies', []):
                    user_r = r['nickname'] or "Anonymous"; aura_badge_r = f" [{get_aura_title(r['aura_points'])}]" if r['aura_points'] > 0 else ""
                    reply_markup = build_comment_markup(r, current_user, is_reply=True)
                    
                    if r['media_type'] == 'sticker':
                        await context.bot.send_sticker(chat_id=update.effective_chat.id, sticker=r['media_file_id'], reply_to_message_id=update.effective_message.message_id)
                        await update.effective_message.reply_text(f"  ↳ {r['emoji']} *{user_r}*{aura_badge_r}", parse_mode="Markdown", reply_markup=reply_markup)
                    elif r['media_type'] == 'animation':
                        await context.bot.send_animation(chat_id=update.effective_chat.id, animation=r['media_file_id'], caption=f"  ↳ {r['emoji']} *{user_r}*{aura_badge_r}", parse_mode="Markdown", reply_to_message_id=update.effective_message.message_id, reply_markup=reply_markup)
                    else:
                        await update.effective_message.reply_text(f"  ↳ {r['emoji']} *{user_r}*{aura_badge_r}:\n_{r['text']}_", parse_mode="Markdown", reply_markup=reply_markup)
            except (BadRequest, TimedOut, NetworkError): pass

    try:
        await update.effective_message.reply_text(
            "👇 *Actions:*", 
            parse_mode="Markdown",
            reply_markup=InlineKeyboardMarkup([
                [InlineKeyboardButton("➕ Add Comment", callback_data=f"c_{cid}")],
                [InlineKeyboardButton("🔄 Refresh", callback_data=f"browse_{cid}")]
            ])
        )
    except (BadRequest, TimedOut, NetworkError): pass
    return VIEWING

# --- Comment Handling (WITH REPLY NOTIFICATION) ---
async def handle_comment_input(update: Update, context: ContextTypes.DEFAULT_TYPE):
    if update.message.text and update.message.text.strip() in MENU_BUTTONS: return await global_menu_interceptor(update, context)
    user_id = update.effective_user.id
    is_blocked, _ = is_user_blocked(user_id)
    if is_blocked: await update.message.reply_text("🚫 *Restricted*", parse_mode="Markdown"); return MAIN_MENU
    cid = context.user_data.get('on') or context.user_data.get('conf_id'); parent = context.user_data.get('reply')
    if not cid: await update.message.reply_text("❌ *Expired*", parse_mode="Markdown"); return MAIN_MENU
    
    media_type = None; media_file_id = None; text = "Media"; user = get_user(user_id); voice_effect = 'Original'
    
    if update.message.voice:
        media_type = "voice"; media_file_id = update.message.voice.file_id; voice_effect = user.get('voice_effect', 'Original')
        text = f"🎙️ *[{voice_effect.upper()}]* Voice"
    elif update.message.sticker:
        media_type = "sticker"; media_file_id = update.message.sticker.file_id; text = "🎭 Sticker"
    elif update.message.animation:
        media_type = "animation"; media_file_id = update.message.animation.file_id; text = "🎬 GIF"
    elif update.message.text:
        text = update.message.text.strip()
        if len(text) > 280: await update.message.reply_text("❌ *Max 280*", parse_mode="Markdown"); return AWAIT_COMMENT if parent is None else AWAIT_REPLY
    else: 
        await update.message.reply_text("❌ *Unsupported Format*\n\nPlease send text, a voice note, a sticker, or a GIF.", parse_mode="Markdown")
        return AWAIT_COMMENT if parent is None else AWAIT_REPLY
    
    add_comment(cid, user_id, text, media_type=media_type, media_file_id=media_file_id, voice_effect=voice_effect, parent_id=parent)
    add_aura_points(user_id, 1)
    
    if parent:
        parent_author_id = get_comment_author(parent)
        if parent_author_id and parent_author_id != user_id:
            parent_author = get_user(parent_author_id)
            if parent_author and parent_author.get('notify_reply', 1):
                try:
                    await context.bot.send_message(parent_author_id, "🔔 *Notification*\n\nSomeone replied to your comment!", parse_mode="Markdown")
                except (BadRequest, TimedOut, NetworkError): pass

    await update_channel(context, cid)
    await update.message.reply_text("✅ *Added! +1✨*", parse_mode="Markdown")
    context.user_data['reply'] = None; context.user_data['conf_id'] = cid
    await show_confession_comments(update, context); return VIEWING

# --- Global Callback Router (BULLETPROOF & NOTIFICATIONS) ---
async def global_callback(update: Update, context: ContextTypes.DEFAULT_TYPE):
    q = update.callback_query; await q.answer(); data = q.data
    
    if data.startswith("aok_") or data.startswith("ano_"): return await admin_callback(update, context)
    elif data.startswith("del_perm_"): return await admin_delete_permanent(update, context)
    elif data.startswith("admin_history_"): return await admin_view_history(update, context)
    elif data.startswith("admin_"): return await admin_moderation_global(update, context)
    elif data.startswith("ad_"): return await admin_ad_decision(update, context)

    if data.startswith("v_"): context.user_data['conf_id'] = int(data[2:]); await show_confession_intro(update, context); return VIEWING
    elif data.startswith("browse_"):
        cid = int(data.split("_")[1]); context.user_data['conf_id'] = cid; await show_confession_comments(update, context); return VIEWING
    elif data.startswith("c_"): context.user_data['on'] = int(data[2:]); context.user_data['reply'] = None; await q.message.reply_text("*📝 Please send your comment as text, a Voice, a Sticker, or a GIF:*", parse_mode="Markdown"); return AWAIT_COMMENT
    elif data.startswith("r_"): context.user_data['reply'] = int(data[2:]); await q.message.reply_text("✏️ *Reply:*", parse_mode="Markdown"); return AWAIT_REPLY
    
    elif data.startswith("vprof_"):
        target_id = int(data.split("_")[1]); target_user = get_user(target_id); current_id = q.from_user.id
        if not target_user: await q.message.reply_text("❌ Not found."); return VIEWING
        title = get_aura_title(target_user['aura_points']); bio = target_user['bio'] if target_user['bio'] and target_user['bio'] != "No bio set" else "_No bio._"
        follow_text = "👤 Unfollow" if is_following(current_id, target_id) else "➕ Follow"
        
        text = f"👤 *{target_user['nickname']}* [{title}]\n\n"
        text += f"✨ Aura: {target_user['aura_points']} | ⭐️ Stars: {target_user['star_balance']}\n"
        text += f"👥 Followers: {target_user['followers_count']} | Following: {target_user['following_count']}\n"
        text += f"📖 Bio: {bio}\n\n"
        
        details_text = "📝 *Public Details:*\n"
        has_details = False
        if target_user.get('gender_visible') and target_user.get('gender'): details_text += f"👤 Gender: {target_user['gender']}\n"; has_details = True
        if target_user.get('age_visible') and target_user.get('age'): details_text += f"🎂 Age: {target_user['age']}\n"; has_details = True
        if target_user.get('job_visible') and target_user.get('job'): details_text += f"💼 Job: {target_user['job']}\n"; has_details = True
        if target_user.get('work_visible') and target_user.get('work'): details_text += f"🏢 Work: {target_user['work']}\n"; has_details = True
        if target_user.get('marital_status_visible') and target_user.get('marital_status'): details_text += f"💍 Status: {target_user['marital_status']}\n"; has_details = True
        if target_user.get('country_visible') and target_user.get('country'): details_text += f"🌍 Country: {target_user['country']}\n"; has_details = True
        if target_user.get('region_visible') and target_user.get('region'): details_text += f"📍 Region: {target_user['region']}\n"; has_details = True
            
        if has_details: text += details_text
            
        kb = [[InlineKeyboardButton(follow_text, callback_data=f"follow_{target_id}")], [InlineKeyboardButton("🚩 Report", callback_data=f"report_{target_id}"), InlineKeyboardButton("💬 Chat", callback_data=f"chat_prof_{target_id}")]]
        try:
            if q.message.text: await q.message.edit_text(text, parse_mode="Markdown", reply_markup=InlineKeyboardMarkup(kb))
            else: await q.message.reply_text(text, parse_mode="Markdown", reply_markup=InlineKeyboardMarkup(kb))
        except (BadRequest, TimedOut, NetworkError): pass
        return VIEWING
        
    elif data.startswith("report_"):
        target_id = int(data.split("_")[1]); context.user_data['report_target_id'] = target_id
        kb = [[InlineKeyboardButton("Spam", callback_data="rep_reason_Spam")], [InlineKeyboardButton("Harassment", callback_data="rep_reason_Harassment")], [InlineKeyboardButton("Inappropriate", callback_data="rep_reason_Inappropriate")], [InlineKeyboardButton("Skip", callback_data="rep_reason_Skip")], [InlineKeyboardButton("Other", callback_data="rep_reason_Other")]]
        await q.message.reply_text("🚩 *Reason:*", parse_mode="Markdown", reply_markup=InlineKeyboardMarkup(kb)); return AWAIT_REPORT_REASON
        
    elif data.startswith("chat_prof_"):
        target_id = int(data.split("_")[2]); target_user = get_user(target_id)
        if not target_user['allow_chats']: await q.message.reply_text("❌ *Disabled*", parse_mode="Markdown"); return VIEWING
        req_id = create_chat_request(q.from_user.id, target_id, 0, 0)
        try:
            await context.bot.send_message(target_id, f"✨ *Connect?*", parse_mode="Markdown", reply_markup=InlineKeyboardMarkup([[InlineKeyboardButton("✅ Yes", url=f"https://t.me/{BOT_USERNAME}?start=accept_{req_id}")], [InlineKeyboardButton("❌ No", callback_data=f"decline_{req_id}")]]))
            await q.message.reply_text("💌 *Sent*", parse_mode="Markdown")
        except (BadRequest, TimedOut, NetworkError):
            await q.message.reply_text("❌ *Failed to send.*", parse_mode="Markdown")
        return VIEWING
        
    elif data.startswith("chat_"):
        parts = data.split("_"); to_id, conf_id, comm_id = int(parts[1]), int(parts[2]), int(parts[3])
        target_user = get_user(to_id)
        if not target_user['allow_chats']: await q.message.reply_text("❌ *Disabled*", parse_mode="Markdown"); return VIEWING
        req_id = create_chat_request(q.from_user.id, to_id, conf_id, comm_id)
        try:
            await context.bot.send_message(to_id, f"✨ *Connect?*", parse_mode="Markdown", reply_markup=InlineKeyboardMarkup([[InlineKeyboardButton("✅ Yes", url=f"https://t.me/{BOT_USERNAME}?start=accept_{req_id}")], [InlineKeyboardButton("❌ No", callback_data=f"decline_{req_id}")]]))
            await q.message.reply_text("💌 *Sent*", parse_mode="Markdown")
        except (BadRequest, TimedOut, NetworkError):
            await q.message.reply_text("❌ *Failed to send.*", parse_mode="Markdown")
        return VIEWING
        
    elif data.startswith("decline_"): 
        update_chat_request(int(data.split("_")[1]), 'declined')
        try: await q.message.edit_text("❌ *Declined*", parse_mode="Markdown")
        except: pass
        return VIEWING
    
    elif data.startswith(("l_", "d_")):
        reaction = "like" if data.startswith("l_") else "dislike"; comm_id = int(data[2:])
        likes, dislikes = toggle_reaction(q.from_user.id, comm_id, reaction)
        author_id = get_comment_author(comm_id)
        if author_id and author_id != q.from_user.id:
            if reaction == "like": add_aura_points(author_id, 1)
            else: add_aura_points(author_id, -1)
            author_user = get_user(author_id)
            if author_user and author_user.get('notify_like', 1):
                action = "liked 👍" if reaction == "like" else "disliked 👎"
                try: await context.bot.send_message(author_id, f"🔔 *Notification*\n\nSomeone {action} your comment!", parse_mode="Markdown")
                except (BadRequest, TimedOut, NetworkError): pass
        conn = sqlite3.connect(DB); conn.row_factory = sqlite3.Row; c = conn.cursor(); c.execute("SELECT * FROM comments WHERE id = ?", (comm_id,)); comment = dict(c.fetchone()); conn.close()
        markup = build_comment_markup(comment, q.from_user.id, comment['parent_id'] is not None)
        try: await q.message.edit_reply_markup(reply_markup=markup)
        except (BadRequest, TimedOut, NetworkError): pass
        await q.answer(f"Reacted: {reaction}!"); return VIEWING
        
    elif data.startswith("star_"):
        comm_id = int(data.split("_")[1]); user_id = q.from_user.id; user = get_user(user_id)
        if user['star_balance'] >= 5:
            spend_stars(user_id, 5); highlight_comment(comm_id); await q.answer("🌟 Comment Highlighted!"); await show_confession_comments(update, context)
        else:
            await q.answer(f"❌ Need 5 Stars. You have {user['star_balance']}.", show_alert=True)
        return VIEWING
        
    elif data == "noop": await q.answer("Already highlighted!", show_alert=True); return VIEWING
    
    elif data.startswith("follow_"):
        target_id = int(data.split("_")[1]); current_id = q.from_user.id
        is_mutual = is_following(target_id, current_id)
        if is_following(current_id, target_id):
            unfollow_user(current_id, target_id); await q.answer("Unfollowed")
        else:
            follow_user(current_id, target_id); await q.answer("Followed!"); add_aura_points(target_id, 1)
            target_user = get_user(target_id); follower_user = get_user(current_id)
            follower_name = follower_user['nickname'] if follower_user else "Anonymous"
            target_name = target_user['nickname'] if target_user else "Anonymous"
            if target_user and target_user.get('notify_follow', 1):
                try: await context.bot.send_message(target_id, f"🔔 *New Follower*\n\n*{follower_name}* started following you!", parse_mode="Markdown")
                except (BadRequest, TimedOut, NetworkError): pass
            if is_mutual:
                current_user = get_user(current_id)
                current_name = current_user['nickname'] if current_user else "Anonymous"
                if current_user and current_user.get('notify_follow', 1):
                    try: await context.bot.send_message(current_id, f"🔔 *Mutual Follow*\n\nYou and *{target_name}* are now following each other!", parse_mode="Markdown")
                    except (BadRequest, TimedOut, NetworkError): pass
                if target_user and target_user.get('notify_follow', 1):
                    try: await context.bot.send_message(target_id, f"🔔 *Mutual Follow*\n\nYou and *{current_name}* are now following each other!", parse_mode="Markdown")
                    except (BadRequest, TimedOut, NetworkError): pass
        await show_confession_intro(update, context); return VIEWING

    # --- ADVANCED NETWORK & PROFILE DETAILS ROUTING ---
    elif data.startswith("prof_details"): return await show_profile_details_view(update, context)
    elif data.startswith("det_edit:") or data.startswith("det_vis:") or data.startswith("det_val:"): return await handle_profile_detail_callback(update, context)
    
    elif data.startswith("prof_activity"): 
        await q.message.reply_text("📢 *Activity Feed*\n\nCheck your Notification Settings to manage alerts from users you follow!", parse_mode="Markdown")
        return MAIN_MENU
    elif data.startswith("prof_network"): return await show_network(update, context)
    elif data.startswith("net_view_fol_"):
        page = int(data.split("_")[3]); return await show_list_page(update, context, 'fol', page)
    elif data.startswith("net_view_fing_"):
        page = int(data.split("_")[3]); return await show_list_page(update, context, 'fing', page)
    elif data.startswith("net_unf_"):
        parts = data.split("_"); target_id = int(parts[2]); page = int(parts[3])
        unfollow_user(q.from_user.id, target_id); await q.answer("Unfollowed!")
        return await show_list_page(update, context, 'fing', page)
    elif data.startswith("net_req_"):
        target_id = int(data.split("_")[2]); from_id = q.from_user.id
        if target_id == from_id: await q.answer("You can't request a chat with yourself!", show_alert=True); return VIEWING
        req_id = create_chat_request(from_id, target_id, 0, 0)
        target_user = get_user(target_id); from_user = get_user(from_id)
        try:
            await context.bot.send_message(target_id, f"✨ *New Chat Request*\n\n{from_user['emoji']} *{from_user['nickname']}* wants to connect with you!", parse_mode="Markdown", reply_markup=InlineKeyboardMarkup([[InlineKeyboardButton("✅ Accept", callback_data=f"acc_net_{req_id}")], [InlineKeyboardButton("❌ Decline", callback_data=f"dec_net_{req_id}")]]))
            await q.message.reply_text("💌 *Request Sent!*", parse_mode="Markdown")
        except (BadRequest, TimedOut, NetworkError):
            await q.message.reply_text("❌ *Failed to send request.*", parse_mode="Markdown")
        return VIEWING
    elif data.startswith("acc_net_"):
        req_id = int(data.split("_")[2]); req = get_chat_request(req_id)
        if req and req['status'] == 'pending':
            update_chat_request(req_id, 'accepted')
            from_u = get_user(req['from_user_id']); to_u = get_user(req['to_user_id'])
            from_un = from_u['telegram_username'] or f"ID: {req['from_user_id']}"; to_un = to_u['telegram_username'] or f"ID: {req['to_user_id']}"
            try:
                await context.bot.send_message(req['from_user_id'], f"✅ *Request Accepted!*\n\nContact: {to_un}", parse_mode="Markdown")
                await q.message.edit_text("✅ *Accepted!*", parse_mode="Markdown")
            except (BadRequest, TimedOut, NetworkError): pass
        return MAIN_MENU
    elif data.startswith("dec_net_"):
        req_id = int(data.split("_")[2]); update_chat_request(req_id, 'declined')
        try: await q.message.edit_text("❌ *Declined*", parse_mode="Markdown")
        except: pass
        return MAIN_MENU
        
    return MAIN_MENU

# --- Report Handlers ---
async def handle_report_reason(update: Update, context: ContextTypes.DEFAULT_TYPE):
    q = update.callback_query; await q.answer(); reason = q.data.split("rep_reason_", 1)[1]
    if reason == "Other": await q.message.reply_text("📝 *Custom Reason:*", parse_mode="Markdown"); return AWAIT_REPORT_CUSTOM_REASON
    else: 
        await submit_report(context, q.from_user.id, context.user_data.get('report_target_id'), reason, context.user_data.get('conf_id', 0), context.user_data.get('reply', 0))
        await q.message.reply_text("✅ *Reported*", parse_mode="Markdown"); return VIEWING

async def handle_report_custom(update: Update, context: ContextTypes.DEFAULT_TYPE):
    if update.message.text.strip() in MENU_BUTTONS: return await global_menu_interceptor(update, context)
    await submit_report(context, update.effective_user.id, context.user_data.get('report_target_id'), update.message.text.strip(), context.user_data.get('conf_id', 0), context.user_data.get('reply', 0))
    await update.message.reply_text("✅ *Reported*", parse_mode="Markdown"); return VIEWING

async def submit_report(context, reporter_id, target_id, reason, conf_id, comm_id):
    add_report(reporter_id, target_id, conf_id, comm_id, reason)
    target_user = get_user(target_id); target_name = target_user['nickname'] if target_user else "Unknown"
    total_reports = get_user_report_count(target_id)
    report_msg = (
        f"🚨 *New User Report*\n\n"
        f"👤 *Target:* {target_name} (`ID: {target_id}`)\n"
        f"📊 *Total Reports:* {total_reports}\n"
        f"📝 *Reason:* {reason}\n"
        f"📍 *Context:* Confession #{conf_id} | Comment #{comm_id}\n"
        f"🕵️ *Reporter:* `ID: {reporter_id}`"
    )
    kb = [
        [InlineKeyboardButton("⚠️ Warn", callback_data=f"admin_warn_{target_id}"), InlineKeyboardButton("⏳ Block 24h", callback_data=f"admin_block_{target_id}")],
        [InlineKeyboardButton("🚫 Perm Ban", callback_data=f"admin_ban_{target_id}"), InlineKeyboardButton("✅ Dismiss", callback_data=f"admin_dismiss_{target_id}")],
        [InlineKeyboardButton("📊 View Full History", callback_data=f"admin_history_{target_id}")]
    ]
    try: await context.bot.send_message(ADMIN_USER_ID, report_msg, parse_mode="Markdown", reply_markup=InlineKeyboardMarkup(kb))
    except (BadRequest, TimedOut, NetworkError): pass

async def admin_view_history(update: Update, context: ContextTypes.DEFAULT_TYPE):
    q = update.callback_query; await q.answer()
    target_id = int(q.data.split("_")[2]); target_user = get_user(target_id); target_name = target_user['nickname'] if target_user else "Unknown"
    reports = get_user_reports(target_id, limit=5); confs = get_user_confessions(target_id)
    text = f"📊 *User History: {target_name} (`ID: {target_id}`)*\n\n*Recent Reports ({len(reports)}):*\n"
    for r in reports: text += f"• {r['reason']} (Conf: #{r['confession_id']})\n"
    text += f"\n*Recent Confessions ({len(confs)}):*\n"
    for c in confs[:3]:
        status = "Live" if c['approved'] else "Pending"
        text += f"• #{c['id']} ({status}): {c['text'][:40]}...\n"
    await q.message.reply_text(text, parse_mode="Markdown"); return MAIN_MENU

# --- GLOBAL ADMIN MODERATION (ADVANCED & FIXED) ---
async def admin_moderation_global(update: Update, context: ContextTypes.DEFAULT_TYPE):
    q = update.callback_query
    await q.answer()
    data = q.data
    parts = data.split("_")
    action = parts[1]
    target_id = int(parts[2])
    
    # CRITICAL FIX: Set the flag so the next message is caught correctly
    context.user_data['mod_action'] = action
    context.user_data['mod_target_id'] = target_id
    context.user_data['awaiting_admin_reason'] = True
    
    action_names = {"warn": "Warning", "block": "24-Hour Block", "ban": "Permanent Ban"}
    action_name = action_names.get(action, "Action")
    
    try:
        await q.message.reply_text(
            f"📝 *Provide Reason for {action_name}*\n\n"
            f"Please type the reason. The user will be notified of this {action_name.lower()}.\n"
            f"(Type 'None' if no specific reason is needed)",
            parse_mode="Markdown"
        )
    except (BadRequest, TimedOut, NetworkError):
        pass
        
    return AWAIT_ADMIN_REASON

async def admin_reason_receive_global(update: Update, context: ContextTypes.DEFAULT_TYPE):
    if update.effective_user.id != ADMIN_USER_ID or not context.user_data.get('awaiting_admin_reason'): 
        return MAIN_MENU
        
    reason = update.message.text.strip()
    action = context.user_data.get('mod_action')
    target_id = context.user_data.get('mod_target_id')
    target_user = get_user(target_id)
    target_name = target_user['nickname'] if target_user else "User"
    
    # Clean up state immediately to prevent stuck states
    context.user_data.pop('awaiting_admin_reason', None)
    context.user_data.pop('mod_action', None)
    context.user_data.pop('mod_target_id', None)
    
    notify_text = ""
    if reason.lower() != "none" and reason:
        notify_text = f"\n\n*Reason:* {reason}"
        
    try:
        if action == "warn":
            warn_user(target_id)
            if target_user:
                await context.bot.send_message(
                    target_id, 
                    f"⚠️ *Official Warning*\n\nYou have received an official warning from the administration.{notify_text}\n\nFurther violations may result in a temporary or permanent ban.", 
                    parse_mode="Markdown"
                )
            await update.message.reply_text(f"✅ *User Warned*\n\n{target_name} has been warned successfully.", parse_mode="Markdown")
            
        elif action == "block":
            block_user_24h(target_id)
            if target_user:
                await context.bot.send_message(
                    target_id, 
                    f"⏳ *Temporary Block (24 Hours)*\n\nYour account has been temporarily blocked from submitting confessions and comments.{notify_text}\n\nThis restriction will be automatically lifted in 24 hours.", 
                    parse_mode="Markdown"
                )
            await update.message.reply_text(f"✅ *User Blocked*\n\n{target_name} has been blocked for 24 hours.", parse_mode="Markdown")
            
        elif action == "ban":
            ban_user(target_id)
            if target_user:
                await context.bot.send_message(
                    target_id, 
                    f"🚫 *Permanent Ban*\n\nYour account has been permanently banned from this bot.{notify_text}\n\nYou can no longer use any features of this bot.", 
                    parse_mode="Markdown"
                )
            await update.message.reply_text(f"✅ *User Permanently Banned*\n\n{target_name} has been permanently banned.", parse_mode="Markdown")
            
    except (BadRequest, TimedOut, NetworkError) as e:
        logger.error(f"Admin action failed: {e}")
        # Even if DM fails (e.g., user blocked bot), the action still happened locally
        action_done = {"warn": "warned", "block": "blocked", "ban": "permanently banned"}.get(action, "processed")
        await update.message.reply_text(f"✅ *User {action_done}*\n\n(Note: The user could not be notified, possibly because they have blocked the bot.)", parse_mode="Markdown")
        
    return MAIN_MENU

# --- Global Admin Approval Handler (WITH ACTIVITY NOTIFICATION) ---
async def admin_callback(update: Update, context: ContextTypes.DEFAULT_TYPE):
    q = update.callback_query; await q.answer(); data = q.data
    if data.startswith("aok_"):
        cid = int(data[4:]); conf = get_confession(cid)
        if not conf: return
        num = len(get_all_confessions()) + 1; stats = get_confession_stats(cid)
        post = f"🪪 *Confession #{num}*\n\n{conf['text']}\n\n🏷️ {conf.get('categories') or '#General'}\n\n⭐️ _Earn Stars!_"
        btn = InlineKeyboardButton(f"💬 Comments ({stats['comments']})", url=f"https://t.me/{BOT_USERNAME}?start=conf_{cid}")
        try:
            if conf.get('media_type') == 'photo': msg = await context.bot.send_photo(CONFESS_CHANNEL, conf['media_file_id'], caption=post, parse_mode='Markdown', reply_markup=InlineKeyboardMarkup([[btn]]))
            elif conf.get('media_type') == 'video': msg = await context.bot.send_video(CONFESS_CHANNEL, conf['media_file_id'], caption=post, parse_mode='Markdown', reply_markup=InlineKeyboardMarkup([[btn]]), supports_streaming=True)
            else: msg = await context.bot.send_message(CONFESS_CHANNEL, post, parse_mode='Markdown', reply_markup=InlineKeyboardMarkup([[btn]]))
            approve_confession(cid, msg.message_id, conf.get('categories', 'General'))
            try: await context.bot.send_message(conf['user_id'], "✅ *Approved!*\n\nYour confession is now live.", parse_mode="Markdown")
            except: pass
            await safe_admin_update(q, f"✅ *Approved as #{num}*")
            
            followers = get_followers(conf['user_id']); author = get_user(conf['user_id']); author_name = author['nickname'] if author else "Anonymous"
            for f_id in followers:
                f_user = get_user(f_id)
                if f_user and f_user.get('notify_activity', 1):
                    try: await context.bot.send_message(f_id, f"📢 *New Post from {author_name}*\n\n*{author_name}* just posted a new confession!", parse_mode="Markdown", reply_markup=InlineKeyboardMarkup([[InlineKeyboardButton("👀 View Confession", callback_data=f"v_{cid}")]]))
                    except (BadRequest, TimedOut, NetworkError): pass
        except (BadRequest, TimedOut, NetworkError) as e: 
            logger.error(f"Post failed: {e}")
            await safe_admin_update(q, "❌ *Failed to Post*")
    elif data.startswith("ano_"):
        cid = int(data[4:]); conf = get_confession(cid)
        if conf: 
            try: await context.bot.send_message(conf['user_id'], "❌ *Rejected*\n\nDid not meet guidelines.", parse_mode="Markdown")
            except: pass
        await safe_admin_update(q, "❌ *Rejected*")
    return MAIN_MENU

# --- GLOBAL ADMIN PERMANENT DELETION ---
async def admin_delete_permanent(update: Update, context: ContextTypes.DEFAULT_TYPE):
    q = update.callback_query; await q.answer()
    conf_id = int(q.data.split("_")[2]); conf = get_confession(conf_id)
    if not conf: await safe_admin_update(q, "❌ *Not Found*"); return
    delete_confession_permanently(conf_id)
    try: 
        await context.bot.send_message(conf['user_id'], "🗑️ *Confession Deleted*\n\nYour request has been approved and it has been permanently removed.", parse_mode="Markdown")
        await safe_admin_update(q, f"🗑️ *Deleted Permanently*\n\nConfession #{conf_id} wiped from database.")
    except (BadRequest, TimedOut, NetworkError): pass

# --- ADVERTISE REQUEST HANDLER ---
async def handle_ad_request(update: Update, context: ContextTypes.DEFAULT_TYPE):
    if update.message.text and update.message.text.strip() in MENU_BUTTONS: return await global_menu_interceptor(update, context)
    user_id = update.effective_user.id; user = get_user(user_id); username = user['telegram_username'] or f"ID: {user_id}"
    admin_msg = f"📢 *New Advertisement Request*\n\n👤 *From:* {username}\n\n"
    try:
        if update.message.text:
            admin_msg += f"📝 *Details:*\n{update.message.text}"
            await context.bot.send_message(ADMIN_USER_ID, admin_msg, parse_mode="Markdown", reply_markup=InlineKeyboardMarkup([[InlineKeyboardButton("✅ Approve & Notify", callback_data=f"ad_approve_{user_id}")], [InlineKeyboardButton("❌ Reject", callback_data=f"ad_reject_{user_id}")]]))
        elif update.message.photo:
            await context.bot.send_photo(ADMIN_USER_ID, update.message.photo[-1].file_id, caption=admin_msg + "📸 *Photo attached*", parse_mode="Markdown", reply_markup=InlineKeyboardMarkup([[InlineKeyboardButton("✅ Approve & Notify", callback_data=f"ad_approve_{user_id}")], [InlineKeyboardButton("❌ Reject", callback_data=f"ad_reject_{user_id}")]]))
        elif update.message.video:
            await context.bot.send_video(ADMIN_USER_ID, update.message.video.file_id, caption=admin_msg + "🎥 *Video attached*", parse_mode="Markdown", reply_markup=InlineKeyboardMarkup([[InlineKeyboardButton("✅ Approve & Notify", callback_data=f"ad_approve_{user_id}")], [InlineKeyboardButton("❌ Reject", callback_data=f"ad_reject_{user_id}")]]))
        else:
            await update.message.reply_text("❌ *Unsupported Format*\n\nPlease send text, a photo, or a video.", parse_mode="Markdown"); return AWAIT_AD_REQUEST
        await update.message.reply_text("✅ *Request Sent*\n\nThe admin has received your advertisement request and will review it shortly.", parse_mode="Markdown")
    except (BadRequest, TimedOut, NetworkError) as e:
        logger.error(f"Ad request failed: {e}"); await update.message.reply_text("❌ *Failed to send request.*", parse_mode="Markdown")
    return MAIN_MENU

async def admin_ad_decision(update: Update, context: ContextTypes.DEFAULT_TYPE):
    q = update.callback_query; await q.answer(); data = q.data; parts = data.split("_"); action = parts[1]; user_id = int(parts[2])
    if action == "approve":
        try:
            await context.bot.send_message(user_id, "✅ *Advertisement Approved!*\n\nYour ad has been approved. Please contact the admin to finalize the broadcast and payment details.", parse_mode="Markdown")
            await safe_admin_update(q, "✅ *Ad Request Approved*\n\nUser notified to contact you.")
        except (BadRequest, TimedOut, NetworkError): pass
    elif action == "reject":
        try:
            await context.bot.send_message(user_id, "❌ *Advertisement Rejected*\n\nYour ad request did not meet the requirements.", parse_mode="Markdown")
            await safe_admin_update(q, "❌ *Ad Request Rejected*\n\nUser notified.")
        except (BadRequest, TimedOut, NetworkError): pass

# --- STRICT ADMIN BROADCAST ---
async def broadcast_start(update: Update, context: ContextTypes.DEFAULT_TYPE):
    if update.effective_user.id != ADMIN_USER_ID: 
        await update.message.reply_text("🚫 *Access Denied*\n\nOnly the administrator can use this command.", parse_mode="Markdown"); return ConversationHandler.END
    await update.message.reply_text("📢 *Advanced Announcement*\n\nPlease send the message, photo, video, GIF, or sticker you want to broadcast to all users:", parse_mode="Markdown"); return AWAIT_BROADCAST

async def broadcast_receive(update: Update, context: ContextTypes.DEFAULT_TYPE):
    if update.effective_user.id != ADMIN_USER_ID:
        await update.message.reply_text("🚫 *Access Denied*", parse_mode="Markdown"); return ConversationHandler.END
    user_ids = get_all_user_ids(); total = len(user_ids); logger.info(f"Starting broadcast to {total} users.")
    status_msg = await update.message.reply_text(f"📢 *Advanced Announcement*\n\nPreparing to send to {total} users...\n\n_This may take a moment._", parse_mode="Markdown")
    sent = 0; failed = 0; update_interval = 50
    for i, uid in enumerate(user_ids):
        try:
            if update.message.photo: await context.bot.send_photo(uid, update.message.photo[-1].file_id, caption=update.message.caption or "")
            elif update.message.video: await context.bot.send_video(uid, update.message.video.file_id, caption=update.message.caption or "", supports_streaming=True)
            elif update.message.animation: await context.bot.send_animation(uid, update.message.animation.file_id, caption=update.message.caption or "")
            elif update.message.text: await context.bot.send_message(uid, update.message.text)
            elif update.message.sticker: await context.bot.send_sticker(uid, update.message.sticker.file_id)
            else: await context.bot.send_message(uid, "📢 *New Announcement*", parse_mode="Markdown")
            sent += 1
        except (BadRequest, TimedOut, NetworkError): failed += 1
        if (i + 1) % update_interval == 0 or (i + 1) == total:
            try: await status_msg.edit_text(f"📢 *Advanced Announcement*\n\n🔄 *Progress:* {(i + 1)}/{total}\n✅ *Sent:* {sent}\n❌ *Failed:* {failed}", parse_mode="Markdown")
            except (BadRequest, TimedOut, NetworkError): pass
        await asyncio.sleep(0.05)
    try: await status_msg.edit_text(f"✅ *Announcement Complete!*\n\n👥 *Total Users:* {total}\n✅ *Successfully Sent:* {sent}\n❌ *Failed (Blocked/Deleted):* {failed}", parse_mode="Markdown")
    except (BadRequest, TimedOut, NetworkError): pass
    return MAIN_MENU

async def cancel_command(update: Update, context: ContextTypes.DEFAULT_TYPE):
    await update.message.reply_text("🛑 *Cancelled*", parse_mode="Markdown"); return ConversationHandler.END

async def catch_all_callback(update: Update, context: ContextTypes.DEFAULT_TYPE):
    q = update.callback_query; await q.answer("Processed!", show_alert=False)

# --- Main ---
def main():
    app = Application.builder().token(BOT_TOKEN).build()
    
    conv = ConversationHandler(
        entry_points=[
            CommandHandler('start', start),
            CommandHandler('announce', broadcast_start)
        ],
        states={
            AWAIT_POLICY: [CallbackQueryHandler(handle_policy, pattern=r"^(accept_policy|decline_policy)$")],
            MAIN_MENU: [
                MessageHandler(filters.TEXT & ~filters.COMMAND, menu_router),
                CallbackQueryHandler(handle_daily_reward, pattern=r"^daily_reward$"),
                CallbackQueryHandler(profile_edit_menu, pattern=r"^prof_edit$"),
                CallbackQueryHandler(handle_profile_edit, pattern=r"^(edit_emoji|edit_nick|edit_bio|prof_back)$"),
                CallbackQueryHandler(show_settings, pattern=r"^prof_settings$"),
                CallbackQueryHandler(show_my_chats, pattern=r"^prof_chats$"),
                CallbackQueryHandler(show_my_confessions, pattern=r"^prof_confs$"),
                CallbackQueryHandler(handle_request_deletion, pattern=r"^req_del_\d+$"),
                CallbackQueryHandler(global_callback)
            ],
            SUBMIT_TEXT: [MessageHandler(filters.TEXT & ~filters.COMMAND, submit_receive), MessageHandler(filters.PHOTO, submit_receive), MessageHandler(filters.VIDEO, submit_receive), CallbackQueryHandler(global_callback)],
            AWAIT_MEDIA_TEXT: [MessageHandler(filters.TEXT & ~filters.COMMAND, await_media_text_receive), CallbackQueryHandler(global_callback)],
            PREVIEW_CONF: [CallbackQueryHandler(preview_callback, pattern=r"^prev_"), CallbackQueryHandler(global_callback)],
            EDIT_CONF: [MessageHandler(filters.TEXT & ~filters.COMMAND, edit_conf_receive), CallbackQueryHandler(global_callback)],
            SELECT_CATEGORIES: [CallbackQueryHandler(category_callback, pattern=r"^cat_"), CallbackQueryHandler(global_callback)],
            VIEWING: [CallbackQueryHandler(global_callback)],
            AWAIT_COMMENT: [MessageHandler(filters.ALL, handle_comment_input), CallbackQueryHandler(global_callback)],
            AWAIT_REPLY: [MessageHandler(filters.ALL, handle_comment_input), CallbackQueryHandler(global_callback)],
            SET_NICKNAME: [MessageHandler(filters.TEXT & ~filters.COMMAND, set_nickname), CallbackQueryHandler(global_callback)],
            SET_BIO: [MessageHandler(filters.TEXT & ~filters.COMMAND, set_bio), CallbackQueryHandler(global_callback)],
            SET_EMOJI: [MessageHandler(filters.TEXT & ~filters.COMMAND, set_emoji), CallbackQueryHandler(global_callback)],
            SETTINGS_MENU: [CallbackQueryHandler(settings_callback, pattern=r"^(set_|notif_|voice_|prof_|edit_)"), CallbackQueryHandler(global_callback)],
            AWAIT_REPORT_REASON: [CallbackQueryHandler(handle_report_reason, pattern=r"^rep_reason_"), CallbackQueryHandler(global_callback)],
            AWAIT_REPORT_CUSTOM_REASON: [MessageHandler(filters.TEXT & ~filters.COMMAND, handle_report_custom), CallbackQueryHandler(global_callback)],
            AWAIT_AD_REQUEST: [MessageHandler(filters.ALL, handle_ad_request), CallbackQueryHandler(global_callback)],
            AWAIT_BROADCAST: [MessageHandler(filters.ALL, broadcast_receive), CallbackQueryHandler(global_callback)],
            AWAIT_PROFILE_DETAIL: [MessageHandler(filters.TEXT & ~filters.COMMAND, handle_profile_detail_text), CallbackQueryHandler(global_callback)],
            # CRUCIAL FIX: This state now correctly catches the admin's typed reason
            AWAIT_ADMIN_REASON: [MessageHandler(filters.TEXT & ~filters.COMMAND, admin_reason_receive_global)]
        },
        fallbacks=[
            CommandHandler('start', start), 
            CommandHandler('cancel', cancel_command),
            MessageHandler(filters.TEXT & filters.Regex(r"^(📖 Browse Feed|📨 Confess|👤 Profile|⚙️ Settings|🏆 Leaderboard|ℹ️ Help|📢 Advertise|❌ Cancel)$"), global_menu_interceptor)
        ],
        allow_reentry=True
    )
    app.add_handler(conv)
    
    app.add_handler(CommandHandler("help", show_help))
    app.add_handler(CommandHandler("privacy", show_privacy))
    app.add_handler(CommandHandler("profile", show_profile))
    
    app.add_handler(CallbackQueryHandler(admin_callback, pattern=r"^(aok_|ano_)\d+$"))
    app.add_handler(CallbackQueryHandler(admin_delete_permanent, pattern=r"^del_perm_\d+$"))
    app.add_handler(CallbackQueryHandler(admin_moderation_global, pattern=r"^admin_(warn|block|ban|dismiss)_\d+$"))
    app.add_handler(CallbackQueryHandler(admin_view_history, pattern=r"^admin_history_\d+$"))
    app.add_handler(CallbackQueryHandler(admin_ad_decision, pattern=r"^ad_(approve|reject)_\d+$"))
    app.add_handler(CallbackQueryHandler(catch_all_callback))
    
    logger.info("✅ Abyssinia UV Confessions Bot v43 (Ultimate Bulletproof & Next-Level) is LIVE!")
    app.run_polling(allowed_updates=Update.ALL_TYPES)

if __name__ == '__main__':
    main()