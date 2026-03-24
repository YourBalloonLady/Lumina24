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
    Message, ReplyKeyboardMarkup, KeyboardButton,
    InlineKeyboardMarkup, InlineKeyboardButton, CallbackQuery,
)

# --- CONFIG ---
TOKEN = os.getenv("BOT_TOKEN")
ADMIN_ID = int(os.getenv("ADMIN_ID", 5839927114))
DB_PATH = os.getenv("DATABASE_URL", "/app/data/store.db")
MY_USERNAME = "@Admi_181"
SUPA_URL = os.getenv("SUPABASE_URL")
SUPA_KEY = os.getenv("SUPABASE_KEY")

supabase: Client | None = None
logging.basicConfig(level=logging.INFO)

# --- CATEGORY MAPPING ---
# This maps your Supabase IDs to specific categories
CATEGORIES = {
    "GLP-1 & Weight Loss": ["item3", "item4", "item6", "item7"],
    "Skin & Anti-Aging": ["item5"],
    "Recovery & Healing": ["item1"],
    "Cognitive & Brain": ["item2"]
}

BANK_DETAILS = """
🏦 <b>PAYMENT DETAILS</b>
Bank: Barclays | Name: Lumina | Sort: 20-19-96 | Acc: 63112098
⚠️ <b>IMPORTANT:</b> Use your <b>Order Number</b> or <b>Full Name</b> as reference.
"""

# --- DB & SUPABASE INIT ---
def init_supabase():
    global supabase
    if SUPA_URL and SUPA_KEY: supabase = create_client(SUPA_URL, SUPA_KEY)

async def get_live_products():
    if not supabase: return {}
    try:
        res = supabase.table("products").select("*").execute()
        return {p["id"]: p for p in res.data}
    except: return {}

def init_db():
    conn = sqlite3.connect(DB_PATH)
    conn.execute("CREATE TABLE IF NOT EXISTS orders (id INTEGER PRIMARY KEY AUTOINCREMENT, user_id INTEGER, name TEXT, address TEXT, items TEXT, total INTEGER, status TEXT DEFAULT 'Pending', tracking TEXT DEFAULT 'None')")
    conn.close()

# --- KEYBOARDS ---
main_kb = ReplyKeyboardMarkup(keyboard=[
    [KeyboardButton(text="🛍 Shop Now")],
    [KeyboardButton(text="🛒 My Cart"), KeyboardButton(text="📦 My Orders")],
    [KeyboardButton(text="❓ Help"), KeyboardButton(text="📞 Contact")]
], resize_keyboard=True)

def build_category_kb():
    buttons = [[InlineKeyboardButton(text=cat, callback_data=f"cat_{cat}")] for cat in CATEGORIES.keys()]
    buttons.append([InlineKeyboardButton(text="🛒 View Cart", callback_data="view_cart")])
    return InlineKeyboardMarkup(inline_keyboard=buttons)

async def build_item_kb(category_name):
    products = await get_live_products()
    item_ids = CATEGORIES.get(category_name, [])
    rows = []
    for pid in item_ids:
        p = products.get(pid)
        if p:
            label = f"{p['name']} - £{p['price']}"
            if p['stock'] <= 0: label += " (OUT)"
            rows.append([InlineKeyboardButton(text=label, callback_data=f"view_{pid}")])
    rows.append([InlineKeyboardButton(text="⬅ Back to Categories", callback_data="back_to_cats")])
    return InlineKeyboardMarkup(inline_keyboard=rows)

# --- HANDLERS ---
dp = Dispatcher(storage=MemoryStorage())
carts = {}

@dp.message(CommandStart())
async def start(m: Message):
    await m.answer("👋 Welcome to Lumina Store!", reply_markup=main_kb)

@dp.message(F.text == "🛍 Shop Now")
async def shop(m: Message):
    await m.answer("<b>📂 Select a Category:</b>", reply_markup=build_category_kb())

@dp.callback_query(F.data == "back_to_cats")
async def back_to_cats(cb: CallbackQuery):
    await cb.answer()
    await cb.message.edit_text("<b>📂 Select a Category:</b>", reply_markup=build_category_kb())

@dp.callback_query(F.data.startswith("cat_"))
async def show_category_items(cb: CallbackQuery):
    category = cb.data.split("_", 1)[1]
    kb = await build_item_kb(category)
    await cb.message.edit_text(f"<b>📦 {category}</b>", reply_markup=kb)
    await cb.answer()

@dp.callback_query(F.data.startswith("view_"))
async def view_item(cb: CallbackQuery):
    pid = cb.data.split("_", 1)[1]
    products = await get_live_products()
    p = products.get(pid)
    if not p: return
    
    # Find which category this item belongs to for the back button
    parent_cat = next((cat for cat, ids in CATEGORIES.items() if pid in ids), "GLP-1 & Weight Loss")
    
    kb = InlineKeyboardMarkup(inline_keyboard=[
        [InlineKeyboardButton(text="🛒 Add to Cart", callback_data=f"add_{pid}")] if p['stock'] > 0 else [],
        [InlineKeyboardButton(text="⬅ Back", callback_data=f"cat_{parent_cat}")]
    ])
    await cb.message.edit_text(f"<b>{p['name']}</b>\nPrice: £{p['price']}\nStock: {p['stock']}", reply_markup=kb)
    await cb.answer()

@dp.callback_query(F.data.startswith("add_"))
async def add_to_cart(cb: CallbackQuery):
    pid, uid = cb.data.split("_", 1)[1], cb.from_user.id
    carts.setdefault(uid, {})[pid] = carts[uid].get(pid, 0) + 1
    await cb.answer("✅ Added!")

@dp.message(F.text == "🛒 My Cart")
async def view_cart(m: Message):
    uid = m.from_user.id
    user_cart = carts.get(uid, {})
    if not user_cart: return await m.answer("Your cart is empty.")
    
    products = await get_live_products()
    summary = "\n".join([f"• {products[pid]['name']} x{qty}" for pid, qty in user_cart.items() if pid in products])
    total = sum(products[pid]['price'] * qty for pid, qty in user_cart.items() if pid in products)
    
    kb = InlineKeyboardMarkup(inline_keyboard=[
        [InlineKeyboardButton(text="💳 Checkout", callback_data="start_checkout")],
        [InlineKeyboardButton(text="🛍 Continue Shopping", callback_data="back_to_cats")]
    ])
    await m.answer(f"🛒 <b>Your Cart</b>\n\n{summary}\n\n<b>Total: £{total}</b>", reply_markup=kb)

# [Keeping My Orders, Checkout, and Admin logic the same as the last version...]
# Make sure to include the customer_orders and admin handlers from previous blocks here.

async def main():
    init_supabase(); init_db()
    bot = Bot(token=TOKEN, default=DefaultBotProperties(parse_mode=ParseMode.HTML))
    await dp.start_polling(bot)

if __name__ == "__main__":
    asyncio.run(main())
