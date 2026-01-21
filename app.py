import logging
import requests
import re
import json
import os
import random
import asyncio
import datetime
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

# ⚠️ LOG GROUP ID (Where reports are sent)
LOG_GROUP_ID = -1003280360902

# File to store allowed users, cookies, and usage stats
DATA_FILE = "allowed_users.json"

# --- DISHVUSOCKS CONFIG ---
COUNTRY_OVERRIDES = {
    'RU': 'Russia', 'VN': 'Vietnam', 'KR': 'South Korea', 'IR': 'Iran',
    'MD': 'Moldova', 'TZ': 'Tanzania', 'SY': 'Syria', 'LA': 'Laos',
    'VE': 'Venezuela', 'BO': 'Bolivia', 'CD': 'Congo', 'EG': 'Egypt',
    'MM': 'Myanmar', 'US': 'United States'
}

# ⛔ BLACKLISTED COUNTRIES (Standardized English Names)
# These names must match what pycountry or COUNTRY_OVERRIDES returns.
FORBIDDEN_COUNTRIES = {
    'United States', 'Peru', 'Ghana', 'Ethiopia', 'Yemen', 'Benin', 
    'Comoros', 'Sudan', 'Zimbabwe', 'Afghanistan', 'Mali', 'Myanmar', 
    'Ecuador', 'Tanzania', 'Togo', 'Kenya', 'Lebanon', 'Romania', 
    'Oman', 'Bolivia', 'Bhutan', 'Georgia', 'Ukraine', 'Senegal', 
    'Nepal', 'Sri Lanka', 'Sierra Leone', 'Russia', 'Greece', 
    'Finland', 'Azerbaijan', 'Algeria', 'Morocco', 'Denmark', 'Malaysia'
}

