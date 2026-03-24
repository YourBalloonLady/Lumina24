import os
import asyncio
import logging

from aiogram import Bot, Dispatcher, F
from aiogram.filters import CommandStart
from aiogram.fsm.storage.memory import MemoryStorage
from aiogram.client.default import DefaultBotProperties
from aiogram.types import (
    Message,
    CallbackQuery,
    InlineKeyboardMarkup,
    InlineKeyboardButton,
)
from aiogram.fsm.state import State, StatesGroup
from aiogram.fsm.context import FSMContext

import database as db
import keyboards as kb

TOKEN = os.getenv("BOT_TOKEN")
ADMIN_ID = int(os.getenv("ADMIN_ID", 5839927114))

logging.basicConfig(level=logging.INFO)


class Checkout(StatesGroup):
    name = State()
    street = State()
    city = State()
    postcode = State()


dp = Dispatcher(storage=MemoryStorage())


# -----------------------------
# NAVIGATION
# -----------------------------
@dp.message(CommandStart())
async def cmd_start(m: Message):
    await m.answer(
        "👋 Welcome to Lumina Store!",
        reply_markup=kb.main_kb
    )


@dp.message(F.text == "🛍 Shop Now")
async def shop(m: Message):
    await m.answer(
        "<b>📂 Select a Category:</b>",
        reply_markup=kb.category_kb()
    )


@dp.message(F.text == "🛒 My Cart")
async def my_cart(m: Message):
    uid = m.from_user.id
    user_cart = db.get_user_cart(uid)
    products = await db.get_live_products()

    if not user_cart:
        await m.answer("🛒 Your cart is empty.")
        return

    await send_cart_message(m, products, user_cart)


@dp.message(F.text == "📦 My Orders")
async def my_orders(m: Message):
    orders = db.get_user_orders(m.from_user.id)

    if not orders:
        await m.answer("📦 You have no orders yet.")
        return

    lines = ["📦 <b>Your Recent Orders</b>\n"]

    for order in orders:
        order_id = order.get("id")
        total = float(order.get("total", 0))
        status = order.get("status", "Unknown")
        tracking = order.get("tracking", "None")

        lines.append(
            f"• <b>Order #{order_id}</b>\n"
            f"Status: {status}\n"
            f"Total: £{total:.2f}\n"
            f"Tracking: {tracking}\n"
        )

    await m.answer("\n".join(lines))


@dp.message(F.text == "❓ Help")
async def help_handler(m: Message):
    await m.answer(
        "Use <b>Shop Now</b> to browse categories and <b>My Cart</b> to review your items."
    )


@dp.message(F.text == "📞 Contact")
async def contact_handler(m: Message):
    await m.answer("📞 Support is available via your usual contact method.")


# -----------------------------
# SHOP / CART HELPERS
# -----------------------------
async def send_cart_message(target, products, user_cart):
    lines = ["🛒 <b>Your Cart</b>\n"]
    total = 0.0

    for pid, qty in user_cart.items():
        p = products.get(pid)
        if not p:
            continue

        line_total = float(p["price"]) * qty
        total += line_total
        lines.append(f"• {p['name']} ×{qty} — £{line_total:.2f}")

    lines.append("")
    lines.append(f"💰 <b>Total: £{total:.2f}</b>")

    text = "\n".join(lines)

    if isinstance(target, Message):
        await target.answer(
            text,
            reply_markup=kb.cart_edit_kb(products, user_cart)
        )
    else:
        await target.message.edit_text(
            text,
            reply_markup=kb.cart_edit_kb(products, user_cart)
        )


# -----------------------------
# CATEGORY / PRODUCT CALLBACKS
# -----------------------------
@dp.callback_query(F.data.startswith("cat_"))
async def open_category(cb: CallbackQuery):
    await cb.answer()

    category_name = cb.data.replace("cat_", "", 1)
    products = await db.get_live_products()

    await cb.message.edit_text(
        f"<b>🛍 {category_name}</b>",
        reply_markup=kb.item_list_kb(products, category_name)
    )


@dp.callback_query(F.data == "back_to_cats")
async def back_to_categories(cb: CallbackQuery):
    await cb.answer()
    await cb.message.edit_text(
        "<b>📂 Select a Category:</b>",
        reply_markup=kb.category_kb()
    )


