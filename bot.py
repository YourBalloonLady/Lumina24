import os, asyncio, logging
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
BANK_DETAILS = """🏦 <b>PAYMENT DETAILS</b>\nBank: Barclays\nSort: 20-19-96\nAcc: 63112098\n⚠️ Reference: <b>Order Number</b> or <b>Full Name</b>"""

class Checkout(StatesGroup):
    name = State()
    street = State()
    city = State()
    postcode = State()

dp = Dispatcher(storage=MemoryStorage())

# --- NAVIGATION ---
@dp.message(F.text == "/start")
async def cmd_start(m: Message):
    await m.answer("👋 Welcome to Lumina Store!", reply_markup=kb.main_kb)

@dp.message(F.text == "🛍 Shop Now")
async def shop(m: Message):
    await m.answer("<b>📂 Select a Category:</b>", reply_markup=kb.category_kb())

# --- THE CHECKOUT FLOW (AS PER SCREENSHOTS) ---
@dp.callback_query(F.data == "start_checkout")
async def start_checkout(cb: CallbackQuery, state: FSMContext):
    await cb.answer()
    profile = db.get_profile(cb.from_user.id)
    if profile:
        text = f"📋 <b>Checkout</b>\n━━━━━━━━━━━━━━\n🚚 <b>FREE Shipping</b>\n📍 <b>Saved Address:</b>\n👤 {profile[0]}\n🏠 {profile[1]}\n🏙 {profile[2]}\n📮 {profile[3]}\n\nShip to this address?"
        btns = [[InlineKeyboardButton(text="✅ Use This Address", callback_data="use_saved")],
                [InlineKeyboardButton(text="📝 New Address", callback_data="ask_name")],
                [InlineKeyboardButton(text="❌ Cancel", callback_data="view_cart")]]
        await cb.message.edit_text(text, reply_markup=InlineKeyboardMarkup(inline_keyboard=btns))
    else:
        await ask_name(cb.message, state)

@dp.callback_query(F.data == "ask_name")
async def ask_name_cb(cb: CallbackQuery, state: FSMContext):
    await cb.answer()
    await ask_name(cb.message, state)

async def ask_name(m: Message, state: FSMContext):
    await m.answer("📋 <b>Step 2 — Full Name</b>\nPlease type your full name:")
    await state.set_state(Checkout.name)

@dp.message(Checkout.name)
async def get_name(m: Message, state: FSMContext):
    await state.update_data(name=m.text)
    await m.answer("🏠 <b>Step 3 — Street Address</b>\nEnter your house number and street:")
    await state.set_state(Checkout.street)

@dp.message(Checkout.street)
async def get_street(m: Message, state: FSMContext):
    await state.update_data(street=m.text)
    await m.answer("🏙 <b>Step 4 — City</b>\nEnter your city or town:")
    await state.set_state(Checkout.city)

@dp.message(Checkout.city)
async def get_city(m: Message, state: FSMContext):
    await state.update_data(city=m.text)
    await m.answer("📮 <b>Step 5 — Postcode</b>\nEnter your UK postcode:")
    await state.set_state(Checkout.postcode)

@dp.message(Checkout.postcode)
async def finalize_address(m: Message, state: FSMContext):
    data = await state.get_data()
    db.save_profile(m.from_user.id, data['name'], data['street'], data['city'], m.text)
    await show_summary(m, state, data['name'], f"{data['street']}, {data['city']} {m.text}")

@dp.callback_query(F.data == "use_saved")
async def use_saved_addr(cb: CallbackQuery, state: FSMContext):
    await cb.answer()
    p = db.get_profile(cb.from_user.id)
    await show_summary(cb.message, state, p[0], f"{p[1]}, {p[2]} {p[3]}")

async def show_summary(m, state, name, full_addr):
    uid = m.chat.id # Use chat.id as callback and message share different structures
    cart = db.get_user_cart(uid)
    products = await db.get_live_products()
    
    items_text = "\n".join([f"• {products[pid]['name']} ×{qty}" for pid, qty in cart.items() if pid in products])
    total = sum(products[pid]['price'] * qty for pid, qty in cart.items() if pid in products)

    summary = (f"📋 <b>Order Summary</b>\n"
               f"━━━━━━━━━━━━━━\n"
               f"👤 <b>{name}</b>\n📍 {full_addr}\n\n"
               f"🧬 <b>Items</b>\n{items_text}\n\n"
               f"🚚 <b>FREE Shipping</b>\n"
               f"━━━━━━━━━━━━━━\n"
               f"💰 <b>Total: £{total:.2f}</b>\n\n"
               f"Please confirm to proceed to payment.")
    
    btns = [[InlineKeyboardButton(text="✅ Confirm & Pay", callback_data="finish_order")],
            [InlineKeyboardButton(text="❌ Cancel", callback_data="back_to_cats")]]
    
    await m.answer(summary, reply_markup=InlineKeyboardMarkup(inline_keyboard=btns))
    await state.update_data(final_name=name, final_addr=full_addr, final_total=total, final_items=items_text)

@dp.callback_query(F.data == "finish_order")
async def finish_order(cb: CallbackQuery, state: FSMContext):
    await cb.answer()
    data = await state.get_data()
    uid = cb.from_user.id
    cart = db.get_user_cart(uid)

    # 1. Stock & DB
    db.deduct_supabase_stock(cart)
    oid = db.save_order(uid, data['final_name'], data['final_addr'], data['final_items'], data['final_total'])
    
    # 2. Customer Notify
    await cb.message.edit_text(f"🏁 <b>Order #{oid} Logged!</b>\n\n{BANK_DETAILS}")
    
    # 3. Admin Notify
    admin_kb = InlineKeyboardMarkup(inline_keyboard=[
        [InlineKeyboardButton(text="✅ Paid", callback_data=f"adm_p_{oid}_{uid}")], 
        [InlineKeyboardButton(text="🚚 Track", callback_data=f"adm_t_{oid}_{uid}")]
    ])
    await cb.bot.send_message(ADMIN_ID, f"🔔 <b>NEW ORDER #{oid}</b>\n👤 {data['final_name']}\n📍 {data['final_addr']}\n\n{data['final_items']}\n\nTotal: £{data['final_total']}", reply_markup=admin_kb)
    
    db.clear_cart(uid)
    await state.clear()

# --- ADMIN FUNCTIONS REMAIN THE SAME ---
@dp.callback_query(F.data.startswith("adm_p_"))
async def admin_paid(cb: CallbackQuery):
    _, _, oid, cid = cb.data.split("_")
    db.update_db_order(oid, status="Paid")
    await cb.bot.send_message(cid, f"✅ <b>Payment Received for Order #{oid}!</b>")
    await cb.answer("Marked Paid")

# (Add other handlers for tracking and view_cart as before)

async def main():
    db.init_db()
    bot = Bot(token=TOKEN, default=DefaultBotProperties(parse_mode=ParseMode.HTML))
    await dp.start_polling(bot)

if __name__ == "__main__":
    asyncio.run(main())
