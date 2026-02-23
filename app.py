import logging
import requests
import re
import json
import os
import random
import asyncio
import datetime
import pycountry
import math
import time
from urllib.parse import unquote
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

# ⚠️ LOG GROUP ID (Where reports and join requests are sent)
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

DEFAULT_COOKIE = '_ga=GA1.2.907186445.1766117007; ...' # Keep your full cookie here

HEADERS = {
    'User-Agent': 'Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/141.0.0.0 Safari/537.36 OPR/125.0.0.0',
    'Accept': '*/*',
    'X-Requested-With': 'XMLHttpRequest',
    'Referer': 'https://dichvusocks.net/sockslist',
}

# --- GLOBAL STATE ---
USER_COOLDOWNS = {} # {user_id: last_request_timestamp}

# --- DATA MANAGEMENT ---

def load_data():
    default_data = {
        'allowed_ids': list(ADMIN_IDS), 
        'username_map': {}, 
        'cookie': DEFAULT_COOKIE,
        'usage': {}
    }
    if not os.path.exists(DATA_FILE):
        return default_data
    try:
        with open(DATA_FILE, 'r') as f:
            data = json.load(f)
            # Ensure keys exist
            for key in default_data:
                if key not in data: data[key] = default_data[key]
            # Ensure Admins are always allowed
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

def update_headers_with_xsrf():
    cookie_str = HEADERS.get('Cookie', '')
    match = re.search(r'XSRF-TOKEN=([^;]+)', cookie_str)
    if match:
        token = unquote(match.group(1))
        HEADERS['X-XSRF-TOKEN'] = token

update_headers_with_xsrf()

def increment_usage(user_id):
    today_str = str(datetime.date.today())
    str_id = str(user_id)
    if str_id not in BOT_DATA['usage']:
        BOT_DATA['usage'][str_id] = {'date': today_str, 'count': 0}
    user_stat = BOT_DATA['usage'][str_id]
    if user_stat['date'] != today_str:
        user_stat['date'] = today_str
        user_stat['count'] = 0
    user_stat['count'] += 1
    save_data(BOT_DATA)
    return user_stat['count']

# --- PROXY API LOGIC ---

def _sync_get_available_proxies(country_full_name):
    url = "https://dichvusocks.net/api/socks/data"
    params = {
        'auth': '', 'useType': '', 'country': country_full_name,
        'region': '', 'city': '', 'blacklist': 'no',
        'zipcode': '', 'Host': '', 'page': '1', 'limit': '200' 
    }
    try:
        response = requests.get(url, headers=HEADERS, params=params, timeout=10)
        if response.status_code == 200:
            data = response.json()
            rows = data.get('rows', [])
            proxies = []
            for r in rows:
                if not r.get('Region') or r['Region'] == 'Unknown': continue
                ptype = r.get('useType', 'N/A')
                ptype_short = ptype[:3] if ptype else "UNK"
                proxies.append({
                    'id': r['Id'], 'region': r['Region'],
                    'speed': r.get('Speed', 0), 'type': ptype_short
                })
            proxies.sort(key=lambda x: (x['region'], -float(x['speed'])))
            return proxies, None
        return [], f"API Error: {response.status_code}"
    except Exception as e:
        return [], str(e)

def _sync_fetch_proxy_obj_random(country_full_name, region=''):
    url = "https://dichvusocks.net/api/socks/data"
    params = {
        'auth': '', 'useType': '', 'country': country_full_name,
        'region': region, 'city': '', 'blacklist': 'no', 
        'zipcode': '', 'Host': '', 'page': '1', 'limit': '20'
    }
    try:
        response = requests.get(url, headers=HEADERS, params=params, timeout=10)
        if response.status_code == 200:
            data = response.json()
            proxy_list = data.get('rows', [])
            if not proxy_list: return None, "No proxies found."
            return random.choice(proxy_list), None 
        return None, f"API Error: {response.status_code}"
    except Exception as e:
        return None, str(e)

def _sync_reveal_credentials(proxy_id):
    url = "https://dichvusocks.net/api/socks/view"
    params = {'id': proxy_id}
    try:
        response = requests.get(url, headers=HEADERS, params=params, timeout=10)
        if response.status_code == 200:
            data = response.json()
            if data.get('success') is True and 'data' in data:
                d = data['data']
                return f"{d['ip']}:{d['port']}:{d['username']}:{d['password']}", None
            return None, "API Error: Success False or Data Missing"
        return None, f"HTTP Error: {response.status_code}"
    except Exception as e:
        return None, str(e)

