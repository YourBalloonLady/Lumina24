from aiogram.types import (
    ReplyKeyboardMarkup,
    KeyboardButton,
    InlineKeyboardMarkup,
    InlineKeyboardButton,
)

# -----------------------------
# CATEGORY MAP
# -----------------------------
CATEGORIES = {
    "GLP-1 Weight Loss": [
        "item3", "item4", "item6", "item7", "item8", "item9",
        "item10", "item11", "item12", "item13", "item14", "item15", "item17"
    ],
    "Recovery & Performance": [
        "item1", "item2"
    ],
    "Skin & Longevity": [
        "item5", "item16", "item18"
    ],
}

# -----------------------------
# MAIN MENU
# -----------------------------
main_kb = ReplyKeyboardMarkup(
    keyboard=[
        [KeyboardButton(text="🛍 Shop Now")],
        [KeyboardButton(text="🛒 My Cart"), KeyboardButton(text="📦 My Orders")],
        [KeyboardButton(text="❓ Help"), KeyboardButton(text="📞 Contact")],
    ],
    resize_keyboard=True
)

# -----------------------------
# CATEGORY KEYBOARD
# -----------------------------
def category_kb():
    buttons = [
        [InlineKeyboardButton(text=cat, callback_data=f"cat_{cat}")]
        for cat in CATEGORIES.keys()
    ]
    buttons.append([InlineKeyboardButton(text="🛒 View Cart", callback_data="view_cart")])
    return InlineKeyboardMarkup(inline_keyboard=buttons)

# -----------------------------
# ITEM LIST KEYBOARD
# -----------------------------
def item_list_kb(products, category_name):
    item_ids = CATEGORIES.get(category_name, [])
    rows = []

    for pid in item_ids:
        p = products.get(pid)
        if p:
            label = f"{p['name']} - £{p['price']}"
            if p.get("stock", 0) <= 0:
                label += " (Sold Out)"
            rows.append([
                InlineKeyboardButton(text=label, callback_data=f"view_{pid}")
            ])

    rows.append([InlineKeyboardButton(text="🛒 View Cart", callback_data="view_cart")])
    rows.append([InlineKeyboardButton(text="⬅ Back", callback_data="back_to_cats")])

    return InlineKeyboardMarkup(inline_keyboard=rows)

# -----------------------------
# CART EDIT KEYBOARD
# -----------------------------
def cart_edit_kb(products, user_cart):
    rows = []

    for pid, qty in user_cart.items():
        p = products.get(pid)
        if p:
            rows.append([
                InlineKeyboardButton(text="➖", callback_data=f"qty_minus_{pid}"),
                InlineKeyboardButton(text=f"{p['name']} (x{qty})", callback_data="ignore"),
                InlineKeyboardButton(text="➕", callback_data=f"qty_plus_{pid}")
            ])

    if user_cart:
        rows.append([InlineKeyboardButton(text="✅ Checkout", callback_data="start_checkout")])

    rows.append([InlineKeyboardButton(text="🛍 Continue Shopping", callback_data="back_to_cats")])

    return InlineKeyboardMarkup(inline_keyboard=rows)
