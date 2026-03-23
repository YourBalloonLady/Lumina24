import asyncio
import logging
import sqlite3
import os  
from supabase import create_client, Client
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
DB_PATH = os.getenv("DATABASE_URL", "/app/data/store.db") 
MY_USERNAME = "@Admi_181" 

# SUPABASE SETUP
SUPA_URL = os.getenv("SUPABASE_URL")
SUPA_KEY = os.getenv("SUPABASE_KEY")
supabase: Client = create_client(SUPA_URL, SUPA_KEY)

BANK_DETAILS = """
🏦 **PAYMENT DETAILS**
Bank: Barclays
Account Name: Lumina
Sort Code: 20-19-96
Account Number: 63112098

⚠️ **IMPORTANT:** Use your **Order Number** or **Full Name** as the reference.
"""

# --- DATABASE SETUP ---
def init_db():
    try:
        db_dir = os.path.dirname(DB_PATH)
        if db_dir and not os.path.exists(db_dir):
            os.makedirs(db_dir, exist_ok=True)
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
    except Exception as e:
        logging.error(f"Database error: {e}")

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
    if status: cursor.execute('UPDATE orders SET status = ? WHERE id = ?', (status, order_id))
    if tracking: cursor.execute('UPDATE orders SET tracking = ? WHERE id = ?', (tracking, order_id))
    conn.commit()
    conn.close()

# --- SUPABASE HELPERS ---
async def get_live_products():
    response = supabase.table("products").select("*").execute()
    return {p['id']: {"name": p['name'], "price": p['price'], "stock": p['stock']} for p in response.data}

def update_supabase_stock(pid, new_stock):
    supabase.table("products").update({"stock": new_stock}).eq("id", pid).execute()

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

async def build_shop_kb():
    products = await get_live_products()
    rows = []
    # Sort by the number in 'itemX'
    sorted_items = sorted(products.items(), key=lambda x: int(x[0].replace('item', '')))
    for pid, p in sorted_items:
        label = f"{p['name']} - £{p['price']}"
        if p['stock'] <= 0: label += " (SOLD OUT)"
        rows.append([InlineKeyboardButton(text=label, callback_data=f"view_{pid}")])
    return InlineKeyboardMarkup(inline_keyboard=rows)

async def get_cart_summary(uid):
    user_cart = carts.get(uid, {})
    if not user_cart: return "Empty", 0
    products = await get_live_products()
    summary = "\n".join([f"• {products[pid]['name']} x{q}" for pid, q in user_cart.items() if pid in products])
    total = sum(products[pid]['price'] * q for pid, q in user_cart.items() if pid in products)
    return summary, total

# --- HANDLERS ---
@dp.message(CommandStart())
async def start(m: Message):
    await m.answer("👋 Welcome to JJS Store!", reply_markup=main_kb)

@dp.message(F.text == "🛍 Shop Now")
async def shop(m: Message):
    kb = await build_shop_kb()
    await m.answer("🛍 **Product Catalog**", reply_markup=kb)

@dp.callback_query(F.data.startswith("view_"))
async def view(cb: CallbackQuery):
    pid = cb.data.split("_")[1]
    products = await get_live_products()
    p = products[pid]
    stock_status = f"✅ In Stock ({p['stock']})" if p['stock'] > 0 else "❌ OUT OF STOCK"
    kb = InlineKeyboardMarkup(inline_keyboard=[
        [InlineKeyboardButton(text="🛒 Add to Cart", callback_data=f"add_{pid}")],
        [InlineKeyboardButton(text="⬅ Back", callback_data="back_shop")]
    ])
    await cb.message.edit_text(f"📦 **{p['name']}**\nPrice: £{p['price']}\nStatus: {stock_status}", reply_markup=kb)

@dp.callback_query(F.data == "back_shop")
async def back_to_shop(cb: CallbackQuery):
    kb = await build_shop_kb()
    await cb.message.edit_text("🛍 **Product Catalog**", reply_markup=kb)

