import asyncio
import logging
import sqlite3
import os  
from aiogram import Bot, Dispatcher, F, types
from aiogram.filters import CommandStart, Command
from aiogram.fsm.context import FSMContext
from aiogram.fsm.state import State, StatesGroup
from aiogram.fsm.storage.memory import MemoryStorage
from aiogram.types import (
    Message, ReplyKeyboardMarkup, KeyboardButton, 
    InlineKeyboardMarkup, InlineKeyboardButton, CallbackQuery
)

# --- CONFIGURATION ---
TOKEN = os.getenv("BOT_TOKEN")
ADMIN_ID = int(os.getenv("ADMIN_ID", 5839927114)) 
DB_PATH = '/app/data/store.db'
MY_USERNAME = "@YourUsername" # <--- CHANGE THIS to your actual Telegram handle

BANK_DETAILS = """
🏦 **PAYMENT DETAILS**
Bank: Barclays
Account Name: Lumina - (Name Wont Match)
Sort Code: 20-19-96
Account Number: 63112098

⚠️ **IMPORTANT:** Use your **Order Number** or **Full Name** as the reference.
Once payment is made, we will process your order immediately.
"""

# --- DATABASE SETUP ---
def init_db():
    os.makedirs(os.path.dirname(DB_PATH), exist_ok=True)
    conn = sqlite3.connect(DB_PATH)
    cursor = conn.cursor()
    cursor.execute('''
        CREATE TABLE IF NOT EXISTS orders (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            user_id INTEGER,
            name TEXT,
            address TEXT,
            items TEXT,
            total INTEGER,
            status TEXT DEFAULT 'Pending',
            tracking TEXT DEFAULT 'None'
        )
    ''')
    conn.commit()
    conn.close()

def save_order(user_id, name, address, items, total):
    conn = sqlite3.connect(DB_PATH)
    cursor = conn.cursor()
    cursor.execute('INSERT INTO orders (user_id, name, address, items, total) VALUES (?, ?, ?, ?, ?)',
                   (user_id, name, address, items, total))
    order_id = cursor.lastrowid
    conn.commit()
    conn.close()
    return order_id

def update_db_order(order_id, status=None, tracking=None):
    conn = sqlite3.connect(DB_PATH)
    cursor = conn.cursor()
    if status:
        cursor.execute('UPDATE orders SET status = ? WHERE id = ?', (status, order_id))
    if tracking:
        cursor.execute('UPDATE orders SET tracking = ? WHERE id = ?', (tracking, order_id))
    conn.commit()
    conn.close()

# --- INITIALIZE ---
logging.basicConfig(level=logging.INFO)
init_db()
dp = Dispatcher(storage=MemoryStorage())

class CheckoutState(StatesGroup):
    waiting_for_name = State()
    waiting_for_address = State()
    waiting_for_postcode = State()

class AdminState(StatesGroup):
    waiting_for_tracking_num = State()
    current_order_id = State()
    current_customer_id = State()

# --- PRODUCTS ---
products = {
    "item1": {"name": "BPC-157 & TB500 Blend 10mg", "price": 35, "stock": 10},
    "item2": {"name": "MOTS-C", "price": 55, "stock": 10},
    "item3": {"name": "Semaglutide 20mg Pen", "price": 100, "stock": 10},
    "item4": {"name": "Semaglutide 20mg Vial", "price": 100, "stock": 10},
    "item5": {"name": "GHK-CU 10mg", "price": 150, "stock": 10},
    "item6": {"name": "Tirzepatide 20mg Pen", "price": 110, "stock": 10},
    "item7": {"name": "Tirzepatide 20mg Vial", "price": 110, "stock": 10},
}

carts = {}

# --- KEYBOARDS ---
main_kb = ReplyKeyboardMarkup(
    keyboard=[
        [KeyboardButton(text="🛍 Shop Now")],
        [KeyboardButton(text="🛒 My Cart")],
        [KeyboardButton(text="❓ Help"), KeyboardButton(text="📞 Contact")]
    ], 
    resize_keyboard=True
)

