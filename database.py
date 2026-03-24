import os
import sqlite3
import logging
from typing import Optional

from supabase import create_client, Client

SUPA_URL = os.getenv("SUPABASE_URL")
SUPA_KEY = os.getenv("SUPABASE_KEY")
DB_PATH = "store.db"

supabase: Optional[Client] = None
if SUPA_URL and SUPA_KEY:
    try:
        supabase = create_client(SUPA_URL, SUPA_KEY)
    except Exception as e:
        logging.error(f"Supabase init failed: {e}")
        supabase = None


def init_db():
    conn = sqlite3.connect(DB_PATH)

    # Cart and saved addresses
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


# --- ADDRESS MEMORY ---
def get_profile(uid):
    conn = sqlite3.connect(DB_PATH)
    res = conn.execute(
        "SELECT name, street, city, postcode FROM profiles WHERE user_id = ?",
        (uid,)
    ).fetchone()
    conn.close()
    return res


def save_profile(uid, name, street, city, postcode):
    conn = sqlite3.connect(DB_PATH)
    conn.execute(
        "INSERT OR REPLACE INTO profiles VALUES (?, ?, ?, ?, ?)",
        (uid, name, street, city, postcode)
    )
    conn.commit()
    conn.close()


# --- INVENTORY & ORDERS ---
async def get_live_products():
    if not supabase:
        return {}

    try:
        res = supabase.table("products").select("*").execute()
        return {p["id"]: p for p in (res.data or [])}
    except Exception as e:
        logging.error(f"Failed to fetch products: {e}")
        return {}


def deduct_supabase_stock(cart_items):
    if not supabase:
        return

    try:
        for pid, qty in cart_items.items():
            res = supabase.table("products").select("stock").eq("id", pid).single().execute()
            if res.data:
                new_stock = max(0, int(res.data["stock"]) - int(qty))
                supabase.table("products").update({"stock": new_stock}).eq("id", pid).execute()
    except Exception as e:
        logging.error(f"Failed to deduct stock: {e}")


def save_order(uid, name, addr, items, total):
    if not supabase:
        return None

    try:
        data = {
            "user_id": uid,
            "customer_name": name,
            "address": addr,
            "items": items,
            "total": total,
            "status": "Pending"
        }
        res = supabase.table("orders").insert(data).execute()
        return res.data[0]["id"] if res.data else None
    except Exception as e:
        logging.error(f"Failed to save order: {e}")
        return None


def update_db_order(order_id, status=None, tracking=None):
    if not supabase:
        return

    try:
        payload = {}
        if status is not None:
            payload["status"] = status
        if tracking is not None:
            payload["tracking"] = tracking

        if payload:
            supabase.table("orders").update(payload).eq("id", order_id).execute()
    except Exception as e:
        logging.error(f"Failed to update order {order_id}: {e}")


# --- CART HELPERS ---
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
    rows = conn.execute(
        "SELECT product_id, quantity FROM cart WHERE user_id = ?",
        (uid,)
    ).fetchall()
    conn.close()
    return {r[0]: r[1] for r in rows}


def clear_cart(uid):
    conn = sqlite3.connect(DB_PATH)
    conn.execute("DELETE FROM cart WHERE user_id = ?", (uid,))
    conn.commit()
    conn.close()
