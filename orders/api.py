"""JSON HTTP API over the order service.

Routes:
    GET  /items                    list/search items
    POST /items                    create an item (requires admin token)
    GET  /customers?email=<frag>   search customers by email
    POST /customers                create a customer
    GET  /orders                   list orders
    POST /orders                   start an order
    GET  /orders/<id>              order summary
    POST /orders/<id>/lines        add a line
    POST /orders/<id>/submit       submit an order
"""

import json
import os
import re
from dataclasses import asdict
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from typing import Optional
from urllib.parse import parse_qs, urlparse

from .db import Database
from .service import OrderService, ServiceError

ADMIN_TOKEN_ENV = "ORDERS_ADMIN_TOKEN"

ORDER_RE = re.compile(r"^/orders/(\d+)$")
ORDER_LINES_RE = re.compile(r"^/orders/(\d+)/lines$")
ORDER_SUBMIT_RE = re.compile(r"^/orders/(\d+)/submit$")


class OrdersRequestHandler(BaseHTTPRequestHandler):
    service: OrderService = None  # set by make_server
    admin_token: Optional[str] = None

    protocol_version = "HTTP/1.1"

    def log_message(self, fmt, *args):  # pragma: no cover - quieter tests
        pass

    # -- plumbing ----------------------------------------------------------

    def _send(self, status: int, payload) -> None:
        body = json.dumps(payload).encode()
        self.send_response(status)
        self.send_header("Content-Type", "application/json")
        self.send_header("Content-Length", str(len(body)))
        self.end_headers()
        self.wfile.write(body)

    def _read_json(self) -> dict:
        length = int(self.headers.get("Content-Length") or 0)
        if not length:
            return {}
        return json.loads(self.rfile.read(length) or b"{}")

    def _is_admin(self) -> bool:
        return bool(self.admin_token) and (
            self.headers.get("X-Admin-Token") == self.admin_token
        )

    # -- routing -----------------------------------------------------------

    def do_GET(self):
        parsed = urlparse(self.path)
        path = parsed.path.rstrip("/") or "/"
        query = parse_qs(parsed.query)

        try:
            if path == "/items":
                items = self.service.find_items(
                    query=_first(query, "q"),
                    category=_first(query, "category"),
                    in_stock_only=_first(query, "in_stock") == "true",
                    max_price_cents=_int(_first(query, "max_price_cents")),
                    sort_by=_first(query, "sort_by") or "name",
                    descending=_first(query, "desc") == "true",
                )
                return self._send(200, [asdict(item) for item in items])

            if path == "/customers":
                customers = self.service.find_customers(_first(query, "email") or "")
                return self._send(200, [asdict(c) for c in customers])

            if path == "/orders":
                orders = self.service.list_orders(
                    customer_id=_int(_first(query, "customer_id")),
                    status=_first(query, "status"),
                )
                return self._send(200, [order.to_dict() for order in orders])

            match = ORDER_RE.match(path)
            if match:
                return self._send(200, self.service.order_summary(int(match.group(1))))

            return self._send(404, {"error": "not found"})
        except ServiceError as exc:
            return self._send(400, {"error": str(exc)})

    def do_POST(self):
        path = urlparse(self.path).path.rstrip("/") or "/"

        try:
            body = self._read_json()

            if path == "/items":
                if not self._is_admin():
                    return self._send(403, {"error": "admin token required"})
                item = self.service.create_item(
                    sku=body["sku"],
                    name=body["name"],
                    unit_price_cents=int(body["unit_price_cents"]),
                    stock=int(body.get("stock", 0)),
                    category=body.get("category", "general"),
                )
                return self._send(201, asdict(item))

            if path == "/customers":
                customer = self.service.create_customer(body["name"], body["email"])
                return self._send(201, asdict(customer))

            if path == "/orders":
                order = self.service.start_order(int(body["customer_id"]))
                return self._send(201, order.to_dict())

            match = ORDER_LINES_RE.match(path)
            if match:
                order = self.service.add_line(
                    int(match.group(1)),
                    int(body["item_id"]),
                    int(body.get("quantity", 1)),
                )
                return self._send(201, order.to_dict())

            match = ORDER_SUBMIT_RE.match(path)
            if match:
                order = self.service.submit_order(int(match.group(1)))
                return self._send(200, order.to_dict())

            return self._send(404, {"error": "not found"})
        except (KeyError, ValueError) as exc:
            return self._send(400, {"error": f"bad request: {exc}"})
        except ServiceError as exc:
            return self._send(400, {"error": str(exc)})


def _first(query: dict, key: str) -> Optional[str]:
    values = query.get(key)
    return values[0] if values else None


def _int(value: Optional[str]) -> Optional[int]:
    return int(value) if value not in (None, "") else None


def make_server(
    service: OrderService,
    host: str = "127.0.0.1",
    port: int = 8000,
    admin_token: Optional[str] = None,
) -> ThreadingHTTPServer:
    handler = type(
        "BoundOrdersRequestHandler",
        (OrdersRequestHandler,),
        {
            "service": service,
            "admin_token": admin_token or os.environ.get(ADMIN_TOKEN_ENV),
        },
    )
    return ThreadingHTTPServer((host, port), handler)


def main() -> None:  # pragma: no cover - manual entrypoint
    db = Database(os.environ.get("ORDERS_DB_PATH", "orders.sqlite3"))
    server = make_server(
        OrderService(db),
        host=os.environ.get("ORDERS_HOST", "127.0.0.1"),
        port=int(os.environ.get("ORDERS_PORT", "8000")),
    )
    server.serve_forever()


if __name__ == "__main__":  # pragma: no cover
    main()