def build_shop_kb():
    rows = [[InlineKeyboardButton(text=f"{p['name']} - £{p['price']}", callback_data=f"view_{pid}")] for pid, p in products.items()]
    return InlineKeyboardMarkup(inline_keyboard=rows)

def get_cart_summary(uid):
    user_cart = carts.get(uid, {})
    if not user_cart: return "Empty", 0
    summary = "\n".join([f"• {products[pid]['name']} x{q}" for pid, q in user_cart.items()])
    total = sum(products[pid]['price'] * q for pid, q in user_cart.items())
    return summary, total

# --- HANDLERS ---
@dp.message(CommandStart())
async def start(m: Message):
    await m.answer("👋 Welcome to JJS Store! Use the menu below to browse our products.", reply_markup=main_kb)

@dp.message(F.text == "🛍 Shop Now")
async def shop(m: Message):
    await m.answer("🛍 **Product Catalog**", reply_markup=build_shop_kb())

@dp.message(F.text == "❓ Help")
async def help_handler(m: Message):
    await m.answer("❓ **Help & FAQ**\n\n1. Select items in the Shop.\n2. Go to Cart and Checkout.\n3. Complete the Bank Transfer.\n4. We ship within 24-48 hours of payment.")

@dp.message(F.text == "📞 Contact")
async def contact_handler(m: Message):
    await m.answer(f"📞 **Customer Support**\n\nNeed help with an order? Contact us directly: {MY_USERNAME}")

@dp.callback_query(F.data.startswith("view_"))
async def view(cb: CallbackQuery):
    pid = cb.data.split("_")[1]
    p = products[pid]
    kb = InlineKeyboardMarkup(inline_keyboard=[[InlineKeyboardButton(text="🛒 Add to Cart", callback_data=f"add_{pid}")], [InlineKeyboardButton(text="⬅ Back", callback_data="back_shop")]])
    await cb.message.edit_text(f"📦 **{p['name']}**\nPrice: £{p['price']}", reply_markup=kb)

@dp.callback_query(F.data == "back_shop")
async def back_to_shop(cb: CallbackQuery):
    await cb.message.edit_text("🛍 **Product Catalog**", reply_markup=build_shop_kb())

@dp.callback_query(F.data.startswith("add_"))
async def add(cb: CallbackQuery):
    uid, pid = cb.from_user.id, cb.data.split("_")[1]
    carts.setdefault(uid, {})[pid] = carts.get(uid, {}).get(pid, 0) + 1
    summary, total = get_cart_summary(uid)
    kb = InlineKeyboardMarkup(inline_keyboard=[[InlineKeyboardButton(text="💳 Checkout", callback_data="start_checkout")], [InlineKeyboardButton(text="🛍 Continue Shopping", callback_data="back_shop")]])
    await cb.message.answer(f"✅ Added!\n\n{summary}\n\n💰 **Total: £{total}**", reply_markup=kb)

@dp.message(F.text == "🛒 My Cart")
async def show_cart(m: Message):
    summary, total = get_cart_summary(m.from_user.id)
    kb = InlineKeyboardMarkup(inline_keyboard=[[InlineKeyboardButton(text="💳 Checkout", callback_data="start_checkout")]]) if total > 0 else None
    await m.answer(f"🛒 **Your Cart:**\n\n{summary}\n\n💰 **Total: £{total}**", reply_markup=kb)

# --- CHECKOUT ---
@dp.callback_query(F.data == "start_checkout")
async def check1(cb: CallbackQuery, state: FSMContext):
    await cb.message.answer("📝 **Checkout**\nPlease enter your **Full Name**:")
    await state.set_state(CheckoutState.waiting_for_name)