def get_full_country_name(code_or_name):
    clean_input = code_or_name.strip().upper()
    if clean_input in COUNTRY_OVERRIDES: return COUNTRY_OVERRIDES[clean_input]
    if len(clean_input) == 2:
        try:
            country = pycountry.countries.get(alpha_2=clean_input)
            if country: return country.name.split(',')[0]
        except: pass
    return code_or_name.title()

# --- HANDLERS ---

async def start(update: Update, context: ContextTypes.DEFAULT_TYPE):
    user = update.effective_user
    
    # Save user to map
    if user.username:
        BOT_DATA['username_map'][user.username.lower()] = user.id
    save_data(BOT_DATA)

    # 1. NOTIFY ADMINS OF NEW JOIN
    user_mention = f"@{user.username}" if user.username else "No Username"
    log_msg = (
        f"🔔 **New User Joined**\n\n"
        f"👤 **User:** {user_mention}\n"
        f"📛 **First Name:** {user.first_name}\n"
        f"📛 **Last Name:** {user.last_name or 'N/A'}\n"
        f"🆔 **ID:** `{user.id}`"
    )
    
    # Show allow button to admins if not already allowed
    kb = None
    if user.id not in BOT_DATA['allowed_ids']:
        kb = InlineKeyboardMarkup([[InlineKeyboardButton("✅ Allow User", callback_data=f"allow_user_{user.id}")]])
    
    await context.bot.send_message(chat_id=LOG_GROUP_ID, text=log_msg, reply_markup=kb, parse_mode='Markdown')

    # 2. Check access
    if user.id not in BOT_DATA['allowed_ids']:
        await update.message.reply_text(f"⌛ **Your request has been sent to admins.**\nPlease wait for approval. ID: `{user.id}`", parse_mode='Markdown')
        return

    markup = ReplyKeyboardMarkup([['Get Proxy ✨']], resize_keyboard=True)
    await update.message.reply_text("👋 **Welcome Back!**\nClick **Get Proxy** to start.", reply_markup=markup, parse_mode='Markdown')

async def handle_message(update: Update, context: ContextTypes.DEFAULT_TYPE):
    user = update.effective_user
    if user.id not in BOT_DATA['allowed_ids']: return

    text = update.message.text.strip()
    
    if text == 'Get Proxy ✨':
        await update.message.reply_text("🌍 **Select Country**\nType the **2-letter Code** (e.g., `US`, `VN`, `CA`).", parse_mode='Markdown')
        return

    # Process if it looks like a country code
    if len(text) == 2 or len(text) > 3:
        await process_country_selection(update.message, text, context)

async def process_country_selection(message_obj, country_input, context):
    full_name = get_full_country_name(country_input)
    msg = await message_obj.reply_text(f"🔍 Fetching proxies for **{full_name}**...", parse_mode='Markdown')
    
    loop = asyncio.get_running_loop()
    proxies, error = await loop.run_in_executor(None, _sync_get_available_proxies, full_name)
    
    if error:
        await msg.edit_text(f"❌ Error: {error}")
        return

    context.user_data['country_full'] = full_name
    context.user_data['regions_list'] = proxies
    
    if not proxies:
        await msg.edit_text(f"⚠️ No proxies found for **{full_name}**.", 
                            reply_markup=InlineKeyboardMarkup([[InlineKeyboardButton("🎲 Try Random Proxy", callback_data="get_proxy_random")]]))
        return

    await show_region_page(msg, 1, context)

