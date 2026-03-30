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

# --- CONFIGURATION ---
TELEGRAM_BOT_TOKEN = "8223325004:AAEIIhDOSAOPmALWmwEHuYeaJpjlzKNGJ1k"

# ⚠️ BOT USERNAME (Without @)
BOT_USERNAME = "Ismailproxybot"

# ⚠️ ADMIN IDS
ADMIN_IDS = [6616624640, 5473188537]

# ⚠️ LOG GROUP ID (Where usage logs and join notifications are sent)
LOG_GROUP_ID = -1003280360902

# --- PIPRAPAY PHP BRIDGE CONFIG ---
PHP_BRIDGE_URL = 'https://proxy.yamin.bd/api.php'
PHP_BRIDGE_SECRET = 'rubel_proxy_secret_2026'

# File to store usernames, cookies, usage stats, and balances
DATA_FILE = "bot_data.json"

# --- DISHVUSOCKS CONFIG ---
COUNTRY_OVERRIDES = {
    'RU': 'Russia', 'VN': 'Vietnam', 'KR': 'South Korea', 'IR': 'Iran',
    'MD': 'Moldova', 'TZ': 'Tanzania', 'SY': 'Syria', 'LA': 'Laos',
    'VE': 'Venezuela', 'BO': 'Bolivia', 'CD': 'Congo', 'EG': 'Egypt',
    'MM': 'Myanmar', 'US': 'United States'
}

DEFAULT_COOKIE = '_ga=GA1.2...; '

HEADERS = {
    'User-Agent': 'Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/141.0.0.0 Safari/537.36 OPR/125.0.0.0',
    'Accept': '*/*',
    'X-Requested-With': 'XMLHttpRequest',
    'Referer': 'https://dichvusocks.net/sockslist',
}

