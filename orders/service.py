"""Order lifecycle orchestration."""

import logging
import secrets

from orders import db
from orders.models import Item, Order, OrderLine

log = logging.getLogger(__name__)

VALID_STATUSES = ["open", "submitted", "paid", "shipped", "cancelled"]


class OrderError(Exception):
    pass


def create_customer(email):
    """Create a customer and return (id, freshly generated api token)."""
    log.info("creating customer")
    api_token = secrets.token_urlsafe(32)
    customer_id = db.execute(
        "INSERT INTO customers (email, api_token) VALUES (?, ?)", (email, api_token)
    )
    return customer_id, api_token


def create_item(sku, name, price_cents, stock=0):
    return db.execute(
        "INSERT INTO items (sku, name, price_cents, stock) VALUES (?, ?, ?, ?)",
        (sku, name, price_cents, stock),
    )


def get_item(item_id):
    row = db.query_one("SELECT * FROM items WHERE id = ?", (item_id,))
    if row is None:
        raise OrderError("no such item: %s" % item_id)
    return Item.from_row(row)


def load_order(order_id):
    row = db.query_one("SELECT * FROM orders WHERE id = ?", (order_id,))
    if row is None:
        raise OrderError("no such order: %s" % order_id)
    order = Order(customer_id=row["customer_id"], status=row["status"], id=row["id"])
    lines = db.query("SELECT * FROM order_lines WHERE order_id = ?", (order_id,))
    for line in lines:
        item = get_item(line["item_id"])
        order.lines.append(
            OrderLine(
                item=item,
                qty=line["qty"],
                unit_price_cents=line["unit_price_cents"],
            )
        )
    return order


def start_order(customer_id):
    order_id = db.execute(
        "INSERT INTO orders (customer_id, status) VALUES (?, 'open')", (customer_id,)
    )
    return Order(customer_id=customer_id, id=order_id)


def add_to_order(order_id, item_id, qty):
    order = load_order(order_id)
    if order.status != "open":
        raise OrderError("cannot add lines to a %s order" % order.status)
    item = get_item(item_id)
    already = sum(l.qty for l in order.lines if l.item.id == item.id)
    if qty < 1:
        raise OrderError("qty must be positive")
    if item.stock < already + qty:
        raise OrderError(
            "only %s of %s available" % (item.stock - already, item.sku)
        )
    line = order.add_line(item, qty)
    existing = db.query_one(
        "SELECT id FROM order_lines WHERE order_id = ? AND item_id = ?",
        (order_id, item_id),
    )
    if existing:
        db.execute(
            "UPDATE order_lines SET qty = ? WHERE id = ?", (line.qty, existing["id"])
        )
    else:
        db.execute(
            "INSERT INTO order_lines (order_id, item_id, qty, unit_price_cents) "
            "VALUES (?, ?, ?, ?)",
            (order_id, item_id, qty, item.price_cents),
        )
    db.execute(
        "UPDATE orders SET total_cents = ? WHERE id = ?",
        (order.total_cents(), order_id),
    )
    return order


def apply_discount(order, kind, value):
    order.discounts.append({"kind": kind, "value": value})
    return order.total_cents()


def submit_order(order_id):
    order = load_order(order_id)
    if order.status != "open":
        raise OrderError("order %s is %s" % (order_id, order.status))
    done = []
    try:
        for line in order.lines:
            db.decrement_stock(line.item.id, line.qty)
            done.append(line)
    except Exception:
        for line in done:
            db.decrement_stock(line.item.id, -line.qty)
        raise
    set_status(order_id, "submitted")
    order.status = "submitted"
    return order


def set_status(order_id, status):
    if status not in VALID_STATUSES:
        raise OrderError("bad status " + status)
    db.execute("UPDATE orders SET status = ? WHERE id = ?", (status, order_id))


def cancel_order(order_id):
    order = load_order(order_id)
    if order.status == "cancelled":
        return order
    if order.status not in ("open", "submitted"):
        raise OrderError("cannot cancel a %s order" % order.status)
    if order.status == "submitted":
        for line in order.lines:
            db.decrement_stock(line.item.id, -line.qty)
    set_status(order_id, "cancelled")
    order.status = "cancelled"
    return order


def order_summary(order_id):
    order = load_order(order_id)
    return {
        "id": order.id,
        "status": order.status,
        "lines": [
            {"sku": l.item.sku, "qty": l.qty, "subtotal": l.subtotal_cents()}
            for l in order.lines
        ],
        "subtotal_cents": order.subtotal_cents(),
        "tax_cents": order.tax_cents(),
        "shipping_cents": order.shipping_cents(),
        "total_cents": order.total_cents(),
    }
