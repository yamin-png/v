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
import urllib3
from html import escape
from urllib.parse import unquote
from telegram import Update, InlineKeyboardButton, InlineKeyboardMarkup, ReplyKeyboardMarkup
from telegram.error import BadRequest
from telegram.ext import (
    ApplicationBuilder, 
    CommandHandler, 
    ContextTypes, 
    CallbackQueryHandler,
    MessageHandler,
    filters
)

# Suppress insecure request warnings from urllib3 (since we are using verify=False)
urllib3.disable_warnings(urllib3.exceptions.InsecureRequestWarning)

# --- CONFIGURATION ---
TELEGRAM_BOT_TOKEN = "8223325004:AAEIIhDOSAOPmALWmwEHuYeaJpjlzKNGJ1k"

# ⚠️ BOT USERNAME (Without @) - Used to redirect users back to the bot after payment
BOT_USERNAME = "Ismailproxybot"

# ⚠️ ADMIN IDS (List of integers)
ADMIN_IDS = [6616624640, 5473188537]

# ⚠️ LOG GROUP ID (Where usage logs and join notifications are sent)
LOG_GROUP_ID = -1003280360902

# --- PIPRAPAY PHP BRIDGE CONFIG ---
PHP_BRIDGE_URL = 'https://proxy.yamin.bd/api.php'
PHP_BRIDGE_SECRET = 'rubel_proxy_secret_2026' # Must match the $SECRET_TOKEN in api.php

# File to store usernames, cookies, usage stats, and balances
DATA_FILE = "bot_data.json"

# --- DISHVUSOCKS CONFIG ---
COUNTRY_OVERRIDES = {
    'RU': 'Russia', 'VN': 'Vietnam', 'KR': 'South Korea', 'IR': 'Iran',
    'MD': 'Moldova', 'TZ': 'Tanzania', 'SY': 'Syria', 'LA': 'Laos',
    'VE': 'Venezuela', 'BO': 'Bolivia', 'CD': 'Congo', 'EG': 'Egypt',
    'MM': 'Myanmar', 'US': 'United States'
}

DEFAULT_COOKIE = '_ga=GA1.2...; ' # Set your default cookie here

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
        'username_map': {}, 
        'cookie': DEFAULT_COOKIE,
        'usage': {},
        'users': {}, # {user_id_str: {'balance': 0.0}}
        'pending_payments': {}, # {order_id: {user_id, amount, status, pp_id}}
        'proxy_price': 10 # Default price per proxy
    }
    if not os.path.exists(DATA_FILE):
        return default_data
    try:
        with open(DATA_FILE, 'r') as f:
            data = json.load(f)
            for key in default_data:
                if key not in data: data[key] = default_data[key]
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

def init_user_balance(user_id):
    str_id = str(user_id)
    if str_id not in BOT_DATA['users']:
        BOT_DATA['users'][str_id] = {'balance': 0.0}
    return BOT_DATA['users'][str_id]

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

# --- PIPRAPAY API LOGIC (VIA PHP BRIDGE) ---
def _sync_create_piprapay(amount, user_id):
    order_id = f"PAY_{user_id}_{int(time.time())}"
    payload = {
        'secret': PHP_BRIDGE_SECRET,
        'action': 'create',
        'order_id': order_id,
        'user_id': str(user_id),
        'amount': str(amount)
    }
    try:
        res = requests.post(PHP_BRIDGE_URL, json=payload, timeout=15, verify=False)
        if res.status_code == 200:
            data = res.json()
            payment_url = data.get('pp_url') or data.get('payment_url') or data.get('url')
            pp_id = data.get('bp_id') or data.get('pp_id') or data.get('id') or data.get('invoice_id')
            if payment_url and pp_id:
                return payment_url, order_id, pp_id
        else:
            print(f"Bridge API Error: Status {res.status_code}, Response: {res.text}")
        return None, None, None
    except Exception as e:
        print("Bridge Create Error:", e)
        return None, None, None

