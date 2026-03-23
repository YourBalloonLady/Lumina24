import asyncio
import logging
import sqlite3
import os  
from aiogram import Bot, Dispatcher, F, types
from aiogram.filters import CommandStart
from aiogram.fsm.context import FSMContext
from aiogram.fsm.state import State, StatesGroup
from aiogram.fsm.storage.memory import MemoryStorage
from aiogram.types import (
    Message, ReplyKeyboardMarkup, KeyboardButton, 
    InlineKeyboardMarkup, InlineKeyboardButton, CallbackQuery
)

# --- CONFIGURATION (Safe for Railway) ---
# It will look for variables in Railway; if not found, it uses the backup ID.
TOKEN = os.getenv("BOT_TOKEN")
ADMIN_ID = int(os.getenv("ADMIN_ID", 5839927114)) 

# Path to your persistent database on Railway
DB_PATH = '/app/data/store.db'

BANK_DETAILS = """
🏦 **PAYMENT DETAILS**
Bank: [Your Bank Name]
Account Name: [Your Name/Business]
Sort Code: 00-00-00
Account Number: 12345678
"""

# --- DATABASE SETUP ---
def init_db():
    # Ensure the directory exists (helpful for first-time setup)
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
    "item8": {"name": "Tirzepatide 40mg Pen", "price": 130, "stock": 0},
    "item9": {"name": "Tirzepatide 40mg Vial", "price": 130, "stock": 0},
    "item10": {"name": "Tirzepatide 60mg Pen", "price": 150, "stock": 0},
    "item11": {"name": "Tirzepatide 60mg Vial", "price": 150, "stock": 0},
    "item12": {"name": "Retatrutide 60mg Pen", "price": 180, "stock": 0},
    "item13": {"name": "Retatrutide 60mg Vial", "price": 180, "stock": 0},
}

carts = {}

# --- KEYBOARDS & HELPERS ---
main_kb = ReplyKeyboardMarkup(keyboard=[[KeyboardButton(text="🛍 Shop Now")], [KeyboardButton(text="🛒 My Cart")]], resize_keyboard=True)

def build_shop_kb():
    rows = []
    for pid, p in products.items():
        label = f"{p['name']} - £{p['price']}"
        if p['stock'] <= 0: label += " (Sold Out)"
        rows.append([InlineKeyboardButton(text=label, callback_data=f"view_{pid}")])
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
    await m.answer("👋 Welcome to JJS Store!", reply_markup=main_kb)

@dp.message(F.text == "🛍 Shop Now")
async def shop(m: Message):
    await m.answer("🛍 Select a product:", reply_markup=build_shop_kb())

@dp.callback_query(F.data.startswith("view_"))
async def view(cb: CallbackQuery):
    pid = cb.data.split("_")[1]
    p = products[pid]
    kb = InlineKeyboardMarkup(inline_keyboard=[[InlineKeyboardButton(text="🛒 Add to Cart", callback_data=f"add_{pid}")], [InlineKeyboardButton(text="⬅ Back", callback_data="back_shop")]])
    await cb.message.edit_text(f"📦 **{p['name']}**\nPrice: £{p['price']}\n\nSelect an option below:", reply_markup=kb)

@dp.callback_query(F.data == "back_shop")
async def back_to_shop(cb: CallbackQuery):
    await cb.message.edit_text("🛍 Select a product:", reply_markup=build_shop_kb())

@dp.callback_query(F.data.startswith("add_"))
async def add(cb: CallbackQuery):
    uid, pid = cb.from_user.id, cb.data.split("_")[1]
    if products[pid]['stock'] <= 0:
        return await cb.answer("Sorry, out of stock!", show_alert=True)
    carts.setdefault(uid, {})[pid] = carts.get(uid, {}).get(pid, 0) + 1
    summary, total = get_cart_summary(uid)
    kb = InlineKeyboardMarkup(inline_keyboard=[[InlineKeyboardButton(text="💳 Checkout", callback_data="start_checkout")], [InlineKeyboardButton(text="🛍 Continue Shopping", callback_data="back_shop")]])
    await cb.message.answer(f"✅ Added to cart!\n\n{summary}\n\n💰 **Total: £{total}**", reply_markup=kb)

@dp.message(F.text == "🛒 My Cart")
async def show_cart(m: Message):
    uid = m.from_user.id
    summary, total = get_cart_summary(uid)
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
    await m.answer("📍 Please enter your **Delivery Address** (House & Street):")
    await state.set_state(CheckoutState.waiting_for_address)

@dp.message(CheckoutState.waiting_for_address)
async def check3(m: Message, state: FSMContext):
    await state.update_data(address=m.text)
    await m.answer("📮 Please enter your **Postcode**:")
    await state.set_state(CheckoutState.waiting_for_postcode)

@dp.message(CheckoutState.waiting_for_postcode)
async def check4(m: Message, state: FSMContext):
    postcode = m.text
    data = await state.get_data()
    uid = m.from_user.id
    summary, total = get_cart_summary(uid)
    full_address = f"{data['address']}, {postcode}"
    
    order_id = save_order(uid, data['name'], full_address, summary, total)
    
    await m.answer(f"🏁 **Order #{order_id} Logged!**\n\n{BANK_DETAILS}\n📸 Please send a screenshot of payment to @yourusername")
    
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
    await cb.bot.send_message(cid, f"✅ **Payment for Order #{oid} Received!**\nYour order is now being processed.")
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

async def main():
    bot = Bot(token=TOKEN)
    await dp.start_polling(bot)

if __name__ == "__main__":
    asyncio.run(main())
