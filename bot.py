import os
import logging
from supabase import create_

SUPA_URL = os.getenv("SUPA_URL")
SUPA_KEY = os.getenv("SUPA_KEY")

supabase = None

try:
    if not SUPA_URL or not SUPA_KEY:
        raise ValueError("Missing SUPA_URL or SUPA_KEY")

    supabase = create_client(SUPA_URL, SUPA_KEY)
    logging.info("✅ Supabase connected")
except Exception as e:
    logging.error(f"❌ Supabase init failed: {e}")
    supabase = None

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
from aiogram..default import DefaultBotProperties
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

supabase:  | None = None

logging.basicConfig(level=logging.INFO)

BANK_DETAILS = """
🏦 <b>PAYMENT DETAILS</b>

Bank: Barclays
Account Name: Lumina
Sort Code: 20-19-96
Account Number: 63112098

⚠️ <b>IMPORTANT:</b> Use your <b>Order Number</b> or <b>Full Name</b> as the reference.
"""

# -----------------------------
# SUPABASE
# -----------------------------
def init_supabase():
    global supabase
    if not SUPA_URL or not SUPA_KEY:
        logging.error("❌ SUPABASE_URL or SUPABASE_KEY missing")
        return
    try:
        supabase = create_(SUPA_URL, SUPA_KEY)
        logging.info("✅ Supabase connected")
    except Exception as e:
        logging.error(f"❌ Supabase init failed: {e}")
        supabase = None

async def get_live_products():
    if not supabase:
        logging.error("❌ Supabase not available")
        return {}

    try:
        response = supabase.table("products").select("*").execute()
        return {
            p["id"]: {
                "name": p["name"],
                "price": p["price"],
                "stock": p["stock"],
            }
            for p in response.data
        }
    except Exception as e:
        logging.error(f"❌ Failed to fetch products: {e}")
        return {}

def update_supabase_stock(pid, new_stock):
    try:
        supabase.table("products").update({"stock": new_stock}).eq("id", pid).execute()
    except Exception as e:
        logging.error(f"❌ Failed to update stock for {pid}: {e}")

# -----------------------------
# DATABASE
# -----------------------------
def init_db():
    try:
        db_dir = os.path.dirname(DB_PATH)
        if db_dir and not os.path.exists(db_dir):
            os.makedirs(db_dir, exist_ok=True)

        conn = sqlite3.connect(DB_PATH)
        cursor = conn.cursor()

        cursor.execute("""
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
        """)

        conn.commit()
        conn.close()
    except Exception as e:
        logging.error(f"Database error: {e}")

def save_order(user_id, name, address, items, total):
    conn = sqlite3.connect(DB_PATH)
    cursor = conn.cursor()
    cursor.execute(
        "INSERT INTO orders (user_id, name, address, items, total) VALUES (?, ?, ?, ?, ?)",
        (user_id, name, address, items, total),
    )
    order_id = cursor.lastrowid
    conn.commit()
    conn.close()
    return order_id

def update_db_order(order_id, status=None, tracking=None):
    conn = sqlite3.connect(DB_PATH)
    cursor = conn.cursor()

    if status:
        cursor.execute("UPDATE orders SET status = ? WHERE id = ?", (status, order_id))
    if tracking:
        cursor.execute("UPDATE orders SET tracking = ? WHERE id = ?", (tracking, order_id))

    conn.commit()
    conn.close()

def get_order_items(order_id):
    conn = sqlite3.connect(DB_PATH)
    cursor = conn.cursor()
    cursor.execute("SELECT items FROM orders WHERE id = ?", (order_id,))
    row = cursor.fetchone()
    conn.close()
    return row[0] if row else ""

# -----------------------------
# INIT
# -----------------------------
init_db()
dp = Dispatcher(storage=MemoryStorage())
carts = {}

# -----------------------------
# STATES
# -----------------------------
class CheckoutState(StatesGroup):
    waiting_for_name = State()
    waiting_for_address = State()
    waiting_for_postcode = State()

class AdminState(StatesGroup):
    waiting_for_tracking_num = State()

# -----------------------------
# KEYBOARDS
# -----------------------------
main_kb = ReplyKeyboardMarkup(
    keyboard=[
        [KeyboardButton(text="🛍 Shop Now")],
        [KeyboardButton(text="🛒 My Cart")],
        [KeyboardButton(text="❓ Help"), KeyboardButton(text="📞 Contact")],
    ],
    resize_keyboard=True,
)