def _sync_verify_piprapay(order_id, pp_id):
    payload = {
        'secret': PHP_BRIDGE_SECRET,
        'action': 'verify',
        'order_id': order_id,
        'pp_id': pp_id
    }
    try:
        res = requests.post(PHP_BRIDGE_URL, json=payload, timeout=15, verify=False)
        if res.status_code == 200:
            data = res.json()
            status = str(data.get('status', '')).upper()
            return status in ['SUCCESS', '1', 'COMPLETED', 'PAID']
        return False
    except Exception as e:
        print("Bridge Verify Error:", e)
        return False

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
    
    if not user.username:
        await update.message.reply_text(
            "⚠️ <b>Username Required</b>\n\nYou do not have a Telegram Username set. For security reasons, you cannot use this bot without one.",
            parse_mode='HTML'
        )
        return

    # Save user to map & init balance
    BOT_DATA['username_map'][user.username.lower()] = user.id
    init_user_balance(user.id)
    save_data(BOT_DATA)

    log_msg = (
        f"🔔 <b>New User Joined</b>\n\n"
        f"👤 <b>User:</b> @{escape(str(user.username))}\n"
        f"🆔 <b>ID:</b> <code>{user.id}</code>"
    )
    
    try:
        await context.bot.send_message(chat_id=LOG_GROUP_ID, text=log_msg, parse_mode='HTML')
    except Exception:
        pass

    markup = ReplyKeyboardMarkup([
        ['Get Proxy ✨', '💳 Add Balance'],
        ['👤 Profile']
    ], resize_keyboard=True)
    await update.message.reply_text("👋 <b>Welcome!</b>\nSelect an option below to start.", reply_markup=markup, parse_mode='HTML')

async def handle_message(update: Update, context: ContextTypes.DEFAULT_TYPE):
    user = update.effective_user
    if not user.username: return
    
    text = update.message.text.strip()
    
    # 1. State: Awaiting Deposit Amount
    if context.user_data.get('state') == 'awaiting_deposit':
        try:
            amount = float(text)
            if amount < 10:
                await update.message.reply_text("⚠️ Minimum deposit amount is 10 TK. Try again:")
                return
            
            msg = await update.message.reply_text("⏳ Generating payment link...")
            loop = asyncio.get_running_loop()
            payment_url, order_id, pp_id = await loop.run_in_executor(None, _sync_create_piprapay, amount, user.id)
            
            if payment_url and order_id:
                # Save Pending Payment
                BOT_DATA['pending_payments'][order_id] = {
                    'user_id': user.id, 'amount': amount, 'status': 'pending', 'pp_id': pp_id
                }
                save_data(BOT_DATA)
                
                kb = InlineKeyboardMarkup([
                    [InlineKeyboardButton(f"💳 Pay {amount} TK", url=payment_url)],
                    [InlineKeyboardButton("✅ Check Payment", callback_data=f"checkpay_{order_id}")]
                ])
                await msg.edit_text(f"🔗 <b>Payment Link Created!</b>\n\nClick the button below to pay <b>{amount} TK</b>. After completing the payment, click <b>Check Payment</b>.", reply_markup=kb, parse_mode='HTML')
            else:
                await msg.edit_text("❌ Payment Gateway Error. Please try again later.")
                
            context.user_data['state'] = None
            return
        except ValueError:
            await update.message.reply_text("❌ Please enter a valid number.")
            return

    # 2. State: Awaiting Credit Amount (Admin)
    if context.user_data.get('state') == 'awaiting_credit_amount' and user.id in ADMIN_IDS:
        try:
            amount = float(text)
            target = context.user_data.get('credit_target')
            
            # Resolve Target (Username or ID)
            target_id = None
            if target.startswith('@'):
                target_id = BOT_DATA['username_map'].get(target[1:].lower())
            elif target.isdigit():
                target_id = int(target)
                
            if not target_id:
                await update.message.reply_text("❌ Could not find user. Make sure they have started the bot.")
                context.user_data['state'] = None
                return
                
            init_user_balance(target_id)
            BOT_DATA['users'][str(target_id)]['balance'] += amount
            save_data(BOT_DATA)
            
            await update.message.reply_text(f"✅ Successfully added <b>{amount} TK</b> to user <code>{target_id}</code>.", parse_mode='HTML')
            try:
                await context.bot.send_message(chat_id=target_id, text=f"💰 <b>Funds Added!</b>\nAdmin has credited <b>{amount} TK</b> to your account.", parse_mode='HTML')
            except: pass
            
            context.user_data['state'] = None
            return
        except ValueError:
            await update.message.reply_text("❌ Please enter a valid number.")
            return

    # Standard Button Actions
    if text == 'Get Proxy ✨':
        await update.message.reply_text("🌍 <b>Select Country</b>\nType the <b>2-letter Code</b> (e.g., <code>US</code>, <code>VN</code>, <code>CA</code>).", parse_mode='HTML')
        return
        
    elif text == '💳 Add Balance':
        context.user_data['state'] = 'awaiting_deposit'
        await update.message.reply_text("💰 <b>How much TK do you want to add?</b>\n\nEnter the amount below (Min 10):", parse_mode='HTML')
        return
        
    elif text == '👤 Profile':
        init_user_balance(user.id)
        bal = round(BOT_DATA['users'][str(user.id)]['balance'], 2)
        price = BOT_DATA.get('proxy_price', 10)
        
        msg = (
            f"👤 <b>Your Profile</b>\n\n"
            f"🆔 <b>ID:</b> <code>{user.id}</code>\n"
            f"💰 <b>Balance:</b> {bal} TK\n"
            f"🚀 <b>Proxy Cost:</b> {price} TK per IP\n"
        )
        await update.message.reply_text(msg, parse_mode='HTML')
        return

    if len(text) == 2 or len(text) > 3:
        await process_country_selection(update.message, text, context)

