import logging
import requests
import re
import json
import os
import random
import asyncio
from telegram import Update, InlineKeyboardButton, InlineKeyboardMarkup, ReplyKeyboardMarkup
from telegram.ext import (
    ApplicationBuilder, 
    CommandHandler, 
    ContextTypes, 
    CallbackQueryHandler,
    MessageHandler,
    filters
)

# --- CONFIGURATION ---
# ⚠️ REPLACE THIS WITH YOUR REAL TOKEN
TELEGRAM_BOT_TOKEN = "8223325004:AAEIIhDOSAOPmALWmwEHuYeaJpjlzKNGJ1k"

# ⚠️ THE ADMIN ID (Must be an integer)
ADMIN_ID = 6616624640

# File to store allowed users and cookies
DATA_FILE = "allowed_users.json"

# --- DISHVUSOCKS CONFIG ---
COUNTRY_MAP = {
    'us': 'United States',
    'uk': 'United Kingdom',
    'gb': 'United Kingdom',
    'it': 'Italy',
    'fr': 'France',
    'de': 'Germany',
    'ca': 'Canada',
    'au': 'Australia',
    'nl': 'Netherlands',
    'all': 'all'
}

# Default cookie (updated from your request) - used if no saved cookie exists
DEFAULT_COOKIE = 'notice=1; notice_time=1739170824; _ga=GA1.2.907186445.1766117007; _gid=GA1.2.509279953.1766117007; _gat=1; PHPSESSID=pnca790u3m3teqi5s4na32aip9; 0878fb59c92af61fa8719cf910b34ff6=7c1cbe6f7c318625856daaded3811345d48ef7e7a%3A4%3A%7Bi%3A0%3Bs%3A6%3A%22348422%22%3Bi%3A1%3Bs%3A14%3A%22miismailhassan%22%3Bi%3A2%3Bi%3A2592000%3Bi%3A3%3Ba%3A0%3A%7B%7D%7D; loginCookie=GDK8QwXEHH; _ga_N1LC62MVC1=GS2.2.s1766206699$o6$g1$t1766206725$j34$l0$h0'

# Base headers without the cookie
HEADERS = {
    'User-Agent': 'Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/140.0.0.0 Safari/537.36 OPR/124.0.0.0',
    'Content-Type': 'application/x-www-form-urlencoded; charset=UTF-8',
    'X-Requested-With': 'XMLHttpRequest',
    'Origin': 'https://dichvusocks.net',
    'Referer': 'https://dichvusocks.net/sockslist',
    'Cookie': DEFAULT_COOKIE 
}

# --- DATA MANAGEMENT ---

def load_data():
    default_data = {
        'allowed_ids': [ADMIN_ID], 
        'username_map': {}, 
        'cookie': DEFAULT_COOKIE
    }
    
    if not os.path.exists(DATA_FILE):
        return default_data
    
    try:
        with open(DATA_FILE, 'r') as f:
            data = json.load(f)
            # Ensure all keys exist
            if 'allowed_ids' not in data: data['allowed_ids'] = [ADMIN_ID]
            if 'username_map' not in data: data['username_map'] = {}
            if 'cookie' not in data: data['cookie'] = DEFAULT_COOKIE
            
            # Ensure Admin is always allowed
            if ADMIN_ID not in data['allowed_ids']:
                data['allowed_ids'].append(ADMIN_ID)
                
            return data
    except:
        return default_data

def save_data(data):
    with open(DATA_FILE, 'w') as f:
        json.dump(data, f, indent=4)

# Load data and apply saved cookie
BOT_DATA = load_data()
HEADERS['Cookie'] = BOT_DATA['cookie']

# --- DISHVUSOCKS LOGIC ---

def fetch_proxy_id(country_full_name):
    url = "https://dichvusocks.net/Socks/GetData"
    payload = {
        'page': '1', 'auth': 'all', 'useType': 'all',
        'country': country_full_name, 'region': 'all', 'city': 'all',
        'blacklist': 'all', 'hostname': '', 'zipcode': ''
    }
    try:
        response = requests.post(url, headers=HEADERS, data=payload, timeout=10)
        if response.status_code == 200:
            data = response.json()
            proxy_list = data.get('data', [])
            if not proxy_list: return None, "No proxies found."
            return random.choice(proxy_list)['Id'], None
        return None, f"API Error: {response.status_code}"
    except Exception as e:
        return None, str(e)

