import pytest

from orders.db import Database
from orders.models import Order, OrderLine, OrderStatus
from orders.reporting import Reporting
from orders.service import OrderService, ServiceError


def line(item_id=1, price=1000, quantity=1):
    return OrderLine(
        item_id=item_id,
        sku=f"SKU-{item_id}",
        name=f"Item {item_id}",
        unit_price_cents=price,
        quantity=quantity,
    )


@pytest.fixture
def service():
    return OrderService(Database(":memory:"))


def test_line_subtotal():
    assert line(price=1250, quantity=3).subtotal_cents == 3750


def test_order_totals_with_shipping_and_discount():
    order = Order(customer_id=1)
    order.add_line(line(price=1000, quantity=2))
    assert order.subtotal_cents == 2000
    assert order.shipping_cents == 799
    assert order.tax_cents == 165
    assert order.total_cents == 2000 + 165 + 799

    order.discount_percent = 10
    assert order.discount_cents == 200
    assert order.total_cents == 1800 + order.tax_cents + 799


def test_free_shipping_over_threshold():
    order = Order(customer_id=1)
    order.add_line(line(price=6000, quantity=1))
    assert order.shipping_cents == 0
    assert order.total_cents == 6000 + 495


def test_add_line_merges_same_item():
    order = Order(customer_id=1)
    order.add_line(line(item_id=7, quantity=2))
    order.add_line(line(item_id=7, quantity=3))
    assert len(order.lines) == 1
    assert order.lines[0].quantity == 5


def test_end_to_end_flow(service):
    customer = service.create_customer("Ada", "ada@example.com")
    widget = service.create_item("W-1", "Widget", 2500, stock=10, category="tools")
    bolt = service.create_item("B-1", "Bolt", 150, stock=100)

    order = service.start_order(customer.id)
    service.add_line(order.id, widget.id, 2)
    service.add_line(order.id, bolt.id, 4)
    order = service.add_line(order.id, widget.id, 1)
    assert len(order.lines) == 2
    assert order.subtotal_cents == 3 * 2500 + 4 * 150

    order = service.apply_discount(order.id, 5)
    order = service.submit_order(order.id)
    assert order.status is OrderStatus.SUBMITTED
    assert service.db.get_item(widget.id).stock == 7

    with pytest.raises(ServiceError):
        service.add_line(order.id, bolt.id, 1)

    summary = service.order_summary(order.id)
    assert summary["customer"]["email"] == "ada@example.com"
    assert summary["item_count"] == 7

    assert service.find_items(query="widg")[0].sku == "W-1"
    assert service.find_customers("ada@")[0].id == customer.id

    reporting = Reporting(service.db)
    assert reporting.revenue_by_status()["submitted"] == order.total_cents
    assert reporting.top_items()[0]["sku"] == "B-1"
    assert reporting.average_order_value_cents() == order.total_cents
    assert "order_id" in reporting.export_orders_csv().splitlines()[0]
