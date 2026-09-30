"""Loopback-only governed metric receipt and constrained intent API."""
import argparse
import json
import re
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path
from urllib.parse import parse_qs, urlsplit

from .core import Store, AuthenticationError, WorkflowConflictError

MAX_BODY = 32768
MAX_TARGET = 8192
STATIC = {"/": ("index.html", "text/html; charset=utf-8"),
          "/index.html": ("index.html", "text/html; charset=utf-8"),
          "/app.js": ("app.js", "text/javascript; charset=utf-8"),
          "/styles.css": ("styles.css", "text/css; charset=utf-8")}


def make_server(store, port=19084, static_dir=None):
    static_dir = Path(static_dir or Path(__file__).resolve().parents[1] / "static")
    class Handler(BaseHTTPRequestHandler):
        server_version = "SyntheticMetricReview"
        sys_version = ""
        def log_message(self, format, *args):
            pass

        def _send(self, status, value, content_type="application/json; charset=utf-8"):
            body = value if isinstance(value, bytes) else json.dumps(value, ensure_ascii=False, allow_nan=False).encode()
            self.send_response(status)
            self.send_header("Content-Type", content_type)
            self.send_header("Content-Length", str(len(body)))
            self.send_header("Cache-Control", "no-store")
            self.send_header("X-Content-Type-Options", "nosniff")
            self.send_header("X-Frame-Options", "DENY")
            self.send_header("Referrer-Policy", "no-referrer")
            self.send_header("Content-Security-Policy", "default-src 'self'; script-src 'self'; style-src 'self'; img-src 'self' data:; connect-src 'self'; frame-ancestors 'none'; base-uri 'none'; form-action 'none'")
            self.end_headers()
            self.wfile.write(body)

        def _body(self):
            if self.headers.get("Transfer-Encoding"):
                raise ValueError("unsupported_transfer")
            lengths = self.headers.get_all("Content-Length", [])
            if len(lengths) != 1 or not lengths[0].isdigit():
                raise ValueError("content_length_required")
            length = int(lengths[0])
            if length > MAX_BODY:
                self._send(413, {"error": "Request body too large"})
                return None
            if self.headers.get("Content-Type", "").split(";", 1)[0].strip().lower() != "application/json":
                raise ValueError("json_required")
            body = json.loads(self.rfile.read(length))
            if not isinstance(body, dict):
                raise ValueError("json_object_required")
            return body

        def _principal(self):
            authorization = self.headers.get("Authorization", "")
            if not authorization.startswith("Bearer ") or len(authorization) > 200:
                raise AuthenticationError("authentication_required")
            return store.principal(authorization[7:])

        def _route(self, method):
            if len(self.path) > MAX_TARGET:
                self._send(414, {"error": "Request target too long"})
                return
            port = str(self.server.server_port)
            allowed_hosts = {"127.0.0.1:" + port, "localhost:" + port}
            if self.headers.get("Host", "").lower() not in allowed_hosts:
                raise PermissionError("invalid_host")
            origin = self.headers.get("Origin")
            if origin and origin not in {"http://" + host for host in allowed_hosts}:
                raise PermissionError("invalid_origin")
            parsed = urlsplit(self.path)
            path = parsed.path
            if parsed.scheme or parsed.netloc or "%" in path or "\\" in path:
                raise KeyError("not_found")
            query = parse_qs(parsed.query, keep_blank_values=True, max_num_fields=8)
            if any(len(values) != 1 for values in query.values()):
                raise ValueError("duplicate_query")
            query = {key: values[0] for key, values in query.items()}
            if method == "GET" and path in STATIC:
                name, content_type = STATIC[path]
                try:
                    body = (static_dir / name).read_bytes()
                except OSError:
                    raise KeyError("not_found")
                self._send(200, body, content_type)
                return
            if method == "GET" and path == "/api/health":
                self._send(200, {"ok": True, "synthetic": True,
                                 "scope": "synthetic_governed_metric_review_not_factory_certification",
                                 "authentication": "server-allowlisted demo profiles"})
                return
            if method == "GET" and path == "/api/profiles":
                self._send(200, {"profiles": store.profiles()})
                return
            if method == "POST" and path == "/api/session":
                body = self._body()
                if body is not None:
                    self._send(200, store.session(body.get("profile")))
                return
            if not path.startswith("/api/"):
                raise KeyError("not_found")
            principal = self._principal()
            if method == "GET" and path == "/api/datasets":
                self._send(200, {"datasets": store.datasets(principal)})
            elif method == "GET" and path == "/api/catalog":
                self._send(200, {"catalog": store.catalog(principal)})
            elif method == "GET" and path == "/api/sources":
                if set(query)-{"dataset_id","site_id"}:raise ValueError("unknown_query")
                self._send(200, store.sources(principal,query.get("dataset_id","baseline"),query.get("site_id","PLANT-A")))
            elif method == "POST" and path == "/api/calculate":
                body=self._body()
                if body is not None:self._send(200, {"receipt":store.calculate(principal,body)})
            elif method == "POST" and path == "/api/route":
                body=self._body()
                if body is not None:self._send(200, {"route":store.route(principal,body)})
            elif method == "GET" and re.fullmatch(r"/api/receipts/[^/]+",path):
                self._send(200, {"receipt":store.receipt(principal,path.rsplit("/",1)[1])})
            elif method == "POST" and re.fullmatch(r"/api/receipts/[^/]+/review",path):
                body=self._body()
                if body is not None:
                    if set(body)-{"comment","expected_fingerprint"}:raise ValueError("unknown_review_field")
                    self._send(200,store.review(principal,path.split("/")[3],body.get("comment",""),body.get("expected_fingerprint")))
            elif method == "GET" and path == "/api/audit":
                self._send(200, {"events":store.audit(principal)})
            else:
                raise KeyError("not_found")

        def _handle(self, method):
            try:
                self._route(method)
            except WorkflowConflictError as error:
                self._send(409, {"error":"Snapshot or receipt state changed; refresh the explicit source and selectors","code":str(error) if str(error) in {"snapshot_unavailable","fingerprint_mismatch","receipt_stale","review_already_recorded"} else "workflow_changed"})
            except AuthenticationError:
                self._send(401, {"error": "Session missing or expired; sign in to the synthetic demo"})
            except PermissionError:
                self._send(403, {"error": "Access denied"})
            except KeyError:
                self._send(404, {"error": "Not found"})
            except (ValueError, TypeError, UnicodeError):
                self._send(400, {"error": "Invalid request or source validation failed"})
            except TimeoutError:
                self._send(503, {"error":"Model route timed out; use the deterministic selector and verify shared-runtime recovery","code":"model_timeout"})
            except RuntimeError:
                self._send(503, {"error":"Model route unavailable; use the approved deterministic selector","code":"model_routing_failed"})
            except (ConnectionError, BrokenPipeError):
                self.close_connection = True
            except Exception:
                self._send(500, {"error": "Internal request failure"})

        def do_GET(self):
            self._handle("GET")

        def do_POST(self):
            self._handle("POST")

        def do_OPTIONS(self):
            self._send(405, {"error": "Method not allowed"})

    class LoopbackServer(ThreadingHTTPServer):
        def get_request(self):
            connection, address = super().get_request()
            connection.settimeout(15)
            return connection, address
    server = LoopbackServer(("127.0.0.1", port), Handler)
    server.daemon_threads = True
    return server


def main():
    root = Path(__file__).resolve().parents[1]
    parser = argparse.ArgumentParser(description="Synthetic governed shift metrics, loopback only")
    parser.add_argument("--data-dir", default=str(root / "data"))
    parser.add_argument("--db", default=str(root / "data/metrics.sqlite3"))
    parser.add_argument("--port", type=int, default=19084)
    args = parser.parse_args()
    store = Store(args.data_dir, args.db)
    server = make_server(store, args.port)
    try:
        server.serve_forever()
    except KeyboardInterrupt:
        pass
    finally:
        server.server_close()
        store.close()


if __name__ == "__main__":
    main()
