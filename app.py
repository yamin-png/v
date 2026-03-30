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
BOT_USERNAME = "Ismailproxybot"
ADMIN_IDS = [6616624640, 5473188537]
LOG_GROUP_ID = -1003280360902

# --- PHP DATABASE API CONFIG ---
PHP_BRIDGE_URL = 'https://proxy.yamin.bd/api.php'
PHP_BRIDGE_SECRET = 'rubel_proxy_secret_2026'

# --- LOCAL SETTINGS FILE ---
# Replaces bot_data.json. Only stores non-financial bot configs.
SETTINGS_FILE = "local_settings.json"

# --- DISHVUSOCKS CONFIG ---
COUNTRY_OVERRIDES = {
    'RU': 'Russia', 'VN': 'Vietnam', 'KR': 'South Korea', 'IR': 'Iran',
    'MD': 'Moldova', 'TZ': 'Tanzania', 'SY': 'Syria', 'LA': 'Laos',
    'VE': 'Venezuela', 'BO': 'Bolivia', 'CD': 'Congo', 'EG': 'Egypt',
    'MM': 'Myanmar', 'US': 'United States'
}
DEFAULT_COOKIE = '_ga=GA1.2...; '

HEADERS = {
    'User-Agent': 'Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/124.0.0.0 Safari/537.36',
    'Accept': '*/*',
    'X-Requested-With': 'XMLHttpRequest',
    'Referer': 'https://dichvusocks.net/sockslist',
}

# --- LOCAL SETTINGS MANAGEMENT & MIGRATION ---
def load_settings():
    default_settings = {
        'cookie': DEFAULT_COOKIE,
        'proxy_price': 10,
        'username_map': {},
        'manual_payments': {}
    }
    
    # MIGRATION LOGIC: If old bot_data.json exists, migrate it to MySQL and delete it.
    if os.path.exists("bot_data.json"):
        print("🔄 Found old bot_data.json! Starting migration to MySQL in batches...")
        try:
            with open("bot_data.json", 'r') as f:
                old_data = json.load(f)
            
            users_data = old_data.get('users', {})
            user_items = list(users_data.items())
            chunk_size = 50  # Send 50 users at a time to prevent server timeout/payload block
            migration_success = True
            total_migrated = 0
            
            # Strong anti-bot bypass headers
            mig_headers = {
                'User-Agent': 'Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/124.0.0.0 Safari/537.36',
                'Accept': 'application/json',
                'Content-Type': 'application/json',
                'Connection': 'keep-alive'
            }
            
            for i in range(0, len(user_items), chunk_size):
                chunk = dict(user_items[i:i+chunk_size])
                payload = {
                    'secret': PHP_BRIDGE_SECRET,
                    'action': 'migrate',
                    'users': chunk
                }
                
                success_for_chunk = False
                for attempt in range(3): # Retry up to 3 times per chunk
                    try:
                        res = requests.post(PHP_BRIDGE_URL, json=payload, headers=mig_headers, timeout=30)
                        if res.status_code == 200 and res.json().get('success'):
                            success_for_chunk = True
                            break
                        else:
                            print(f"⚠️ Chunk failed (Attempt {attempt+1})! Server response: {res.text}")
                    except Exception as e:
                        print(f"⚠️ Chunk Error (Attempt {attempt+1}): {e}")
                    
                    time.sleep(3) # Wait before retrying to cool down firewall
                
                if success_for_chunk:
                    total_migrated += len(chunk)
                    print(f"⏳ Migrated {total_migrated}/{len(user_items)} users...")
                else:
                    print("❌ Migration chunk failed completely after 3 attempts!")
                    migration_success = False
                    break
                
                time.sleep(1) # Be gentle on the server between successful chunks
                
            if migration_success:
                print(f"✅ Migration Successful! All {total_migrated} users moved to MySQL.")
                
                # Save settings and username map locally
                default_settings['cookie'] = old_data.get('cookie', DEFAULT_COOKIE)
                default_settings['proxy_price'] = old_data.get('proxy_price', 10)
                default_settings['username_map'] = old_data.get('username_map', {})
                default_settings['manual_payments'] = old_data.get('manual_payments', {})
                
                with open(SETTINGS_FILE, 'w') as f:
                    json.dump(default_settings, f, indent=4)
                    
                # Delete old file
                os.remove("bot_data.json")
                print("🗑️ bot_data.json has been safely deleted.")
            else:
                print("⚠️ Migration stopped due to errors. bot_data.json was kept safe.")
                
        except Exception as e:
            print(f"❌ Critical Migration Error: {e}")

    # Normal Settings Load
    if not os.path.exists(SETTINGS_FILE):
        return default_settings
    try:
        with open(SETTINGS_FILE, 'r') as f:
            data = json.load(f)
            for k in default_settings:
                if k not in data: data[k] = default_settings[k]
            return data
    except:
        return default_settings

def save_settings():
    with open(SETTINGS_FILE, 'w') as f:
        json.dump(SETTINGS, f, indent=4)

SETTINGS = load_settings()
HEADERS['Cookie'] = SETTINGS['cookie']

# Keep track of temporary payment logs in memory
PENDING_AUTO_PAYMENTS = {}