async def build_shop_kb():
    products = await get_live_products()
    if not products:
        return None

    rows = []
    sorted_items = sorted(products.items(), key=lambda x: int(x[0].replace("item", "")))

    for pid, p in sorted_items:
        label = f"{p['name']} - £{p['price']}"
        if p["stock"] <= 0:
            label += " (SOLD OUT)"
        rows.append([InlineKeyboardButton(text=label, callback_data=f"view_{pid}")])

    rows.append([InlineKeyboardButton(text="🛒 View Cart", callback_data="view_cart")])
    return InlineKeyboardMarkup(inline_keyboard=rows)

def build_product_kb(pid: str, in_stock: bool):
    rows = []

    if in_stock:
        rows.append([InlineKeyboardButton(text="🛒 Add to Cart", callback_data=f"add_{pid}")])

    rows.append([InlineKeyboardButton(text="⬅ Back", callback_data="back_shop")])
    rows.append([InlineKeyboardButton(text="🛒 View Cart", callback_data="view_cart")])

    return InlineKeyboardMarkup(inline_keyboard=rows)

def build_cart_kb(uid: int):
    user_cart = carts.get(uid, {})
    rows = []

    for pid in user_cart.keys():
        rows.append([
            InlineKeyboardButton(text=f"❌ Remove {pid}", callback_data=f"remove_{pid}")
        ])

    if user_cart:
        rows.append([InlineKeyboardButton(text="🧾 Checkout", callback_data="start_checkout")])

    rows.append([InlineKeyboardButton(text="🛍 Continue Shopping", callback_data="back_shop")])
    return InlineKeyboardMarkup(inline_keyboard=rows)

# -----------------------------
# HELPERS
# -----------------------------
async def get_cart_summary(uid):
    user_cart = carts.get(uid, {})
    if not user_cart:
        return "Empty", 0

    products = await get_live_products()
    lines = []
    total = 0

    for pid, qty in user_cart.items():
        p = products.get(pid)
        if not p:
            continue
        lines.append(f"• {p['name']} x{qty} — £{p['price'] * qty}")
        total += p["price"] * qty

    if not lines:
        return "Empty", 0

    return "\n".join(lines), total

# -----------------------------
# HANDLERS
# -----------------------------
@dp.message(CommandStart())
async def start(m: Message):
    await m.answer("👋 Welcome to JJS Store!", reply_markup=main_kb)

@dp.message(F.text == "🛍 Shop Now")
async def shop(m: Message):
    kb = await build_shop_kb()
    if kb:
        await m.answer("<b>🛍 Product Catalog</b>", reply_markup=kb)
    else:
        await m.answer("❌ The shop is currently empty or loading. Try again in a second!")

@dp.callback_query(F.data.startswith("view_"))
async def view(cb: CallbackQuery):
    await cb.answer()
    pid = cb.data.split("_", 1)[1]

    products = await get_live_products()
    p = products.get(pid)
    if not p:
        await cb.message.answer("❌ Product not found.")
        return

    stock_status = f"✅ In Stock ({p['stock']})" if p["stock"] > 0 else "❌ OUT OF STOCK"

    await cb.message.edit_text(
        f"<b>📦 {p['name']}</b>\nPrice: £{p['price']}\nStatus: {stock_status}",
        reply_markup=build_product_kb(pid, p["stock"] > 0),
    )

@dp.callback_query(F.data == "back_shop")
async def back_to_shop(cb: CallbackQuery):
    await cb.answer()
    kb = await build_shop_kb()
    if kb:
        await cb.message.edit_text("<b>🛍 Product Catalog</b>", reply_markup=kb)

@dp.callback_query(F.data.startswith("add_"))
async def add(cb: CallbackQuery):
    await cb.answer()
    pid = cb.data.split("_", 1)[1]
    uid = cb.from_user.id

    products = await get_live_products()
    p = products.get(pid)

    if not p or p["stock"] <= 0:
        await cb.answer("❌ Out of stock!", show_alert=True)
        return

    carts.setdefault(uid, {})
    carts[uid][pid] = carts[uid].get(pid, 0) + 1

    summary, total = await get_cart_summary(uid)
    await cb.message.answer(
        f"✅ Item added to cart!\n\n{summary}\n\n💰 <b>Total: £{total}</b>",
        reply_markup=build_cart_kb(uid),
    )

