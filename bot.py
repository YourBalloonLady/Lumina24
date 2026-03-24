import os
os.environ["HTTPX_CLIENT_KWARGS"] = "{}"

import asyncio
import logging
import sqlite3

from supabase import create_client, Client
from aiogram import Bot, Dispatcher, F
from aiogram.filters import CommandStart, Command
from aiogram.fsm.context import FSMContext
from aiogram.fsm.state import State, StatesGroup
from aiogram.fsm.storage.memory import MemoryStorage
from aiogram.enums import ParseMode
from aiogram.client.default import DefaultBotProperties
from aiogram.types import (
    Message,
    ReplyKeyboardMarkup,
    KeyboardButton,
    InlineKeyboardMarkup,
    InlineKeyboardButton,
    CallbackQuery,
)

# -----------------------------
# CONFIG
# -----------------------------
TOKEN = os.getenv("BOT_TOKEN")
ADMIN_ID = int(os.getenv("ADMIN_ID", 5839927114))
DB_PATH = os.getenv("DATABASE_URL", "/app/data/store.db")
MY_USERNAME = "@Admi_181"

SUPA_URL = os.getenv("SUPABASE_URL")
SUPA_KEY = os.getenv("SUPABASE_KEY")

supabase: Client | None = None

logging.basicConfig(level=logging.INFO)

BANK_DETAILS = """
🏦 <b>PAYMENT DETAILS</b>

Bank: Barclays
Account Name: Lumina (Name Wont Match)
Sort Code: 20-19-96
Account Number: 63112098

⚠️ <b>IMPORTANT:</b> Use your <b>Order Number</b> or <b>Full Name</b> as the reference.
"""

# -----------------------------
# SUPABASE & DB INIT
# -----------------------------
def init_supabase():
    global supabase
    if not SUPA_URL or not SUPA_KEY: return
    try:
        supabase = create_client(SUPA_URL, SUPA_KEY)
    except Exception as e:
        logging.error(f"Supabase init failed: {e}")

async def get_live_products():
    if not supabase: return {}
    try:
        response = supabase.table("products").select("*").execute()
        return {p["id"]: {"name": p["name"], "price": p["price"], "stock": p["stock"]} for p in response.data}
    except Exception: return {}

def init_db():
    db_dir = os.path.dirname(DB_PATH)
    if db_dir and not os.path.exists(db_dir): os.makedirs(db_dir, exist_ok=True)
    conn = sqlite3.connect(DB_PATH)
    conn.execute("CREATE TABLE IF NOT EXISTS orders (id INTEGER PRIMARY KEY AUTOINCREMENT, user_id INTEGER, name TEXT, address TEXT, items TEXT, total INTEGER, status TEXT DEFAULT 'Pending', tracking TEXT DEFAULT 'None')")
    conn.close()

def save_order(user_id, name, address, items, total):
    conn = sqlite3.connect(DB_PATH)
    cursor = conn.cursor()
    cursor.execute("INSERT INTO orders (user_id, name, address, items, total) VALUES (?, ?, ?, ?, ?)", (user_id, name, address, items, total))
    order_id = cursor.lastrowid
    conn.commit()
    conn.close()
    return order_id

def update_db_order(order_id, status=None, tracking=None):
    conn = sqlite3.connect(DB_PATH)
    if status: conn.execute("UPDATE orders SET status = ? WHERE id = ?", (status, order_id))
    if tracking: conn.execute("UPDATE orders SET tracking = ? WHERE id = ?", (tracking, order_id))
    conn.commit()
    conn.close()

# -----------------------------
# LOGIC & HANDLERS
# -----------------------------
class CheckoutState(StatesGroup):
    waiting_for_name = State()
    waiting_for_address = State()

class AdminState(StatesGroup):
    waiting_for_tracking_num = State()

dp = Dispatcher(storage=MemoryStorage())
carts = {}