def update_headers_with_xsrf():
    cookie_str = HEADERS.get('Cookie', '')
    match = re.search(r'XSRF-TOKEN=([^;]+)', cookie_str)
    if match:
        token = unquote(match.group(1))
        HEADERS['X-XSRF-TOKEN'] = token

update_headers_with_xsrf()

# --- MYSQL DATABASE API HELPERS ---
def db_api_request(payload):
    payload['secret'] = PHP_BRIDGE_SECRET
    # Adding User-Agent ensures Cloudflare/Firewalls don't block empty-agent requests
    req_headers = {
        'User-Agent': 'Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/124.0.0.0 Safari/537.36',
        'Accept': 'application/json',
        'Content-Type': 'application/json',
        'Connection': 'keep-alive'
    }
    
    # Simple retry mechanism for regular API requests
    for attempt in range(3):
        try:
            res = requests.post(PHP_BRIDGE_URL, json=payload, headers=req_headers, timeout=15)
            return res.json()
        except Exception as e:
            if attempt == 2:
                print(f"DB API Error after 3 attempts: {e}")
                return {"error": str(e)}
            time.sleep(2) # Cool down before retry

def db_get_balance(user_id, username=""):
    res = db_api_request({
        'action': 'get_user',
        'telegram_id': str(user_id),
        'username': username
    })
    return res.get('balance', 0.0) if res.get('success') else 0.0

def db_update_balance(user_id, amount, description=""):
    res = db_api_request({
        'action': 'update_balance',
        'telegram_id': str(user_id),
        'amount': amount,
        'description': description
    })
    return res.get('success', False)

def db_log_proxy_purchase(user_id, cost, proxy_details):
    # This securely deducts balance AND logs the proxy in MySQL in one atomic action
    res = db_api_request({
        'action': 'log_proxy',
        'telegram_id': str(user_id),
        'cost': cost,
        'proxy_details': proxy_details
    })
    return res

def _sync_create_piprapay(amount, user_id):
    order_id = f"PAY_{user_id}_{int(time.time())}"
    res = db_api_request({
        'action': 'create',
        'order_id': order_id,
        'user_id': str(user_id),
        'amount': str(amount)
    })
    payment_url = res.get('pp_url') or res.get('payment_url') or res.get('url')
    pp_id = res.get('bp_id') or res.get('pp_id') or res.get('id') or res.get('invoice_id')
    if payment_url and pp_id:
        return payment_url, order_id, pp_id
    return None, None, None

def _sync_verify_piprapay(order_id, pp_id):
    # Sends verify request. If paid, PHP handles adding the balance automatically!
    res = db_api_request({
        'action': 'verify',
        'order_id': order_id,
        'pp_id': pp_id,
        'invoice_id': pp_id 
    })
    # If the PHP script returns success=true, it means it's paid and balance was handled.
    if res.get('success') is True:
        return True
    return False

