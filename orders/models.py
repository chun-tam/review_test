"""Domain models for the order-management service.

All monetary amounts are integer cents.
"""

from dataclasses import dataclass, field
from enum import Enum
from typing import List, Optional

TAX_RATE = 0.0825
FLAT_SHIPPING_CENTS = 799
FREE_SHIPPING_THRESHOLD_CENTS = 5000


class OrderStatus(str, Enum):
    DRAFT = "draft"
    SUBMITTED = "submitted"
    CANCELLED = "cancelled"


@dataclass
class Customer:
    name: str
    email: str
    id: Optional[int] = None


@dataclass
class Item:
    sku: str
    name: str
    unit_price_cents: int
    stock: int = 0
    category: str = "general"
    id: Optional[int] = None


@dataclass
class OrderLine:
    item_id: int
    sku: str
    name: str
    unit_price_cents: int
    quantity: int
    id: Optional[int] = None

    @property
    def subtotal_cents(self) -> int:
        return self.unit_price_cents * self.quantity


@dataclass
class Order:
    customer_id: int
    status: OrderStatus = OrderStatus.DRAFT
    discount_percent: float = 0.0
    lines: List[OrderLine] = field(default_factory=list)
    created_at: Optional[str] = None
    id: Optional[int] = None

    def add_line(self, line: OrderLine) -> None:
        """Add a line, merging into an existing line for the same item."""
        for existing in self.lines:
            if existing.item_id == line.item_id:
                existing.quantity += line.quantity
                return
        self.lines.append(line)

    @property
    def subtotal_cents(self) -> int:
        return sum(line.subtotal_cents for line in self.lines)

    @property
    def discount_cents(self) -> int:
        return round(self.subtotal_cents * self.discount_percent / 100.0)

    @property
    def discounted_subtotal_cents(self) -> int:
        return self.subtotal_cents - self.discount_cents

    @property
    def tax_cents(self) -> int:
        return round(self.discounted_subtotal_cents * TAX_RATE)

    @property
    def shipping_cents(self) -> int:
        if not self.lines:
            return 0
        if self.discounted_subtotal_cents >= FREE_SHIPPING_THRESHOLD_CENTS:
            return 0
        return FLAT_SHIPPING_CENTS

    @property
    def total_cents(self) -> int:
        return self.discounted_subtotal_cents + self.tax_cents + self.shipping_cents

    def to_dict(self) -> dict:
        return {
            "id": self.id,
            "customer_id": self.customer_id,
            "status": self.status.value,
            "discount_percent": self.discount_percent,
            "created_at": self.created_at,
            "lines": [
                {
                    "id": line.id,
                    "item_id": line.item_id,
                    "sku": line.sku,
                    "name": line.name,
                    "unit_price_cents": line.unit_price_cents,
                    "quantity": line.quantity,
                    "subtotal_cents": line.subtotal_cents,
                }
                for line in self.lines
            ],
            "subtotal_cents": self.subtotal_cents,
            "discount_cents": self.discount_cents,
            "tax_cents": self.tax_cents,
            "shipping_cents": self.shipping_cents,
            "total_cents": self.total_cents,
        }