@dp.callback_query(F.data.startswith("view_"))
async def view_product(cb: CallbackQuery):
    await cb.answer()

    pid = cb.data.replace("view_", "", 1)
    products = await db.get_live_products()
    p = products.get(pid)

    if not p:
        await cb.message.answer("❌ Product not found.")
        return

    stock = int(p.get("stock", 0))
    status = f"✅ In stock ({stock})" if stock > 0 else "❌ Out of stock"

    buttons = []

    if stock > 0:
        buttons.append([
            InlineKeyboardButton(text="🛒 Add to Cart", callback_data=f"qty_plus_{pid}")
        ])

    buttons.append([
        InlineKeyboardButton(text="🛒 View Cart", callback_data="view_cart")
    ])
    buttons.append([
        InlineKeyboardButton(text="⬅ Back", callback_data="back_to_cats")
    ])

    product_kb = InlineKeyboardMarkup(inline_keyboard=buttons)

    await cb.message.edit_text(
        f"<b>📦 {p['name']}</b>\n"
        f"💰 Price: £{float(p['price']):.2f}\n"
        f"{status}",
        reply_markup=product_kb
    )


@dp.callback_query(F.data == "view_cart")
async def view_cart(cb: CallbackQuery):
    await cb.answer()

    uid = cb.from_user.id
    user_cart = db.get_user_cart(uid)
    products = await db.get_live_products()

    if not user_cart:
        await cb.message.edit_text("🛒 Your cart is empty.")
        return

    await send_cart_message(cb, products, user_cart)


@dp.callback_query(F.data.startswith("qty_plus_"))
async def qty_plus(cb: CallbackQuery):
    await cb.answer()

    uid = cb.from_user.id
    pid = cb.data.replace("qty_plus_", "", 1)

    products = await db.get_live_products()
    p = products.get(pid)

    if not p:
        await cb.answer("Product not found.", show_alert=True)
        return

    stock = int(p.get("stock", 0))
    user_cart = db.get_user_cart(uid)
    current_qty = user_cart.get(pid, 0)

    if stock <= 0:
        await cb.answer("Out of stock.", show_alert=True)
        return

    if current_qty >= stock:
        await cb.answer("No more stock available.", show_alert=True)
        return

    db.update_cart(uid, pid, 1)

    user_cart = db.get_user_cart(uid)
    await send_cart_message(cb, products, user_cart)


@dp.callback_query(F.data.startswith("qty_minus_"))
async def qty_minus(cb: CallbackQuery):
    await cb.answer()

    uid = cb.from_user.id
    pid = cb.data.replace("qty_minus_", "", 1)

    db.update_cart(uid, pid, -1)

    user_cart = db.get_user_cart(uid)
    products = await db.get_live_products()

    if not user_cart:
        await cb.message.edit_text("🛒 Your cart is empty.")
        return

    await send_cart_message(cb, products, user_cart)


@dp.callback_query(F.data == "ignore")
async def ignore_button(cb: CallbackQuery):
    await cb.answer()


# -----------------------------
# CHECKOUT FLOW
# -----------------------------
@dp.callback_query(F.data == "start_checkout")
async def start_checkout(cb: CallbackQuery, state: FSMContext):
    await cb.answer()

    uid = cb.from_user.id
    user_cart = db.get_user_cart(uid)

    if not user_cart:
        await cb.message.edit_text("🛒 Your cart is empty.")
        return

    profile = db.get_profile(uid)

    if profile:
        text = (
            "📋 <b>Checkout</b>\n"
            "━━━━━━━━━━━━━━\n"
            "📍 <b>Saved Address</b>\n\n"
            f"👤 {profile[0]}\n"
            f"📍 {profile[1]}\n"
            f"🏙 {profile[2]}\n"
            f"📮 {profile[3]}\n\n"
            "Ship to this address?"
        )

        btns = [
            [InlineKeyboardButton(text="✅ Use This Address", callback_data="use_saved")],
            [InlineKeyboardButton(text="📝 New Address", callback_data="ask_name")],
            [InlineKeyboardButton(text="🚚 Change Delivery", callback_data="ask_name")],
            [InlineKeyboardButton(text="❌ Cancel", callback_data="view_cart")],
        ]

        await cb.message.edit_text(
            text,
            reply_markup=InlineKeyboardMarkup(inline_keyboard=btns)
        )
    else:
        await ask_name(cb.message, state)


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
    total = 0.0

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


# -----------------------------
# ADMIN
# -----------------------------
@dp.callback_query(F.data.startswith("adm_p_"))
async def admin_paid(cb: CallbackQuery):
    _, _, oid, cid = cb.data.split("_")
    db.update_db_order(oid, status="Paid")
    await cb.bot.send_message(
        cid,
        f"✅ <b>Payment Received for Order #{oid}!</b>"
    )
    await cb.answer("Marked Paid")


# -----------------------------
# RUN
# -----------------------------
async def main():
    db.init_db()
    bot = Bot(
        token=TOKEN,
        default=DefaultBotProperties(parse_mode="HTML"),
    )
    await dp.start_polling(bot)


if __name__ == "__main__":
    asyncio.run(main())