# Updated Cookie from latest log
DEFAULT_COOKIE = '_ga=GA1.2.907186445.1766117007; _gid=GA1.2.409351101.1768402779; notice=1; notice_time=1739170824; PHPSESSID=c05e028ff8e962f21bc3cfa2b94ee4d4; 0878fb59c92af61fa8719cf910b34ff6=1e6047aef118f49bf18fa82f8ff7e03fb61bf4e9a%3A4%3A%7Bi%3A0%3Bi%3A498299%3Bi%3A1%3Bs%3A11%3A%22syaminhasan%22%3Bi%3A2%3Bi%3A2592000%3Bi%3A3%3Ba%3A0%3A%7B%7D%7D; loginCookie=KCKJX956h0; _ga_N1LC62MVC1=GS2.2.s1768978726$o67$g1$t1768978931$j60$l0$h0; cf_clearance=bnFyij3y39cvidXqCV9rCK7L0UJwjgRV0LWPAxC2DY4-1768987008-1.2.1.1-eqwzq9Zl4un2k2Jf4W4W3jLIxTnHZhA4m6DsU_YIW.wFhMG23jtD606sFj9s1wnXc7S8rOZ.WaoEmB3uFPrNkyKeerDMPtX6s79hkftk.LkvenclJ42Z39rw4IfThwS2eDtTMYRLXu0h.9Gc0twNta1BvCFMpvqmwgKLC0BEdsrlNPawZyKMdxWv1nfw.3F9ryo8Hf6.3q15BaXonm098PPkswBkl2ubCumd.3Ar0GQ; remember_user_59ba36addc2b2f9401580f014c7f58ea4e30989d=eyJpdiI6Ikx5a09seTRWQlJvWWN0alUrSmI4OXc9PSIsInZhbHVlIjoiK3ozcXhoTnNXUkdyQmU2RFVOd3M3ODIyYzF4VkRiN056WU9id3JhYzdWcTJKd2NBS0NHaFRzNy9CSWNGWnZ2T0JlR3VBMDZXMzdlL2N1VGNsNkVGQWY4T0ZndXg2ZE5BWlM2YzRsSFd6UysvUzR3UU1udUY5RHZvRThJeDgwRlU3Z0NrVmNscE40eC96Y2tTemlKRlhlOFREbDIwbVRhbTNJazUwZWRxdGZLdjRROFFMZjVBYVh4S0EwYmF2MWlsUGZYRHhPbWNSR2w5Q3NzcW1JaUI5OTZxZTJYMDJDUy9NSTI3bEZUZDUvST0iLCJtYWMiOiIwNmY1NDIwODU1OWQ3ZWFiOTM0ZmMwYjNkY2Y0M2VlMGQ3MDY5Y2JlNTNhMWIwYTIwYmFmYThmYjA5YzcwMDA2IiwidGFnIjoiIn0%3D; notice_seen=eyJpdiI6Im9PUXV6Rk5ORzNUNzNaT0FtK3FNSHc9PSIsInZhbHVlIjoidDNXcXcxSjJSU3RyNWVScURiYWFudWczUGpFNFpEbTBoSnhnbzNteDZSSFJWWVdqWFFEK3dKdnY3TkdlOE50cWdTS1QwMGE1c1JmTlNVYkZ4clQ1NUduUTNZTjEyZUxGT2dGWCtnU2gza0U9IiwibWFjIjoiYTkyNDMxMjA3MDg3M2M1ZmMyODEyNWRmMTY5OTdiZDVkMzg5NzA1MWM3YmM0YjNlM2FlMjI2MjQ0ODAyMWM5MiIsInRhZyI6IiJ9; XSRF-TOKEN=eyJpdiI6IldHWTE1WG1hYVplb0xJUVc0SWNEYlE9PSIsInZhbHVlIjoiN1dQSW5xVDZkT2hTa3BOTXZOc0JIYTJiK1hNTlJjVFUrc2VpeXZJYUUwVXMxMlJRQzlzR2dMU0UyTklubVIyTEorQzYrNUorc2NUbkxPdzFYMXM1dXh4dWY2QkZnb2tMbSs5VUxVMTZtSmdDSlFYUGU1Z211ajRSZFRUNU05V1kiLCJtYWMiOiIwMWI5YmU1M2RlNmRjZTJlMDUyYmQ5OWI0ZDFhNjQwMzIyM2IxZjg5ZWJmYjU1YmIyYTE1MzNkN2UyNzc4YzZiIiwidGFnIjoiIn0%3D; dichvusocksnet-session=eyJpdiI6IjRhbEpRUUNHazZKOWRNODlzTFk2YXc9PSIsInZhbHVlIjoiNVczSTRFS3A5cFZEZnFRemlxQ2RmdkJyV1V6UGZWVkptb3JyT01taTNLVDdOSjRXWlZ6WEd3Ym5nSEVxTm1vWkNCZjFxdVBsMkJhYlNub3FjQmhYQTkxR2lsMUxob0VENVNqRXFtSVZvbVZwWjdaVStacmN2UTZSeU9zeFZRaFgiLCJtYWMiOiIzYjYxOTdmMDQxNzliYjliMGFmZjZkYjkxZDUwYzQyNzMyYWE3MGU0NjUwNGYwNGFiZGEyZjQyMmI5ZDc3ODUzIiwidGFnIjoiIn0%3D'

HEADERS = {
    'User-Agent': 'Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/141.0.0.0 Safari/537.36 OPR/125.0.0.0',
    'Accept': '*/*',
    'X-Requested-With': 'XMLHttpRequest',
    'Referer': 'https://dichvusocks.net/sockslist',
    'Cookie': DEFAULT_COOKIE 
}

# --- DATA MANAGEMENT ---

def load_data():
    default_data = {
        'allowed_ids': list(ADMIN_IDS), 
        'username_map': {}, 
        'cookie': DEFAULT_COOKIE,
        'usage': {}  # New field for tracking daily usage
    }
    
    if not os.path.exists(DATA_FILE):
        return default_data
    
    try:
        with open(DATA_FILE, 'r') as f:
            data = json.load(f)
            if 'allowed_ids' not in data: data['allowed_ids'] = list(ADMIN_IDS)
            if 'username_map' not in data: data['username_map'] = {}
            if 'cookie' not in data: data['cookie'] = DEFAULT_COOKIE
            if 'usage' not in data: data['usage'] = {}
            
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