async def show_region_page(message_obj, page, context):
    proxies = context.user_data.get('regions_list', [])
    full_name = context.user_data.get('country_full', 'Unknown')
    
    items_per_page = 10
    total_pages = math.ceil(len(proxies) / items_per_page)
    start_idx = (page - 1) * items_per_page
    end_idx = start_idx + items_per_page
    current_proxies = proxies[start_idx:end_idx]
    
    keyboard = []
    row = []
    for p in current_proxies:
        label = f"{p['region']} ({p['speed']} - {p['type']})"
        row.append(InlineKeyboardButton(label, callback_data=f"sel_id_{p['id']}"))
        if len(row) == 2:
            keyboard.append(row); row = []
    if row: keyboard.append(row)
    
    nav = []
    if page > 1: nav.append(InlineKeyboardButton("⬅️", callback_data=f"reg_page_{page-1}"))
    nav.append(InlineKeyboardButton(f"{page}/{total_pages}", callback_data="noop"))
    if page < total_pages: nav.append(InlineKeyboardButton("➡️", callback_data=f"reg_page_{page+1}"))
    keyboard.append(nav)

    keyboard.append([InlineKeyboardButton("🎲 Any Region (Random)", callback_data="get_proxy_random")])
    keyboard.append([InlineKeyboardButton("🌍 Change Country", callback_data="change_country")])
    
    await message_obj.edit_text(
        f"🌍 **Select Proxy for {full_name}**\nChoose a region from the list below:",
        reply_markup=InlineKeyboardMarkup(keyboard),
        parse_mode='Markdown'
    )

async def process_proxy_fetch(message_obj, country, region, context, user, proxy_id=None, is_edit=True):
    # Determine wait time
    now = time.time()
    last_req = USER_COOLDOWNS.get(user.id, 0)
    if now - last_req < 30:
        remaining = int(30 - (now - last_req))
        await context.bot.send_message(chat_id=user.id, text=f"⏳ **Cooldown active!**\nPlease wait **{remaining} seconds** before generating another proxy.")
        return

    USER_COOLDOWNS[user.id] = now

    # Show loading
    status_msg = None
    if is_edit and hasattr(message_obj, 'edit_text'):
        status_msg = await message_obj.edit_text("⏳ Unlocking proxy...", parse_mode='Markdown')
    else:
        status_msg = await context.bot.send_message(chat_id=user.id, text="⏳ Unlocking proxy...", parse_mode='Markdown')

    loop = asyncio.get_running_loop()
    
    if proxy_id:
        pid = proxy_id
        p_list = context.user_data.get('regions_list', [])
        p_obj = next((p for p in p_list if str(p['id']) == str(pid)), {})
        speed, p_type, real_region = p_obj.get('speed', 'N/A'), p_obj.get('type', 'N/A'), p_obj.get('region', region)
        context.user_data['last_region'] = real_region
    else:
        proxy_obj, error = await loop.run_in_executor(None, _sync_fetch_proxy_obj_random, country, region)
        if error:
            await status_msg.edit_text(f"❌ **Error:** {error}")
            return
        pid, speed, p_type, real_region = proxy_obj['Id'], proxy_obj.get('Speed', 'N/A'), proxy_obj.get('useType', 'N/A'), proxy_obj.get('Region', region)
        context.user_data['last_region'] = real_region

    creds, error = await loop.run_in_executor(None, _sync_reveal_credentials, pid)
    if error:
        await status_msg.edit_text(f"❌ **Reveal Error:** {error}")
        return

    try:
        ip, port, u, p = creds.split(':')
    except:
        ip, port, u, p = "N/A", "N/A", "N/A", "N/A"

    final_text = (
        f"✅ **{country} Proxy Generated**\n"
        f"📍 Region: {real_region}\n"
        f"🚀 Speed: **{speed}** | 📶 Type: **{p_type}**\n\n"
        f"`{creds}`\n\n"
        f"**Details:**\nHost: `{ip}`\nPort: `{port}`\nUser: `{u}`\nPass: `{p}`"
    )
    
    kb = InlineKeyboardMarkup([
        [InlineKeyboardButton("🔄 Get Another (Same Region)", callback_data="get_same_proxy")],
        [InlineKeyboardButton("🔙 Back to Regions", callback_data="back_to_regions")],
        [InlineKeyboardButton("🌍 Change Country", callback_data="change_country")]
    ])
    
    await status_msg.edit_text(final_text, parse_mode='Markdown', reply_markup=kb)

    # --- LOGGING ---
    usage_count = increment_usage(user.id)
    log_message = (
        f"🚀 **Proxy Generated**\n"
        f"👤 User: @{user.username} (`{user.id}`)\n"
        f"🏳️ Country: {country} | 📍 {real_region}\n"
        f"⚡ Speed: {speed}\n"
        f"📊 Daily Use: {usage_count}"
    )
    await context.bot.send_message(chat_id=LOG_GROUP_ID, text=log_message, parse_mode='Markdown')

