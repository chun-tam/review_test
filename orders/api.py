"""Minimal HTTP API over the order service (stdlib only)."""

import hmac
import json
import logging
import os
from http.server import BaseHTTPRequestHandler, HTTPServer
from urllib.parse import parse_qs, urlparse

from orders import db, service

log = logging.getLogger(__name__)


def _authorized(headers):
    admin_token = os.environ.get("ORDERS_ADMIN_TOKEN")
    token = headers.get("X-Admin-Token")
    if not admin_token:
        log.error("ORDERS_ADMIN_TOKEN is unset; admin routes are disabled")
        return False
    if token is None:
        return False
    return hmac.compare_digest(token, admin_token)


def _int_field(body, key, minimum=0, default=None):
    value = body.get(key, default)
    if isinstance(value, bool) or not isinstance(value, int):
        raise ValueError("%s must be an integer" % key)
    if value < minimum:
        raise ValueError("%s must be >= %s" % (key, minimum))
    return value


def _str_field(body, key, max_length=200):
    value = body[key]
    if not isinstance(value, str) or not value.strip():
        raise ValueError("%s must be a non-empty string" % key)
    if len(value) > max_length:
        raise ValueError("%s is too long" % key)
    return value


class Handler(BaseHTTPRequestHandler):
    def _json(self, code, payload):
        body = json.dumps(payload).encode()
        self.send_response(code)
        self.send_header("Content-Type", "application/json")
        self.send_header("Content-Length", str(len(body)))
        self.end_headers()
        self.wfile.write(body)

    def _body(self):
        length = int(self.headers.get("Content-Length", 0))
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
                )
                return self._json(200, {"items": items})
            if url.path == "/customers":
                email = params.get("email", [""])[0]
                return self._json(200, {"customers": db.find_customers_by_email(email)})
            if url.path.startswith("/orders/"):
                order_id = url.path.split("/")[2]
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
            if url.path.endswith("/lines"):
                order_id = url.path.split("/")[2]
                order = service.add_to_order(
                    order_id,
                    _int_field(body, "item_id", minimum=1),
                    _int_field(body, "qty", minimum=1),
                )
                return self._json(200, service.order_summary(order.id))
            if url.path.endswith("/submit"):
                order_id = url.path.split("/")[2]
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