def reveal_credentials(proxy_id):
    url = f"https://dichvusocks.net/viewsocks&id={proxy_id}"
    try:
        response = requests.get(url, headers=HEADERS, timeout=10)
        content = response.text
        match = re.search(r'show_socks_info\(\d+,"(.*?)","(.*?)","(.*?)","(.*?)"', content)
        if match:
            return f"{match.group(1)}:{match.group(2)}:{match.group(3)}:{match.group(4)}", None
        return None, "Failed to parse credentials."
    except Exception as e:
        return None, str(e)

# --- BOT HANDLERS ---

async def start(update: Update, context: ContextTypes.DEFAULT_TYPE):
    user = update.effective_user
    user_id = user.id
    username = user.username.lower() if user.username else None

    if username:
        BOT_DATA['username_map'][username] = user_id
        save_data(BOT_DATA)

    if user_id not in BOT_DATA['allowed_ids']:
        await update.message.reply_text(
            f"🚫 **Access Denied**\n\n"
            f"You are not allowed to use this bot.\n"
            f"Please contact the admin.\n\n"
            f"🆔 Your User ID: `{user_id}`",
            parse_mode='Markdown'
        )
        return

    # Add Permanent Keyboard Button
    reply_keyboard = [['Get Proxy ✨']]
    markup = ReplyKeyboardMarkup(reply_keyboard, resize_keyboard=True)
    
    await update.message.reply_text("👋 Bot Started!", reply_markup=markup)
    await show_main_menu(update, user.first_name)