async def button_click(update: Update, context: ContextTypes.DEFAULT_TYPE):
    query = update.callback_query
    action = query.data
    user = query.from_user

    # Admin: Allow User
    if action.startswith('allow_user_'):
        if user.id not in ADMIN_IDS:
            await query.answer("🚫 Admin Only", show_alert=True)
            return
        target_id = int(action.split('_')[2])
        if target_id not in BOT_DATA['allowed_ids']:
            BOT_DATA['allowed_ids'].append(target_id)
            save_data(BOT_DATA)
            await query.answer("✅ User Allowed")
            await query.message.edit_text(f"{query.message.text}\n\n✅ **APPROVED BY ADMIN**")
            # Notify User
            try:
                await context.bot.send_message(chat_id=target_id, text="✅ **Access Granted!**\nYour account has been approved by an admin. Click /start to begin.", parse_mode='Markdown')
            except: pass
        return

    # Admin: Ban User
    if action.startswith('ban_user_'):
        if user.id not in ADMIN_IDS:
            await query.answer("🚫 Admin Only", show_alert=True)
            return
        target_id = int(action.split('_')[2])
        if target_id in BOT_DATA['allowed_ids']:
            BOT_DATA['allowed_ids'].remove(target_id)
            save_data(BOT_DATA)
            await query.answer("🚫 Banned")
            await query.message.edit_text(f"{query.message.text}\n\n🚫 **BANNED**")
            # Notify User
            try:
                reason = "Violation of terms or suspicious activity."
                await context.bot.send_message(chat_id=target_id, text=f"🚫 **You have been banned.**\n\n**Reason:** {reason}\nContact an admin if you believe this is a mistake.")
            except: pass
        return

    if user.id not in BOT_DATA['allowed_ids']:
        await query.answer("🚫 Access Denied", show_alert=True)
        return

    country = context.user_data.get('country_full')
    
    if action.startswith('reg_page_'):
        await show_region_page(query.message, int(action.split('_')[2]), context)
    
    elif action.startswith('sel_id_'):
        pid = action.split('sel_id_')[1]
        await process_proxy_fetch(query.message, country, '', context, user, proxy_id=pid, is_edit=True)

    elif action == 'get_proxy_random':
        await process_proxy_fetch(query.message, country, '', context, user, is_edit=True)

    elif action == 'get_same_proxy':
        # Send in NEW message (is_edit=False)
        region = context.user_data.get('last_region', '')
        await process_proxy_fetch(query.message, country, region, context, user, is_edit=False)

    elif action == 'back_to_regions':
        await show_region_page(query.message, 1, context)

    elif action == 'change_country':
        await query.message.edit_text("🌍 **Select Country**\nType the 2-letter Code.", parse_mode='Markdown')

    await query.answer()

async def reset_users(update: Update, context: ContextTypes.DEFAULT_TYPE):
    if update.effective_user.id not in ADMIN_IDS: return
    BOT_DATA['allowed_ids'] = list(ADMIN_IDS)
    save_data(BOT_DATA)
    await update.message.reply_text("✅ All users reset to admins only.")

async def update_cookie(update: Update, context: ContextTypes.DEFAULT_TYPE):
    if update.effective_user.id not in ADMIN_IDS: return
    try:
        new_cookie = update.message.text.split(None, 1)[1]
        BOT_DATA['cookie'] = new_cookie
        HEADERS['Cookie'] = new_cookie
        save_data(BOT_DATA)
        update_headers_with_xsrf()
        await update.message.reply_text("✅ Cookie Updated!")
    except: await update.message.reply_text("Usage: `/new <cookie>`")

if __name__ == '__main__':
    application = ApplicationBuilder().token(TELEGRAM_BOT_TOKEN).build()
    
    application.add_handler(CommandHandler('start', start))
    application.add_handler(CommandHandler('reset', reset_users))
    application.add_handler(CommandHandler('new', update_cookie))
    application.add_handler(MessageHandler(filters.TEXT & (~filters.COMMAND), handle_message))
    application.add_handler(CallbackQueryHandler(button_click))

    print("Bot is starting...")
    application.run_polling()
