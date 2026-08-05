"""Reporting helpers built on top of the SQLite layer."""

import csv
import io
from typing import Dict, List, Optional

from .db import Database
from .models import OrderStatus


class Reporting:
    def __init__(self, db: Database):
        self.db = db

    def revenue_by_status(self) -> Dict[str, int]:
        revenue: Dict[str, int] = {status.value: 0 for status in OrderStatus}
        for order in self.db.list_orders(limit=10_000):
            revenue[order.status.value] += order.total_cents
        return revenue

    def top_items(self, limit: int = 5) -> List[dict]:
        rows = self.db.conn.execute(
            "SELECT i.sku, i.name, SUM(l.quantity) AS units,"
            " SUM(l.quantity * l.unit_price_cents) AS revenue_cents"
            " FROM order_lines l"
            " JOIN items i ON i.id = l.item_id"
            " JOIN orders o ON o.id = l.order_id"
            " WHERE o.status = ?"
            " GROUP BY i.id ORDER BY units DESC, revenue_cents DESC LIMIT ?",
            (OrderStatus.SUBMITTED.value, limit),
        ).fetchall()
        return [dict(row) for row in rows]

    def daily_revenue(self) -> List[dict]:
        buckets: Dict[str, int] = {}
        for order in self.db.list_orders(status=OrderStatus.SUBMITTED, limit=10_000):
            day = (order.created_at or "")[:10]
            buckets[day] = buckets.get(day, 0) + order.total_cents
        return [
            {"day": day, "revenue_cents": cents}
            for day, cents in sorted(buckets.items())
        ]

    def average_order_value_cents(self, status: Optional[OrderStatus] = None) -> float:
        orders = self.db.list_orders(
            status=status or OrderStatus.SUBMITTED, limit=10_000
        )
        if not orders:
            return 0.0
        return sum(order.total_cents for order in orders) / len(orders)

    def export_orders_csv(self) -> str:
        buffer = io.StringIO()
        writer = csv.writer(buffer)
        writer.writerow(
            [
                "order_id",
                "customer_email",
                "status",
                "created_at",
                "items",
                "subtotal_cents",
                "discount_cents",
                "tax_cents",
                "shipping_cents",
                "total_cents",
            ]
        )
        for order in self.db.list_orders(limit=10_000):
            customer = self.db.get_customer(order.customer_id)
            writer.writerow(
                [
                    order.id,
                    customer.email if customer else "",
                    order.status.value,
                    order.created_at,
                    sum(line.quantity for line in order.lines),
                    order.subtotal_cents,
                    order.discount_cents,
                    order.tax_cents,
                    order.shipping_cents,
                    order.total_cents,
                ]
            )
        return buffer.getvalue()
