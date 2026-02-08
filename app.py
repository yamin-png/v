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

# File to store allowed users, cookies, and usage stats
DATA_FILE = "allowed_users.json"

# --- DISHVUSOCKS CONFIG ---
COUNTRY_OVERRIDES = {
    'RU': 'Russia', 'VN': 'Vietnam', 'KR': 'South Korea', 'IR': 'Iran',
    'MD': 'Moldova', 'TZ': 'Tanzania', 'SY': 'Syria', 'LA': 'Laos',
    'VE': 'Venezuela', 'BO': 'Bolivia', 'CD': 'Congo', 'EG': 'Egypt',
    'MM': 'Myanmar', 'US': 'United States'
}

DEFAULT_COOKIE = '_ga=GA1.2.907186445.1766117007; _gid=GA1.2.409351101.1768402779; notice=1; notice_time=1739170824; PHPSESSID=c05e028ff8e962f21bc3cfa2b94ee4d4; 0878fb59c92af61fa8719cf910b34ff6=1e6047aef118f49bf18fa82f8ff7e03fb61bf4e9a%3A4%3A%7Bi%3A0%3Bi%3A498299%3Bi%3A1%3Bs%3A11%3A%22syaminhasan%22%3Bi%3A2%3Bi%3A2592000%3Bi%3A3%3Ba%3A0%3A%7B%7D%7D; loginCookie=KCKJX956h0; _ga_N1LC62MVC1=GS2.2.s1768978726$o67$g1$t1768978931$j60$l0$h0; cf_clearance=bnFyij3y39cvidXqCV9rCK7L0UJwjgRV0LWPAxC2DY4-1768987008-1.2.1.1-eqwzq9Zl4un2k2Jf4W4W3jLIxTnHZhA4m6DsU_YIW.wFhMG23jtD606sFj9s1wnXc7S8rOZ.WaoEmB3uFPrNkyKeerDMPtX6s79hkftk.LkvenclJ42Z39rw4IfThwS2eDtTMYRLXu0h.9Gc0twNta1BvCFMpvqmwgKLC0BEdsrlNPawZyKMdxWv1nfw.3F9ryo8Hf6.3q15BaXonm098PPkswBkl2ubCumd.3Ar0GQ; remember_user_59ba36addc2b2f9401580f014c7f58ea4e30989d=eyJpdiI6Ikx5a09seTRWQlJvWWN0alUrSmI4OXc9PSIsInZhbHVlIjoiK3ozcXhoTnNXUkdyQmU2RFVOd3M3ODIyYzF4VkRiN056WU9id3JhYzdWcTJKd2NBS0NHaFRzNy9CSWNGWnZ2T0JlR3VBMDZXMzdlL2N1VGNsNkVGQWY4T0ZndXg2ZE5BWlM2YzRsSFd6UysvUzR3UU1udUY5RHZvRThJeDgwRlU3Z0NrVmNscE40eC96Y2tTemlKRlhlOFREbDIwbVRhbTNJazUwZWRxdGZLdjRROFFMZjVBYVh4S0EwYmF2MWlsUGZYRHhPbWNSR2w5Q3NzcW1JaUI5OTZxZTJYMDJDUy9NSTI3bEZUZDUvST0iLCJtYWMiOiIwNmY1NDIwODU1OWQ3ZWFiOTM0ZmMwYjNkY2Y0M2VlMGQ3MDY5Y2JlNTNhMWIwYTIwYmFmYThmYjA5YzcwMDA2IiwidGFnIjoiIn0%3D; notice_seen=eyJpdiI6Im9PUXV6Rk5ORzNUNzNaT0FtK3FNSHc9PSIsInZhbHVlIjoidDNXcXcxSjJSU3RyNWVScURiYWFudWczUGpFNFpEbTBoSnhnbzNteDZSSFJWWVdqWFFEK3dKdnY3TkdlOE50cWdTS1QwMGE1c1JmTlNVYkZ4clQ1NUduUTNZTjEyZUxGT2dGWCtnU2gza0U9IiwibWFjIjoiYTkyNDMxMjA3MDg3M2M1ZmMyODEyNWRmMTY5OTdiZDVkMzg5NzA1MWM3YmM0YjNlM2FlMjI2MjQ0ODAyMWM5MiIsInRhZyI6IiJ9; XSRF-TOKEN=eyJpdiI6IjZjd2NxaEJpNmk1bkJKYjVuRjZ5Vmc9PSIsInZhbHVlIjoiaHlSc1hDZU1ZbGpPQlBtV3hkZU0vTERmemJXaDkwbkFiR1Z6Nm81YkhxRDN4WGR6dUtYL3d3T280N29ZYW41WENuWUVNaVFWNUN0VGFuVTNxMVRyS0hibXh1L2FuSDNxYjlQSzByVFgwZVJGY3d5b2hCdE1YeWRuQ3VyWS9RVmUiLCJtYWMiOiI5YTAyNWQ4MzU1MjI0OThjODNhNmVkYjM2NjhiNWQxNzIyN2NhNThlNzU0NTc5MWQ4MWE0NThlZTk3ODY2MzliIiwidGFnIjoiIn0%3D; dichvusocksnet-session=eyJpdiI6Imt6dXRzRkxsWkp6L0cxdWpXT0N1RGc9PSIsInZhbHVlIjoiK0U5d1BQRnlGdzZacmZmbEp1Qm5idVAzVFVIMUZKczZyZktKL3RwZkQ5T3p3ZXRVTytrL084cnZLRFo5Q05jd1ZoVUhVUUlaYWxrelMxWkk0STArd2dMSjFoNlNENklNbitsVWpYTGl2L2RvbkozOUN0a3FaRklMWE1RVWFsVnMiLCJtYWMiOiI5NGVhOWFjZGFkYjJkNWJkNjA1NzU0ODE2NDQ1MWIwZjAyMDY1NTFmNjk2MTc1NDE0MzQwNmNiNGUyOGMzYjIxIiwidGFnIjoiIn0%3D'

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
        'usage': {}
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

