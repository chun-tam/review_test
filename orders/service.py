"""Order lifecycle operations."""

from typing import List, Optional

from .db import Database
from .models import Customer, Item, Order, OrderLine, OrderStatus


class ServiceError(Exception):
    """Raised when a requested operation is not valid."""


class OrderService:
    def __init__(self, db: Database):
        self.db = db

    # -- catalogue ---------------------------------------------------------

    def create_customer(self, name: str, email: str) -> Customer:
        return self.db.insert_customer(Customer(name=name, email=email))

    def create_item(
        self,
        sku: str,
        name: str,
        unit_price_cents: int,
        stock: int = 0,
        category: str = "general",
    ) -> Item:
        return self.db.insert_item(
            Item(
                sku=sku,
                name=name,
                unit_price_cents=unit_price_cents,
                stock=stock,
                category=category,
            )
        )

    def find_items(self, **kwargs) -> List[Item]:
        return self.db.search_items(**kwargs)

    def find_customers(self, email_fragment: str) -> List[Customer]:
        return self.db.search_customers_by_email(email_fragment)

    # -- orders ------------------------------------------------------------

    def start_order(self, customer_id: int) -> Order:
        if self.db.get_customer(customer_id) is None:
            raise ServiceError(f"unknown customer {customer_id}")
        return self.db.insert_order(Order(customer_id=customer_id))

    def get_order(self, order_id: int) -> Order:
        order = self.db.get_order(order_id)
        if order is None:
            raise ServiceError(f"unknown order {order_id}")
        return order

    def add_line(self, order_id: int, item_id: int, quantity: int) -> Order:
        if quantity <= 0:
            raise ServiceError("quantity must be positive")
        order = self.get_order(order_id)
        if order.status is not OrderStatus.DRAFT:
            raise ServiceError("can only add lines to a draft order")
        item = self.db.get_item(item_id)
        if item is None:
            raise ServiceError(f"unknown item {item_id}")

        for line in order.lines:
            if line.item_id == item_id:
                new_quantity = line.quantity + quantity
                self.db.update_order_line_quantity(line.id, new_quantity)
                return self.get_order(order_id)

        self.db.insert_order_line(
            order_id,
            OrderLine(
                item_id=item.id,
                sku=item.sku,
                name=item.name,
                unit_price_cents=item.unit_price_cents,
                quantity=quantity,
            ),
        )
        return self.get_order(order_id)

    def apply_discount(self, order_id: int, discount_percent: float) -> Order:
        order = self.get_order(order_id)
        if order.status is not OrderStatus.DRAFT:
            raise ServiceError("can only discount a draft order")
        order.discount_percent = discount_percent
        self.db.update_order(order)
        return self.get_order(order_id)

    def submit_order(self, order_id: int) -> Order:
        order = self.get_order(order_id)
        if order.status is not OrderStatus.DRAFT:
            raise ServiceError("only a draft order can be submitted")
        if not order.lines:
            raise ServiceError("cannot submit an empty order")
        for line in order.lines:
            self.db.decrement_stock(line.item_id, line.quantity)
        order.status = OrderStatus.SUBMITTED
        self.db.update_order(order)
        return self.get_order(order_id)

    def cancel_order(self, order_id: int) -> Order:
        order = self.get_order(order_id)
        if order.status is OrderStatus.CANCELLED:
            return order
        order.status = OrderStatus.CANCELLED
        self.db.update_order(order)
        return self.get_order(order_id)

    def list_orders(
        self, customer_id: Optional[int] = None, status: Optional[str] = None
    ) -> List[Order]:
        return self.db.list_orders(
            customer_id=customer_id,
            status=OrderStatus(status) if status else None,
        )

    def order_summary(self, order_id: int) -> dict:
        order = self.get_order(order_id)
        customer = self.db.get_customer(order.customer_id)
        summary = order.to_dict()
        summary["customer"] = (
            {"id": customer.id, "name": customer.name, "email": customer.email}
            if customer
            else None
        )
        summary["item_count"] = sum(line.quantity for line in order.lines)
        return summary
