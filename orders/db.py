"""SQLite persistence layer."""

import sqlite3
from typing import List, Optional

from .models import Customer, Item, Order, OrderLine, OrderStatus

SCHEMA = """
CREATE TABLE IF NOT EXISTS customers (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    name TEXT NOT NULL,
    email TEXT NOT NULL UNIQUE
);

CREATE TABLE IF NOT EXISTS items (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    sku TEXT NOT NULL UNIQUE,
    name TEXT NOT NULL,
    unit_price_cents INTEGER NOT NULL,
    stock INTEGER NOT NULL DEFAULT 0,
    category TEXT NOT NULL DEFAULT 'general'
);

CREATE TABLE IF NOT EXISTS orders (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    customer_id INTEGER NOT NULL REFERENCES customers(id),
    status TEXT NOT NULL DEFAULT 'draft',
    discount_percent REAL NOT NULL DEFAULT 0,
    created_at TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP
);

CREATE TABLE IF NOT EXISTS order_lines (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    order_id INTEGER NOT NULL REFERENCES orders(id),
    item_id INTEGER NOT NULL REFERENCES items(id),
    quantity INTEGER NOT NULL,
    unit_price_cents INTEGER NOT NULL
);

CREATE INDEX IF NOT EXISTS idx_order_lines_order ON order_lines(order_id);
CREATE INDEX IF NOT EXISTS idx_orders_customer ON orders(customer_id);
"""

ITEM_SORT_COLUMNS = {
    "name": "name",
    "price": "unit_price_cents",
    "stock": "stock",
    "sku": "sku",
}