@dp.callback_query(F.data.startswith("remove_"))
async def remove_item(cb: CallbackQuery):
    await cb.answer()
    uid = cb.from_user.id
    pid = cb.data.split("_", 1)[1]

    if uid in carts and pid in carts[uid]:
        del carts[uid][pid]
        if not carts[uid]:
            del carts[uid]
            await cb.message.edit_text("🛒 Your cart is empty.")
            return

    summary, total = await get_cart_summary(uid)
    await cb.message.edit_text(
        f"🛒 <b>Your Cart</b>\n\n{summary}\n\n💰 <b>Total: £{total}</b>",
        reply_markup=build_cart_kb(uid),
    )

@dp.callback_query(F.data == "view_cart")
async def view_cart(cb: CallbackQuery):
    await cb.answer()
    uid = cb.from_user.id
    summary, total = await get_cart_summary(uid)

    if total <= 0:
        await cb.message.edit_text("🛒 Your cart is empty.")
        return

    await cb.message.edit_text(
        f"🛒 <b>Your Cart</b>\n\n{summary}\n\n💰 <b>Total: £{total}</b>",
        reply_markup=build_cart_kb(uid),
    )

@dp.message(F.text == "🛒 My Cart")
async def show_cart(m: Message):
    summary, total = await get_cart_summary(m.from_user.id)

    if total <= 0:
        await m.answer("🛒 Your cart is empty.")
        return

    await m.answer(
        f"🛒 <b>Your Cart</b>\n\n{summary}\n\n💰 <b>Total: £{total}</b>",
        reply_markup=build_cart_kb(m.from_user.id),
    )

@dp.message(F.text == "❓ Help")
async def help_handler(m: Message):
    await m.answer("Use Shop Now to browse items and My Cart to review selections.")

@dp.message(F.text == "📞 Contact")
async def contact_handler(m: Message):
    await m.answer(f"Support: {MY_USERNAME}")

# -----------------------------
# CHECKOUT
# -----------------------------
@dp.callback_query(F.data == "start_checkout")
async def check1(cb: CallbackQuery, state: FSMContext):
    await cb.answer()

    uid = cb.from_user.id
    summary, total = await get_cart_summary(uid)

    if total <= 0:
        await cb.message.answer("🛒 Your cart is empty.")
        return

    await cb.message.answer("📝 <b>Checkout</b>\nPlease enter your <b>Full Name</b>:")
    await state.set_state(CheckoutState.waiting_for_name)

@dp.message(CheckoutState.waiting_for_name)
async def check2(m: Message, state: FSMContext):
    await state.update_data(name=m.text.strip())
    await m.answer("📍 Please enter your <b>Full Delivery Address</b>:")
    await state.set_state(CheckoutState.waiting_for_address)

@dp.message(CheckoutState.waiting_for_address)
async def check3(m: Message, state: FSMContext):
    await state.update_data(address=m.text.strip())
    await m.answer("📮 Please enter your <b>Postcode</b>:")
    await state.set_state(CheckoutState.waiting_for_postcode)

@dp.message(CheckoutState.waiting_for_postcode)
async def check4(m: Message, state: FSMContext):
    data = await state.get_data()
    uid = m.from_user.id
    summary, total = await get_cart_summary(uid)

    if total <= 0:
        await m.answer("🛒 Your cart is empty.")
        await state.clear()
        return

    full_address = f"{data['address']}, {m.text.strip()}"

    order_id = save_order(uid, data["name"], full_address, summary, total)

    await m.answer(
        f"🏁 <b>Order #{order_id} Logged!</b>\n\n"
        f"{summary}\n\n"
        f"💰 <b>Total: £{total}</b>\n\n"
        f"{BANK_DETAILS}"
    )

    admin_kb = InlineKeyboardMarkup(
        inline_keyboard=[
            [InlineKeyboardButton(text="✅ Mark Paid", callback_data=f"adm_p_{order_id}_{uid}")],
            [InlineKeyboardButton(text="🚚 Add Tracking", callback_data=f"adm_t_{order_id}_{uid}")],
        ]
    )

    await m.bot.send_message(
        ADMIN_ID,
        f"🔔 <b>NEW ORDER #{order_id}</b>\n"
        f"👤 {data['name']}\n"
        f"📍 {full_address}\n\n"
        f"{summary}\n\n"
        f"💰 <b>Total: £{total}</b>",
        reply_markup=admin_kb,
    )

    if uid in carts:
        del carts[uid]

    await state.clear()

