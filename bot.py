import os, asyncio, logging
import sqlite3
from aiogram import Bot, Dispatcher, F
from aiogram.fsm.storage.memory import MemoryStorage
from aiogram.enums import ParseMode
from aiogram.client.default import DefaultBotProperties
from aiogram.types import Message, CallbackQuery, InlineKeyboardMarkup, InlineKeyboardButton
from aiogram.fsm.state import State, StatesGroup
from aiogram.fsm.context import FSMContext

import database as db
import keyboards as kb

TOKEN = os.getenv("BOT_TOKEN")
ADMIN_ID = int(os.getenv("ADMIN_ID", 5839927114))
DB_PATH = os.getenv("DATABASE_URL", "store.db")
BANK_DETAILS = """🏦 <b>PAYMENT DETAILS</b>\nBank: Barclays\nSort: 20-19-96\nAcc: 63112098\n⚠️ Reference: <b>Order Number</b> or <b>Full Name</b>"""

class CheckoutState(StatesGroup):
    waiting_for_name = State()
    waiting_for_address = State()

class AdminState(StatesGroup):
    waiting_for_tracking = State()

dp = Dispatcher(storage=MemoryStorage())

# --- COMMANDS ---
@dp.message(F.text == "/start")
async def cmd_start(m: Message):
    await m.answer("👋 Welcome to Lumina Store!", reply_markup=kb.main_kb)

@dp.message(F.text == "🛍 Shop Now")
async def shop(m: Message):
    await m.answer("<b>📂 Select a Category:</b>", reply_markup=kb.category_kb())

# --- SHOPPING & NAVIGATION ---
@dp.callback_query(F.data == "back_to_cats")
async def back_cats(cb: CallbackQuery):
    await cb.answer() # FIXES LAG
    await cb.message.edit_text("<b>📂 Select a Category:</b>", reply_markup=kb.category_kb())

@dp.callback_query(F.data.startswith("cat_"))
async def show_items(cb: CallbackQuery):
    await cb.answer() # FIXES LAG
    cat = cb.data.split("_", 1)[1]
    products = await db.get_live_products()
    await cb.message.edit_text(f"<b>📦 {cat}</b>", reply_markup=kb.item_list_kb(products, cat))

@dp.callback_query(F.data.startswith("view_"))
async def view_item(cb: CallbackQuery):
    await cb.answer() # FIXES LAG
    pid = cb.data.split("_", 1)[1]
    products = await db.get_live_products()
    p = products.get(pid)
    if not p: return
    
    parent_cat = next((cat for cat, ids in kb.CATEGORIES.items() if pid in ids), "back_to_cats")
    inline_kb = InlineKeyboardMarkup(inline_keyboard=[
        [InlineKeyboardButton(text="🛒 Add to Cart", callback_data=f"qty_plus_{pid}")] if p['stock'] > 0 else [],
        [InlineKeyboardButton(text="⬅ Back", callback_data=f"cat_{parent_cat}")]
    ])
    await cb.message.edit_text(f"<b>{p['name']}</b>\nPrice: £{p['price']}\nStock: {p['stock']}", reply_markup=inline_kb)

# --- CART LOGIC ---
@dp.callback_query(F.data.startswith("qty_"))
async def change_qty(cb: CallbackQuery):
    _, action, pid = cb.data.split("_")
    db.update_cart(cb.from_user.id, pid, 1 if action == "plus" else -1)
    await cb.answer("Cart Updated!") # FIXES LAG
    
    # Update view if currently in cart
    if "Your Cart" in cb.message.text:
        products = await db.get_live_products()
        cart = db.get_user_cart(cb.from_user.id)
        if not cart:
            await cb.message.edit_text("🛒 Your cart is empty.", reply_markup=kb.category_kb())
        else:
            await cb.message.edit_reply_markup(reply_markup=kb.cart_edit_kb(products, cart))

@dp.message(F.text == "🛒 My Cart")
@dp.callback_query(F.data == "view_cart")
async def view_cart(event):
    uid = event.from_user.id
    cart = db.get_user_cart(uid)
    if not cart:
        msg = "🛒 Your cart is empty."
        if isinstance(event, Message): await event.answer(msg)
        else: 
            await event.answer()
            await event.message.edit_text(msg, reply_markup=kb.category_kb())
        return
        
    products = await db.get_live_products()
    total = sum(products[pid]['price'] * qty for pid, qty in cart.items() if pid in products)
    text = f"🛒 <b>Your Cart</b>\n\nTotal: <b>£{total}</b>"
    
    if isinstance(event, Message): await event.answer(text, reply_markup=kb.cart_edit_kb(products, cart))
    else: 
        await event.answer()
        await event.message.edit_text(text, reply_markup=kb.cart_edit_kb(products, cart))