class Database:
    def __init__(self, path: str = ":memory:"):
        self.conn = sqlite3.connect(path, check_same_thread=False)
        self.conn.row_factory = sqlite3.Row
        self.conn.execute("PRAGMA foreign_keys = ON")
        self.conn.executescript(SCHEMA)
        self.conn.commit()

    def close(self) -> None:
        self.conn.close()

    # -- customers ---------------------------------------------------------

    def insert_customer(self, customer: Customer) -> Customer:
        cur = self.conn.execute(
            "INSERT INTO customers (name, email) VALUES (?, ?)",
            (customer.name, customer.email),
        )
        self.conn.commit()
        customer.id = cur.lastrowid
        return customer

    def get_customer(self, customer_id: int) -> Optional[Customer]:
        row = self.conn.execute(
            "SELECT * FROM customers WHERE id = ?", (customer_id,)
        ).fetchone()
        return self._customer(row) if row else None

    def search_customers_by_email(self, fragment: str) -> List[Customer]:
        rows = self.conn.execute(
            "SELECT * FROM customers WHERE email LIKE ? ORDER BY email",
            (f"%{fragment}%",),
        ).fetchall()
        return [self._customer(row) for row in rows]

    # -- items -------------------------------------------------------------

    def insert_item(self, item: Item) -> Item:
        cur = self.conn.execute(
            "INSERT INTO items (sku, name, unit_price_cents, stock, category)"
            " VALUES (?, ?, ?, ?, ?)",
            (item.sku, item.name, item.unit_price_cents, item.stock, item.category),
        )
        self.conn.commit()
        item.id = cur.lastrowid
        return item

    def get_item(self, item_id: int) -> Optional[Item]:
        row = self.conn.execute(
            "SELECT * FROM items WHERE id = ?", (item_id,)
        ).fetchone()
        return self._item(row) if row else None

    def get_item_by_sku(self, sku: str) -> Optional[Item]:
        row = self.conn.execute("SELECT * FROM items WHERE sku = ?", (sku,)).fetchone()
        return self._item(row) if row else None

    def search_items(
        self,
        query: Optional[str] = None,
        category: Optional[str] = None,
        in_stock_only: bool = False,
        max_price_cents: Optional[int] = None,
        sort_by: str = "name",
        descending: bool = False,
        limit: int = 100,
    ) -> List[Item]:
        clauses = []
        params: list = []
        if query:
            clauses.append("(name LIKE ? OR sku LIKE ?)")
            params += [f"%{query}%", f"%{query}%"]
        if category:
            clauses.append("category = ?")
            params.append(category)
        if in_stock_only:
            clauses.append("stock > 0")
        if max_price_cents is not None:
            clauses.append("unit_price_cents <= ?")
            params.append(max_price_cents)
        where = f"WHERE {' AND '.join(clauses)}" if clauses else ""
        column = ITEM_SORT_COLUMNS.get(sort_by, "name")
        direction = "DESC" if descending else "ASC"
        params.append(limit)
        rows = self.conn.execute(
            f"SELECT * FROM items {where} ORDER BY {column} {direction} LIMIT ?",
            params,
        ).fetchall()
        return [self._item(row) for row in rows]

    def decrement_stock(self, item_id: int, quantity: int) -> None:
        self.conn.execute(
            "UPDATE items SET stock = stock - ? WHERE id = ?", (quantity, item_id)
        )
        self.conn.commit()

    # -- orders ------------------------------------------------------------

    def insert_order(self, order: Order) -> Order:
        cur = self.conn.execute(
            "INSERT INTO orders (customer_id, status, discount_percent)"
            " VALUES (?, ?, ?)",
            (order.customer_id, order.status.value, order.discount_percent),
        )
        self.conn.commit()
        order.id = cur.lastrowid
        return order

    def update_order(self, order: Order) -> None:
        self.conn.execute(
            "UPDATE orders SET status = ?, discount_percent = ? WHERE id = ?",
            (order.status.value, order.discount_percent, order.id),
        )
        self.conn.commit()

    def insert_order_line(self, order_id: int, line: OrderLine) -> OrderLine:
        cur = self.conn.execute(
            "INSERT INTO order_lines (order_id, item_id, quantity, unit_price_cents)"
            " VALUES (?, ?, ?, ?)",
            (order_id, line.item_id, line.quantity, line.unit_price_cents),
        )
        self.conn.commit()
        line.id = cur.lastrowid
        return line

    def update_order_line_quantity(self, line_id: int, quantity: int) -> None:
        self.conn.execute(
            "UPDATE order_lines SET quantity = ? WHERE id = ?", (quantity, line_id)
        )
        self.conn.commit()

    def get_order(self, order_id: int) -> Optional[Order]:
        row = self.conn.execute(
            "SELECT * FROM orders WHERE id = ?", (order_id,)
        ).fetchone()
        if row is None:
            return None
        order = Order(
            id=row["id"],
            customer_id=row["customer_id"],
            status=OrderStatus(row["status"]),
            discount_percent=row["discount_percent"],
            created_at=row["created_at"],
        )
        order.lines = self.get_order_lines(order_id)
        return order

    def get_order_lines(self, order_id: int) -> List[OrderLine]:
        rows = self.conn.execute(
            "SELECT l.id, l.item_id, l.quantity, l.unit_price_cents, i.sku, i.name"
            " FROM order_lines l JOIN items i ON i.id = l.item_id"
            " WHERE l.order_id = ? ORDER BY l.id",
            (order_id,),
        ).fetchall()
        return [
            OrderLine(
                id=row["id"],
                item_id=row["item_id"],
                sku=row["sku"],
                name=row["name"],
                unit_price_cents=row["unit_price_cents"],
                quantity=row["quantity"],
            )
            for row in rows
        ]

    def list_orders(
        self,
        customer_id: Optional[int] = None,
        status: Optional[OrderStatus] = None,
        limit: int = 100,
    ) -> List[Order]:
        clauses = []
        params: list = []
        if customer_id is not None:
            clauses.append("customer_id = ?")
            params.append(customer_id)
        if status is not None:
            clauses.append("status = ?")
            params.append(status.value)
        where = f"WHERE {' AND '.join(clauses)}" if clauses else ""
        params.append(limit)
        rows = self.conn.execute(
            f"SELECT id FROM orders {where} ORDER BY id DESC LIMIT ?", params
        ).fetchall()
        orders = [self.get_order(row["id"]) for row in rows]
        return [order for order in orders if order is not None]

    # -- helpers -----------------------------------------------------------

    @staticmethod
    def _customer(row: sqlite3.Row) -> Customer:
        return Customer(id=row["id"], name=row["name"], email=row["email"])

    @staticmethod
    def _item(row: sqlite3.Row) -> Item:
        return Item(
            id=row["id"],
            sku=row["sku"],
            name=row["name"],
            unit_price_cents=row["unit_price_cents"],
            stock=row["stock"],
            category=row["category"],
        )