async def handle_message(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Handles text messages from the keyboard button"""
    text = update.message.text
    user = update.effective_user
    
    if user.id not in BOT_DATA['allowed_ids']:
        return

    if text == 'Get Proxy ✨':
        await show_main_menu(update, user.first_name)

async def show_main_menu(update: Update, user_name):
    keyboard = [
        [
            InlineKeyboardButton("🇺🇸 US", callback_data='us'),
            InlineKeyboardButton("🇬🇧 UK", callback_data='uk'),
            InlineKeyboardButton("🇮🇹 IT", callback_data='it')
        ],
        [
            InlineKeyboardButton("🇫🇷 FR", callback_data='fr'),
            InlineKeyboardButton("🇩🇪 DE", callback_data='de'),
            InlineKeyboardButton("🇨🇦 CA", callback_data='ca')
        ],
        [
            InlineKeyboardButton("🇦🇺 AU", callback_data='au'),
            InlineKeyboardButton("🇳🇱 NL", callback_data='nl'),
            InlineKeyboardButton("🌍 Random (All)", callback_data='all')
        ]
    ]
    reply_markup = InlineKeyboardMarkup(keyboard)
    text = f"Select a country to generate a Socks5 proxy:"
    
    if update.callback_query:
        await update.callback_query.message.edit_text(text, reply_markup=reply_markup)
    else:
        await update.message.reply_text(text, reply_markup=reply_markup)

async def button_click(update: Update, context: ContextTypes.DEFAULT_TYPE):
    query = update.callback_query
    await query.answer()
    
    user_id = query.from_user.id
    if user_id not in BOT_DATA['allowed_ids']:
        await query.message.edit_text("🚫 Access Revoked.")
        return

    country_code = query.data
    country_name = COUNTRY_MAP.get(country_code, 'all')

    await query.message.edit_text(f"⏳ **Fetching {country_name} Proxy...**\nPlease wait...", parse_mode='Markdown')

    pid, error = fetch_proxy_id(country_name)
    if error:
        retry_btn = InlineKeyboardMarkup([[InlineKeyboardButton("🔄 Try Again", callback_data=country_code)]])
        await query.message.edit_text(f"❌ Error: {error}", reply_markup=retry_btn)
        return

    creds, error = reveal_credentials(pid)
    if error:
        retry_btn = InlineKeyboardMarkup([[InlineKeyboardButton("🔄 Try Again", callback_data=country_code)]])
        await query.message.edit_text(f"❌ Error: {error}", reply_markup=retry_btn)
        return

    # Parse credentials for expanded view
    try:
        ip, port, user, password = creds.split(':')
    except:
        ip, port, user, password = "N/A", "N/A", "N/A", "N/A"

    back_btn = InlineKeyboardMarkup([[InlineKeyboardButton("🔙 Main Menu", callback_data='menu_main')]])
    
    await query.message.edit_text(
        f"✅ **{country_name} Proxy Generated**\n\n"
        f"`{creds}`\n\n"
        f"**Details:**\n"
        f"Server : `{ip}`\n"
        f"Port : `{port}`\n"
        f"User : `{user}`\n"
        f"Pass : `{password}`",
        parse_mode='Markdown',
        reply_markup=back_btn
    )

async def menu_main_handler(update: Update, context: ContextTypes.DEFAULT_TYPE):
    query = update.callback_query
    await query.answer()
    await show_main_menu(update, query.from_user.first_name)

# --- ADMIN COMMANDS ---

async def allow_user(update: Update, context: ContextTypes.DEFAULT_TYPE):
    user_id = update.effective_user.id
    if user_id != ADMIN_ID: return

    try:
        target = context.args[0]
        target_id = None
        if target.startswith('@'):
            clean_username = target[1:].lower()
            target_id = BOT_DATA['username_map'].get(clean_username)
            if not target_id:
                await update.message.reply_text(f"⚠️ Unknown username '{target}'.\nAsk them to /start first.")
                return
        else:
            target_id = int(target)

        if target_id not in BOT_DATA['allowed_ids']:
            BOT_DATA['allowed_ids'].append(target_id)
            save_data(BOT_DATA)
            await update.message.reply_text(f"✅ User {target} (ID: {target_id}) allowed.")
        else:
            await update.message.reply_text(f"ℹ️ User {target} is already allowed.")
    except (IndexError, ValueError):
        await update.message.reply_text("Usage: `/allow <id>` or `/allow @username`", parse_mode='Markdown')

async def list_users(update: Update, context: ContextTypes.DEFAULT_TYPE):
    if update.effective_user.id != ADMIN_ID: return
    await update.message.reply_text(f"👥 Allowed IDs: {BOT_DATA['allowed_ids']}")

async def update_cookie(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Allows admin to update cookies dynamically"""
    user_id = update.effective_user.id
    if user_id != ADMIN_ID: return

    try:
        # Get the full text after the command
        new_cookie = update.message.text.split(None, 1)[1]
        
        # Update Memory
        BOT_DATA['cookie'] = new_cookie
        HEADERS['Cookie'] = new_cookie
        
        # Save to disk
        save_data(BOT_DATA)
        
        await update.message.reply_text("✅ **Cookie Updated Successfully!**\nNew session is active immediately.", parse_mode='Markdown')
    except IndexError:
        await update.message.reply_text("⚠️ Usage: `/new <paste_cookie_string_here>`", parse_mode='Markdown')

# --- BACKGROUND TASKS (Replaces JobQueue) ---

async def background_keep_alive():
    """Runs forever in the background to keep cookies alive"""
    print("💓 Keep-alive background task started.")
    while True:
        try:
            requests.post(
                "https://dichvusocks.net/Socks/GetData", 
                headers=HEADERS, 
                data={'page': '1', 'auth': 'all', 'country': 'all'}, 
                timeout=10
            )
        except Exception as e:
            print(f"⚠️ Keep-alive ping failed: {e}")
        
        await asyncio.sleep(600) # Sleep 10 minutes

async def on_startup(application):
    """Called when bot starts, launches background task"""
    asyncio.create_task(background_keep_alive())

# --- MAIN ---

if __name__ == '__main__':
    application = ApplicationBuilder().token(TELEGRAM_BOT_TOKEN)\
        .post_init(on_startup)\
        .read_timeout(30)\
        .write_timeout(30)\
        .connect_timeout(30)\
        .job_queue(None)\
        .build()

    application.add_handler(CommandHandler('start', start))
    application.add_handler(CommandHandler('allow', allow_user))
    application.add_handler(CommandHandler('users', list_users))
    application.add_handler(CommandHandler('new', update_cookie)) # New command
    
    # Handle the 'Get Proxy' button
    application.add_handler(MessageHandler(filters.TEXT & (~filters.COMMAND), handle_message))
    
    application.add_handler(CallbackQueryHandler(menu_main_handler, pattern='^menu_main$'))
    application.add_handler(CallbackQueryHandler(button_click))

    print("Bot is running...")
    application.run_polling()