# --- DATA MANAGEMENT ---
def load_data():
    default_data = {
        'username_map': {}, 
        'cookie': DEFAULT_COOKIE,
        'usage': {},
        'users': {}, 
        'pending_payments': {}, 
        'manual_payments': {}, 
        'proxy_price': 10 
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

# --- SECURE PIPRAPAY API LOGIC ---
def _sync_create_piprapay(amount, user_id):
    order_id = f"PAY_{user_id}_{int(time.time())}"
    payload = {
        'secret': PHP_BRIDGE_SECRET,
        'action': 'create',
        'order_id': order_id,
        'user_id': str(user_id),
        'amount': str(amount)
    }
    bridge_headers = {
        'User-Agent': 'Mozilla/5.0 (Windows NT 10.0; Win64; x64)',
        'Accept': 'application/json',
        'Content-Type': 'application/json'
    }
    try:
        res = requests.post(PHP_BRIDGE_URL, json=payload, headers=bridge_headers, timeout=15)
        if res.status_code == 200:
            data = res.json()
            payment_url = data.get('pp_url') or data.get('payment_url') or data.get('url')
            pp_id = data.get('bp_id') or data.get('pp_id') or data.get('id') or data.get('invoice_id')
            if payment_url and pp_id:
                return payment_url, order_id, pp_id
    except Exception as e:
        print(f"Secure Bridge Create Error: {e}")
    return None, None, None

def _sync_verify_piprapay(order_id, pp_id):
    payload = {
        'secret': PHP_BRIDGE_SECRET,
        'action': 'verify',
        'order_id': order_id,
        'pp_id': pp_id,
        'invoice_id': pp_id  # Send multiple id fields just in case PHP bridge expects it
    }
    bridge_headers = {'Content-Type': 'application/json'}
    
    # Retry mechanism (2 attempts) in case of bridge timeouts or temporary network lags
    for attempt in range(2):
        try:
            res = requests.post(PHP_BRIDGE_URL, json=payload, headers=bridge_headers, timeout=15)
            if res.status_code == 200:
                data = res.json()
                
                # Broaden the parsing logic to catch all success variations
                status = str(data.get('status', '')).upper()
                data_status = str(data.get('data', {}).get('status', '')).upper() if isinstance(data.get('data'), dict) else ''
                msg_text = str(data.get('message', '')).upper()
                
                valid_statuses = ['SUCCESS', '1', 'COMPLETED', 'PAID', 'TRUE', 'APPROVED']
                
                if status in valid_statuses or data_status in valid_statuses:
                    return True
                if 'SUCCESS' in msg_text or 'PAID' in msg_text:
                    return True
                    
        except Exception as e:
            print(f"Secure Bridge Verify Error (Attempt {attempt+1}): {e}")
            time.sleep(1.5) # Wait slightly before retrying
            
    return False

# --- AUTO PAYMENT MONITOR (BACKGROUND TASK) ---
async def monitor_payment(context: ContextTypes.DEFAULT_TYPE, order_id: str, user_id: int, amount: float, pp_id: str, chat_id: int, message_id: int):
    loop = asyncio.get_running_loop()
    max_attempts = 60  # Check for 10 minutes (60 attempts * 10 seconds)
    
    for _ in range(max_attempts):
        await asyncio.sleep(10)  # Wait 10 seconds between checks
        
        # Stop checking if order was manually approved/rejected by admin
        order = BOT_DATA.get('pending_payments', {}).get(order_id)
        if not order or order.get('status') != 'pending':
            break
            
        is_paid = await loop.run_in_executor(None, _sync_verify_piprapay, order_id, pp_id)
        
        if is_paid:
            # Double check to prevent race conditions
            if BOT_DATA['pending_payments'][order_id]['status'] == 'completed':
                break
                
            # Update Balance
            init_user_balance(user_id)
            BOT_DATA['users'][str(user_id)]['balance'] += amount
            BOT_DATA['pending_payments'][order_id]['status'] = 'completed'
            save_data(BOT_DATA)
            
            # Notify User of Success
            success_msg = (
                f"✅ <b>PAYMENT AUTO-VERIFIED!</b>\n"
                f"━━━━━━━━━━━━━━━━━━━━\n"
                f"<b>{amount} TK</b> has been successfully added to your balance."
            )
            try:
                # Update the original payment message so the link disappears
                await context.bot.edit_message_text(
                    chat_id=chat_id,
                    message_id=message_id,
                    text=f"✅ <b>Payment of {amount} TK Completed & Verified!</b>",
                    parse_mode='HTML'
                )
                # Send a direct notification
                await context.bot.send_message(chat_id=user_id, text=success_msg, parse_mode='HTML')
            except: pass
            
            # Notify Admin Log Group
            log_receipt = (
                f"💰 <b>New Auto-Deposit Notification!</b>\n"
                f"━━━━━━━━━━━━━━━━━━━━\n"
                f"👤 User ID: <code>{user_id}</code>\n"
                f"💵 Amount: <b>{amount} TK</b>\n"
                f"💳 Method: PipraPay (Auto-Detected)\n"
                f"📅 Date: {datetime.datetime.now().strftime('%d-%m-%Y | %I:%M %p')}\n"
                f"━━━━━━━━━━━━━━━━━━━━\n"
                f"✅ Status: Successfully Added"
            )
            try: await context.bot.send_message(chat_id=LOG_GROUP_ID, text=log_receipt, parse_mode='HTML')
            except: pass
            
            # Update Admin Log Message
            log_msg_id = order.get('log_msg_id')
            if log_msg_id:
                try: 
                    await context.bot.edit_message_text(
                        chat_id=LOG_GROUP_ID, 
                        message_id=log_msg_id,
                        text=f"✅ <b>Processed for User ID:</b> <code>{user_id}</code>\n<b>Action:</b> Approved Automatically by System",
                        parse_mode='HTML'
                    )
                except: pass
            break
    else:
        # If loop finishes without breaking (10 minutes passed without payment)
        if BOT_DATA.get('pending_payments', {}).get(order_id, {}).get('status') == 'pending':
            BOT_DATA['pending_payments'][order_id]['status'] = 'expired'
            save_data(BOT_DATA)
            try:
                await context.bot.edit_message_text(
                    chat_id=chat_id,
                    message_id=message_id,
                    text=f"⏳ <b>Payment link expired.</b> Please generate a new deposit link.",
                    parse_mode='HTML'
                )
            except: pass

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

def resolve_user(target_str):
    target_str = target_str.strip()
    if target_str.startswith('@'):
        return BOT_DATA['username_map'].get(target_str[1:].lower())
    elif target_str.isdigit():
        return int(target_str)
    return None

def get_main_keyboard(user_id):
    kb = [
        ['Get Proxy ✨', '💳 Add Balance'],
        ['👤 Profile', '💸 Transfer']
    ]
    if user_id in ADMIN_IDS:
        kb.append(['⚙️ Admin Menu'])
    return ReplyKeyboardMarkup(kb, resize_keyboard=True)

# --- HANDLERS ---
async def start(update: Update, context: ContextTypes.DEFAULT_TYPE):
    user = update.effective_user
    
    if not user.username:
        await update.message.reply_text(
            "⚠️ <b>Username Required</b>\n━━━━━━━━━━━━━━━━━━━━\nYou do not have a Telegram Username set. For security reasons, you cannot use this bot without one.",
            parse_mode='HTML'
        )
        return

    BOT_DATA['username_map'][user.username.lower()] = user.id
    init_user_balance(user.id)
    save_data(BOT_DATA)

    log_msg = (
        f"🔔 <b>New User Joined</b>\n"
        f"━━━━━━━━━━━━━━━━━━━━\n"
        f"👤 <b>User:</b> @{escape(str(user.username))}\n"
        f"🆔 <b>ID:</b> <code>{user.id}</code>"
    )
    try:
        await context.bot.send_message(chat_id=LOG_GROUP_ID, text=log_msg, parse_mode='HTML')
    except: pass

    markup = get_main_keyboard(user.id)
    welcome_msg = (
        f"👋 <b>Welcome to Ismail Proxy Bot!</b>\n"
        f"━━━━━━━━━━━━━━━━━━━━\n"
        f"Get high-speed, premium proxies instantly.\n"
        f"Select an option from the menu below to begin! 👇"
    )
    await update.message.reply_text(welcome_msg, reply_markup=markup, parse_mode='HTML')

async def handle_message(update: Update, context: ContextTypes.DEFAULT_TYPE):
    user = update.effective_user
    if not user.username: return
    
    text = update.message.text.strip() if update.message.text else ""
    
    # --- COMMAND INTERCEPTION ---
    main_commands = ['Get Proxy ✨', '💳 Add Balance', '👤 Profile', '💸 Transfer', '⚙️ Admin Menu']
    if text in main_commands:
        context.user_data['state'] = None 
        
        if text == 'Get Proxy ✨':
            msg = (
                "🌍 <b>SELECT A COUNTRY</b>\n"
                "━━━━━━━━━━━━━━━━━━━━\n"
                "Type the <b>2-letter Country Code</b> or full name.\n\n"
                "<i>Examples:</i>\n"
                "🇺🇸 <code>US</code> for United States\n"
                "🇬🇧 <code>GB</code> for United Kingdom\n"
                "🇻🇳 <code>VN</code> for Vietnam"
            )
            await update.message.reply_text(msg, parse_mode='HTML')
            return
            
        elif text == '💳 Add Balance':
            kb = InlineKeyboardMarkup([
                [InlineKeyboardButton("⚡ PipraPay (Auto Deposit)", callback_data="pay_piprapay")],
                [InlineKeyboardButton("🟡 Binance (Manual)", callback_data="pay_binance")],
                [InlineKeyboardButton("❌ Cancel", callback_data="cancel_action")]
            ])
            msg = (
                "💳 <b>ADD BALANCE</b>\n"
                "━━━━━━━━━━━━━━━━━━━━\n"
                "Choose your preferred payment method below.\n"
                "Auto-payments are credited <b>instantly</b>! ⚡"
            )
            await update.message.reply_text(msg, parse_mode='HTML', reply_markup=kb)
            return
            
        elif text == '👤 Profile':
            init_user_balance(user.id)
            bal = round(BOT_DATA['users'][str(user.id)]['balance'], 2)
            price = BOT_DATA.get('proxy_price', 10)
            
            msg = (
                f"👤 <b>USER PROFILE</b>\n"
                f"━━━━━━━━━━━━━━━━━━━━\n"
                f"🆔 <b>Account ID:</b> <code>{user.id}</code>\n"
                f"🪪 <b>Username:</b> @{user.username}\n"
                f"💰 <b>Current Balance:</b> <b>{bal} TK</b>\n"
                f"━━━━━━━━━━━━━━━━━━━━\n"
                f"🚀 <b>Proxy Price:</b> {price} TK / IP\n"
            )
            await update.message.reply_text(msg, parse_mode='HTML')
            return
            
        elif text == '💸 Transfer':
            context.user_data['state'] = 'awaiting_transfer_target'
            kb = InlineKeyboardMarkup([[InlineKeyboardButton("❌ Cancel", callback_data="cancel_action")]])
            msg = (
                "💸 <b>TRANSFER BALANCE</b>\n"
                "━━━━━━━━━━━━━━━━━━━━\n"
                "Enter the Telegram <b>@username</b> or <b>User ID</b> of the recipient:"
            )
            await update.message.reply_text(msg, parse_mode='HTML', reply_markup=kb)
            return
            
        elif text == '⚙️ Admin Menu' and user.id in ADMIN_IDS:
            kb = InlineKeyboardMarkup([
                [InlineKeyboardButton("💳 Credit User", callback_data="admin_credit")],
                [InlineKeyboardButton("💰 Set Proxy Price", callback_data="admin_setprice")]
            ])
            await update.message.reply_text("⚙️ <b>Admin Control Panel</b>\n━━━━━━━━━━━━━━━━━━━━\nSelect an option below:", reply_markup=kb, parse_mode='HTML')
            return
            
        return 
    
    # --- STATE HANDLING ---
    state = context.user_data.get('state')
    
    # 0. State: Awaiting Binance Screenshot
    if state == 'awaiting_binance_ss':
        if not update.message.photo:
            await update.message.reply_text("❌ <b>Error:</b> Please send a screenshot (photo) of your Binance transaction.", parse_mode='HTML')
            return
            
        photo_file_id = update.message.photo[-1].file_id
        amount = context.user_data.get('binance_amount')
        trx_id = context.user_data.get('binance_trx')
        
        order_id = f"MAN_{user.id}_{int(time.time())}"
        BOT_DATA.setdefault('manual_payments', {})[order_id] = {
            'user_id': user.id,
            'amount': amount,
            'trx_id': trx_id,
            'status': 'pending'
        }
        save_data(BOT_DATA)
        
        kb = InlineKeyboardMarkup([
            [InlineKeyboardButton("✅ Approve", callback_data=f"man_approve_{order_id}"),
             InlineKeyboardButton("❌ Reject", callback_data=f"man_reject_{order_id}")]
        ])
        
        caption = (
            f"🟡 <b>Manual Binance Payment Request</b>\n"
            f"━━━━━━━━━━━━━━━━━━━━\n"
            f"👤 User: @{user.username} (<code>{user.id}</code>)\n"
            f"💰 Amount: <b>{amount} TK</b>\n"
            f"🧾 Trx ID: <code>{trx_id}</code>\n"
            f"━━━━━━━━━━━━━━━━━━━━\n"
            f"Status: Pending Admin Review"
        )
        
        await context.bot.send_photo(chat_id=LOG_GROUP_ID, photo=photo_file_id, caption=caption, parse_mode='HTML', reply_markup=kb)
        
        success_msg = (
            "✅ <b>PAYMENT SUBMITTED!</b>\n"
            "━━━━━━━━━━━━━━━━━━━━\n"
            "Your screenshot and Transaction ID have been sent to the admins for verification.\n\n"
            "<i>Your balance will be updated automatically upon approval.</i>"
        )
        await update.message.reply_text(success_msg, parse_mode='HTML')
        context.user_data['state'] = None
        return

    # 1. State: Awaiting Binance Amount
    if state == 'awaiting_binance_amount':
        try:
            amount = float(text)
            if amount <= 0:
                await update.message.reply_text("❌ Amount must be greater than 0.")
                return
            context.user_data['binance_amount'] = amount
            context.user_data['state'] = 'awaiting_binance_trx'
            kb = InlineKeyboardMarkup([[InlineKeyboardButton("❌ Cancel", callback_data="cancel_action")]])
            msg = (
                f"🟡 <b>BINANCE DEPOSIT</b>\n"
                f"━━━━━━━━━━━━━━━━━━━━\n"
                f"💰 Deposit Amount: <b>{amount} TK</b>\n\n"
                f"Please transfer this amount to Binance UID: <code>805398719</code>\n\n"
                f"After transferring, please enter your <b>Order ID</b> (Transaction Hash/ID):"
            )
            await update.message.reply_text(msg, parse_mode='HTML', reply_markup=kb)
            return
        except ValueError:
            await update.message.reply_text("❌ Please enter a valid number.")
            return

    # 2. State: Awaiting Binance Trx ID
    if state == 'awaiting_binance_trx':
        if not text:
            await update.message.reply_text("❌ Please enter a valid Order ID.")
            return
        context.user_data['binance_trx'] = text
        context.user_data['state'] = 'awaiting_binance_ss'
        kb = InlineKeyboardMarkup([[InlineKeyboardButton("❌ Cancel", callback_data="cancel_action")]])
        msg = (
            "📸 <b>ALMOST DONE!</b>\n"
            "━━━━━━━━━━━━━━━━━━━━\n"
            "Please upload a <b>Screenshot</b> of your successful Binance transaction as proof:"
        )
        await update.message.reply_text(msg, parse_mode='HTML', reply_markup=kb)
        return
        
    # 3. State: Awaiting Deposit Amount (PipraPay)
    if state == 'awaiting_deposit':
        try:
            amount = float(text)
            if amount < 10:
                await update.message.reply_text("⚠️ <b>Minimum deposit amount is 10 TK.</b> Try again:", parse_mode='HTML')
                return
            
            msg = await update.message.reply_text("⏳ <i>Generating secure payment link...</i>", parse_mode='HTML')
            loop = asyncio.get_running_loop()
            
            payment_url, order_id, pp_id = await loop.run_in_executor(None, _sync_create_piprapay, amount, user.id)
            
            if payment_url and order_id:
                BOT_DATA['pending_payments'][order_id] = {
                    'user_id': user.id, 'amount': amount, 'status': 'pending', 'pp_id': pp_id
                }
                
                admin_msg = (
                    f"⚡ <b>Auto Payment Initiated</b>\n"
                    f"━━━━━━━━━━━━━━━━━━━━\n"
                    f"👤 User: <code>{user.id}</code> (@{user.username})\n"
                    f"💰 Amount: <b>{amount} TK</b>\n"
                    f"🆔 Order: <code>{order_id}</code>\n"
                    f"🔗 <a href='{payment_url}'>View Payment Page</a>\n"
                    f"━━━━━━━━━━━━━━━━━━━━\n"
                    f"Status: Pending Auto Verification"
                )
                
                admin_kb = InlineKeyboardMarkup([
                    [InlineKeyboardButton("✅ Approve Manually", callback_data=f"pdec_a_{order_id}"),
                     InlineKeyboardButton("❌ Reject", callback_data=f"pdec_r_{order_id}")]
                ])
                
                res_msg = await context.bot.send_message(chat_id=LOG_GROUP_ID, text=admin_msg, parse_mode='HTML', reply_markup=admin_kb)
                BOT_DATA['pending_payments'][order_id]['log_msg_id'] = res_msg.message_id
                save_data(BOT_DATA)
                
                user_kb = InlineKeyboardMarkup([
                    [InlineKeyboardButton(f"💳 Pay {amount} TK", url=payment_url)],
                    [InlineKeyboardButton("❌ Cancel Payment", callback_data="cancel_action")]
                ])
                
                payment_text = (
                    f"🔗 <b>PAYMENT LINK GENERATED!</b>\n"
                    f"━━━━━━━━━━━━━━━━━━━━\n"
                    f"Click the button below to pay <b>{amount} TK</b>.\n\n"
                    f"⏳ <i>Waiting for payment... (This will automatically verify once you pay)</i>"
                )
                payment_msg = await msg.edit_text(payment_text, reply_markup=user_kb, parse_mode='HTML')
                
                # Start the background task to monitor the payment
                context.application.create_task(
                    monitor_payment(
                        context, order_id, user.id, amount, pp_id, 
                        payment_msg.chat_id, payment_msg.message_id
                    )
                )
            else:
                await msg.edit_text("❌ <b>Payment Gateway Error.</b> Please try again later.", parse_mode='HTML')
                
            context.user_data['state'] = None
            return
        except ValueError:
            await update.message.reply_text("❌ Please enter a valid number.")
            return

    # 4. State: Transfer Feature
    if state == 'awaiting_transfer_target':
        target_id = resolve_user(text)
        if not target_id:
            await update.message.reply_text("❌ Could not find user. Make sure the username is correct and they have started the bot.")
            context.user_data['state'] = None
            return
        
        if str(target_id) == str(user.id):
            await update.message.reply_text("❌ You cannot transfer funds to yourself.")
            context.user_data['state'] = None
            return

        context.user_data['transfer_target'] = target_id
        context.user_data['state'] = 'awaiting_transfer_amount'
        kb = InlineKeyboardMarkup([[InlineKeyboardButton("❌ Cancel", callback_data="cancel_action")]])
        
        transfer_msg = (
            f"💸 <b>TRANSFER BALANCE</b>\n"
            f"━━━━━━━━━━━━━━━━━━━━\n"
            f"👤 <b>Recipient:</b> <code>{target_id}</code>\n\n"
            f"🔢 Enter the amount of TK you want to transfer:"
        )
        await update.message.reply_text(transfer_msg, parse_mode='HTML', reply_markup=kb)
        return

    if state == 'awaiting_transfer_amount':
        try:
            amount = float(text)
            if amount <= 0:
                await update.message.reply_text("❌ Amount must be greater than 0.")
                return
            
            init_user_balance(user.id)
            if BOT_DATA['users'][str(user.id)]['balance'] < amount:
                await update.message.reply_text("❌ <b>Insufficient balance</b> for this transfer.", parse_mode='HTML')
                context.user_data['state'] = None
                return

            target_id = context.user_data.get('transfer_target')
            init_user_balance(target_id)
            
            BOT_DATA['users'][str(user.id)]['balance'] -= amount
            BOT_DATA['users'][str(target_id)]['balance'] += amount
            save_data(BOT_DATA)
            
            success_msg = (
                f"✅ <b>TRANSFER SUCCESSFUL!</b>\n"
                f"━━━━━━━━━━━━━━━━━━━━\n"
                f"💸 <b>Amount:</b> {amount} TK\n"
                f"👤 <b>Sent to:</b> <code>{target_id}</code>"
            )
            await update.message.reply_text(success_msg, parse_mode='HTML')
            try:
                receive_msg = (
                    f"💰 <b>FUNDS RECEIVED!</b>\n"
                    f"━━━━━━━━━━━━━━━━━━━━\n"
                    f"You have received a transfer of <b>{amount} TK</b>.\n"
                    f"👤 <b>From:</b> <code>{user.id}</code> (@{user.username})"
                )
                await context.bot.send_message(chat_id=target_id, text=receive_msg, parse_mode='HTML')
            except: pass
            
            context.user_data['state'] = None
            return
        except ValueError:
            await update.message.reply_text("❌ Please enter a valid number.")
            return

    # 5. State: Admin Credit User
    if state == 'awaiting_admin_credit_target' and user.id in ADMIN_IDS:
        target_id = resolve_user(text)
        if not target_id:
            await update.message.reply_text("❌ Could not find user. Make sure they have started the bot.")
            context.user_data['state'] = None
            return
            
        context.user_data['credit_target'] = target_id
        context.user_data['state'] = 'awaiting_admin_credit_amount'
        kb = InlineKeyboardMarkup([[InlineKeyboardButton("❌ Cancel", callback_data="cancel_action")]])
        await update.message.reply_text(f"💰 Target selected: <code>{target_id}</code>\n\nEnter the amount to credit (use negative numbers to deduct):", parse_mode='HTML', reply_markup=kb)
        return

    if state == 'awaiting_admin_credit_amount' and user.id in ADMIN_IDS:
        try:
            amount = float(text)
            target_id = context.user_data.get('credit_target')
            
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

    # 6. State: Admin Set Price
    if state == 'awaiting_admin_set_price' and user.id in ADMIN_IDS:
        try:
            price = float(text)
            if price < 0:
                await update.message.reply_text("❌ Price cannot be negative.")
                return
            BOT_DATA['proxy_price'] = price
            save_data(BOT_DATA)
            await update.message.reply_text(f"✅ <b>Success:</b> Proxy price updated to {price} TK.", parse_mode='HTML')
            context.user_data['state'] = None
            return
        except ValueError:
            await update.message.reply_text("❌ Please enter a valid number.")
            return

    # Normal text processing (e.g. 2-letter country code)
    if len(text) == 2 or len(text) > 3:
        await process_country_selection(update.message, text, context)

async def cmd_credit(update: Update, context: ContextTypes.DEFAULT_TYPE):
    if update.effective_user.id not in ADMIN_IDS: return
    try:
        target = resolve_user(context.args[0])
        if not target:
            await update.message.reply_text("❌ Could not find user.")
            return
        context.user_data['credit_target'] = target
        context.user_data['state'] = 'awaiting_admin_credit_amount'
        await update.message.reply_text(f"💰 Target selected: <b>{target}</b>\n\nEnter the amount to credit (use negative numbers to deduct):", parse_mode='HTML')
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
    msg = await message_obj.reply_text(f"🔍 <i>Fetching proxies for <b>{escape(str(full_name))}</b>...</i>", parse_mode='HTML')
    
    loop = asyncio.get_running_loop()
    proxies, error = await loop.run_in_executor(None, _sync_get_available_proxies, full_name)
    
    if error:
        try:
            await msg.edit_text(f"❌ <b>Error:</b> {escape(str(error))}", parse_mode='HTML')
        except BadRequest as e:
            if "Message is not modified" not in str(e): raise e
        return

    context.user_data['country_full'] = full_name
    context.user_data['regions_list'] = proxies
    
    if not proxies:
        try:
            err_msg = (
                f"⚠️ <b>NO PROXIES FOUND</b>\n"
                f"━━━━━━━━━━━━━━━━━━━━\n"
                f"There are currently no active proxies available for <b>{escape(str(full_name))}</b>."
            )
            await msg.edit_text(err_msg, reply_markup=InlineKeyboardMarkup([[InlineKeyboardButton("🎲 Try Random Proxy", callback_data="get_proxy_random")]]), parse_mode='HTML')
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
        region_msg = (
            f"🌍 <b>SELECT A REGION: {escape(str(full_name))}</b>\n"
            f"━━━━━━━━━━━━━━━━━━━━\n"
            f"Choose a specific region from the list below:"
        )
        await message_obj.edit_text(region_msg, reply_markup=InlineKeyboardMarkup(keyboard), parse_mode='HTML')
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
        err = (
            f"❌ <b>INSUFFICIENT BALANCE!</b>\n"
            f"━━━━━━━━━━━━━━━━━━━━\n"
            f"💰 Your Balance: <b>{BOT_DATA['users'][user_str]['balance']} TK</b>\n"
            f"🚀 Proxy Price: <b>{price} TK</b>\n\n"
            f"Please click <b>💳 Add Balance</b> to top up your account."
        )
        if is_edit and hasattr(message_obj, 'edit_text'):
            try: await message_obj.edit_text(err, parse_mode='HTML')
            except: pass
        else: await context.bot.send_message(chat_id=user.id, text=err, parse_mode='HTML')
        return

    status_msg = message_obj
    if is_edit and hasattr(message_obj, 'edit_text'):
        try: status_msg = await message_obj.edit_text("⏳ <i>Unlocking premium proxy...</i>", parse_mode='HTML')
        except: pass
    else:
        status_msg = await context.bot.send_message(chat_id=user.id, text="⏳ <i>Unlocking premium proxy...</i>", parse_mode='HTML')

    loop = asyncio.get_running_loop()
    
    # 3. Fetch Proxy Details using Executor
    if proxy_id:
        pid = proxy_id
        p_list = context.user_data.get('regions_list', [])
        p_obj = next((p for p in p_list if str(p['id']) == str(pid)), {})
        speed, p_type, real_region = p_obj.get('speed', 'N/A'), p_obj.get('type', 'N/A'), p_obj.get('region', region)
        context.user_data['last_region'] = real_region
    else:
        proxy_obj, error = await loop.run_in_executor(None, _sync_fetch_proxy_obj_random, country, region)
        if error:
            try: await status_msg.edit_text(f"❌ <b>Error:</b> {escape(str(error))}", parse_mode='HTML')
            except: pass
            return # Exit safely. NO BALANCE DEDUCTED
            
        pid, speed, p_type, real_region = proxy_obj['Id'], proxy_obj.get('Speed', 'N/A'), proxy_obj.get('useType', 'N/A'), proxy_obj.get('Region', region)
        context.user_data['last_region'] = real_region

    # 4. Reveal Proxy Credentials
    creds, error = await loop.run_in_executor(None, _sync_reveal_credentials, pid)
    if error:
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
        f"✅ <b>PROXY SUCCESSFULLY GENERATED!</b>\n"
        f"━━━━━━━━━━━━━━━━━━━━\n"
        f"🌍 <b>Location:</b> {escape(str(country))} (📍 {escape(str(real_region))})\n"
        f"⚡ <b>Speed:</b> {escape(str(speed))} | 📶 <b>Type:</b> {escape(str(p_type))}\n\n"
        f"📥 <b>Format (IP:Port:User:Pass):</b>\n"
        f"<code>{escape(str(creds))}</code>\n\n"
        f"📝 <b>Detailed Info:</b>\n"
        f"🌐 Host: <code>{escape(str(ip))}</code>\n"
        f"🔌 Port: <code>{escape(str(port))}</code>\n"
        f"👤 User: <code>{escape(str(u))}</code>\n"
        f"🔑 Pass: <code>{escape(str(p))}</code>\n"
        f"━━━━━━━━━━━━━━━━━━━━\n"
        f"💳 <b>Balance Deducted:</b> -{price} TK\n"
        f"💰 <b>Remaining Balance:</b> {new_bal} TK"
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
        f"━━━━━━━━━━━━━━━━━━━━\n"
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

    # Handle Deposit/Action Cancellation
    if action in ['cancel_deposit', 'cancel_action']:
        context.user_data['state'] = None
        await query.answer("Cancelled")
        try:
            await query.message.edit_text("❌ <b>Action cancelled.</b>", parse_mode='HTML')
        except: pass
        return

    # Handle Payment Selection
    if action == 'pay_piprapay':
        context.user_data['state'] = 'awaiting_deposit'
        kb = InlineKeyboardMarkup([[InlineKeyboardButton("❌ Cancel", callback_data="cancel_action")]])
        msg = (
            "⚡ <b>PIPRAPAY AUTO-DEPOSIT</b>\n"
            "━━━━━━━━━━━━━━━━━━━━\n"
            "💰 How much TK do you want to add?\n\n"
            "<i>Please enter the amount below (Min 10):</i>"
        )
        await query.message.edit_text(msg, parse_mode='HTML', reply_markup=kb)
        return
        
    if action == 'pay_binance':
        context.user_data['state'] = 'awaiting_binance_amount'
        kb = InlineKeyboardMarkup([[InlineKeyboardButton("❌ Cancel", callback_data="cancel_action")]])
        msg = (
            "🟡 <b>BINANCE MANUAL DEPOSIT</b>\n"
            "━━━━━━━━━━━━━━━━━━━━\n"
            "Binance UID: <code>805398719</code>\n\n"
            "💰 How much TK are you depositing?\n"
            "<i>Enter the amount below:</i>"
        )
        await query.message.edit_text(msg, parse_mode='HTML', reply_markup=kb)
        return

    # Handle Manual Payment Admin Approval
    if action.startswith('man_approve_'):
        if user.id not in ADMIN_IDS:
            await query.answer("❌ Unauthorized!", show_alert=True)
            return
            
        order_id = action.replace('man_approve_', '')
        order = BOT_DATA.get('manual_payments', {}).get(order_id)
        
        if not order:
            await query.answer("❌ Order not found.", show_alert=True)
            return
        if order['status'] != 'pending':
            await query.answer(f"⚠️ Order already {order['status']}!", show_alert=True)
            return
            
        order['status'] = 'approved'
        amount = order['amount']
        target_id = order['user_id']
        
        init_user_balance(target_id)
        BOT_DATA['users'][str(target_id)]['balance'] += amount
        save_data(BOT_DATA)
        
        await query.answer("✅ Approved!")
        new_caption = (query.message.caption_html or "") + "\n\n✅ <b>APPROVED</b> by Admin"
        try: await query.message.edit_caption(caption=new_caption, parse_mode='HTML')
        except: pass
        
        target_msg = (
            f"🎉 <b>PAYMENT APPROVED!</b>\n"
            f"━━━━━━━━━━━━━━━━━━━━\n"
            f"Your manual deposit of <b>{amount} TK</b> has been verified and successfully added to your balance."
        )
        try: await context.bot.send_message(chat_id=target_id, text=target_msg, parse_mode='HTML')
        except: pass
        return

    # Handle Manual Payment Admin Rejection
    if action.startswith('man_reject_'):
        if user.id not in ADMIN_IDS:
            await query.answer("❌ Unauthorized!", show_alert=True)
            return
            
        order_id = action.replace('man_reject_', '')
        order = BOT_DATA.get('manual_payments', {}).get(order_id)
        
        if not order:
            await query.answer("❌ Order not found.", show_alert=True)
            return
        if order['status'] != 'pending':
            await query.answer(f"⚠️ Order already {order['status']}!", show_alert=True)
            return
            
        order['status'] = 'rejected'
        save_data(BOT_DATA)
        
        await query.answer("❌ Rejected!")
        new_caption = (query.message.caption_html or "") + "\n\n❌ <b>REJECTED</b> by Admin"
        try: await query.message.edit_caption(caption=new_caption, parse_mode='HTML')
        except: pass
        
        target_msg = (
            f"❌ <b>PAYMENT REJECTED!</b>\n"
            f"━━━━━━━━━━━━━━━━━━━━\n"
            f"Your manual deposit for Order ID <code>{order['trx_id']}</code> was rejected by the admin.\n\n"
            f"<i>Please contact support if you think this is a mistake.</i>"
        )
        try: await context.bot.send_message(chat_id=order['user_id'], text=target_msg, parse_mode='HTML')
        except: pass
        return
        
    # Handle Auto Payment Admin Approval/Reject Flow
    if action.startswith('pdec_a_') or action.startswith('pdec_r_'):
        if user.id not in ADMIN_IDS:
            await query.answer("❌ Unauthorized!", show_alert=True)
            return
            
        is_approve = action.startswith('pdec_a_')
        order_id = action.replace('pdec_a_', '').replace('pdec_r_', '')
        order = BOT_DATA.get('pending_payments', {}).get(order_id)

        if not order:
            await query.answer("❌ Order not found.", show_alert=True)
            return
            
        if order['status'] != 'pending':
            await query.answer("⚠️ Payment has already been processed (e.g. by Webhook).", show_alert=True)
            new_text = query.message.text_html + f"\n\n⚠️ <b>Already Processed ({order['status']})</b>"
            try: await query.message.edit_text(text=new_text, parse_mode='HTML')
            except: pass
            return

        target_id = order['user_id']
        amount = order['amount']

        if is_approve:
            init_user_balance(target_id)
            BOT_DATA['users'][str(target_id)]['balance'] += amount
            order['status'] = 'completed'
            save_data(BOT_DATA)
            
            await query.answer("✅ Approved!")
            new_text = query.message.text_html + "\n\n✅ <b>APPROVED</b> manually by Admin"
            try: await query.message.edit_text(text=new_text, parse_mode='HTML')
            except: pass
            
            target_msg = (
                f"🎉 <b>PAYMENT APPROVED!</b>\n"
                f"━━━━━━━━━━━━━━━━━━━━\n"
                f"Your auto-deposit of <b>{amount} TK</b> was manually verified and added to your balance."
            )
            try: await context.bot.send_message(chat_id=target_id, text=target_msg, parse_mode='HTML')
            except: pass
            
            log_receipt = (
                f"💰 <b>New Deposit Notification!</b>\n"
                f"━━━━━━━━━━━━━━━━━━━━\n"
                f"👤 User ID: <code>{target_id}</code>\n"
                f"💵 Amount: <b>{amount} TK</b>\n"
                f"💳 Method: Auto Payment (Manual Override)\n"
                f"📅 Date: {datetime.datetime.now().strftime('%d-%m-%Y | %I:%M %p')}\n"
                f"━━━━━━━━━━━━━━━━━━━━\n"
                f"✅ Status: Successfully Added"
            )
            try: await context.bot.send_message(chat_id=LOG_GROUP_ID, text=log_receipt, parse_mode='HTML')
            except: pass

        else:
            order['status'] = 'rejected'
            save_data(BOT_DATA)
            await query.answer("❌ Rejected!")
            new_text = query.message.text_html + "\n\n❌ <b>REJECTED</b> manually by Admin"
            try: await query.message.edit_text(text=new_text, parse_mode='HTML')
            except: pass
            
            target_msg = (
                f"❌ <b>PAYMENT REJECTED!</b>\n"
                f"━━━━━━━━━━━━━━━━━━━━\n"
                f"Your auto-deposit order <code>{order_id}</code> was cancelled."
            )
            try: await context.bot.send_message(chat_id=target_id, text=target_msg, parse_mode='HTML')
            except: pass

        return

    # Handle Admin Menu Callbacks
    if action == 'admin_credit' and user.id in ADMIN_IDS:
        context.user_data['state'] = 'awaiting_admin_credit_target'
        kb = InlineKeyboardMarkup([[InlineKeyboardButton("❌ Cancel", callback_data="cancel_action")]])
        await query.message.edit_text("💳 <b>Credit User</b>\n━━━━━━━━━━━━━━━━━━━━\nEnter the Telegram <b>@username</b> or <b>User ID</b> of the target:", parse_mode='HTML', reply_markup=kb)
        return
        
    if action == 'admin_setprice' and user.id in ADMIN_IDS:
        context.user_data['state'] = 'awaiting_admin_set_price'
        kb = InlineKeyboardMarkup([[InlineKeyboardButton("❌ Cancel", callback_data="cancel_action")]])
        msg = (
            f"💰 <b>SET PROXY PRICE</b>\n"
            f"━━━━━━━━━━━━━━━━━━━━\n"
            f"Current Price: <b>{BOT_DATA.get('proxy_price', 10)} TK</b>\n\n"
            f"Enter the new price:"
        )
        await query.message.edit_text(msg, parse_mode='HTML', reply_markup=kb)
        return

    # Removed old 'checkpay_' handling as it is now fully automatic

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
        msg = (
            "🌍 <b>SELECT A COUNTRY</b>\n"
            "━━━━━━━━━━━━━━━━━━━━\n"
            "Type the <b>2-letter Country Code</b> or full name."
        )
        try: await query.message.edit_text(msg, parse_mode='HTML')
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
    application.add_handler(MessageHandler((filters.TEXT | filters.PHOTO) & (~filters.COMMAND), handle_message))
    application.add_handler(CallbackQueryHandler(button_click))

    print("High-Speed Proxy Bot with Premium UI is starting...")
    application.run_polling()