@dp.callback_query(F.data.startswith("add_"))
async def add(cb: CallbackQuery):
    uid, pid = cb.from_user.id, cb.data.split("_")[1]
    products = await get_live_products()
    if products[pid]['stock'] <= 0:
        return await cb.answer("❌ Out of stock!", show_alert=True)
    
    carts.setdefault(uid, {})[pid] = carts.get(uid, {}).get(pid, 0) + 1
    summary, total = await get_cart_summary(uid)
    kb = InlineKeyboardMarkup(inline_keyboard=[[InlineKeyboardButton(text="💳 Checkout", callback_data="start_checkout")], [InlineKeyboardButton(text="🛍 Continue Shopping", callback_data="back_shop")]])
    await cb.message.answer(f"✅ Added!\n\n{summary}\n\n💰 **Total: £{total}**", reply_markup=kb)

@dp.message(F.text == "🛒 My Cart")
async def show_cart(m: Message):
    summary, total = await get_cart_summary(m.from_user.id)
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
    await m.answer("📍 Please enter your **Full Delivery Address**:")
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
    products = await get_live_products()
    summary, total = await get_cart_summary(uid)
    full_address = f"{data['address']}, {m.text}"
    
    # Update Supabase
    user_cart = carts.get(uid, {})
    for pid, quantity in user_cart.items():
        if pid in products:
            new_stock = max(0, products[pid]['stock'] - quantity)
            update_supabase_stock(pid, new_stock)

    order_id = save_order(uid, data['name'], full_address, summary, total)
    await m.answer(f"🏁 **Order #{order_id} Logged!**\n\n{BANK_DETAILS}")
    
    admin_kb = InlineKeyboardMarkup(inline_keyboard=[
        [InlineKeyboardButton(text="✅ Mark Paid", callback_data=f"adm_p_{order_id}_{uid}")],
        [InlineKeyboardButton(text="🚚 Add Tracking", callback_data=f"adm_t_{order_id}_{uid}")]
    ])
    await m.bot.send_message(ADMIN_ID, f"🔔 **NEW ORDER #{order_id}**\n👤 {data['name']}\n📍 {full_address}\n\n{summary}\n\n💰 Total: £{total}", reply_markup=admin_kb)
    
    if uid in carts: del carts[uid]
    await state.clear()

# --- ADMIN COMMANDS ---

@dp.message(Command("stock"))
async def admin_stock_check(m: Message):
    """Command for Admin to check Supabase inventory levels."""
    if m.from_user.id != ADMIN_ID: return
    products = await get_live_products()
    sorted_p = sorted(products.items(), key=lambda x: int(x[0].replace('item', '')))
    
    report = "📊 **Live Inventory Report**\n\n"
    for pid, p in sorted_p:
        status = "🟢" if p['stock'] > 5 else "🟡" if p['stock'] > 0 else "🔴"
        report += f"{status} `{pid}`: {p['name']} | **{p['stock']}** left\n"
    
    await m.answer(report)

@dp.message(Command("admin_orders"))
async def view_orders(m: Message):
    if m.from_user.id != ADMIN_ID: return
    conn = sqlite3.connect(DB_PATH)
    cursor = conn.cursor()
    cursor.execute("SELECT id, name, total, status FROM orders ORDER BY id DESC LIMIT 10")
    orders = cursor.fetchall()
    conn.close()
    if not orders: return await m.answer("No orders found.")
    text = "📊 **Last 10 Orders:**\n\n" + "\n".join([f"#{o[0]} | {o[1]} | £{o[2]} | {o[3]}" for o in orders])
    await m.answer(text)

@dp.callback_query(F.data.startswith("adm_p_"))
async def adm_paid(cb: CallbackQuery):
    _, _, oid, cid = cb.data.split("_")
    update_db_order(oid, status="Paid")
    await cb.bot.send_message(cid, f"✅ **Payment Received for Order #{oid}!**")
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
    await m.bot.send_message(data['current_customer_id'], f"🚚 **Order #{data['current_order_id']} Shipped!**\nTracking: `{m.text}`")
    await m.answer(f"✅ Tracking sent!")
    await state.clear()

async def main():
    bot = Bot(token=TOKEN)
    await dp.start_polling(bot)

if __name__ == "__main__":
    asyncio.run(main())