main_kb = ReplyKeyboardMarkup(keyboard=[
    [KeyboardButton(text="🛍 Shop Now")],
    [KeyboardButton(text="🛒 My Cart"), KeyboardButton(text="📦 My Orders")],
    [KeyboardButton(text="❓ Help"), KeyboardButton(text="📞 Contact")]
], resize_keyboard=True)

async def build_shop_kb():
    products = await get_live_products()
    if not products: return None
    rows = []
    sorted_items = sorted(products.items(), key=lambda x: int(x[0].replace("item", "")))
    for pid, p in sorted_items:
        label = f"{p['name']} - £{p['price']}"
        if p["stock"] <= 0: label += " (SOLD OUT)"
        rows.append([InlineKeyboardButton(text=label, callback_data=f"view_{pid}")])
    return InlineKeyboardMarkup(inline_keyboard=rows)

@dp.message(CommandStart())
async def start(m: Message):
    await m.answer("👋 Welcome to the Lumina Store!", reply_markup=main_kb)

@dp.message(F.text == "🛍 Shop Now")
async def shop(m: Message):
    kb = await build_shop_kb()
    if kb: await m.answer("<b>🛍 Product Catalog</b>", reply_markup=kb)
    else: await m.answer("❌ Shop loading...")

# --- FIXED: BACK BUTTON HANDLER ---
@dp.callback_query(F.data == "back_shop")
async def back_to_shop(cb: CallbackQuery):
    await cb.answer()
    kb = await build_shop_kb()
    if kb:
        await cb.message.edit_text("<b>🛍 Product Catalog</b>", reply_markup=kb)

@dp.callback_query(F.data.startswith("view_"))
async def view(cb: CallbackQuery):
    await cb.answer()
    pid = cb.data.split("_", 1)[1]
    products = await get_live_products()
    p = products.get(pid)
    if not p: return
    kb = InlineKeyboardMarkup(inline_keyboard=[
        [InlineKeyboardButton(text="🛒 Add to Cart", callback_data=f"add_{pid}")] if p["stock"] > 0 else [],
        [InlineKeyboardButton(text="⬅ Back", callback_data="back_shop")]
    ])
    await cb.message.edit_text(f"<b>📦 {p['name']}</b>\nPrice: £{p['price']}\nStock: {p['stock']}", reply_markup=kb)

@dp.callback_query(F.data.startswith("add_"))
async def add(cb: CallbackQuery):
    pid, uid = cb.data.split("_", 1)[1], cb.from_user.id
    carts.setdefault(uid, {})[pid] = carts[uid].get(pid, 0) + 1
    await cb.answer("✅ Added to cart!")

@dp.message(F.text == "🛒 My Cart")
async def show_cart(m: Message):
    uid = m.from_user.id
    products = await get_live_products()
    user_cart = carts.get(uid, {})
    if not user_cart: return await m.answer("🛒 Your cart is empty.")
    summary = "\n".join([f"• {products[pid]['name']} x{qty}" for pid, qty in user_cart.items() if pid in products])
    total = sum(products[pid]['price'] * qty for pid, qty in user_cart.items() if pid in products)
    kb = InlineKeyboardMarkup(inline_keyboard=[[InlineKeyboardButton(text="🧾 Checkout", callback_data="start_checkout")], [InlineKeyboardButton(text="🛍 Continue", callback_data="back_shop")]])
    await m.answer(f"🛒 <b>Your Cart</b>\n\n{summary}\n\n💰 <b>Total: £{total}</b>", reply_markup=kb)

@dp.message(F.text == "📦 My Orders")
async def customer_orders(m: Message):
    uid = m.from_user.id
    conn = sqlite3.connect(DB_PATH)
    cursor = conn.cursor()
    cursor.execute("SELECT id, status FROM orders WHERE user_id = ? ORDER BY id DESC LIMIT 5", (uid,))
    rows = cursor.fetchall()
    conn.close()
    if not rows: return await m.answer("No orders yet!")
    buttons = [[InlineKeyboardButton(text=f"🔍 Track #{r[0]} ({r[1]})", callback_data=f"track_{r[0]}")] for r in rows]
    await m.answer("📦 <b>Your Recent Orders:</b>", reply_markup=InlineKeyboardMarkup(inline_keyboard=buttons))

