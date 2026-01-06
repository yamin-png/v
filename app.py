import logging
import requests
import re
import json
import os
import random
import asyncio
import pycountry
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
TELEGRAM_BOT_TOKEN = "8223325004:AAEIIhDOSAOPmALWmwEHuYeaJpjlzKNGJ1k"

# ⚠️ ADMIN IDS (List of integers)
ADMIN_IDS = [6616624640, 5473188537]

# File to store allowed users and cookies
DATA_FILE = "allowed_users.json"

# --- DISHVUSOCKS CONFIG ---
# Manual overrides for countries where Dichvu's name differs from standard ISO names
COUNTRY_OVERRIDES = {
    'RU': 'Russia',
    'VN': 'Vietnam',
    'KR': 'South Korea',
    'IR': 'Iran',
    'MD': 'Moldova',
    'TZ': 'Tanzania',
    'SY': 'Syria',
    'LA': 'Laos',
    'VE': 'Venezuela',
    'BO': 'Bolivia',
    'CD': 'Congo',
    'EG': 'Egypt',
    'MM': 'Myanmar'
}

# Default cookie
DEFAULT_COOKIE = 'notice=1; notice_time=1739170824; _ga=GA1.2.907186445.1766117007; _gid=GA1.2.509279953.1766117007; _gat=1; PHPSESSID=pnca790u3m3teqi5s4na32aip9; 0878fb59c92af61fa8719cf910b34ff6=7c1cbe6f7c318625856daaded3811345d48ef7e7a%3A4%3A%7Bi%3A0%3Bs%3A6%3A%22348422%22%3Bi%3A1%3Bs%3A14%3A%22miismailhassan%22%3Bi%3A2%3Bi%3A2592000%3Bi%3A3%3Ba%3A0%3A%7B%7D%7D; loginCookie=GDK8QwXEHH; _ga_N1LC62MVC1=GS2.2.s1766206699$o6$g1$t1766206725$j34$l0$h0'

# Base headers
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
        'allowed_ids': list(ADMIN_IDS), 
        'username_map': {}, 
        'cookie': DEFAULT_COOKIE
    }
    
    if not os.path.exists(DATA_FILE):
        return default_data
    
    try:
        with open(DATA_FILE, 'r') as f:
            data = json.load(f)
            if 'allowed_ids' not in data: data['allowed_ids'] = list(ADMIN_IDS)
            if 'username_map' not in data: data['username_map'] = {}
            if 'cookie' not in data: data['cookie'] = DEFAULT_COOKIE
            
            for admin_id in ADMIN_IDS:
                if admin_id not in data['allowed_ids']:
                    data['allowed_ids'].append(admin_id)
            return data
    except:
        return default_data

def save_data(data):
    with open(DATA_FILE, 'w') as f:
        json.dump(data, f, indent=4)

BOT_DATA = load_data()
HEADERS['Cookie'] = BOT_DATA['cookie']

# --- HELPER: COUNTRY NAME RESOLVER ---
def get_full_country_name(code_or_name):
    """Converts 'EG' -> 'Egypt', 'RU' -> 'Russia', or returns title case."""
    clean_input = code_or_name.strip().upper()
    
    # 1. Check Manual Overrides
    if clean_input in COUNTRY_OVERRIDES:
        return COUNTRY_OVERRIDES[clean_input]

    # 2. Check Pycountry for 2-letter codes
    if len(clean_input) == 2:
        try:
            country = pycountry.countries.get(alpha_2=clean_input)
            if country:
                return country.name.split(',')[0]
        except:
            pass
            
    # 3. Fallback: Return formatted string
    return code_or_name.title()

# --- DISHVUSOCKS LOGIC (THREADED) ---

def _sync_fetch_proxy_id(country_full_name):
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

def _sync_reveal_credentials(proxy_id):
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

async def process_proxy_request(update_obj, country_input, context):
    """
    Handles fetching and revealing proxies.
    Uses run_in_executor to handle high concurrency (200+ users).
    """
    
    # Determine if this is a callback (button) or message (text)
    is_callback = isinstance(update_obj, str) == False and hasattr(update_obj, 'data')
    message_obj = update_obj.message if is_callback else update_obj
    
    # Resolve Country Name
    full_name = get_full_country_name(country_input)
    
    # Save to user context for "Get Another" button
    context.user_data['last_country_code'] = country_input

    # UI Feedback
    status_text = f"⏳ **Fetching {full_name} Proxy...**\nPlease wait..."
    if is_callback:
        await message_obj.edit_text(status_text, parse_mode='Markdown')
    else:
        status_msg = await message_obj.reply_text(status_text, parse_mode='Markdown')

    # 1. Fetch ID (Async / Threaded for concurrency)
    loop = asyncio.get_running_loop()
    pid, error = await loop.run_in_executor(None, _sync_fetch_proxy_id, full_name)
    
    if error:
        err_text = f"❌ **Error:** {error}\nPlease check the code and try again."
        # If error, offer Change Country button
        btns = InlineKeyboardMarkup([[InlineKeyboardButton("🌍 Change Country", callback_data='change_country')]])
        
        if is_callback:
            await message_obj.edit_text(err_text, reply_markup=btns)
        else:
            await status_msg.edit_text(err_text, reply_markup=btns)
        return

    # 2. Reveal Credentials (Async / Threaded)
    creds, error = await loop.run_in_executor(None, _sync_reveal_credentials, pid)
    
    if error:
        err_text = f"❌ **Error:** {error}"
        if is_callback:
            await message_obj.edit_text(err_text)
        else:
            await status_msg.edit_text(err_text)
        return

    # 3. Format Output
    try:
        ip, port, user, password = creds.split(':')
    except:
        ip, port, user, password = "N/A", "N/A", "N/A", "N/A"

    final_text = (
        f"✅ **{full_name} Proxy Generated**\n\n"
        f"`{creds}`\n\n"
        f"**Details:**\n"
        f"Server : `{ip}`\n"
        f"Port : `{port}`\n"
        f"User : `{user}`\n"
        f"Pass : `{password}`"
    )

    # Success Buttons
    keyboard = [
        [InlineKeyboardButton(f"🔄 Get Another ({country_input.upper()})", callback_data='get_same_proxy')],
        [InlineKeyboardButton("🌍 Change Country", callback_data='change_country')]
    ]
    reply_markup = InlineKeyboardMarkup(keyboard)

    if is_callback:
        await message_obj.edit_text(final_text, parse_mode='Markdown', reply_markup=reply_markup)
    else:
        await status_msg.edit_text(final_text, parse_mode='Markdown', reply_markup=reply_markup)

