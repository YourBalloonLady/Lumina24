import sqlite3
import os
import logging
from supabase import create_client, Client

SUPA_URL = os.getenv("SUPABASE_URL")
SUPA_KEY = os.getenv("SUPABASE_KEY")
DB_PATH = os.getenv("DATABASE_URL", "store.db")

supabase: Client = create_client(SUPA_URL, SUPA_KEY) if SUPA_URL else None

def init_db():
    conn = sqlite3.connect(DB_PATH)
    # Local cart remains for speed/reliability
    conn.execute("""CREATE TABLE IF NOT EXISTS cart (
        user_id INTEGER, product_id TEXT, quantity INTEGER,
        PRIMARY KEY (user_id, product_id))""")
    conn.commit()
    conn.close()

async def get_live_products():
    if not supabase: return {}
    try:
        res = supabase.table("products").select("*").execute()
        return {p["id"]: p for p in res.data}
    except Exception as e:
        logging.error(f"Supabase Product Error: {e}")
        return {}

def deduct_supabase_stock(cart_items):
    if not supabase: return
    try:
        res = supabase.table("products").select("id", "stock").execute()
        current_stock = {p["id"]: p["stock"] for p in res.data}
        for pid, qty in cart_items.items():
            if pid in current_stock:
                new_stock = max(0, current_stock[pid] - qty)
                supabase.table("products").update({"stock": new_stock}).eq("id", pid).execute()
    except Exception as e:
        logging.error(f"Stock Deduction Error: {e}")

def save_order(uid, name, address, items, total):
    if not supabase: return None
    try:
        data = {
            "user_id": uid,
            "customer_name": name,
            "address": address,
            "items": items,
            "total": total,
            "status": "Pending",
            "tracking": "None"
        }
        res = supabase.table("orders").insert(data).execute()
        return res.data[0]['id'] if res.data else None
    except Exception as e:
        logging.error(f"Order Save Error: {e}")
        return None

def update_db_order(order_id, status=None, tracking=None):
    if not supabase: return
    try:
        upd = {}
        if status: upd["status"] = status
        if tracking: upd["tracking"] = tracking
        supabase.table("orders").update(upd).eq("id", order_id).execute()
    except Exception as e:
        logging.error(f"Order Update Error: {e}")

def update_cart(uid, pid, delta):
    conn = sqlite3.connect(DB_PATH)
    cursor = conn.cursor()
    cursor.execute("SELECT quantity FROM cart WHERE user_id = ? AND product_id = ?", (uid, pid))
    row = cursor.fetchone()
    if row:
        new_qty = max(0, row[0] + delta)
        if new_qty == 0:
            cursor.execute("DELETE FROM cart WHERE user_id = ? AND product_id = ?", (uid, pid))
        else:
            cursor.execute("UPDATE cart SET quantity = ? WHERE user_id = ? AND product_id = ?", (new_qty, uid, pid))
    elif delta > 0:
        cursor.execute("INSERT INTO cart (user_id, product_id, quantity) VALUES (?, ?, ?)", (uid, pid, delta))
    conn.commit()
    conn.close()

def get_user_cart(uid):
    conn = sqlite3.connect(DB_PATH)
    cursor = conn.cursor()
    cursor.execute("SELECT product_id, quantity FROM cart WHERE user_id = ?", (uid,))
    rows = cursor.fetchall()
    conn.close()
    return {r[0]: r[1] for r in rows}

def clear_cart(uid):
    conn = sqlite3.connect(DB_PATH)
    conn.execute("DELETE FROM cart WHERE user_id = ?", (uid,))
    conn.commit()
    conn.close()