@dp.callback_query(F.data.startswith("track_"))
async def track_detail(cb: CallbackQuery):
    await cb.answer()
    oid = cb.data.split("_")[1]
    conn = sqlite3.connect(DB_PATH)
    cursor = conn.cursor()
    cursor.execute("SELECT status, tracking, items, total FROM orders WHERE id = ?", (oid,))
    row = cursor.fetchone()
    conn.close()
    if row:
        await cb.message.answer(f"<b>📄 Order #{oid}</b>\nStatus: {row[0]}\nTracking: <code>{row[1]}</code>\nItems:\n{row[2]}\nTotal: £{row[3]}")

@dp.callback_query(F.data == "start_checkout")
async def check1(cb: CallbackQuery, state: FSMContext):
    await cb.answer()
    await cb.message.answer("📝 <b>Checkout</b>\nEnter your <b>Full Name</b>:")
    await state.set_state(CheckoutState.waiting_for_name)

@dp.message(CheckoutState.waiting_for_name)
async def check2(m: Message, state: FSMContext):
    await state.update_data(name=m.text)
    await m.answer("📍 Enter <b>Full Address & Postcode</b>:")
    await state.set_state(CheckoutState.waiting_for_address)

@dp.message(CheckoutState.waiting_for_address)
async def check4(m: Message, state: FSMContext):
    data = await state.get_data()
    uid = m.from_user.id
    products = await get_live_products()
    user_cart = carts.get(uid, {})
    summary = "\n".join([f"• {products[pid]['name']} x{qty}" for pid, qty in user_cart.items() if pid in products])
    total = sum(products[pid]['price'] * qty for pid, qty in user_cart.items() if pid in products)
    order_id = save_order(uid, data["name"], m.text, summary, total)
    await m.answer(f"🏁 <b>Order #{order_id} Logged!</b>\n\n{BANK_DETAILS}")
    admin_kb = InlineKeyboardMarkup(inline_keyboard=[[InlineKeyboardButton(text="✅ Paid", callback_data=f"adm_p_{order_id}_{uid}")], [InlineKeyboardButton(text="🚚 Track", callback_data=f"adm_t_{order_id}_{uid}")]])
    await m.bot.send_message(ADMIN_ID, f"🔔 <b>NEW ORDER #{order_id}</b>\n👤 {data['name']}\n\n{summary}\n\nTotal: £{total}", reply_markup=admin_kb)
    if uid in carts: del carts[uid]
    await state.clear()

@dp.callback_query(F.data.startswith("adm_p_"))
async def adm_paid(cb: CallbackQuery):
    _, _, oid, cid = cb.data.split("_")
    update_db_order(oid, status="Paid")
    await cb.bot.send_message(cid, f"✅ <b>Payment Received for Order #{oid}!</b>")
    await cb.answer("Marked Paid")

@dp.callback_query(F.data.startswith("adm_t_"))
async def adm_track(cb: CallbackQuery, state: FSMContext):
    _, _, oid, cid = cb.data.split("_")
    await state.update_data(current_order_id=oid, current_customer_id=cid)
    await state.set_state(AdminState.waiting_for_tracking_num)
    await cb.message.answer(f"📦 Enter Tracking for Order #{oid}:")

@dp.message(AdminState.waiting_for_tracking_num)
async def adm_finish(m: Message, state: FSMContext):
    data = await state.get_data()
    update_db_order(data["current_order_id"], tracking=m.text)
    await m.bot.send_message(data["current_customer_id"], f"🚚 <b>Order #{data['current_order_id']} Shipped!</b>\nTracking: <code>{m.text}</code>")
    await m.answer("✅ Tracking sent!")
    await state.clear()

async def main():
    init_supabase(); init_db()
    bot = Bot(token=TOKEN, default=DefaultBotProperties(parse_mode=ParseMode.HTML))
    await dp.start_polling(bot)

if __name__ == "__main__":
    asyncio.run(main())