async def cmd_credit(update: Update, context: ContextTypes.DEFAULT_TYPE):
    if update.effective_user.id not in ADMIN_IDS: return
    try:
        target = context.args[0]
        context.user_data['credit_target'] = target
        context.user_data['state'] = 'awaiting_credit_amount'
        await update.message.reply_text(f"💰 Target selected: <b>{target}</b>\n\nEnter the amount to credit (You can use negative numbers to deduct):", parse_mode='HTML')
    except IndexError:
        await update.message.reply_text("⚙️ <b>Usage:</b>\n<code>/credit @username</code> OR <code>/credit 123456789</code>", parse_mode='HTML')

async def cmd_set_price(update: Update, context: ContextTypes.DEFAULT_TYPE):
    if update.effective_user.id not in ADMIN_IDS: return
    try:
        price = float(context.args[0])
        BOT_DATA['proxy_price'] = price
        save_data(BOT_DATA)
        await update.message.reply_text(f"✅ <b>Success:</b> Proxy price updated to {price} TK.", parse_mode='HTML')
    except:
        await update.message.reply_text("⚙️ <b>Usage:</b>\n<code>/setprice 10.5</code>", parse_mode='HTML')

async def process_country_selection(message_obj, country_input, context):
    full_name = get_full_country_name(country_input)
    msg = await message_obj.reply_text(f"🔍 Fetching proxies for <b>{escape(str(full_name))}</b>...", parse_mode='HTML')
    
    loop = asyncio.get_running_loop()
    proxies, error = await loop.run_in_executor(None, _sync_get_available_proxies, full_name)
    
    if error:
        try:
            await msg.edit_text(f"❌ Error: {escape(str(error))}", parse_mode='HTML')
        except BadRequest as e:
            if "Message is not modified" not in str(e): raise e
        return

    context.user_data['country_full'] = full_name
    context.user_data['regions_list'] = proxies
    
    if not proxies:
        try:
            await msg.edit_text(f"⚠️ No proxies found for <b>{escape(str(full_name))}</b>.", 
                                reply_markup=InlineKeyboardMarkup([[InlineKeyboardButton("🎲 Try Random Proxy", callback_data="get_proxy_random")]]),
                                parse_mode='HTML')
        except BadRequest as e:
            if "Message is not modified" not in str(e): raise e
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
    
    try:
        await message_obj.edit_text(
            f"🌍 <b>Select Proxy for {escape(str(full_name))}</b>\nChoose a region from the list below:",
            reply_markup=InlineKeyboardMarkup(keyboard),
            parse_mode='HTML'
        )
    except BadRequest as e:
        if "Message is not modified" not in str(e): raise e

