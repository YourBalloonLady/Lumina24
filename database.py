import sqlite3
import os
import logging
from typing import Optional

from supabase import create_client, Client

# -----------------------------
# ENV / CONFIG
# -----------------------------
SUPA_URL = os.getenv("SUPABASE_URL")
SUPA_KEY = os.getenv("SUPABASE_KEY")
DB_PATH = os.getenv("DATABASE_URL", "store.db")

logging.basicConfig(level=logging.INFO)

# -----------------------------
# SUPABASE
# -----------------------------
supabase: Optional[Client] = None
if SUPA_URL and SUPA_KEY:
    try:
        supabase = create_client(SUPA_URL, SUPA_KEY)
        logging.info("✅ Supabase connected")
    except Exception as e:
        logging.error(f"❌ Supabase init failed: {e}")
        supabase = None
else:
    logging.warning("⚠️ SUPABASE_URL or SUPABASE_KEY missing")


# -----------------------------
# LOCAL SQLITE SETUP
# -----------------------------
def init_db():
    """Initialise local SQLite tables for cart + saved delivery profiles."""
    conn = sqlite3.connect(DB_PATH)

    conn.execute("""
        CREATE TABLE IF NOT EXISTS cart (
            user_id INTEGER,
            product_id TEXT,
            quantity INTEGER,
            PRIMARY KEY (user_id, product_id)
        )
    """)

    conn.execute("""
        CREATE TABLE IF NOT EXISTS profiles (
            user_id INTEGER PRIMARY KEY,
            name TEXT,
            street TEXT,
            city TEXT,
            postcode TEXT
        )
    """)

    conn.commit()
    conn.close()


# -----------------------------
# SAVED DELIVERY PROFILE
# -----------------------------
def get_profile(uid):
    conn = sqlite3.connect(DB_PATH)
    cursor = conn.cursor()
    cursor.execute(
        "SELECT name, street, city, postcode FROM profiles WHERE user_id = ?",
        (uid,)
    )
    row = cursor.fetchone()
    conn.close()
    return row


def save_profile(uid, name, street, city, postcode):
    conn = sqlite3.connect(DB_PATH)
    conn.execute(
        """
        INSERT OR REPLACE INTO profiles (user_id, name, street, city, postcode)
        VALUES (?, ?, ?, ?, ?)
        """,
        (uid, name, street, city, postcode)
    )
    conn.commit()
    conn.close()


# -----------------------------
# SUPABASE PRODUCTS
# -----------------------------
async def get_live_products():
    """Fetch all live products from Supabase."""
    if not supabase:
        return {}

    try:
        res = supabase.table("products").select("*").execute()
        return {p["id"]: p for p in (res.data or [])}
    except Exception as e:
        logging.error(f"Supabase Fetch Error: {e}")
        return {}


def deduct_supabase_stock(cart_items):
    """
    Subtract purchased quantities from Supabase.
    cart_items = {product_id: quantity}
    """
    if not supabase:
        return

    try:
        for pid, qty in cart_items.items():
            res = supabase.table("products").select("stock").eq("id", pid).single().execute()

            if res.data:
                current_stock = int(res.data.get("stock", 0))
                new_stock = max(0, current_stock - int(qty))

                supabase.table("products").update(
                    {"stock": new_stock}
                ).eq("id", pid).execute()

                logging.info(f"✅ Stock updated: {pid} -> {new_stock}")
            else:
                logging.warning(f"⚠️ Item {pid} not found in Supabase for stock deduction")
    except Exception as e:
        logging.error(f"❌ Stock deduction failed: {e}")


# -----------------------------
# SUPABASE ORDERS
# -----------------------------
def save_order(uid, name, address, items, total):
    """Save order to Supabase orders table."""
    if not supabase:
        return None

    try:
        data = {
            "user_id": uid,
            "customer_name": name,
            "address": address,
            "items": items,
            "total": total,
            "status": "Pending",
            "tracking": "None",
        }

        res = supabase.table("orders").insert(data).execute()
        return res.data[0]["id"] if res.data else None
    except Exception as e:
        logging.error(f"Order Save Error: {e}")
        return None


def update_db_order(order_id, status=None, tracking=None):
    """Update order status/tracking in Supabase."""
    if not supabase:
        return

    try:
        upd = {}
        if status is not None:
            upd["status"] = status
        if tracking is not None:
            upd["tracking"] = tracking

        if upd:
            supabase.table("orders").update(upd).eq("id", order_id).execute()
    except Exception as e:
        logging.error(f"Order Update Error: {e}")


# -----------------------------
# LOCAL CART FUNCTIONS
# -----------------------------
def update_cart(uid, pid, delta):
    conn = sqlite3.connect(DB_PATH)
    cursor = conn.cursor()

    cursor.execute(
        "SELECT quantity FROM cart WHERE user_id = ? AND product_id = ?",
        (uid, pid)
    )
    row = cursor.fetchone()

    if row:
        new_qty = max(0, row[0] + delta)

        if new_qty == 0:
            cursor.execute(
                "DELETE FROM cart WHERE user_id = ? AND product_id = ?",
                (uid, pid)
            )
        else:
            cursor.execute(
                "UPDATE cart SET quantity = ? WHERE user_id = ? AND product_id = ?",
                (new_qty, uid, pid)
            )
    elif delta > 0:
        cursor.execute(
            "INSERT INTO cart (user_id, product_id, quantity) VALUES (?, ?, ?)",
            (uid, pid, delta)
        )

    conn.commit()
    conn.close()


def get_user_cart(uid):
    conn = sqlite3.connect(DB_PATH)
    cursor = conn.cursor()
    cursor.execute(
        "SELECT product_id, quantity FROM cart WHERE user_id = ?",
        (uid,)
    )
    rows = cursor.fetchall()
    conn.close()
    return {r[0]: r[1] for r in rows}


def clear_cart(uid):
    conn = sqlite3.connect(DB_PATH)
    conn.execute("DELETE FROM cart WHERE user_id = ?", (uid,))
    conn.commit()
    conn.close()
