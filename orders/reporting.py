"""Aggregate reporting over orders."""

import csv
import datetime
import io

from orders import db


def revenue_by_status():
    rows = db.query("SELECT status, total_cents FROM orders")
    out = {}
    for row in rows:
        out[row["status"]] = out.get(row["status"], 0) + row["total_cents"]
    return out


def top_items(limit=10):
    rows = db.query(
        "SELECT item_id, SUM(qty) AS units, SUM(qty * unit_price_cents) AS revenue "
        "FROM order_lines GROUP BY item_id ORDER BY units DESC LIMIT ?",
        (limit,),
    )
    for row in rows:
        item = db.query_one("SELECT sku, name FROM items WHERE id = ?", (row["item_id"],))
        row["sku"] = item["sku"] if item else None
        row["name"] = item["name"] if item else None
    return rows


def daily_revenue(days=30):
    cutoff = datetime.datetime.now(datetime.timezone.utc) - datetime.timedelta(days=days)
    rows = db.query(
        "SELECT created_at, total_cents FROM orders WHERE created_at >= ?",
        (cutoff.strftime("%Y-%m-%d %H:%M:%S"),),
    )
    buckets = {}
    for row in rows:
        day = row["created_at"][0:10]
        buckets[day] = buckets.get(day, 0) + row["total_cents"]
    return sorted(buckets.items())


def export_csv(path=None):
    rows = top_items(limit=1000)
    buf = io.StringIO()
    writer = csv.writer(buf)
    writer.writerow(["sku", "name", "units", "revenue_cents"])
    for row in rows:
        writer.writerow([row["sku"], row["name"], row["units"], row["revenue"]])
    if path:
        with open(path, "w") as f:
            f.write(buf.getvalue())
    return buf.getvalue()


def average_order_value():
    rows = db.query("SELECT total_cents FROM orders")
    if not rows:
        return 0
    return sum(r["total_cents"] for r in rows) / len(rows)