@dp.message(CheckoutState.waiting_for_name)
async def check2(m: Message, state: FSMContext):
    await state.update_data(name=m.text)
    await m.answer("📍 Please enter your **Full Delivery Address** (inc. House No/Street):")
    await state.set_state(CheckoutState.waiting_for_address)

@dp.message(CheckoutState.waiting_for_address)
async def check3(m: Message, state: FSMContext):
    await state.update_data(address=m.text)
    await m.answer("📮 Please enter your **Postcode**:")
    await state.set_state(CheckoutState.waiting_for_postcode)

@dp.message(CheckoutState.waiting_for_postcode)
async def check4(m: Message, state: FSMContext):
    data = await state.get_data()
    uid = m.from_user.id
    summary, total = get_cart_summary(uid)
    full_address = f"{data['address']}, {m.text}"
    
    order_id = save_order(uid, data['name'], full_address, summary, total)
    
    # Customer confirmation (Removed screenshot request)
    await m.answer(f"🏁 **Order #{order_id} Logged!**\n\n{BANK_DETAILS}\n\nWe will notify you here as soon as payment is confirmed.")
    
    # Admin Alert
    admin_kb = InlineKeyboardMarkup(inline_keyboard=[
        [InlineKeyboardButton(text="✅ Mark Paid", callback_data=f"adm_p_{order_id}_{uid}")],
        [InlineKeyboardButton(text="🚚 Add Tracking", callback_data=f"adm_t_{order_id}_{uid}")]
    ])
    await m.bot.send_message(ADMIN_ID, f"🔔 **NEW ORDER #{order_id}**\n👤 {data['name']}\n📍 {full_address}\n\n{summary}\n\n💰 Total: £{total}", reply_markup=admin_kb)
    
    if uid in carts: del carts[uid]
    await state.clear()

# --- ADMIN ACTIONS ---
@dp.callback_query(F.data.startswith("adm_p_"))
async def adm_paid(cb: CallbackQuery):
    _, _, oid, cid = cb.data.split("_")
    update_db_order(oid, status="Paid")
    await cb.bot.send_message(cid, f"✅ **Payment Received for Order #{oid}!**\nWe are now preparing your shipment.")
    await cb.answer(f"Order #{oid} marked Paid")

@dp.callback_query(F.data.startswith("adm_t_"))
async def adm_track(cb: CallbackQuery, state: FSMContext):
    _, _, oid, cid = cb.data.split("_")
    await state.update_data(current_order_id=oid, current_customer_id=cid)
    await state.set_state(AdminState.waiting_for_tracking_num)
    await cb.message.answer(f"📦 Enter Tracking Number for Order #{oid}:")

@dp.message(AdminState.waiting_for_tracking_num)
async def adm_finish(m: Message, state: FSMContext):
    if m.from_user.id != ADMIN_ID: return
    data = await state.get_data()
    update_db_order(data['current_order_id'], tracking=m.text)
    await m.bot.send_message(data['current_customer_id'], f"🚚 **Order #{data['current_order_id']} Shipped!**\n\nTracking Number: `{m.text}`")
    await m.answer(f"✅ Tracking sent for Order #{data['current_order_id']}!")
    await state.clear()

# --- ADMIN VIEW ORDERS COMMAND ---
@dp.message(Command("admin_orders"))
async def view_orders(m: Message):
    if m.from_user.id != ADMIN_ID: return
    conn = sqlite3.connect(DB_PATH)
    cursor = conn.cursor()
    cursor.execute("SELECT id, name, total, status FROM orders ORDER BY id DESC LIMIT 10")
    orders = cursor.fetchall()
    conn.close()
    
    if not orders:
        return await m.answer("No orders found in database.")
    
    text = "📊 **Last 10 Orders:**\n\n"
    for o in orders:
        text += f"#{o[0]} | {o[1]} | £{o[2]} | {o[3]}\n"
    await m.answer(text)

async def main():
    bot = Bot(token=TOKEN)
    await dp.start_polling(bot)

if __name__ == "__main__":
    asyncio.run(main())