# --- HEADER HELPER (Auto XSRF) ---
def update_headers_with_xsrf():
    """Extracts XSRF-TOKEN from cookies and adds it to headers."""
    cookie_str = HEADERS.get('Cookie', '')
    match = re.search(r'XSRF-TOKEN=([^;]+)', cookie_str)
    if match:
        token = unquote(match.group(1))
        HEADERS['X-XSRF-TOKEN'] = token

update_headers_with_xsrf()

# --- DISHVUSOCKS LOGIC ---

def _sync_get_available_regions(country_full_name):
    """Fetches list of available regions for a country."""
    url = "https://dichvusocks.net/api/socks/data"
    params = {
        'auth': '', 'useType': '', 'country': country_full_name,
        'region': '', 'city': '', 'blacklist': 'no', # Always blacklist=no
        'zipcode': '', 'Host': '', 'page': '1', 'limit': '200' # Fetch more to find regions
    }
    try:
        response = requests.get(url, headers=HEADERS, params=params, timeout=10)
        if response.status_code == 200:
            data = response.json()
            rows = data.get('rows', [])
            regions = sorted(list(set(r['Region'] for r in rows if r.get('Region') and r['Region'] != 'Unknown')))
            return regions, None
        return [], f"API Error: {response.status_code}"
    except Exception as e:
        return [], str(e)

def _sync_fetch_proxy_id(country_full_name, region=''):
    url = "https://dichvusocks.net/api/socks/data"
    params = {
        'auth': '', 'useType': '', 'country': country_full_name,
        'region': region, 'city': '', 'blacklist': 'no', # Always blacklist=no
        'zipcode': '', 'Host': '', 'page': '1', 'limit': '20'
    }
    try:
        response = requests.get(url, headers=HEADERS, params=params, timeout=10)
        if response.status_code == 200:
            data = response.json()
            proxy_list = data.get('rows', [])
            if not proxy_list: return None, "No proxies found."
            return random.choice(proxy_list)['Id'], None
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

