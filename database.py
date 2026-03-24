import sqlite3
import os
import logging
from supabase import create_client, Client

# Load environment variables
SUPA_URL = os.getenv("SUPABASE_URL")
SUPA_KEY = os.getenv("SUPABASE_KEY")
DB_PATH = os.getenv("DATABASE_URL", "store.db")

# Initialize Supabase
supabase: Client = create_client(SUPA_URL, SUPA_KEY) if SUPA_URL else None

def init_db():
    """Initializes the local SQLite database for cart persistence."""
    conn = sqlite3.connect(DB_PATH)
    conn.execute("""CREATE TABLE IF NOT EXISTS cart (
        user_id INTEGER, 
        product_id TEXT, 
        quantity INTEGER, 
        PRIMARY KEY (user_id, product_id))""")
    conn.commit()
    conn.close()

async def get_live_products():
    """Fetches all products from Supabase."""
    if not supabase: return {}
    try:
        res = supabase.table("products").select("*").execute()
        # Maps the 'id' (item1, item2, etc.) to the product data
        return {p["id"]: p for p in res.data}
    except Exception as e:
        logging.error(f"Supabase Fetch Error: {e}")
        return {}

def deduct_supabase_stock(cart_items):
    """
    Subtracts purchased quantities from Supabase.
    cart_items: dict of {product_id: quantity}
    """
    if not supabase: return
    try:
        for pid, qty in cart_items.items():
            # 1. Get current stock for this specific ID (e.g., 'item1')
            res = supabase.table("products").select("stock").eq("id", pid).single().execute()
            if res.data:
                current_stock = res.data.get('stock', 0)
                new_stock = max(0, current_stock - qty)
                
                # 2. Update Supabase with the new value
                supabase.table("products").update({"stock": new_stock}).eq("id", pid).execute()
                print(f"✅ Stock Updated: {pid} is now {new_stock}")
            else:
                print(f"⚠️ Item {pid} not found in Supabase for stock deduction.")
    except Exception as e:
        print(f"❌ Stock Deduction Failed: {e}")

def save_order(uid, name, address, items, total):
    """Saves the order to the Supabase 'orders' table."""
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
    """Updates status or tracking for an order in Supabase."""
    if not supabase: return
    upd = {}
    if status: upd["status"] = status
    if tracking: upd["tracking"] = tracking
    supabase.table("orders").update(upd).eq("id", order_id).execute()

# --- LOCAL CART FUNCTIONS ---
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