# -----------------------------
# ADMIN
# -----------------------------
@dp.message(Command("stock"))
async def admin_stock_check(m: Message):
    if m.from_user.id != ADMIN_ID:
        return

    products = await get_live_products()
    if not products:
        await m.answer("Inventory empty or failed to load.")
        return

    sorted_p = sorted(products.items(), key=lambda x: int(x[0].replace("item", "")))

    report = "📊 <b>Live Inventory Report</b>\n\n"
    for pid, p in sorted_p:
        status = "🟢" if p["stock"] > 5 else "🟡" if p["stock"] > 0 else "🔴"
        report += f"{status} <code>{pid}</code>: {p['name']} | <b>{p['stock']}</b> left\n"

    await m.answer(report)

@dp.message(Command("admin_orders"))
async def view_orders(m: Message):
    if m.from_user.id != ADMIN_ID:
        return

    conn = sqlite3.connect(DB_PATH)
    cursor = conn.cursor()
    cursor.execute("SELECT id, name, total, status FROM orders ORDER BY id DESC LIMIT 10")
    orders = cursor.fetchall()
    conn.close()

    if not orders:
        await m.answer("No orders found.")
        return

    text = "📊 <b>Last 10 Orders:</b>\n\n" + "\n".join(
        [f"#{o[0]} | {o[1]} | £{o[2]} | {o[3]}" for o in orders]
    )
    await m.answer(text)

@dp.callback_query(F.data.startswith("adm_p_"))
async def adm_paid(cb: CallbackQuery):
    await cb.answer()

    _, _, oid, cid = cb.data.split("_")
    update_db_order(oid, status="Paid")

    # Reduce stock only after marked paid
    conn = sqlite3.connect(DB_PATH)
    cursor = conn.cursor()
    cursor.execute("SELECT items FROM orders WHERE id = ?", (oid,))
    row = cursor.fetchone()
    conn.close()

    products = await get_live_products()
    if row and products:
        items_text = row[0]
        for pid, p in products.items():
            marker = f"• {p['name']} x"
            if marker in items_text:
                try:
                    qty_text = items_text.split(marker)[1].split("—")[0].strip()
                    qty = int(qty_text)
                    new_stock = max(0, p["stock"] - qty)
                    update_supabase_stock(pid, new_stock)
                except Exception:
                    pass

    await cb.bot.send_message(cid, f"✅ <b>Payment Received for Order #{oid}!</b>")
    await cb.message.answer(f"✅ Order #{oid} marked Paid")

@dp.callback_query(F.data.startswith("adm_t_"))
async def adm_track(cb: CallbackQuery, state: FSMContext):
    await cb.answer()

    _, _, oid, cid = cb.data.split("_")
    await state.update_data(current_order_id=oid, current_customer_id=cid)
    await state.set_state(AdminState.waiting_for_tracking_num)
    await cb.message.answer(f"📦 Enter Tracking Number for Order #{oid}:")

@dp.message(AdminState.waiting_for_tracking_num)
async def adm_finish(m: Message, state: FSMContext):
    if m.from_user.id != ADMIN_ID:
        return

    data = await state.get_data()
    update_db_order(data["current_order_id"], tracking=m.text.strip())

    await m.bot.send_message(
        data["current_customer_id"],
        f"🚚 <b>Order #{data['current_order_id']} Shipped!</b>\nTracking: <code>{m.text.strip()}</code>",
    )
    await m.answer("✅ Tracking sent!")
    await state.clear()

# -----------------------------
# RUN
# -----------------------------
async def main():
    init_supabase()
    bot = Bot(
        token=TOKEN,
        default=DefaultBotProperties(parse_mode=ParseMode.HTML),
    )
    await dp.start_polling(bot)

if __name__ == "__main__":
    asyncio.run(main())