# --- USAGE TRACKER ---
def increment_usage(user_id):
    """Increments daily usage count for a user."""
    today_str = str(datetime.date.today())
    str_id = str(user_id)
    
    # Initialize user if not exists
    if str_id not in BOT_DATA['usage']:
        BOT_DATA['usage'][str_id] = {'date': today_str, 'count': 0}
    
    user_stat = BOT_DATA['usage'][str_id]
    
    # Reset if date changed
    if user_stat['date'] != today_str:
        user_stat['date'] = today_str
        user_stat['count'] = 0
        
    user_stat['count'] += 1
    save_data(BOT_DATA)
    return user_stat['count']

# --- DISHVUSOCKS LOGIC (THREADED) ---

def _sync_fetch_proxy_id(country_full_name):
    url = "https://dichvusocks.net/api/socks/data"
    
    params = {
        'auth': '',
        'useType': '',
        'country': country_full_name,
        'region': '',
        'city': '',
        'blacklist': '',
        'zipcode': '',
        'Host': '',
        'page': '1',
        'limit': '20'
    }

    try:
        # Changed to GET request with params
        response = requests.get(url, headers=HEADERS, params=params, timeout=10)
        
        if response.status_code == 200:
            data = response.json()
            # Changed 'data' to 'rows' based on new API structure
            proxy_list = data.get('rows', [])
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

def get_full_country_name(code_or_name):
    clean_input = code_or_name.strip().upper()
    if clean_input in COUNTRY_OVERRIDES:
        return COUNTRY_OVERRIDES[clean_input]
    if len(clean_input) == 2:
        try:
            country = pycountry.countries.get(alpha_2=clean_input)
            if country: return country.name.split(',')[0]
        except: pass
    return code_or_name.title()

