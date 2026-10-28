#!/usr/bin/env python3
import http.server
import json
import mimetypes
import os
import socketserver
import urllib.parse
import urllib.request

PORT = 8090
BASE_DIR = os.path.dirname(os.path.abspath(__file__))
CDN_ORIGIN = "https://d1ym67wyom4bkd.cloudfront.net"

RESERVED_SLUGS = {"admin", "api", "login", "signup", "pricing", "features", "settings", "dashboard", "help", "terms", "privacy"}


def rebrand_text(text: str) -> str:
    text = text.replace("forceNoLiinksFooter", "__PROTECT_FOOTER_PROP__")
    text = text.replace("Liinks.co", "Linklease.co")
    text = text.replace("liinks.co", "linklease.co")
    text = text.replace("liinks.cc", "linklease.cc")
    text = text.replace("Liinks", "Linklease")
    text = text.replace("@liinksco", "@linklease")
    text = text.replace("liinks-co", "linklease")
    text = text.replace("__PROTECT_FOOTER_PROP__", "forceNoLiinksFooter")
    return text


class LinkleaseHandler(http.server.SimpleHTTPRequestHandler):
    def __init__(self, *args, **kwargs):
        super().__init__(*args, directory=BASE_DIR, **kwargs)

    def end_headers(self):
        self.send_header("Access-Control-Allow-Origin", "*")
        self.send_header("Cache-Control", "no-store")
        super().end_headers()

    def handle_trpc(self, parsed_url):
        procs = parsed_url.path.replace("/i/trpc/", "").split(",")
        qs = urllib.parse.parse_qs(parsed_url.query)
        is_batch = qs.get("batch", ["0"])[0] == "1"
        raw_input = qs.get("input", ["{}"])[0]
        try:
            inputs = json.loads(raw_input)
        except Exception:
            inputs = {}

        results = []
        for idx, proc in enumerate(procs):
            proc_input = inputs.get(str(idx), inputs) if isinstance(inputs, dict) else {}
            if proc == "user.checkSlugAvailability":
                slug = (proc_input.get("slug") or "").strip().lower()
                status = "RESERVED" if slug in RESERVED_SLUGS else "AVAILABLE"
                suggestion = f"{slug}.official" if status != "AVAILABLE" else None
                data = {"slug": slug, "status": status, "suggestion": suggestion}
            elif proc in ("user.me", "user.getMyUser"):
                data = None
            elif proc == "user.getFeaturedUsers":
                try:
                    with open(os.path.join(BASE_DIR, "featured_users.json"), "r", encoding="utf-8") as f:
                        batch_data = json.load(f)
                    data = batch_data[1]["result"]["data"]
                except Exception:
                    data = {"docs": [], "hasMore": False, "limit": 20, "offset": 0}
            else:
                data = None
            results.append({"result": {"data": data}})

        payload = json.dumps(results if is_batch else results[0]).encode("utf-8")
        self.send_response(200)
        self.send_header("Content-Type", "application/json")
        self.send_header("Content-Length", str(len(payload)))
        self.end_headers()
        self.wfile.write(payload)

    def do_GET(self):
        parsed = urllib.parse.urlparse(self.path)
        req_path = parsed.path

        if req_path.startswith("/i/trpc"):
            return self.handle_trpc(parsed)

        local_path = os.path.join(BASE_DIR, req_path.lstrip("/"))

        # Transparently fetch, rebrand, and cache any missing CloudFront bundle/image asset
        if req_path.startswith("/assets/bundles/") and not os.path.isfile(local_path):
            os.makedirs(os.path.dirname(local_path), exist_ok=True)
            cdn_url = CDN_ORIGIN + req_path
            try:
                req = urllib.request.Request(cdn_url, headers={"User-Agent": "Mozilla/5.0"})
                with urllib.request.urlopen(req, timeout=15) as resp:
                    content = resp.read()
                if local_path.endswith((".js", ".css")):
                    content = rebrand_text(content.decode("utf-8", errors="ignore")).encode("utf-8")
                with open(local_path, "wb") as f:
                    f.write(content)
            except Exception as exc:
                self.send_error(404, f"Asset not found: {exc}")
                return

        if os.path.isfile(local_path):
            ctype, _ = mimetypes.guess_type(local_path)
            with open(local_path, "rb") as f:
                data = f.read()
            self.send_response(200)
            self.send_header("Content-Type", ctype or "application/octet-stream")
            self.send_header("Content-Length", str(len(data)))
            self.end_headers()
            self.wfile.write(data)
            return

        # SPA fallback to index.html
        index_path = os.path.join(BASE_DIR, "index.html")
        with open(index_path, "rb") as f:
            data = f.read()
        self.send_response(200)
        self.send_header("Content-Type", "text/html; charset=utf-8")
        self.send_header("Content-Length", str(len(data)))
        self.end_headers()
        self.wfile.write(data)

    def do_POST(self):
        parsed = urllib.parse.urlparse(self.path)
        if parsed.path.startswith("/i/trpc"):
            return self.handle_trpc(parsed)
        self.send_response(200)
        self.send_header("Content-Type", "application/json")
        self.end_headers()
        self.wfile.write(b'{"ok":true}')


class ThreadedHTTPServer(socketserver.ThreadingMixIn, http.server.HTTPServer):
    allow_reuse_address = True


if __name__ == "__main__":
    with ThreadedHTTPServer(("0.0.0.0", PORT), LinkleaseHandler) as httpd:
        print(f"Linklease landing page running at http://localhost:{PORT}", flush=True)
        httpd.serve_forever()
