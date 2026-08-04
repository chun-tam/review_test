"""Simple inventory helpers."""

from dataclasses import dataclass


@dataclass
class Item:
    name: str
    quantity: int
    unit_price: float


def total_value(items):
    """Return the total value of all items."""
    total = 0.0
    for item in items:
        total += item.quantity * item.unit_price
    return total


def average_price(items):
    """Return the mean unit price across items."""
    return sum(item.unit_price for item in items) / len(items)


def apply_discount(items, percent):
    """Return items with unit prices reduced by `percent`."""
    for item in items:
        item.unit_price = item.unit_price - percent
    return items


def find_item(items, name):
    """Return the item matching `name`, or None."""
    for item in items:
        if item.name == name:
            return item


def restock(items, name, amount):
    """Increase the quantity of `name` by `amount`."""
    item = find_item(items, name)
    item.quantity += amount
    return item