async def process_proxy_request(update_obj, country_input, context):
    # Determine message and user
    is_callback = isinstance(update_obj, str) == False and hasattr(update_obj, 'data')
    message_obj = update_obj.message if is_callback else update_obj
    user = update_obj.from_user
    
    # Resolve Country Name
    full_name = get_full_country_name(country_input)
    
    # Save to user context
    context.user_data['last_country_code'] = country_input

    # ⛔ CHECK FOR FORBIDDEN COUNTRY ⛔
    if full_name in FORBIDDEN_COUNTRIES:
        warning_text = (
            f"🚫 **ACCESS DENIED: {full_name}**\n\n"
            f"This is not allowed. If you try to get **{full_name}**, you will be **BANNED**.\n"
            f"Do not make requests to this country."
        )
        
        btn = InlineKeyboardMarkup([[InlineKeyboardButton("🌍 Change Country", callback_data='change_country')]])
        
        if is_callback:
            await message_obj.edit_text(warning_text, parse_mode='Markdown', reply_markup=btn)
        else:
            await message_obj.reply_text(warning_text, parse_mode='Markdown', reply_markup=btn)
        return

    # UI Feedback
    status_text = f"⏳ **Fetching {full_name} Proxy...**\nPlease wait..."
    if is_callback:
        await message_obj.edit_text(status_text, parse_mode='Markdown')
    else:
        status_msg = await message_obj.reply_text(status_text, parse_mode='Markdown')

    # 1. Fetch ID
    loop = asyncio.get_running_loop()
    pid, error = await loop.run_in_executor(None, _sync_fetch_proxy_id, full_name)
    
    if error:
        err_text = f"❌ **Error:** {error}\nPlease check the code and try again."
        btns = InlineKeyboardMarkup([[InlineKeyboardButton("🌍 Change Country", callback_data='change_country')]])
        
        if is_callback:
            await message_obj.edit_text(err_text, reply_markup=btns)
        else:
            await status_msg.edit_text(err_text, reply_markup=btns)
        return

    # 2. Reveal Credentials
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
        ip, port, user_p, password = creds.split(':')
    except:
        ip, port, user_p, password = "N/A", "N/A", "N/A", "N/A"

    final_text = (
        f"✅ **{full_name} Proxy Generated**\n\n"
        f"`{creds}`\n\n"
        f"**Details:**\n"
        f"Server : `{ip}`\n"
        f"Port : `{port}`\n"
        f"User : `{user_p}`\n"
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

    # --- 4. LOGGING & USAGE TRACKING ---
    try:
        # Increment Usage
        usage_count = increment_usage(user.id)
        
        # Prepare Log Message
        user_mention = f"@{user.username}" if user.username else "No Username"
        
        log_message = (
            f"🚀 **New Proxy Request**\n\n"
            f"👤 **User:** {user_mention}\n"
            f"🆔 **ID:** `{user.id}`\n"
            f"🏳️ **Country:** {full_name}\n"
            f"📊 **Today Use:** {usage_count}"
        )
        
        # Admin Ban Button
        admin_kb = InlineKeyboardMarkup([
            [InlineKeyboardButton("🚫 Ban User", callback_data=f"ban_user_{user.id}")]
        ])
        
        # Send to Log Group
        await context.bot.send_message(
            chat_id=LOG_GROUP_ID,
            text=log_message,
            reply_markup=admin_kb,
            parse_mode='Markdown'
        )
    except Exception as e:
        print(f"Logging error: {e}")

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

    if text == 'Get Proxy ✨':
        await update.message.reply_text(
            "🌍 **Select Country**\n\n"
            "Please type the **2-letter Country Code** you want.\n"
            "Examples: `CA`, `GB`, `DE`, `FR`",
            parse_mode='Markdown'
        )
        return

    await process_proxy_request(update.message, text, context)

async def button_click(update: Update, context: ContextTypes.DEFAULT_TYPE):
    query = update.callback_query
    action = query.data
    user_id = query.from_user.id

    # --- ADMIN BAN LOGIC ---
    if action.startswith('ban_user_'):
        # Check if clicker is admin
        if user_id not in ADMIN_IDS:
            await query.answer("❌ You are not an admin.", show_alert=True)
            return

        target_id = int(action.split('_')[2])
        
        if target_id in BOT_DATA['allowed_ids']:
            BOT_DATA['allowed_ids'].remove(target_id)
            save_data(BOT_DATA)
            await query.answer("✅ User Banned Successfully!")
            await query.message.edit_text(
                f"{query.message.text_markdown}\n\n🚫 **USER BANNED BY ADMIN**",
                parse_mode='Markdown'
            )
        else:
            await query.answer("⚠️ User is already banned or not found.", show_alert=True)
            await query.message.edit_text(
                f"{query.message.text_markdown}\n\n⚠️ **User already banned**",
                parse_mode='Markdown'
            )
        return

    await query.answer()
    
    # Check if user is allowed (for standard buttons)
    if user_id not in BOT_DATA['allowed_ids']:
        await query.message.edit_text("🚫 Access Revoked.")
        return

    if action == 'change_country':
        await query.message.edit_text(
            "🌍 **Change Country**\n\n"
            "Please type the new **Country Code** below:\n"
            "(e.g., `CA`, `FR`, `DE`)",
            parse_mode='Markdown'
        )
        return

    if action == 'get_same_proxy':
        last_code = context.user_data.get('last_country_code')
        if not last_code:
            await query.message.edit_text("⚠️ Session expired. Please type the country code again.")
            return
        
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
            # Updated to GET with correct endpoint and params
            await loop.run_in_executor(None, lambda: requests.get("https://dichvusocks.net/api/socks/data", headers=HEADERS, params={'page': '1', 'limit': '1'}, timeout=10))
        except: pass
        await asyncio.sleep(600)

async def on_startup(application):
    asyncio.create_task(background_keep_alive())

if __name__ == '__main__':
    application = ApplicationBuilder().token(TELEGRAM_BOT_TOKEN).post_init(on_startup).read_timeout(30).write_timeout(30).connect_timeout(30).job_queue(None).build()
    
    application.add_handler(CommandHandler('start', start))
    application.add_handler(CommandHandler('allow', allow_user))
    application.add_handler(CommandHandler('new', update_cookie))
    
    # Text Handler
    application.add_handler(MessageHandler(filters.TEXT & (~filters.COMMAND), handle_message))
    
    # Callback Handler
    application.add_handler(CallbackQueryHandler(button_click))

    print("Bot is running...")
    application.run_polling()