async def process_proxy_fetch(message_obj, country, region, context, user, proxy_id=None, is_edit=True):
    # 1. Safety Check
    if not country:
        error_text = "❌ <b>Session Lost:</b> Please select a country again by clicking 'Get Proxy ✨'."
        if is_edit and hasattr(message_obj, 'edit_text'):
            try: await message_obj.edit_text(error_text, parse_mode='HTML')
            except: pass
        else: await context.bot.send_message(chat_id=user.id, text=error_text, parse_mode='HTML')
        return

    # 2. Balance Check (Do not deduct yet!)
    price = BOT_DATA.get('proxy_price', 10)
    user_str = str(user.id)
    init_user_balance(user.id)
    
    if BOT_DATA['users'][user_str]['balance'] < price:
        err = f"❌ <b>Insufficient Balance!</b>\n\n💰 Your balance: <b>{BOT_DATA['users'][user_str]['balance']} TK</b>\n🚀 Proxy Price: <b>{price} TK</b>\n\nPlease click <b>💳 Add Balance</b> to top up."
        if is_edit and hasattr(message_obj, 'edit_text'):
            try: await message_obj.edit_text(err, parse_mode='HTML')
            except: pass
        else: await context.bot.send_message(chat_id=user.id, text=err, parse_mode='HTML')
        return

    # 3. Cooldown Check
    now = time.time()
    last_req = USER_COOLDOWNS.get(user.id, 0)
    if now - last_req < 10: # Shortened cooldown to 10 seconds
        remaining = int(10 - (now - last_req))
        await context.bot.send_message(chat_id=user.id, text=f"⏳ Please wait <b>{remaining} seconds</b>...", parse_mode='HTML')
        return
    USER_COOLDOWNS[user.id] = now

    status_msg = message_obj
    if is_edit and hasattr(message_obj, 'edit_text'):
        try: status_msg = await message_obj.edit_text("⏳ Unlocking proxy...", parse_mode='HTML')
        except: pass
    else:
        status_msg = await context.bot.send_message(chat_id=user.id, text="⏳ Unlocking proxy...", parse_mode='HTML')

    loop = asyncio.get_running_loop()
    
    # 4. Fetch Proxy Details
    if proxy_id:
        pid = proxy_id
        p_list = context.user_data.get('regions_list', [])
        p_obj = next((p for p in p_list if str(p['id']) == str(pid)), {})
        speed, p_type, real_region = p_obj.get('speed', 'N/A'), p_obj.get('type', 'N/A'), p_obj.get('region', region)
        context.user_data['last_region'] = real_region
    else:
        proxy_obj, error = await loop.run_in_executor(None, _sync_fetch_proxy_obj_random, country, region)
        if error:
            USER_COOLDOWNS[user.id] = 0
            try: await status_msg.edit_text(f"❌ <b>Error:</b> {escape(str(error))}", parse_mode='HTML')
            except: pass
            return # Exit safely. NO BALANCE DEDUCTED
            
        pid, speed, p_type, real_region = proxy_obj['Id'], proxy_obj.get('Speed', 'N/A'), proxy_obj.get('useType', 'N/A'), proxy_obj.get('Region', region)
        context.user_data['last_region'] = real_region

    # 5. Reveal Proxy Credentials
    creds, error = await loop.run_in_executor(None, _sync_reveal_credentials, pid)
    if error:
        USER_COOLDOWNS[user.id] = 0 
        try: await status_msg.edit_text(f"❌ <b>Reveal Error:</b> {escape(str(error))}", parse_mode='HTML')
        except: pass
        return # Exit safely. NO BALANCE DEDUCTED

    # --- SUCCESS! Deduct Balance ---
    BOT_DATA['users'][user_str]['balance'] -= price
    save_data(BOT_DATA)
    new_bal = round(BOT_DATA['users'][user_str]['balance'], 2)

    try: ip, port, u, p = creds.split(':')
    except: ip, port, u, p = "N/A", "N/A", "N/A", "N/A"

    final_text = (
        f"✅ <b>{escape(str(country))} Proxy Generated</b>\n"
        f"📍 Region: {escape(str(real_region))}\n"
        f"🚀 Speed: <b>{escape(str(speed))}</b> | 📶 Type: <b>{escape(str(p_type))}</b>\n\n"
        f"<code>{escape(str(creds))}</code>\n\n"
        f"<b>Details:</b>\nHost: <code>{escape(str(ip))}</code>\nPort: <code>{escape(str(port))}</code>\nUser: <code>{escape(str(u))}</code>\nPass: <code>{escape(str(p))}</code>\n\n"
        f"<i>💰 New Balance: {new_bal} TK (-{price} TK)</i>"
    )
    
    kb = InlineKeyboardMarkup([
        [InlineKeyboardButton("🔄 Get Another (Same Region)", callback_data="get_same_proxy")],
        [InlineKeyboardButton("🔙 Back to Regions", callback_data="back_to_regions")],
        [InlineKeyboardButton("🌍 Change Country", callback_data="change_country")]
    ])
    
    try: await status_msg.edit_text(final_text, parse_mode='HTML', reply_markup=kb)
    except: pass

    # --- LOGGING ---
    usage_count = increment_usage(user.id)
    log_message = (
        f"🚀 <b>Proxy Generated</b>\n"
        f"👤 <b>User:</b> @{escape(str(user.username))} (<code>{user.id}</code>)\n"
        f"🏳️ <b>Country:</b> {escape(str(country))} | 📍 {escape(str(real_region))}\n"
        f"💰 <b>Spent:</b> {price} TK"
    )
    try: await context.bot.send_message(chat_id=LOG_GROUP_ID, text=log_message, parse_mode='HTML')
    except: pass

