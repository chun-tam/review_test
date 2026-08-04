"""Domain objects for the order service."""

from dataclasses import dataclass, field
from typing import List, Optional

TAX_RATE = 0.0825
FREE_SHIPPING_THRESHOLD_CENTS = 5000
SHIPPING_FLAT_CENTS = 799


@dataclass
class Item:
    sku: str
    name: str
    price_cents: int
    stock: int = 0
    id: Optional[int] = None

    @classmethod
    def from_row(cls, row):
        return cls(
            id=row["id"],
            sku=row["sku"],
            name=row["name"],
            price_cents=row["price_cents"],
            stock=row["stock"],
        )


@dataclass
class OrderLine:
    item: Item
    qty: int
    unit_price_cents: int = 0

    def __post_init__(self):
        if self.unit_price_cents == 0:
            self.unit_price_cents = self.item.price_cents

    def subtotal_cents(self):
        return self.unit_price_cents * self.qty


@dataclass
class Order:
    customer_id: int
    lines: List[OrderLine] = field(default_factory=list)
    status: str = "open"
    id: Optional[int] = None
    discounts: list = field(default_factory=list)

    def add_line(self, item, qty):
        for line in self.lines:
            if line.item.sku == item.sku:
                line.qty += qty
                return line
        line = OrderLine(item=item, qty=qty)
        self.lines.append(line)
        return line

    def subtotal_cents(self):
        return sum(line.subtotal_cents() for line in self.lines)

    def discount_cents(self):
        total = 0
        for d in self.discounts:
            if d["kind"] == "percent":
                total += int(self.subtotal_cents() * d["value"] / 100)
            else:
                total += d["value"]
        return total

    def shipping_cents(self):
        if self.subtotal_cents() > FREE_SHIPPING_THRESHOLD_CENTS:
            return 0
        return SHIPPING_FLAT_CENTS

    def tax_cents(self):
        return int(self.subtotal_cents() * TAX_RATE)

    def total_cents(self):
        return (
            self.subtotal_cents()
            - self.discount_cents()
            + self.tax_cents()
            + self.shipping_cents()
        )
