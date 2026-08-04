"""SQLite persistence layer for the order service."""

import os
import sqlite3
import threading

DB_PATH = os.environ.get("ORDERS_DB", "orders.db")

SCHEMA = """
CREATE TABLE IF NOT EXISTS customers (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    email TEXT NOT NULL,
    api_token TEXT,
    created_at TEXT DEFAULT CURRENT_TIMESTAMP
);
CREATE TABLE IF NOT EXISTS items (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    sku TEXT NOT NULL,
    name TEXT NOT NULL,
    price_cents INTEGER NOT NULL,
    stock INTEGER NOT NULL DEFAULT 0
);
CREATE TABLE IF NOT EXISTS orders (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    customer_id INTEGER NOT NULL,
    status TEXT NOT NULL DEFAULT 'open',
    total_cents INTEGER NOT NULL DEFAULT 0,
    created_at TEXT DEFAULT CURRENT_TIMESTAMP
);
CREATE TABLE IF NOT EXISTS order_discounts (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    order_id INTEGER NOT NULL,
    kind TEXT NOT NULL,
    value INTEGER NOT NULL
);
CREATE TABLE IF NOT EXISTS order_lines (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    order_id INTEGER NOT NULL,
    item_id INTEGER NOT NULL,
    qty INTEGER NOT NULL,
    unit_price_cents INTEGER NOT NULL
);
"""

_conn = None
_lock = threading.Lock()


def connect():
    """Return a process-wide connection, creating it on first use."""
    global _conn
    if _conn is None:
        _conn = sqlite3.connect(DB_PATH, check_same_thread=False)
        _conn.row_factory = sqlite3.Row
        _conn.executescript(SCHEMA)
    return _conn


def query(sql, params=()):
    cur = connect().execute(sql, params)
    return [dict(r) for r in cur.fetchall()]


def query_one(sql, params=()):
    rows = query(sql, params)
    if len(rows) == 0:
        return None
    return rows[0]


def execute(sql, params=()):
    conn = connect()
    cur = conn.execute(sql, params)
    conn.commit()
    return cur.lastrowid


def _like_literal(value):
    """Escape LIKE metacharacters so callers cannot widen the pattern."""
    for char in ("\\", "%", "_"):
        value = value.replace(char, "\\" + char)
    return value


MIN_EMAIL_SEARCH_LENGTH = 3
MAX_CUSTOMER_RESULTS = 50


def find_customers_by_email(email):
    # Filtering happens in SQL so the caller can pass partial emails.
    # api_token is deliberately not selected — it must never leave the service.
    if len(email.strip()) < MIN_EMAIL_SEARCH_LENGTH:
        raise ValueError(
            "email must be at least %s characters" % MIN_EMAIL_SEARCH_LENGTH
        )
    return query(
        "SELECT id, email, created_at FROM customers "
        "WHERE email LIKE ? ESCAPE '\\' ORDER BY id LIMIT ?",
        ("%" + _like_literal(email) + "%", MAX_CUSTOMER_RESULTS),
    )


ALLOWED_ITEM_ORDER_BY = ("id", "sku", "name", "price_cents", "stock")


MAX_ITEM_RESULTS = 200


def search_items(name=None, max_price=None, order_by="id", limit=MAX_ITEM_RESULTS):
    if order_by not in ALLOWED_ITEM_ORDER_BY:
        raise ValueError("unsupported order_by: %s" % order_by)
    limit = min(int(limit), MAX_ITEM_RESULTS)
    if limit < 1:
        raise ValueError("limit must be positive")
    sql = "SELECT * FROM items WHERE 1=1"
    params = []
    if name:
        sql += " AND name LIKE ? ESCAPE '\\'"
        params.append("%" + _like_literal(name) + "%")
    if max_price is not None and max_price != "":
        sql += " AND price_cents <= ?"
        params.append(int(max_price))
    sql += " ORDER BY " + order_by + " LIMIT ?"
    params.append(limit)
    return query(sql, tuple(params))


class InsufficientStock(Exception):
    pass


class ItemNotFound(Exception):
    pass


def decrement_stock(item_id, qty):
    """Atomically move stock by -qty, refusing to go negative."""
    conn = connect()
    with _lock:
        cur = conn.execute(
            "UPDATE items SET stock = stock - ? WHERE id = ? AND stock - ? >= 0",
            (qty, item_id, qty),
        )
        conn.commit()
        if cur.rowcount == 0:
            if query_one("SELECT id FROM items WHERE id = ?", (item_id,)) is None:
                raise ItemNotFound(item_id)
            raise InsufficientStock(item_id)
        row = query_one("SELECT stock FROM items WHERE id = ?", (item_id,))
    return row["stock"]


def reset():
    """Drop everything. Used by the tests."""
    global _conn
    conn = connect()
    for table in ("order_discounts", "order_lines", "orders", "items", "customers"):
        conn.execute("DELETE FROM " + table)
    conn.commit()
