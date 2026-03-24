import os
import asyncio
import logging

from aiogram import Bot, Dispatcher, F
from aiogram.filters import CommandStart
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

BANK_DETAILS = (
    "🏦 <b>PAYMENT DETAILS</b>\n"
    "Bank: Barclays\n"
    "Sort: 20-19-96\n"
    "Acc: 63112098\n"
    "⚠️ Reference: <b>Order Number</b> or <b>Full Name</b>"
)

logging.basicConfig(level=logging.INFO)

class Checkout(StatesGroup):
    name = State()
    street = State()
    city = State()
    postcode = State()

dp = Dispatcher(storage=MemoryStorage())

# --- NAVIGATION ---
@dp.message(CommandStart())
async def cmd_start(m: Message):
    await m.answer("👋 Welcome to Lumina Store!", reply_markup=kb.main_kb)

@dp.message(F.text == "🛍 Shop Now")
async def shop(m: Message):
    await m.answer("<b>📂 Select a Category:</b>", reply_markup=kb.category_kb())

# --- CHECKOUT FLOW ---
@dp.callback_query(

@dp.callback_query(F.data == "ask_name")
async def ask_name_cb(cb: CallbackQuery, state: FSMContext):
    await cb.answer()
    await ask_name(cb.message, state)

async def ask_name(m: Message, state: FSMContext):
    await m.answer(
        "📋 <b>Checkout</b>\n"
        "━━━━━━━━━━━━━━\n\n"
        "👤 <b>Step 1 — Full Name</b>\n\n"
        "Please type your full name:"
    )
    await state.set_state(Checkout.name)


@dp.message(Checkout.name)
async def get_name(m: Message, state: FSMContext):
    await state.update_data(name=m.text.strip())
    await m.answer(
        "📋 <b>Checkout</b>\n"
        "━━━━━━━━━━━━━━\n\n"
        "🏠 <b>Step 2 — Street Address</b>\n\n"
        "Enter your house number and street:"
    )
    await state.set_state(Checkout.street)


@dp.message(Checkout.street)
async def get_street(m: Message, state: FSMContext):
    await state.update_data(street=m.text.strip())
    await m.answer(
        "📋 <b>Checkout</b>\n"
        "━━━━━━━━━━━━━━\n\n"
        "🏙 <b>Step 3 — City</b>\n\n"
        "Enter your city or town:"
    )
    await state.set_state(Checkout.city)


@dp.message(Checkout.city)
async def get_city(m: Message, state: FSMContext):
    await state.update_data(city=m.text.strip())
    await m.answer(
        "📋 <b>Checkout</b>\n"
        "━━━━━━━━━━━━━━\n\n"
        "📮 <b>Step 4 — Postcode</b>\n\n"
        "Enter your postcode:"
    )
    await state.set_state(Checkout.postcode)

@dp.message(Checkout.postcode)
async def finalize_address(m: Message, state: FSMContext):
    data = await state.get_data()
    postcode = m.text.strip()

    db.save_profile(
        m.from_user.id,
        data["name"],
        data["street"],
        data["city"],
        postcode
    )

    await show_summary(
        m,
        state,
        data["name"],
        data["street"],
        data["city"],
        postcode
    )

@dp.callback_query(F.data == "use_saved")
async def use_saved_addr(cb: CallbackQuery, state: FSMContext):
    await cb.answer()
    p = db.get_profile(cb.from_user.id)
    await show_summary(cb.message, state, p[0], p[1], p[2], p[3])

async def show_summary(m, state: FSMContext, name: str, street: str, city: str, postcode: str):
    uid = m.chat.id
    cart = db.get_user_cart(uid)
    products = await db.get_live_products()

    items = []
    total = 0

    for pid, qty in cart.items():
        if pid in products:
            product = products[pid]
            line_total = float(product["price"]) * qty
            total += line_total
            items.append(f"• {product['name']} ×{qty}\n£{line_total:.2f}")

    items_text = "\n\n".join(items) if items else "No items in cart."

    summary = (
        "📋 <b>Order Summary</b>\n"
        "━━━━━━━━━━━━━━\n\n"
        f"👤 {name}\n"
        f"📍 {street}, {city}\n"
        f"{postcode}\n\n"
        "🧬 <b>Items</b>\n"
        f"{items_text}\n\n"
        "━━━━━━━━━━━━━━\n"
        f"💰 <b>Total: £{total:.2f}</b>\n\n"
        "Please confirm to proceed."
    )

    btns = [
        [InlineKeyboardButton(text="✅ Confirm", callback_data="finish_order")],
        [InlineKeyboardButton(text="🚚 Change Delivery", callback_data="ask_name")],
        [
            InlineKeyboardButton(text="✏️ Edit Cart", callback_data="view_cart"),
            InlineKeyboardButton(text="❌ Cancel", callback_data="view_cart"),
        ],
    ]

    await m.answer(
        summary,
        reply_markup=InlineKeyboardMarkup(inline_keyboard=btns)
    )

    await state.update_data(
        final_name=name,
        final_addr=f"{street}, {city} {postcode}",
        final_total=total,
        final_items=items_text,
    )

@dp.callback_query(F.data == "finish_order")
async def finish_order(cb: CallbackQuery, state: FSMContext):
    await cb.answer()

    data = await state.get_data()
    uid = cb.from_user.id
    cart = db.get_user_cart(uid)

    db.deduct_supabase_stock(cart)
    oid = db.save_order(
        uid,
        data["final_name"],
        data["final_addr"],
        data["final_items"],
        data["final_total"],
    )

    await cb.message.edit_text(
        f"✅ <b>Order #{oid} Logged</b>\n"
        "━━━━━━━━━━━━━━\n\n"
        "Your order has been received.\n"
        "We’ll contact you with the next update shortly."
    )

    admin_kb = InlineKeyboardMarkup(
        inline_keyboard=[
            [InlineKeyboardButton(text="✅ Paid", callback_data=f"adm_p_{oid}_{uid}")],
            [InlineKeyboardButton(text="🚚 Track", callback_data=f"adm_t_{oid}_{uid}")],
        ]
    )

    await cb.bot.send_message(
        ADMIN_ID,
        f"🔔 <b>NEW ORDER #{oid}</b>\n\n"
        f"👤 {data['final_name']}\n"
        f"📍 {data['final_addr']}\n\n"
        f"{data['final_items']}\n\n"
        f"💰 Total: £{data['final_total']:.2f}",
        reply_markup=admin_kb,
    )

    db.clear_cart(uid)
    await state.clear()

# --- ADMIN ---
@dp.callback_query(F.data.startswith("adm_p_"))
async def admin_paid(cb: CallbackQuery):
    _, _, oid, cid = cb.data.split("_")
    db.update_db_order(oid, status="Paid")
    await cb.bot.send_message(cid, f"✅ <b>Payment Received for Order #{oid}!</b>")
    await cb.answer("Marked Paid")

async def main():
    db.init_db()
    bot = Bot(
        token=TOKEN,
        default=DefaultBotProperties(parse_mode=ParseMode.HTML),
    )
    await dp.start_polling(bot)

if __name__ == "__main__":
    asyncio.run(main())