async def button_click(update: Update, context: ContextTypes.DEFAULT_TYPE):
    query = update.callback_query
    action = query.data
    user = query.from_user

    if not user.username:
        await query.answer("⚠️ Username Required!", show_alert=True)
        return

    # Handle Check Payment Verification
    if action.startswith('checkpay_'):
        order_id = action.split('_')[1]
        order = BOT_DATA['pending_payments'].get(order_id)
        
        if not order:
            await query.answer("❌ Order not found.", show_alert=True)
            return
            
        if order['status'] == 'completed':
            await query.answer("✅ This payment was already completed!", show_alert=True)
            return
            
        loop = asyncio.get_running_loop()
        is_paid = await loop.run_in_executor(None, _sync_verify_piprapay, order_id, order['pp_id'])
        
        if is_paid:
            # Add balance
            amount = order['amount']
            init_user_balance(order['user_id'])
            BOT_DATA['users'][str(order['user_id'])]['balance'] += amount
            BOT_DATA['pending_payments'][order_id]['status'] = 'completed'
            save_data(BOT_DATA)
            
            await query.answer("🎉 Payment Verified! Balance added.", show_alert=True)
            try:
                await query.message.edit_text(f"✅ <b>Payment Successful!</b>\n\n<b>{amount} TK</b> has been successfully added to your balance.", parse_mode='HTML')
            except: pass
        else:
            await query.answer("⏳ Payment not found or pending. Please wait a minute and try again.", show_alert=True)
        return

    country = context.user_data.get('country_full')
    if action.startswith('reg_page_'):
        await show_region_page(query.message, int(action.split('_')[2]), context)
    elif action.startswith('sel_id_'):
        await process_proxy_fetch(query.message, country, '', context, user, proxy_id=action.split('sel_id_')[1], is_edit=True)
    elif action == 'get_proxy_random':
        await process_proxy_fetch(query.message, country, '', context, user, is_edit=True)
    elif action == 'get_same_proxy':
        await process_proxy_fetch(query.message, country, context.user_data.get('last_region', ''), context, user, is_edit=False)
    elif action == 'back_to_regions':
        await show_region_page(query.message, 1, context)
    elif action == 'change_country':
        try: await query.message.edit_text("🌍 <b>Select Country</b>\nType the 2-letter Code.", parse_mode='HTML')
        except: pass

    await query.answer()

async def update_cookie(update: Update, context: ContextTypes.DEFAULT_TYPE):
    if update.effective_user.id not in ADMIN_IDS: return
    try:
        new_cookie = update.message.text.split(None, 1)[1]
        BOT_DATA['cookie'] = new_cookie
        HEADERS['Cookie'] = new_cookie
        save_data(BOT_DATA)
        update_headers_with_xsrf()
        await update.message.reply_text("✅ Cookie Updated!")
    except: await update.message.reply_text("Usage: <code>/new &lt;cookie&gt;</code>", parse_mode='HTML')

if __name__ == '__main__':
    application = ApplicationBuilder().token(TELEGRAM_BOT_TOKEN).build()
    
    application.add_handler(CommandHandler('start', start))
    application.add_handler(CommandHandler('new', update_cookie))
    application.add_handler(CommandHandler('credit', cmd_credit))
    application.add_handler(CommandHandler('setprice', cmd_set_price))
    application.add_handler(MessageHandler(filters.TEXT & (~filters.COMMAND), handle_message))
    application.add_handler(CallbackQueryHandler(button_click))

    print("Bot is starting...")
    application.run_polling()