async def reset_users(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Resets allowed users list to Admins only."""
    user_id = update.effective_user.id
    if user_id not in ADMIN_IDS: return

    BOT_DATA['allowed_ids'] = list(ADMIN_IDS)
    save_data(BOT_DATA)
    await update.message.reply_text("✅ **All allowed users have been reset.**\nOnly admins remain.", parse_mode='Markdown')

async def start(update: Update, context: ContextTypes.DEFAULT_TYPE):
    user = update.effective_user
    if user.username:
        BOT_DATA['username_map'][user.username.lower()] = user.id
        save_data(BOT_DATA)

    if user.id not in BOT_DATA['allowed_ids']:
        await update.message.reply_text(f"🚫 Access Denied. ID: `{user.id}`", parse_mode='Markdown')
        return

    markup = ReplyKeyboardMarkup([['Get Proxy ✨']], resize_keyboard=True)
    await update.message.reply_text("👋 **Bot Ready!**\nClick **Get Proxy** to start.", reply_markup=markup, parse_mode='Markdown')

async def handle_message(update: Update, context: ContextTypes.DEFAULT_TYPE):
    user = update.effective_user
    text = update.message.text.strip()
    
    # --- ADMIN ALLOW LOGIC ---
    if user.id in ADMIN_IDS:
        # Check if text contains typical separators for bulk input
        if re.search(r'[,\n]', text) or text.isdigit() or text.startswith('@'):
            # It's likely an allow list attempt, process it
            tokens = re.split(r'[,\s\n]+', text)
            added_count = 0
            
            for token in tokens:
                token = token.strip()
                if not token: continue
                
                target_id = None
                if token.isdigit() and len(token) > 5: # ID check
                    target_id = int(token)
                elif token.startswith('@'): # Username check
                    clean_user = token[1:].lower()
                    target_id = BOT_DATA['username_map'].get(clean_user)
                
                if target_id and target_id not in BOT_DATA['allowed_ids']:
                    BOT_DATA['allowed_ids'].append(target_id)
                    added_count += 1
            
            if added_count > 0:
                save_data(BOT_DATA)
                await update.message.reply_text(f"✅ **Added {added_count} users to allow list.**", parse_mode='Markdown')
                return
            # If nothing valid found, fall through to proxy logic (admins might want proxies too)

    # --- NORMAL USER LOGIC ---
    if user.id not in BOT_DATA['allowed_ids']: return

    if text == 'Get Proxy ✨':
        await update.message.reply_text("🌍 **Select Country**\nType the **2-letter Code** (e.g., `CA`, `DE`).", parse_mode='Markdown')
        return

    # Treat text as country code
    await process_country_selection(update.message, text, context)

async def process_country_selection(message_obj, country_input, context):
    full_name = get_full_country_name(country_input)
    
    msg = await message_obj.reply_text(f"🔍 Checking regions for **{full_name}**...", parse_mode='Markdown')
    
    loop = asyncio.get_running_loop()
    regions, error = await loop.run_in_executor(None, _sync_get_available_regions, full_name)
    
    if error:
        await msg.edit_text(f"❌ Error fetching regions: {error}")
        return

    context.user_data['country_full'] = full_name
    context.user_data['regions_list'] = regions
    
    if not regions:
        # No regions found, offer direct proxy
        await msg.edit_text(f"⚠️ No specific regions found for **{full_name}**.\nClick below to get a random proxy.", 
                            reply_markup=InlineKeyboardMarkup([[InlineKeyboardButton("🎲 Get Random Proxy", callback_data="get_proxy_random")]]))
        return

    await show_region_page(msg, 1, context)

async def show_region_page(message_obj, page, context):
    regions = context.user_data.get('regions_list', [])
    full_name = context.user_data.get('country_full', 'Unknown')
    
    items_per_page = 10
    total_pages = math.ceil(len(regions) / items_per_page)
    
    start_idx = (page - 1) * items_per_page
    end_idx = start_idx + items_per_page
    current_regions = regions[start_idx:end_idx]
    
    keyboard = []
    # Region Buttons (2 per row)
    row = []
    for reg in current_regions:
        row.append(InlineKeyboardButton(reg, callback_data=f"sel_reg_{reg}"))
        if len(row) == 2:
            keyboard.append(row)
            row = []
    if row: keyboard.append(row)
    
    # Numbered Pagination
    pagination_row = []
    # Always show pages 1...N
    for i in range(1, total_pages + 1):
        if i == page:
            pagination_row.append(InlineKeyboardButton(f"• {i} •", callback_data="noop"))
        else:
            pagination_row.append(InlineKeyboardButton(str(i), callback_data=f"reg_page_{i}"))
    
    # Split pagination into rows if too long (max 8 per row)
    chunked_pagination = [pagination_row[i:i + 8] for i in range(0, len(pagination_row), 8)]
    for chunk in chunked_pagination:
        keyboard.append(chunk)

    keyboard.append([InlineKeyboardButton("🎲 Any Region", callback_data="get_proxy_random")])
    
    await message_obj.edit_text(
        f"🌍 **Select Region for {full_name}**\nPage {page}/{total_pages}",
        reply_markup=InlineKeyboardMarkup(keyboard),
        parse_mode='Markdown'
    )

async def process_proxy_fetch(message_obj, country, region, context):
    region_display = region if region else "Any"
    
    if hasattr(message_obj, 'edit_text'):
        await message_obj.edit_text(f"⏳ Fetching **{country}** ({region_display})...", parse_mode='Markdown')
    else:
        pass 

    loop = asyncio.get_running_loop()
    pid, error = await loop.run_in_executor(None, _sync_fetch_proxy_id, country, region)
    
    if error:
        btns = InlineKeyboardMarkup([[InlineKeyboardButton("🔙 Back to Regions", callback_data="back_to_regions")]])
        await message_obj.edit_text(f"❌ **Error:** {error}", reply_markup=btns)
        return

    creds, error = await loop.run_in_executor(None, _sync_reveal_credentials, pid)
    
    if error:
        await message_obj.edit_text(f"❌ **Reveal Error:** {error}")
        return

    try:
        ip, port, u, p = creds.split(':')
    except:
        ip, port, u, p = "N/A", "N/A", "N/A", "N/A"

    final_text = (
        f"✅ **{country} Proxy Generated**\n"
        f"📍 Region: {region_display}\n\n"
        f"`{creds}`\n\n"
        f"**Details:**\nHost: `{ip}`\nPort: `{port}`\nUser: `{u}`\nPass: `{p}`"
    )
    
    # Store for "Get Another"
    context.user_data['last_region'] = region

    kb = [
        [InlineKeyboardButton("🔄 Get Another (Same Region)", callback_data="get_same_proxy")],
        [InlineKeyboardButton("🔙 Select Different Region", callback_data="back_to_regions")],
        [InlineKeyboardButton("🌍 Change Country", callback_data="change_country")]
    ]
    
    await message_obj.edit_text(final_text, parse_mode='Markdown', reply_markup=InlineKeyboardMarkup(kb))

async def button_click(update: Update, context: ContextTypes.DEFAULT_TYPE):
    query = update.callback_query
    action = query.data
    user = query.from_user

    if user.id not in BOT_DATA['allowed_ids']:
        await query.answer("🚫 Access Denied")
        return

    await query.answer()
    
    country = context.user_data.get('country_full')
    
    if action.startswith('reg_page_'):
        page = int(action.split('_')[2])
        await show_region_page(query.message, page, context)
        return
        
    if action == 'noop': return

    if action.startswith('sel_reg_'):
        region = action.split('sel_reg_')[1]
        await process_proxy_fetch(query.message, country, region, context)
        return

    if action == 'get_proxy_random':
        await process_proxy_fetch(query.message, country, '', context)
        return

    if action == 'get_same_proxy':
        region = context.user_data.get('last_region', '')
        await process_proxy_fetch(query.message, country, region, context)
        return

    if action == 'back_to_regions':
        await show_region_page(query.message, 1, context)
        return

    if action == 'change_country':
        await query.message.edit_text("🌍 **Select Country**\nType the 2-letter Code.", parse_mode='Markdown')
        return

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

# --- BACKGROUND TASKS ---
async def background_keep_alive():
    loop = asyncio.get_running_loop()
    while True:
        try:
            await loop.run_in_executor(None, lambda: requests.get("https://dichvusocks.net/api/socks/data", headers=HEADERS, params={'page': '1', 'limit': '1'}, timeout=10))
        except: pass
        await asyncio.sleep(600)

async def on_startup(application):
    asyncio.create_task(background_keep_alive())

if __name__ == '__main__':
    application = ApplicationBuilder().token(TELEGRAM_BOT_TOKEN).post_init(on_startup).read_timeout(30).write_timeout(30).connect_timeout(30).job_queue(None).build()
    
    application.add_handler(CommandHandler('start', start))
    application.add_handler(CommandHandler('reset', reset_users))
    application.add_handler(CommandHandler('new', update_cookie))
    application.add_handler(MessageHandler(filters.TEXT & (~filters.COMMAND), handle_message))
    application.add_handler(CallbackQueryHandler(button_click))

    print("Bot is running...")
    application.run_polling()