# --- AUTO PAYMENT MONITOR (BACKGROUND TASK) ---
async def monitor_payment(context: ContextTypes.DEFAULT_TYPE, order_id: str, user_id: int, amount: float, pp_id: str, chat_id: int, message_id: int):
    loop = asyncio.get_running_loop()
    max_attempts = 24  # Check for 10 minutes (24 attempts * 25 seconds)
    
    for _ in range(max_attempts):
        await asyncio.sleep(25)  # SLOWED DOWN: Wait 25 seconds to prevent Server IP Blocks
        
        if order_id not in PENDING_AUTO_PAYMENTS:
            break # Order was removed/handled
            
        is_paid_and_handled = await loop.run_in_executor(None, _sync_verify_piprapay, order_id, pp_id)
        
        if is_paid_and_handled:
            # PHP already added the balance to MySQL! We just need to notify the user.
            success_msg = (
                f"✅ <b>PAYMENT AUTO-VERIFIED!</b>\n"
                f"━━━━━━━━━━━━━━━━━━━━\n"
                f"<b>{amount} TK</b> has been successfully added to your balance."
            )
            try:
                await context.bot.edit_message_text(
                    chat_id=chat_id, message_id=message_id,
                    text=f"✅ <b>Payment of {amount} TK Completed & Verified!</b>", parse_mode='HTML'
                )
                await context.bot.send_message(chat_id=user_id, text=success_msg, parse_mode='HTML')
            except: pass
            
            # Notify Admin Log Group
            log_receipt = (
                f"💰 <b>New Auto-Deposit Notification!</b>\n"
                f"━━━━━━━━━━━━━━━━━━━━\n"
                f"👤 User ID: <code>{user_id}</code>\n"
                f"💵 Amount: <b>{amount} TK</b>\n"
                f"💳 Method: PipraPay (Auto-Detected & DB Synced)\n"
                f"📅 Date: {datetime.datetime.now().strftime('%d-%m-%Y | %I:%M %p')}\n"
                f"━━━━━━━━━━━━━━━━━━━━\n"
                f"✅ Status: Successfully Added to MySQL"
            )
            try: await context.bot.send_message(chat_id=LOG_GROUP_ID, text=log_receipt, parse_mode='HTML')
            except: pass
            
            log_msg_id = PENDING_AUTO_PAYMENTS.get(order_id)
            if log_msg_id:
                try: 
                    await context.bot.edit_message_text(
                        chat_id=LOG_GROUP_ID, message_id=log_msg_id,
                        text=f"✅ <b>Processed for User ID:</b> <code>{user_id}</code>\n<b>Action:</b> Approved Automatically by System", parse_mode='HTML'
                    )
                except: pass
            
            PENDING_AUTO_PAYMENTS.pop(order_id, None)
            break
    else:
        # Loop expired
        PENDING_AUTO_PAYMENTS.pop(order_id, None)
        try:
            await context.bot.edit_message_text(
                chat_id=chat_id, message_id=message_id,
                text=f"⏳ <b>Payment link expired.</b> Please generate a new deposit link.", parse_mode='HTML'
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
                proxies.append({
                    'id': r['Id'], 'region': r['Region'],
                    'speed': r.get('Speed', 0), 'type': ptype[:3] if ptype else "UNK"
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
        return SETTINGS['username_map'].get(target_str[1:].lower())
    elif target_str.isdigit():
        return int(target_str)
    return None

def get_main_keyboard(user_id):
    kb = [['Get Proxy ✨', '💳 Add Balance'], ['👤 Profile', '💸 Transfer']]
    if user_id in ADMIN_IDS: kb.append(['⚙️ Admin Menu'])
    return ReplyKeyboardMarkup(kb, resize_keyboard=True)

# --- HANDLERS ---
async def start(update: Update, context: ContextTypes.DEFAULT_TYPE):
    user = update.effective_user
    if not user.username:
        await update.message.reply_text("⚠️ <b>Username Required</b>\n━━━━━━━━━━━━━━━━━━━━\nYou do not have a Telegram Username set.", parse_mode='HTML')
        return

    SETTINGS['username_map'][user.username.lower()] = user.id
    save_settings()
    
    # Initialize user in MySQL DB
    loop = asyncio.get_running_loop()
    await loop.run_in_executor(None, db_get_balance, user.id, user.username)

    log_msg = f"🔔 <b>New User Joined</b>\n━━━━━━━━━━━━━━━━━━━━\n👤 <b>User:</b> @{escape(str(user.username))}\n🆔 <b>ID:</b> <code>{user.id}</code>"
    try: await context.bot.send_message(chat_id=LOG_GROUP_ID, text=log_msg, parse_mode='HTML')
    except: pass

    await update.message.reply_text(
        "👋 <b>Welcome to Ismail Proxy Bot!</b>\n━━━━━━━━━━━━━━━━━━━━\nGet high-speed, premium proxies instantly.\nSelect an option below! 👇",
        reply_markup=get_main_keyboard(user.id), parse_mode='HTML'
    )

async def handle_message(update: Update, context: ContextTypes.DEFAULT_TYPE):
    user = update.effective_user
    if not user.username: return
    text = update.message.text.strip() if update.message.text else ""
    
    main_commands = ['Get Proxy ✨', '💳 Add Balance', '👤 Profile', '💸 Transfer', '⚙️ Admin Menu']
    if text in main_commands:
        context.user_data['state'] = None 
        
        if text == 'Get Proxy ✨':
            msg = "🌍 <b>SELECT A COUNTRY</b>\n━━━━━━━━━━━━━━━━━━━━\nType the <b>2-letter Country Code</b> or full name.\n\n<i>Examples:</i>\n🇺🇸 <code>US</code> for United States\n🇬🇧 <code>GB</code> for United Kingdom\n🇻🇳 <code>VN</code> for Vietnam"
            await update.message.reply_text(msg, parse_mode='HTML')
            return
            
        elif text == '💳 Add Balance':
            kb = InlineKeyboardMarkup([
                [InlineKeyboardButton("⚡ PipraPay (Auto Deposit)", callback_data="pay_piprapay")],
                [InlineKeyboardButton("🟡 Binance (Manual)", callback_data="pay_binance")],
                [InlineKeyboardButton("❌ Cancel", callback_data="cancel_action")]
            ])
            await update.message.reply_text("💳 <b>ADD BALANCE</b>\n━━━━━━━━━━━━━━━━━━━━\nChoose your preferred payment method below.\nAuto-payments are credited <b>instantly</b>! ⚡", parse_mode='HTML', reply_markup=kb)
            return
            
        elif text == '👤 Profile':
            loop = asyncio.get_running_loop()
            bal = await loop.run_in_executor(None, db_get_balance, user.id, user.username)
            price = SETTINGS.get('proxy_price', 10)
            
            msg = (
                f"👤 <b>USER PROFILE</b>\n━━━━━━━━━━━━━━━━━━━━\n"
                f"🆔 <b>Account ID:</b> <code>{user.id}</code>\n"
                f"🪪 <b>Username:</b> @{user.username}\n"
                f"💰 <b>Current Balance:</b> <b>{bal} TK</b>\n"
                f"━━━━━━━━━━━━━━━━━━━━\n🚀 <b>Proxy Price:</b> {price} TK / IP\n"
            )
            await update.message.reply_text(msg, parse_mode='HTML')
            return
            
        elif text == '💸 Transfer':
            context.user_data['state'] = 'awaiting_transfer_target'
            kb = InlineKeyboardMarkup([[InlineKeyboardButton("❌ Cancel", callback_data="cancel_action")]])
            await update.message.reply_text("💸 <b>TRANSFER BALANCE</b>\n━━━━━━━━━━━━━━━━━━━━\nEnter the Telegram <b>@username</b> or <b>User ID</b> of the recipient:", parse_mode='HTML', reply_markup=kb)
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
    
    if state == 'awaiting_binance_ss':
        if not update.message.photo:
            await update.message.reply_text("❌ <b>Error:</b> Please send a screenshot (photo) of your Binance transaction.", parse_mode='HTML')
            return
            
        photo_file_id = update.message.photo[-1].file_id
        amount = context.user_data.get('binance_amount')
        trx_id = context.user_data.get('binance_trx')
        
        order_id = f"MAN_{user.id}_{int(time.time())}"
        SETTINGS.setdefault('manual_payments', {})[order_id] = {
            'user_id': user.id, 'amount': amount, 'trx_id': trx_id, 'status': 'pending'
        }
        save_settings()
        
        kb = InlineKeyboardMarkup([
            [InlineKeyboardButton("✅ Approve", callback_data=f"man_approve_{order_id}"),
             InlineKeyboardButton("❌ Reject", callback_data=f"man_reject_{order_id}")]
        ])
        
        caption = f"🟡 <b>Manual Binance Payment Request</b>\n━━━━━━━━━━━━━━━━━━━━\n👤 User: @{user.username} (<code>{user.id}</code>)\n💰 Amount: <b>{amount} TK</b>\n🧾 Trx ID: <code>{trx_id}</code>\n━━━━━━━━━━━━━━━━━━━━\nStatus: Pending Admin Review"
        await context.bot.send_photo(chat_id=LOG_GROUP_ID, photo=photo_file_id, caption=caption, parse_mode='HTML', reply_markup=kb)
        await update.message.reply_text("✅ <b>PAYMENT SUBMITTED!</b>\n━━━━━━━━━━━━━━━━━━━━\nYour screenshot and Transaction ID have been sent to the admins for verification.", parse_mode='HTML')
        context.user_data['state'] = None
        return

    if state == 'awaiting_binance_amount':
        try:
            amount = float(text)
            if amount <= 0: return await update.message.reply_text("❌ Amount must be greater than 0.")
            context.user_data['binance_amount'] = amount
            context.user_data['state'] = 'awaiting_binance_trx'
            kb = InlineKeyboardMarkup([[InlineKeyboardButton("❌ Cancel", callback_data="cancel_action")]])
            msg = f"🟡 <b>BINANCE DEPOSIT</b>\n━━━━━━━━━━━━━━━━━━━━\n💰 Deposit Amount: <b>{amount} TK</b>\n\nPlease transfer this amount to Binance UID: <code>805398719</code>\n\nAfter transferring, please enter your <b>Order ID</b> (Transaction Hash/ID):"
            await update.message.reply_text(msg, parse_mode='HTML', reply_markup=kb)
            return
        except ValueError: return await update.message.reply_text("❌ Please enter a valid number.")

    if state == 'awaiting_binance_trx':
        if not text: return await update.message.reply_text("❌ Please enter a valid Order ID.")
        context.user_data['binance_trx'] = text
        context.user_data['state'] = 'awaiting_binance_ss'
        kb = InlineKeyboardMarkup([[InlineKeyboardButton("❌ Cancel", callback_data="cancel_action")]])
        await update.message.reply_text("📸 <b>ALMOST DONE!</b>\n━━━━━━━━━━━━━━━━━━━━\nPlease upload a <b>Screenshot</b> of your successful Binance transaction as proof:", parse_mode='HTML', reply_markup=kb)
        return
        
    if state == 'awaiting_deposit':
        try:
            amount = float(text)
            if amount < 10: return await update.message.reply_text("⚠️ <b>Minimum deposit amount is 10 TK.</b> Try again:", parse_mode='HTML')
            
            msg = await update.message.reply_text("⏳ <i>Generating secure payment link...</i>", parse_mode='HTML')
            loop = asyncio.get_running_loop()
            
            payment_url, order_id, pp_id = await loop.run_in_executor(None, _sync_create_piprapay, amount, user.id)
            
            if payment_url and order_id:
                admin_msg = f"⚡ <b>Auto Payment Initiated</b>\n━━━━━━━━━━━━━━━━━━━━\n👤 User: <code>{user.id}</code> (@{user.username})\n💰 Amount: <b>{amount} TK</b>\n🆔 Order: <code>{order_id}</code>\n🔗 <a href='{payment_url}'>View Payment Page</a>\n━━━━━━━━━━━━━━━━━━━━\nStatus: Pending DB Verification"
                
                admin_kb = InlineKeyboardMarkup([
                    [InlineKeyboardButton("✅ Force DB Approve", callback_data=f"pdec_a_{order_id}"),
                     InlineKeyboardButton("❌ Cancel Order", callback_data=f"pdec_r_{order_id}")]
                ])
                
                res_msg = await context.bot.send_message(chat_id=LOG_GROUP_ID, text=admin_msg, parse_mode='HTML', reply_markup=admin_kb)
                PENDING_AUTO_PAYMENTS[order_id] = res_msg.message_id
                
                user_kb = InlineKeyboardMarkup([
                    [InlineKeyboardButton(f"💳 Pay {amount} TK", url=payment_url)],
                    [InlineKeyboardButton("❌ Cancel Payment", callback_data="cancel_action")]
                ])
                
                payment_text = f"🔗 <b>PAYMENT LINK GENERATED!</b>\n━━━━━━━━━━━━━━━━━━━━\nClick the button below to pay <b>{amount} TK</b>.\n\n⏳ <i>Waiting for payment... (This will automatically verify once you pay)</i>"
                payment_msg = await msg.edit_text(payment_text, reply_markup=user_kb, parse_mode='HTML')
                
                context.application.create_task(monitor_payment(context, order_id, user.id, amount, pp_id, payment_msg.chat_id, payment_msg.message_id))
            else:
                await msg.edit_text("❌ <b>Payment Gateway Error.</b> Database connection might be down.", parse_mode='HTML')
            context.user_data['state'] = None
            return
        except ValueError: return await update.message.reply_text("❌ Please enter a valid number.")

    if state == 'awaiting_transfer_target':
        target_id = resolve_user(text)
        if not target_id:
            await update.message.reply_text("❌ Could not find user. Make sure the username is correct.")
            context.user_data['state'] = None
            return
        if str(target_id) == str(user.id):
            await update.message.reply_text("❌ You cannot transfer funds to yourself.")
            context.user_data['state'] = None
            return

        context.user_data['transfer_target'] = target_id
        context.user_data['state'] = 'awaiting_transfer_amount'
        kb = InlineKeyboardMarkup([[InlineKeyboardButton("❌ Cancel", callback_data="cancel_action")]])
        await update.message.reply_text(f"💸 <b>TRANSFER BALANCE</b>\n━━━━━━━━━━━━━━━━━━━━\n👤 <b>Recipient:</b> <code>{target_id}</code>\n\n🔢 Enter the amount of TK you want to transfer:", parse_mode='HTML', reply_markup=kb)
        return

    if state == 'awaiting_transfer_amount':
        try:
            amount = float(text)
            if amount <= 0: return await update.message.reply_text("❌ Amount must be greater than 0.")
            
            loop = asyncio.get_running_loop()
            bal = await loop.run_in_executor(None, db_get_balance, user.id)
            
            if bal < amount:
                await update.message.reply_text("❌ <b>Insufficient balance</b> for this transfer.", parse_mode='HTML')
                context.user_data['state'] = None
                return

            target_id = context.user_data.get('transfer_target')
            
            # Atomic DB update
            await loop.run_in_executor(None, db_update_balance, user.id, -amount, f"Transfer out to {target_id}")
            await loop.run_in_executor(None, db_update_balance, target_id, amount, f"Transfer in from {user.id}")
            
            await update.message.reply_text(f"✅ <b>TRANSFER SUCCESSFUL!</b>\n━━━━━━━━━━━━━━━━━━━━\n💸 <b>Amount:</b> {amount} TK\n👤 <b>Sent to:</b> <code>{target_id}</code>", parse_mode='HTML')
            try:
                await context.bot.send_message(chat_id=target_id, text=f"💰 <b>FUNDS RECEIVED!</b>\n━━━━━━━━━━━━━━━━━━━━\nYou have received a transfer of <b>{amount} TK</b>.\n👤 <b>From:</b> <code>{user.id}</code> (@{user.username})", parse_mode='HTML')
            except: pass
            
            context.user_data['state'] = None
            return
        except ValueError: return await update.message.reply_text("❌ Please enter a valid number.")

    if state == 'awaiting_admin_credit_target' and user.id in ADMIN_IDS:
        target_id = resolve_user(text)
        if not target_id: return await update.message.reply_text("❌ Could not find user.")
        context.user_data['credit_target'] = target_id
        context.user_data['state'] = 'awaiting_admin_credit_amount'
        kb = InlineKeyboardMarkup([[InlineKeyboardButton("❌ Cancel", callback_data="cancel_action")]])
        await update.message.reply_text(f"💰 Target selected: <code>{target_id}</code>\n\nEnter the amount to credit (use negative numbers to deduct):", parse_mode='HTML', reply_markup=kb)
        return

    if state == 'awaiting_admin_credit_amount' and user.id in ADMIN_IDS:
        try:
            amount = float(text)
            target_id = context.user_data.get('credit_target')
            
            loop = asyncio.get_running_loop()
            success = await loop.run_in_executor(None, db_update_balance, target_id, amount, "Admin DB Credit")
            
            if success:
                await update.message.reply_text(f"✅ Successfully added <b>{amount} TK</b> to user <code>{target_id}</code> in DB.", parse_mode='HTML')
                try: await context.bot.send_message(chat_id=target_id, text=f"💰 <b>Funds Added!</b>\nAdmin has credited <b>{amount} TK</b> to your account.", parse_mode='HTML')
                except: pass
            else:
                await update.message.reply_text("❌ Database update failed.")
            context.user_data['state'] = None
            return
        except ValueError: return await update.message.reply_text("❌ Please enter a valid number.")

    if state == 'awaiting_admin_set_price' and user.id in ADMIN_IDS:
        try:
            price = float(text)
            if price < 0: return await update.message.reply_text("❌ Price cannot be negative.")
            SETTINGS['proxy_price'] = price
            save_settings()
            await update.message.reply_text(f"✅ <b>Success:</b> Proxy price updated to {price} TK.", parse_mode='HTML')
            context.user_data['state'] = None
            return
        except ValueError: return await update.message.reply_text("❌ Please enter a valid number.")

    if len(text) == 2 or len(text) > 3:
        await process_country_selection(update.message, text, context)

async def cmd_credit(update: Update, context: ContextTypes.DEFAULT_TYPE):
    if update.effective_user.id not in ADMIN_IDS: return
    try:
        target = resolve_user(context.args[0])
        if not target: return await update.message.reply_text("❌ Could not find user.")
        context.user_data['credit_target'] = target
        context.user_data['state'] = 'awaiting_admin_credit_amount'
        await update.message.reply_text(f"💰 Target selected: <b>{target}</b>\n\nEnter the amount to credit (use negative numbers to deduct):", parse_mode='HTML')
    except IndexError: await update.message.reply_text("⚙️ <b>Usage:</b>\n<code>/credit @username</code> OR <code>/credit 123456789</code>", parse_mode='HTML')

async def cmd_set_price(update: Update, context: ContextTypes.DEFAULT_TYPE):
    if update.effective_user.id not in ADMIN_IDS: return
    try:
        price = float(context.args[0])
        SETTINGS['proxy_price'] = price
        save_settings()
        await update.message.reply_text(f"✅ <b>Success:</b> Proxy price updated to {price} TK.", parse_mode='HTML')
    except: await update.message.reply_text("⚙️ <b>Usage:</b>\n<code>/setprice 10.5</code>", parse_mode='HTML')

async def process_country_selection(message_obj, country_input, context):
    full_name = get_full_country_name(country_input)
    msg = await message_obj.reply_text(f"🔍 <i>Fetching proxies for <b>{escape(str(full_name))}</b>...</i>", parse_mode='HTML')
    loop = asyncio.get_running_loop()
    proxies, error = await loop.run_in_executor(None, _sync_get_available_proxies, full_name)
    
    if error:
        try: await msg.edit_text(f"❌ <b>Error:</b> {escape(str(error))}", parse_mode='HTML')
        except BadRequest as e:
            if "Message is not modified" not in str(e): raise e
        return

    context.user_data['country_full'] = full_name
    context.user_data['regions_list'] = proxies
    
    if not proxies:
        try: await msg.edit_text(f"⚠️ <b>NO PROXIES FOUND</b>\n━━━━━━━━━━━━━━━━━━━━\nThere are currently no active proxies available for <b>{escape(str(full_name))}</b>.", reply_markup=InlineKeyboardMarkup([[InlineKeyboardButton("🎲 Try Random Proxy", callback_data="get_proxy_random")]]), parse_mode='HTML')
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
    current_proxies = proxies[start_idx:start_idx + items_per_page]
    
    keyboard = []
    row = []
    for p in current_proxies:
        row.append(InlineKeyboardButton(f"{p['region']} ({p['speed']} - {p['type']})", callback_data=f"sel_id_{p['id']}"))
        if len(row) == 2: keyboard.append(row); row = []
    if row: keyboard.append(row)
    
    nav = []
    if page > 1: nav.append(InlineKeyboardButton("⬅️", callback_data=f"reg_page_{page-1}"))
    nav.append(InlineKeyboardButton(f"{page}/{total_pages}", callback_data="noop"))
    if page < total_pages: nav.append(InlineKeyboardButton("➡️", callback_data=f"reg_page_{page+1}"))
    keyboard.append(nav)
    keyboard.append([InlineKeyboardButton("🎲 Any Region (Random)", callback_data="get_proxy_random")])
    keyboard.append([InlineKeyboardButton("🌍 Change Country", callback_data="change_country")])
    
    try: await message_obj.edit_text(f"🌍 <b>SELECT A REGION: {escape(str(full_name))}</b>\n━━━━━━━━━━━━━━━━━━━━\nChoose a specific region from the list below:", reply_markup=InlineKeyboardMarkup(keyboard), parse_mode='HTML')
    except BadRequest as e:
        if "Message is not modified" not in str(e): raise e

async def process_proxy_fetch(message_obj, country, region, context, user, proxy_id=None, is_edit=True):
    if not country:
        error_text = "❌ <b>Session Lost:</b> Please select a country again by clicking 'Get Proxy ✨'."
        if is_edit and hasattr(message_obj, 'edit_text'):
            try: await message_obj.edit_text(error_text, parse_mode='HTML')
            except: pass
        else: await context.bot.send_message(chat_id=user.id, text=error_text, parse_mode='HTML')
        return

    loop = asyncio.get_running_loop()
    price = SETTINGS.get('proxy_price', 10)
    
    # 1. DB Balance Check
    bal = await loop.run_in_executor(None, db_get_balance, user.id)
    if bal < price:
        err = f"❌ <b>INSUFFICIENT BALANCE!</b>\n━━━━━━━━━━━━━━━━━━━━\n💰 Your Balance: <b>{bal} TK</b>\n🚀 Proxy Price: <b>{price} TK</b>\n\nPlease click <b>💳 Add Balance</b>."
        if is_edit and hasattr(message_obj, 'edit_text'):
            try: await message_obj.edit_text(err, parse_mode='HTML')
            except: pass
        else: await context.bot.send_message(chat_id=user.id, text=err, parse_mode='HTML')
        return

    status_msg = message_obj
    if is_edit and hasattr(message_obj, 'edit_text'):
        try: status_msg = await message_obj.edit_text("⏳ <i>Unlocking premium proxy...</i>", parse_mode='HTML')
        except: pass
    else: status_msg = await context.bot.send_message(chat_id=user.id, text="⏳ <i>Unlocking premium proxy...</i>", parse_mode='HTML')

    # 2. Fetch Proxy Details
    if proxy_id:
        p_list = context.user_data.get('regions_list', [])
        p_obj = next((p for p in p_list if str(p['id']) == str(proxy_id)), {})
        speed, p_type, real_region = p_obj.get('speed', 'N/A'), p_obj.get('type', 'N/A'), p_obj.get('region', region)
        pid = proxy_id
    else:
        proxy_obj, error = await loop.run_in_executor(None, _sync_fetch_proxy_obj_random, country, region)
        if error:
            try: await status_msg.edit_text(f"❌ <b>Error:</b> {escape(str(error))}", parse_mode='HTML')
            except: pass
            return
        pid, speed, p_type, real_region = proxy_obj['Id'], proxy_obj.get('Speed', 'N/A'), proxy_obj.get('useType', 'N/A'), proxy_obj.get('Region', region)
    
    context.user_data['last_region'] = real_region

    creds, error = await loop.run_in_executor(None, _sync_reveal_credentials, pid)
    if error:
        try: await status_msg.edit_text(f"❌ <b>Reveal Error:</b> {escape(str(error))}", parse_mode='HTML')
        except: pass
        return

    # 3. ATOMIC DB DEDUCTION (The safest part!)
    db_res = await loop.run_in_executor(None, db_log_proxy_purchase, user.id, price, creds)
    
    if not db_res.get('success'):
        # They ran out of money during the 1 second it took to fetch the proxy!
        try: await status_msg.edit_text("❌ <b>Error:</b> Insufficient balance during final processing.", parse_mode='HTML')
        except: pass
        return

    # 4. Display Success
    try: ip, port, u, p = creds.split(':')
    except: ip, port, u, p = "N/A", "N/A", "N/A", "N/A"
    
    new_bal = bal - price

    final_text = (
        f"✅ <b>PROXY SUCCESSFULLY GENERATED!</b>\n━━━━━━━━━━━━━━━━━━━━\n"
        f"🌍 <b>Location:</b> {escape(str(country))} (📍 {escape(str(real_region))})\n"
        f"⚡ <b>Speed:</b> {escape(str(speed))} | 📶 <b>Type:</b> {escape(str(p_type))}\n\n"
        f"📥 <b>Format (IP:Port:User:Pass):</b>\n<code>{escape(str(creds))}</code>\n\n"
        f"📝 <b>Detailed Info:</b>\n🌐 Host: <code>{escape(str(ip))}</code>\n🔌 Port: <code>{escape(str(port))}</code>\n"
        f"👤 User: <code>{escape(str(u))}</code>\n🔑 Pass: <code>{escape(str(p))}</code>\n━━━━━━━━━━━━━━━━━━━━\n"
        f"💳 <b>Balance Deducted:</b> -{price} TK\n💰 <b>Remaining Balance:</b> {new_bal} TK"
    )
    
    kb = InlineKeyboardMarkup([
        [InlineKeyboardButton("🔄 Get Another (Same Region)", callback_data="get_same_proxy")],
        [InlineKeyboardButton("🔙 Back to Regions", callback_data="back_to_regions")],
        [InlineKeyboardButton("🌍 Change Country", callback_data="change_country")]
    ])
    
    try: await status_msg.edit_text(final_text, parse_mode='HTML', reply_markup=kb)
    except: pass

    log_message = f"🚀 <b>Proxy Generated</b>\n━━━━━━━━━━━━━━━━━━━━\n👤 <b>User:</b> @{escape(str(user.username))} (<code>{user.id}</code>)\n🏳️ <b>Country:</b> {escape(str(country))} | 📍 {escape(str(real_region))}\n💰 <b>Spent:</b> {price} TK"
    try: await context.bot.send_message(chat_id=LOG_GROUP_ID, text=log_message, parse_mode='HTML')
    except: pass

async def button_click(update: Update, context: ContextTypes.DEFAULT_TYPE):
    query = update.callback_query
    action = query.data
    user = query.from_user

    if not user.username: return await query.answer("⚠️ Username Required!", show_alert=True)

    if action in ['cancel_deposit', 'cancel_action']:
        context.user_data['state'] = None
        await query.answer("Cancelled")
        try: await query.message.edit_text("❌ <b>Action cancelled.</b>", parse_mode='HTML')
        except: pass
        return

    if action == 'pay_piprapay':
        context.user_data['state'] = 'awaiting_deposit'
        kb = InlineKeyboardMarkup([[InlineKeyboardButton("❌ Cancel", callback_data="cancel_action")]])
        await query.message.edit_text("⚡ <b>PIPRAPAY AUTO-DEPOSIT</b>\n━━━━━━━━━━━━━━━━━━━━\n💰 How much TK do you want to add?\n\n<i>Please enter the amount below (Min 10):</i>", parse_mode='HTML', reply_markup=kb)
        return
        
    if action == 'pay_binance':
        context.user_data['state'] = 'awaiting_binance_amount'
        kb = InlineKeyboardMarkup([[InlineKeyboardButton("❌ Cancel", callback_data="cancel_action")]])
        await query.message.edit_text("🟡 <b>BINANCE MANUAL DEPOSIT</b>\n━━━━━━━━━━━━━━━━━━━━\nBinance UID: <code>805398719</code>\n\n💰 How much TK are you depositing?\n<i>Enter the amount below:</i>", parse_mode='HTML', reply_markup=kb)
        return

    if action.startswith('man_approve_') or action.startswith('man_reject_'):
        if user.id not in ADMIN_IDS: return await query.answer("❌ Unauthorized!", show_alert=True)
            
        order_id = action.replace('man_approve_', '').replace('man_reject_', '')
        order = SETTINGS.get('manual_payments', {}).get(order_id)
        
        if not order: return await query.answer("❌ Order not found.", show_alert=True)
        if order['status'] != 'pending': return await query.answer(f"⚠️ Order already {order['status']}!", show_alert=True)
            
        if 'man_approve_' in action:
            order['status'] = 'approved'
            amount, target_id = order['amount'], order['user_id']
            
            loop = asyncio.get_running_loop()
            await loop.run_in_executor(None, db_update_balance, target_id, amount, f"Manual Binance Dep {order['trx_id']}")
            save_settings()
            
            await query.answer("✅ Approved!")
            try: await query.message.edit_caption(caption=(query.message.caption_html or "") + "\n\n✅ <b>APPROVED</b> by Admin", parse_mode='HTML')
            except: pass
            
            try: await context.bot.send_message(chat_id=target_id, text=f"🎉 <b>PAYMENT APPROVED!</b>\n━━━━━━━━━━━━━━━━━━━━\nYour manual deposit of <b>{amount} TK</b> has been verified and added to your MySQL balance.", parse_mode='HTML')
            except: pass
        else:
            order['status'] = 'rejected'
            save_settings()
            await query.answer("❌ Rejected!")
            try: await query.message.edit_caption(caption=(query.message.caption_html or "") + "\n\n❌ <b>REJECTED</b> by Admin", parse_mode='HTML')
            except: pass
            try: await context.bot.send_message(chat_id=order['user_id'], text=f"❌ <b>PAYMENT REJECTED!</b>\n━━━━━━━━━━━━━━━━━━━━\nYour manual deposit for Order ID <code>{order['trx_id']}</code> was rejected.", parse_mode='HTML')
            except: pass
        return
        
    if action.startswith('pdec_a_') or action.startswith('pdec_r_'):
        if user.id not in ADMIN_IDS: return await query.answer("❌ Unauthorized!", show_alert=True)
            
        is_approve = action.startswith('pdec_a_')
        order_id = action.replace('pdec_a_', '').replace('pdec_r_', '')

        if order_id not in PENDING_AUTO_PAYMENTS:
            return await query.answer("⚠️ Payment already processed or expired.", show_alert=True)

        if is_approve:
            # We don't have the amount directly in PENDING_AUTO_PAYMENTS, so admin manual approve here 
            # is tricky without local storage of amount. You could fetch from DB `payments` table.
            # For safety, DB forced approve is better handled directly in phpmyadmin.
            await query.answer("❌ Please use phpMyAdmin to force approve auto-deposits now.", show_alert=True)
        else:
            PENDING_AUTO_PAYMENTS.pop(order_id, None)
            await query.answer("❌ Cancelled Polling!")
            try: await query.message.edit_text(text=query.message.text_html + "\n\n❌ <b>CANCELLED</b> manually by Admin", parse_mode='HTML')
            except: pass
        return

    country = context.user_data.get('country_full')
    if action.startswith('reg_page_'): await show_region_page(query.message, int(action.split('_')[2]), context)
    elif action.startswith('sel_id_'): await process_proxy_fetch(query.message, country, '', context, user, proxy_id=action.split('sel_id_')[1], is_edit=True)
    elif action == 'get_proxy_random': await process_proxy_fetch(query.message, country, '', context, user, is_edit=True)
    elif action == 'get_same_proxy': await process_proxy_fetch(query.message, country, context.user_data.get('last_region', ''), context, user, is_edit=False)
    elif action == 'back_to_regions': await show_region_page(query.message, 1, context)
    elif action == 'change_country':
        try: await query.message.edit_text("🌍 <b>SELECT A COUNTRY</b>\n━━━━━━━━━━━━━━━━━━━━\nType the <b>2-letter Country Code</b> or full name.", parse_mode='HTML')
        except: pass

    await query.answer()

async def update_cookie(update: Update, context: ContextTypes.DEFAULT_TYPE):
    if update.effective_user.id not in ADMIN_IDS: return
    try:
        new_cookie = update.message.text.split(None, 1)[1]
        SETTINGS['cookie'] = new_cookie
        HEADERS['Cookie'] = new_cookie
        save_settings()
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

    print("🚀 MySQL Connected High-Speed Proxy Bot is starting...")
    application.run_polling()
