import os
import sys

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from orders import db, service  # noqa: E402
from orders.models import Item, Order, OrderLine  # noqa: E402


def setup_function():
    db.reset()


def test_line_subtotal():
    item = Item(sku="A", name="Widget", price_cents=250, stock=10)
    line = OrderLine(item=item, qty=3)
    assert line.subtotal_cents() == 750


def test_order_totals():
    order = Order(customer_id=1)
    order.add_line(Item(sku="A", name="Widget", price_cents=1000, stock=5), 2)
    assert order.subtotal_cents() == 2000
    assert order.shipping_cents() == 799


def test_add_same_sku_merges():
    order = Order(customer_id=1)
    item = Item(sku="A", name="Widget", price_cents=100, stock=5)
    order.add_line(item, 1)
    order.add_line(item, 2)
    assert len(order.lines) == 1
    assert order.lines[0].qty == 3


def test_service_flow():
    cid = service.create_customer("a@example.com")
    item_id = service.create_item("SKU1", "Thing", 1500, stock=4)
    order = service.start_order(cid)
    service.add_to_order(order.id, item_id, 2)
    summary = service.order_summary(order.id)
    assert summary["subtotal_cents"] == 3000
    service.submit_order(order.id)
    assert service.load_order(order.id).status == "submitted"
    assert service.get_item(item_id).stock == 2
