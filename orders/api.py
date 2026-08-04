"""Minimal HTTP API over the order service (stdlib only)."""

import hmac
import json
import logging
import os
from http.server import BaseHTTPRequestHandler, HTTPServer
from urllib.parse import parse_qs, urlparse

from orders import db, service

log = logging.getLogger(__name__)

MAX_BODY_BYTES = 64 * 1024


def _authorized(headers):
    admin_token = os.environ.get("ORDERS_ADMIN_TOKEN")
    token = headers.get("X-Admin-Token")
    if not admin_token:
        log.error("ORDERS_ADMIN_TOKEN is unset; admin routes are disabled")
        return False
    if token is None:
        return False
    return hmac.compare_digest(
        token.encode("utf-8", "surrogateescape"),
        admin_token.encode("utf-8", "surrogateescape"),
    )


def _int_field(body, key, minimum=0, default=None):
    value = body.get(key, default)
    if isinstance(value, bool) or not isinstance(value, int):
        raise ValueError("%s must be an integer" % key)
    if value < minimum:
        raise ValueError("%s must be >= %s" % (key, minimum))
    return value


def _order_route(path, suffix=None):
    """Return the order id for /orders/<id>[/suffix], or None if it doesn't match."""
    parts = path.strip("/").split("/")
    expected = 3 if suffix else 2
    if len(parts) != expected or parts[0] != "orders" or not parts[1]:
        return None
    if suffix and parts[2] != suffix:
        return None
    return parts[1]


def _str_field(body, key, max_length=200):
    value = body[key]
    if not isinstance(value, str) or not value.strip():
        raise ValueError("%s must be a non-empty string" % key)
    if len(value) > max_length:
        raise ValueError("%s is too long" % key)
    return value


class Handler(BaseHTTPRequestHandler):
    timeout = 15

    def _json(self, code, payload):
        body = json.dumps(payload).encode()
        self.send_response(code)
        self.send_header("Content-Type", "application/json")
        self.send_header("Content-Length", str(len(body)))
        self.end_headers()
        self.wfile.write(body)

    def _body(self):
        length = int(self.headers.get("Content-Length", 0))
        if length < 0:
            raise ValueError("invalid Content-Length")
        if length > MAX_BODY_BYTES:
            raise ValueError("body larger than %s bytes" % MAX_BODY_BYTES)
        raw = self.rfile.read(length)
        if not raw:
            return {}
        return json.loads(raw)

    def do_GET(self):
        url = urlparse(self.path)
        params = parse_qs(url.query)
        try:
            if url.path == "/items":
                items = db.search_items(
                    name=params.get("name", [None])[0],
                    max_price=params.get("max_price", [None])[0],
                    order_by=params.get("order_by", ["id"])[0],
                    limit=params.get("limit", [db.MAX_ITEM_RESULTS])[0],
                )
                return self._json(200, {"items": items})
            if url.path == "/customers":
                email = params.get("email", [""])[0]
                return self._json(200, {"customers": db.find_customers_by_email(email)})
            order_id = _order_route(url.path)
            if order_id is not None:
                return self._json(200, service.order_summary(order_id))
            return self._json(404, {"error": "not found"})
        except service.OrderError as exc:
            return self._json(404, {"error": str(exc)})
        except ValueError as exc:
            return self._json(400, {"error": str(exc)})
        except Exception:
            log.exception("GET %s failed", self.path)
            return self._json(500, {"error": "internal error"})

    def do_POST(self):
        url = urlparse(self.path)
        try:
            body = self._body()
        except (ValueError, TypeError) as exc:
            return self._json(400, {"error": "invalid body: %s" % exc})
        try:
            if not isinstance(body, dict):
                raise ValueError("body must be a JSON object")
            if url.path == "/customers":
                email = _str_field(body, "email")
                if "@" not in email:
                    raise ValueError("email must contain @")
                cid, _ = service.create_customer(email)
                return self._json(201, {"id": cid})
            if url.path == "/items":
                if not _authorized(self.headers):
                    return self._json(403, {"error": "forbidden"})
                item_id = service.create_item(
                    _str_field(body, "sku"),
                    _str_field(body, "name"),
                    _int_field(body, "price_cents"),
                    _int_field(body, "stock", default=0),
                )
                return self._json(201, {"id": item_id})
            if url.path == "/orders":
                order = service.start_order(_int_field(body, "customer_id", minimum=1))
                return self._json(201, {"id": order.id})
            order_id = _order_route(url.path, "lines")
            if order_id is not None:
                order = service.add_to_order(
                    order_id,
                    _int_field(body, "item_id", minimum=1),
                    _int_field(body, "qty", minimum=1),
                )
                return self._json(200, service.order_summary(order.id))
            order_id = _order_route(url.path, "submit")
            if order_id is not None:
                service.submit_order(order_id)
                return self._json(200, service.order_summary(order_id))
            return self._json(404, {"error": "not found"})
        except db.InsufficientStock as exc:
            return self._json(409, {"error": "insufficient stock for item %s" % exc})
        except db.ItemNotFound as exc:
            return self._json(404, {"error": "no such item: %s" % exc})
        except service.OrderError as exc:
            return self._json(409, {"error": str(exc)})
        except KeyError as exc:
            return self._json(400, {"error": "missing field %s" % exc})
        except ValueError as exc:
            return self._json(400, {"error": str(exc)})
        except Exception:
            log.exception("POST %s failed", self.path)
            return self._json(500, {"error": "internal error"})


def serve(port=8080, host=None):
    if not os.environ.get("ORDERS_ADMIN_TOKEN"):
        log.warning("ORDERS_ADMIN_TOKEN is unset; item creation will be rejected")
    host = host or os.environ.get("ORDERS_BIND_HOST", "127.0.0.1")
    httpd = HTTPServer((host, port), Handler)
    log.info("listening on %s", port)
    httpd.serve_forever()


if __name__ == "__main__":
    logging.basicConfig(level=logging.DEBUG)
    serve()