# --- MY ORDERS (FIXED) ---
@dp.message(F.text == "📦 My Orders")
async def customer_orders(m: Message):
    uid = m.from_user.id
    conn = sqlite3.connect(DB_PATH)
    cursor = conn.cursor()
    cursor.execute("SELECT id, status FROM orders WHERE user_id = ? ORDER BY id DESC LIMIT 5", (uid,))
    rows = cursor.fetchall()
    conn.close()
    if not rows: return await m.answer("You haven't placed any orders yet!")
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
        await cb.message.answer(f"<b>📄 Order #{oid} Details</b>\n\nStatus: {row[0]}\nTracking: <code>{row[1]}</code>\n\nItems:\n{row[2]}\nTotal: £{row[3]}")

# --- CHECKOUT & ADMIN ---
@dp.callback_query(F.data == "start_checkout")
async def checkout_start(cb: CallbackQuery, state: FSMContext):
    await cb.answer()
    await cb.message.answer("📝 Enter your <b>Full Name</b>:")
    await state.set_state(CheckoutState.waiting_for_name)

@dp.message(CheckoutState.waiting_for_name)
async def checkout_name(m: Message, state: FSMContext):
    await state.update_data(name=m.text)
    await m.answer("📍 Enter <b>Full Address & Postcode</b>:")
    await state.set_state(CheckoutState.waiting_for_address)

@dp.message(CheckoutState.waiting_for_address)
async def checkout_finish(m: Message, state: FSMContext):
    data = await state.get_data()
    uid = m.from_user.id
    products = await db.get_live_products()
    cart = db.get_user_cart(uid)
    summary = "\n".join([f"• {products[pid]['name']} x{qty}" for pid, qty in cart.items() if pid in products])
    total = sum(products[pid]['price'] * qty for pid, qty in cart.items() if pid in products)
    oid = db.save_order(uid, data['name'], m.text, summary, total)
    
    await m.answer(f"🏁 <b>Order #{oid} Logged!</b>\n\n{BANK_DETAILS}")
    admin_kb = InlineKeyboardMarkup(inline_keyboard=[[InlineKeyboardButton(text="✅ Paid", callback_data=f"adm_p_{oid}_{uid}")], [InlineKeyboardButton(text="🚚 Track", callback_data=f"adm_t_{oid}_{uid}")]])
    await m.bot.send_message(ADMIN_ID, f"🔔 <b>NEW ORDER #{oid}</b>\n👤 {data['name']}\n📍 {m.text}\n\n{summary}\n\nTotal: £{total}", reply_markup=admin_kb)
    db.clear_cart(uid)
    await state.clear()

@dp.callback_query(F.data.startswith("adm_p_"))
async def admin_paid(cb: CallbackQuery):
    _, _, oid, cid = cb.data.split("_")
    conn = sqlite3.connect(DB_PATH)
    conn.execute("UPDATE orders SET status = 'Paid' WHERE id = ?", (oid,))
    conn.commit(); conn.close()
    await cb.bot.send_message(cid, f"✅ <b>Payment Received for Order #{oid}!</b>")
    await cb.answer("Notified customer")

@dp.callback_query(F.data.startswith("adm_t_"))
async def admin_track_start(cb: CallbackQuery, state: FSMContext):
    await cb.answer()
    _, _, oid, cid = cb.data.split("_")
    await state.update_data(oid=oid, cid=cid)
    await cb.message.answer(f"📦 Enter Tracking for Order #{oid}:")
    await state.set_state(AdminState.waiting_for_tracking)

@dp.message(AdminState.waiting_for_tracking)
async def admin_track_finish(m: Message, state: FSMContext):
    data = await state.get_data()
    conn = sqlite3.connect(DB_PATH)
    conn.execute("UPDATE orders SET tracking = ? WHERE id = ?", (m.text, data["oid"]))
    conn.commit(); conn.close()
    await m.bot.send_message(data['cid'], f"🚚 <b>Order #{data['oid']} Shipped!</b>\nTracking: <code>{m.text}</code>")
    await m.answer("✅ Tracking sent!")
    await state.clear()

async def main():
    db.init_db()
    bot = Bot(token=TOKEN, default=DefaultBotProperties(parse_mode=ParseMode.HTML))
    await dp.start_polling(bot)

if __name__ == "__main__":
    asyncio.run(main())