# --- BOT HANDLERS ---

async def start(update: Update, context: ContextTypes.DEFAULT_TYPE):
    user = update.effective_user
    if user.username:
        BOT_DATA['username_map'][user.username.lower()] = user.id
        save_data(BOT_DATA)

    if user.id not in BOT_DATA['allowed_ids']:
        await update.message.reply_text(f"🚫 Access Denied. ID: `{user.id}`", parse_mode='Markdown')
        return

    reply_keyboard = [['Get Proxy ✨']]
    markup = ReplyKeyboardMarkup(reply_keyboard, resize_keyboard=True)
    await update.message.reply_text(
        "👋 **Bot Ready!**\nClick **Get Proxy** to start.", 
        reply_markup=markup, 
        parse_mode='Markdown'
    )

async def handle_message(update: Update, context: ContextTypes.DEFAULT_TYPE):
    user = update.effective_user
    if user.id not in BOT_DATA['allowed_ids']: return

    text = update.message.text.strip()

    # 1. Handle "Get Proxy" Button
    if text == 'Get Proxy ✨':
        await update.message.reply_text(
            "🌍 **Select Country**\n\n"
            "Please type the **2-letter Country Code** you want.\n"
            "Examples: `EG`, `US`, `MM`, `RU`, `VN`, `BR`",
            parse_mode='Markdown'
        )
        return

    # 2. Handle text input (Assumed to be a Country Code)
    # We treat any other text as a country request
    await process_proxy_request(update.message, text, context)

async def button_click(update: Update, context: ContextTypes.DEFAULT_TYPE):
    query = update.callback_query
    await query.answer()
    
    if query.from_user.id not in BOT_DATA['allowed_ids']:
        await query.message.edit_text("🚫 Access Revoked.")
        return

    action = query.data

    if action == 'change_country':
        await query.message.edit_text(
            "🌍 **Change Country**\n\n"
            "Please type the new **Country Code** below:\n"
            "(e.g., `MM`, `EG`, `US`)",
            parse_mode='Markdown'
        )
        return

    if action == 'get_same_proxy':
        # Retrieve the last used country code from user session
        last_code = context.user_data.get('last_country_code')
        if not last_code:
            await query.message.edit_text("⚠️ Session expired. Please type the country code again.")
            return
        
        # Fetch new proxy for same country
        await process_proxy_request(query, last_code, context)
        return

# --- ADMIN COMMANDS ---

async def allow_user(update: Update, context: ContextTypes.DEFAULT_TYPE):
    if update.effective_user.id not in ADMIN_IDS: return
    try:
        target = context.args[0]
        if target.startswith('@'):
            tid = BOT_DATA['username_map'].get(target[1:].lower())
            if not tid: 
                await update.message.reply_text("⚠️ Unknown username. They must /start first.")
                return
        else: tid = int(target)

        if tid not in BOT_DATA['allowed_ids']:
            BOT_DATA['allowed_ids'].append(tid)
            save_data(BOT_DATA)
            await update.message.reply_text(f"✅ User {target} Allowed.")
        else: await update.message.reply_text("ℹ️ Already allowed.")
    except: await update.message.reply_text("Usage: `/allow <id>`", parse_mode='Markdown')

async def update_cookie(update: Update, context: ContextTypes.DEFAULT_TYPE):
    if update.effective_user.id not in ADMIN_IDS: return
    try:
        new_cookie = update.message.text.split(None, 1)[1]
        BOT_DATA['cookie'] = new_cookie
        HEADERS['Cookie'] = new_cookie
        save_data(BOT_DATA)
        await update.message.reply_text("✅ Cookie Updated!")
    except: await update.message.reply_text("Usage: `/new <cookie>`")

# --- BACKGROUND TASKS ---
async def background_keep_alive():
    loop = asyncio.get_running_loop()
    while True:
        try:
            await loop.run_in_executor(None, lambda: requests.post("https://dichvusocks.net/Socks/GetData", headers=HEADERS, data={'page': '1', 'auth': 'all', 'country': 'all'}, timeout=10))
        except: pass
        await asyncio.sleep(600)

async def on_startup(application):
    asyncio.create_task(background_keep_alive())

if __name__ == '__main__':
    application = ApplicationBuilder().token(TELEGRAM_BOT_TOKEN).post_init(on_startup).read_timeout(30).write_timeout(30).connect_timeout(30).job_queue(None).build()
    
    application.add_handler(CommandHandler('start', start))
    application.add_handler(CommandHandler('allow', allow_user))
    application.add_handler(CommandHandler('new', update_cookie))
    
    # Text Handler (For "Get Proxy" button AND Country Codes)
    application.add_handler(MessageHandler(filters.TEXT & (~filters.COMMAND), handle_message))
    
    # Callback Handler (For Inline Buttons)
    application.add_handler(CallbackQueryHandler(button_click))

    print("Bot is running...")
    application.run_polling()
