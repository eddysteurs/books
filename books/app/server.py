"""Books — a small book-collection app for Home Assistant (served through ingress).

Standard library only: http.server + sqlite3 + urllib. Data lives in /data
(included in Home Assistant backups).
"""
import csv
import io
import json
import mimetypes
import os
import re
import sqlite3
import sys
import threading
import time
import traceback
import urllib.parse
import urllib.request
import zlib
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
import clz  # noqa: E402
import lookup  # noqa: E402

VERSION = "0.1.3"
DATA_DIR = os.environ.get("BOOKS_DATA", "/data")
STATIC_DIR = os.path.join(os.path.dirname(os.path.abspath(__file__)), "static")
DB_PATH = os.path.join(DATA_DIR, "books.db")
COVER_DIR = os.path.join(DATA_DIR, "covers")
PORT = int(os.environ.get("BOOKS_PORT", "8099"))


def load_options():
    try:
        with open(os.path.join(DATA_DIR, "options.json"), encoding="utf-8") as f:
            return json.load(f)
    except (OSError, ValueError):
        return {}


OPTIONS = {"google_books_api_key": "", "language": "nl", "publish_sensors": True, "cache_covers": True}
OPTIONS.update(load_options())

# ------------------------------------------------------------------ database

COLUMNS = {
    "clz_id": "TEXT", "clz_hash": "TEXT", "title": "TEXT NOT NULL DEFAULT ''", "subtitle": "TEXT",
    "series": "TEXT", "authors": "TEXT", "isbn": "TEXT", "publisher": "TEXT", "pub_date": "TEXT",
    "pub_year": "INTEGER", "pages": "INTEGER", "language": "TEXT", "format": "TEXT",
    "subjects": "TEXT", "tags": "TEXT", "plot": "TEXT", "cover_url": "TEXT", "cover_file": "TEXT",
    "status": "TEXT DEFAULT 'collection'", "read": "INTEGER DEFAULT 0", "read_date": "TEXT",
    "rating": "INTEGER DEFAULT 0", "location": "TEXT", "owner": "TEXT", "purchase_date": "TEXT",
    "purchase_price": "TEXT", "store": "TEXT", "cover_price": "TEXT", "quantity": "INTEGER DEFAULT 1",
    "dewey": "TEXT", "notes": "TEXT", "source": "TEXT", "added_at": "INTEGER", "modified_at": "INTEGER",
}
JSON_COLS = {"authors", "subjects", "tags"}
EDITABLE = [c for c in COLUMNS if c not in ("cover_file", "added_at", "modified_at", "clz_hash")]
LIST_COLS = ["id", "title", "subtitle", "series", "authors", "isbn", "publisher", "pub_year", "language",
             "format", "status", "read", "rating", "location", "cover_url", "cover_file", "added_at", "pages"]

write_lock = threading.Lock()


def db():
    con = sqlite3.connect(DB_PATH, timeout=30)
    con.row_factory = sqlite3.Row
    return con


def init_db():
    os.makedirs(COVER_DIR, exist_ok=True)
    with db() as con:
        cols = ", ".join(f"{k} {v}" for k, v in COLUMNS.items())
        con.execute(f"CREATE TABLE IF NOT EXISTS books (id INTEGER PRIMARY KEY AUTOINCREMENT, {cols})")
        have = {r["name"] for r in con.execute("PRAGMA table_info(books)")}
        for k, v in COLUMNS.items():  # forward-compatible schema upgrades
            if k not in have:
                con.execute(f"ALTER TABLE books ADD COLUMN {k} {v}")
        con.execute("CREATE INDEX IF NOT EXISTS ix_books_isbn ON books(isbn)")
        con.execute("CREATE INDEX IF NOT EXISTS ix_books_clz ON books(clz_hash)")
        con.execute("CREATE TABLE IF NOT EXISTS authors (name TEXT PRIMARY KEY, data TEXT, fetched_at INTEGER)")


def row_to_dict(row):
    d = dict(row)
    for c in JSON_COLS:
        if c in d:
            try:
                d[c] = json.loads(d[c]) if d[c] else []
            except ValueError:
                d[c] = []
    # Always serve covers through the app (CLZ's CDN blocks images shown on other sites).
    # The ?v= part changes when the cover URL changes, so browsers pick up a new cover.
    if d.get("cover_url") or d.get("cover_file"):
        d["cover"] = f"covers/{d['id']}?v={zlib.crc32((d.get('cover_url') or '').encode()):x}"
    else:
        d["cover"] = ""
    return d


def clean_values(data):
    out = {}
    for k in EDITABLE:
        if k not in data:
            continue
        v = data[k]
        if k in JSON_COLS:
            if isinstance(v, str):
                v = [s.strip() for s in re.split(r"[;\n]", v) if s.strip()]
            v = json.dumps(v or [], ensure_ascii=False)
        elif k in ("pub_year", "pages", "rating", "quantity", "read"):
            try:
                v = int(v) if v not in (None, "") else None
            except (TypeError, ValueError):
                v = None
            if k == "read":
                v = 1 if v else 0
        elif k == "isbn":
            v = lookup.clean_isbn(v)
        elif v is None:
            v = ""
        else:
            v = str(v).strip()
        out[k] = v
    return out


def insert_book(con, data):
    vals = clean_values(data)
    vals.setdefault("status", "collection")
    vals["added_at"] = int(data.get("added_at") or time.time())
    vals["modified_at"] = int(time.time())
    if data.get("clz_hash"):
        vals["clz_hash"] = data["clz_hash"]
    keys = list(vals)
    cur = con.execute(f"INSERT INTO books ({', '.join(keys)}) VALUES ({', '.join('?' for _ in keys)})",
                      [vals[k] for k in keys])
    return cur.lastrowid


def update_book(con, book_id, data):
    vals = clean_values(data)
    if data.get("clz_hash"):
        vals["clz_hash"] = data["clz_hash"]
    if not vals:
        return
    old =con.execute("SELECT cover_url FROM books WHERE id=?", (book_id,)).fetchone()
    if old and "cover_url" in vals and vals["cover_url"] != (old["cover_url"] or ""):
        vals["cover_file"] = ""  # new cover → re-cache
    vals["modified_at"] = int(time.time())
    sets = ", ".join(f"{k}=?" for k in vals)
    con.execute(f"UPDATE books SET {sets} WHERE id=?", [*vals.values(), book_id])


def get_book(con, book_id):
    row = con.execute("SELECT * FROM books WHERE id=?", (book_id,)).fetchone()
    return row_to_dict(row) if row else None


# ------------------------------------------------------------------ covers

cover_state = {"running": False, "done": 0, "total": 0, "failed": 0}
cover_event = threading.Event()
cover_failed = set()  # ids that failed this session; cleared by "Retry missing covers"


def _download_cover(book_id, url):
    req = urllib.request.Request(url, headers={"User-Agent": lookup.USER_AGENT})
    with urllib.request.urlopen(req, timeout=20) as resp:
        data = resp.read()
        ctype = resp.headers.get("Content-Type", "")
    if len(data) < 200 or not ctype.startswith("image/"):
        raise ValueError("not an image")
    ext = ".png" if "png" in ctype else ".webp" if "webp" in ctype else ".jpg"
    name = f"{book_id}{ext}"
    with open(os.path.join(COVER_DIR, name), "wb") as f:
        f.write(data)
    return name


def cover_worker():
    """Keeps a local copy of every cover, so they survive if CLZ/Open Library links die."""
    failed_ids = cover_failed
    while True:
        cover_event.wait(timeout=600)
        cover_event.clear()
        if not OPTIONS.get("cache_covers", True):
            continue
        with db() as con:
            todo = [(r["id"], r["cover_url"]) for r in con.execute(
                "SELECT id, cover_url FROM books WHERE cover_url != '' AND cover_url IS NOT NULL "
                "AND (cover_file IS NULL OR cover_file = '')") if r["id"] not in failed_ids]
        with db() as con:
            missing = [(r["id"], r["isbn"]) for r in con.execute(
                "SELECT id, isbn FROM books WHERE (cover_url IS NULL OR cover_url='') AND isbn != '' "
                "AND isbn IS NOT NULL") if r["id"] not in failed_ids]
        for book_id, isbn in missing:  # books without a cover: try Open Library by ISBN
            url = f"https://covers.openlibrary.org/b/isbn/{isbn}-L.jpg?default=false"
            try:
                name = _download_cover(book_id, url)
                with write_lock, db() as con:
                    con.execute("UPDATE books SET cover_url=?, cover_file=? WHERE id=?", (url, name, book_id))
            except Exception:
                failed_ids.add(book_id)
        if not todo:
            continue
        cover_state.update(running=True, done=0, total=len(todo), failed=0)
        for book_id, url in todo:
            try:
                name = _download_cover(book_id, url)
                with write_lock, db() as con:
                    con.execute("UPDATE books SET cover_file=? WHERE id=?", (name, book_id))
            except Exception as exc:
                failed_ids.add(book_id)
                cover_state["failed"] += 1
                print(f"[covers] book {book_id}: {exc}", flush=True)
            cover_state["done"] += 1
            time.sleep(0.15)
        cover_state["running"] = False
        publish_sensors()


# ------------------------------------------------------------------ HA sensors

def stats():
    with db() as con:
        q = lambda sql: con.execute(sql).fetchone()[0]  # noqa: E731
        last = con.execute("SELECT title, authors FROM books WHERE status='collection' "
                           "ORDER BY added_at DESC, id DESC LIMIT 1").fetchone()
        return {
            "total": q("SELECT COUNT(*) FROM books WHERE status='collection'"),
            "read": q("SELECT COUNT(*) FROM books WHERE status='collection' AND read=1"),
            "unread": q("SELECT COUNT(*) FROM books WHERE status='collection' AND read=0"),
            "wishlist": q("SELECT COUNT(*) FROM books WHERE status='wishlist'"),
            "authors": len({a for r in con.execute("SELECT authors FROM books WHERE status='collection'")
                            for a in json.loads(r[0] or "[]")}),
            "pages": q("SELECT COALESCE(SUM(pages),0) FROM books WHERE status='collection'"),
            "last_added": (f"{last['title']} — {', '.join(json.loads(last['authors'] or '[]'))}" if last else ""),
        }


def _ha_post(entity_id, state, attributes):
    token = os.environ.get("SUPERVISOR_TOKEN")
    if not token:
        return
    body = json.dumps({"state": state, "attributes": attributes}).encode()
    req = urllib.request.Request(f"http://supervisor/core/api/states/{entity_id}", data=body, method="POST",
                                 headers={"Authorization": f"Bearer {token}", "Content-Type": "application/json"})
    urllib.request.urlopen(req, timeout=10).read()


def publish_sensors():
    if not OPTIONS.get("publish_sensors", True) or not os.environ.get("SUPERVISOR_TOKEN"):
        return
    try:
        s = stats()
        base = {"icon": "mdi:bookshelf", "unit_of_measurement": "books", "state_class": "measurement"}
        _ha_post("sensor.books_total", s["total"], {**base, "friendly_name": "Books in collection",
                                                     "read": s["read"], "unread": s["unread"],
                                                     "authors": s["authors"], "pages": s["pages"],
                                                     "last_added": s["last_added"]})
        _ha_post("sensor.books_unread", s["unread"], {**base, "friendly_name": "Books unread",
                                                       "icon": "mdi:book-clock"})
        _ha_post("sensor.books_wishlist", s["wishlist"], {**base, "friendly_name": "Books on wishlist",
                                                           "icon": "mdi:book-heart"})
        _ha_post("sensor.books_last_added", s["last_added"] or "none",
                 {"friendly_name": "Last book added", "icon": "mdi:book-plus"})
    except Exception as exc:
        print(f"[sensors] publish failed: {exc}", flush=True)


def sensor_loop():
    while True:
        publish_sensors()  # states set via the API vanish when HA restarts, so refresh regularly
        time.sleep(300)


# ------------------------------------------------------------------ HTTP

class Handler(BaseHTTPRequestHandler):
    server_version = f"HA-Books/{VERSION}"

    def log_message(self, fmt, *args):  # quieter logs: only errors
        if args and str(args[1] if len(args) > 1 else "").startswith(("4", "5")):
            sys.stderr.write("[http] " + fmt % args + "\n")

    # -- helpers
    def send_json(self, obj, status=200):
        body = json.dumps(obj, ensure_ascii=False).encode("utf-8")
        self.send_response(status)
        self.send_header("Content-Type", "application/json; charset=utf-8")
        self.send_header("Cache-Control", "no-store")
        self.send_header("Content-Length", str(len(body)))
        self.end_headers()
        self.wfile.write(body)

    def send_file(self, path, cache="no-cache", download_name=None):
        if not os.path.isfile(path):
            return self.send_json({"error": "not found"}, 404)
        ctype = mimetypes.guess_type(path)[0] or "application/octet-stream"
        if ctype.startswith("text/") or ctype in ("application/javascript",):
            ctype += "; charset=utf-8"
        with open(path, "rb") as f:
            data = f.read()
        self.send_response(200)
        self.send_header("Content-Type", ctype)
        self.send_header("Cache-Control", cache)
        self.send_header("Content-Length", str(len(data)))
        if download_name:
            self.send_header("Content-Disposition", f'attachment; filename="{download_name}"')
        self.end_headers()
        self.wfile.write(data)

    def send_bytes(self, data, ctype, download_name):
        self.send_response(200)
        self.send_header("Content-Type", ctype)
        self.send_header("Content-Length", str(len(data)))
        self.send_header("Content-Disposition", f'attachment; filename="{download_name}"')
        self.end_headers()
        self.wfile.write(data)

    def serve_cover(self, book_id):
        with db() as con:
            row = con.execute("SELECT cover_url, cover_file FROM books WHERE id=?", (book_id,)).fetchone()
        if not row:
            return self.send_json({"error": "not found"}, 404)
        name = row["cover_file"]
        if not (name and os.path.isfile(os.path.join(COVER_DIR, name))) and row["cover_url"]:
            try:  # not cached yet: fetch it now and keep it
                name = _download_cover(book_id, row["cover_url"])
                with write_lock, db() as con:
                    con.execute("UPDATE books SET cover_file=? WHERE id=?", (name, book_id))
            except Exception as exc:
                print(f"[covers] book {book_id}: {exc}", flush=True)
                name = None
        if not name:
            return self.send_json({"error": "no cover"}, 404)
        return self.send_file(os.path.join(COVER_DIR, name), cache="max-age=604800")

    def body(self):
        n = int(self.headers.get("Content-Length") or 0)
        return self.rfile.read(n) if n else b""

    def json_body(self):
        try:
            return json.loads(self.body() or b"{}")
        except ValueError:
            return {}

    def route(self):
        parsed = urllib.parse.urlparse(self.path)
        path = re.sub(r"/+", "/", parsed.path)
        return path.rstrip("/") or "/", {k: v[-1] for k, v in urllib.parse.parse_qs(parsed.query).items()}

    def guarded(self, fn):
        try:
            fn()
        except Exception as exc:
            traceback.print_exc()
            try:
                self.send_json({"error": str(exc)}, 500)
            except Exception:
                pass

    # -- verbs
    def do_GET(self):
        self.guarded(self._get)

    def do_POST(self):
        self.guarded(self._post)

    def do_PUT(self):
        self.guarded(self._put)

    def do_DELETE(self):
        self.guarded(self._delete)

    def _get(self):
        path, q = self.route()
        if path in ("/", "/index.html"):
            return self.send_file(os.path.join(STATIC_DIR, "index.html"))
        if path.startswith("/static/"):
            name = os.path.basename(path)
            return self.send_file(os.path.join(STATIC_DIR, name), cache="max-age=3600")
        m = re.fullmatch(r"/covers/(\d+)", path)
        if m:
            return self.serve_cover(int(m.group(1)))
        if path.startswith("/covers/"):
            name = os.path.basename(path)
            return self.send_file(os.path.join(COVER_DIR, name), cache="max-age=604800")
        if path == "/api/books":
            with db() as con:
                rows = con.execute(f"SELECT {', '.join(LIST_COLS)} FROM books").fetchall()
            return self.send_json([row_to_dict(r) for r in rows])
        m = re.fullmatch(r"/api/books/(\d+)", path)
        if m:
            with db() as con:
                book = get_book(con, int(m.group(1)))
            return self.send_json(book) if book else self.send_json({"error": "not found"}, 404)
        if path == "/api/lookup/isbn":
            isbn = lookup.clean_isbn(q.get("isbn", ""))
            if len(isbn) not in (10, 13):
                return self.send_json({"error": "An ISBN has 10 or 13 digits"}, 400)
            with db() as con:
                dupes = [dict(r) for r in con.execute(
                    "SELECT id, title FROM books WHERE isbn IN (%s)" % ",".join("?" * len(lookup.isbn_variants(isbn))),
                    lookup.isbn_variants(isbn))]
            warn = []
            res = lookup.lookup_isbn(isbn, OPTIONS.get("google_books_api_key", ""), warn)
            return self.send_json({"results": res, "already_have": dupes, "warnings": warn})
        if path == "/api/lookup/search":
            warn = []
            res = lookup.search(q.get("title", "").strip(), q.get("author", "").strip(), q.get("q", "").strip(),
                                OPTIONS.get("google_books_api_key", ""), warn)
            return self.send_json({"results": res, "warnings": warn})
        if path == "/api/author":
            name = q.get("name", "").strip()
            if not name:
                return self.send_json({"error": "name required"}, 400)
            with db() as con:
                row = con.execute("SELECT data, fetched_at FROM authors WHERE name=?", (name,)).fetchone()
            if row and not q.get("refresh") and time.time() - row["fetched_at"] < 90 * 86400:
                info = json.loads(row["data"])
            else:
                info = lookup.author_details(name, OPTIONS.get("language", "nl"))
                with write_lock, db() as con:
                    con.execute("INSERT OR REPLACE INTO authors (name, data, fetched_at) VALUES (?,?,?)",
                                (name, json.dumps(info, ensure_ascii=False), int(time.time())))
            return self.send_json(info)
        if path == "/api/stats":
            return self.send_json({**stats(), "covers": cover_state, "version": VERSION})
        if path == "/api/export.json":
            with db() as con:
                rows = [row_to_dict(r) for r in con.execute("SELECT * FROM books ORDER BY title")]
            for r in rows:
                r.pop("cover", None)
            return self.send_bytes(json.dumps(rows, ensure_ascii=False, indent=1).encode(), "application/json",
                                   f"books-{time.strftime('%Y%m%d')}.json")
        if path == "/api/export.csv":
            with db() as con:
                rows = [row_to_dict(r) for r in con.execute("SELECT * FROM books ORDER BY title")]
            buf = io.StringIO()
            cols = ["id"] + list(COLUMNS)
            w = csv.DictWriter(buf, fieldnames=cols, extrasaction="ignore", delimiter=";")
            w.writeheader()
            for r in rows:
                for c in JSON_COLS:
                    r[c] = "; ".join(r.get(c) or [])
                w.writerow(r)
            return self.send_bytes(("﻿" + buf.getvalue()).encode("utf-8"), "text/csv",
                                   f"books-{time.strftime('%Y%m%d')}.csv")
        return self.send_json({"error": "not found"}, 404)

    def _post(self):
        path, q = self.route()
        if path == "/api/books":
            data = self.json_body()
            if not (data.get("title") or "").strip():
                return self.send_json({"error": "A title is required"}, 400)
            with write_lock, db() as con:
                book_id = insert_book(con, data)
                book = get_book(con, book_id)
            cover_event.set()
            threading.Thread(target=publish_sensors, daemon=True).start()
            return self.send_json(book, 201)
        if path == "/api/import/clz":
            raw = self.body()
            try:
                books = clz.parse(raw)
            except Exception as exc:
                return self.send_json({"error": f"Could not read this file as a CLZ XML export: {exc}"}, 400)
            added = updated = 0
            with write_lock, db() as con:
                for b in books:
                    # CLZ's per-copy hash is unique (clz_id is shared by duplicate copies)
                    row = None
                    if b["clz_hash"]:
                        row = con.execute("SELECT id FROM books WHERE clz_hash=?", (b["clz_hash"],)).fetchone()
                    if not row and b["isbn"]:  # a book you added by hand before importing
                        row = con.execute("SELECT id FROM books WHERE isbn=? AND (clz_hash IS NULL OR clz_hash='')",
                                          (b["isbn"],)).fetchone()
                    if row:
                        update_book(con, row["id"], b)
                        updated += 1
                    else:
                        insert_book(con, b)
                        added += 1
            cover_event.set()
            threading.Thread(target=publish_sensors, daemon=True).start()
            return self.send_json({"added": added, "updated": updated, "total": len(books)})
        if path == "/api/covers/retry":
            cover_failed.clear()
            cover_event.set()
            return self.send_json({"ok": True})
        return self.send_json({"error": "not found"}, 404)

    def _put(self):
        path, _ = self.route()
        m = re.fullmatch(r"/api/books/(\d+)", path)
        if not m:
            return self.send_json({"error": "not found"}, 404)
        with write_lock, db() as con:
            update_book(con, int(m.group(1)), self.json_body())
            book = get_book(con, int(m.group(1)))
        cover_event.set()
        threading.Thread(target=publish_sensors, daemon=True).start()
        return self.send_json(book) if book else self.send_json({"error": "not found"}, 404)

    def _delete(self):
        path, _ = self.route()
        m = re.fullmatch(r"/api/books/(\d+)", path)
        if not m:
            return self.send_json({"error": "not found"}, 404)
        with write_lock, db() as con:
            row = con.execute("SELECT cover_file FROM books WHERE id=?", (int(m.group(1)),)).fetchone()
            con.execute("DELETE FROM books WHERE id=?", (int(m.group(1)),))
        if row and row["cover_file"]:
            try:
                os.remove(os.path.join(COVER_DIR, row["cover_file"]))
            except OSError:
                pass
        threading.Thread(target=publish_sensors, daemon=True).start()
        return self.send_json({"ok": True})


def main():
    init_db()
    threading.Thread(target=cover_worker, daemon=True).start()
    threading.Thread(target=sensor_loop, daemon=True).start()
    cover_event.set()
    print(f"[books] v{VERSION} listening on :{PORT}, data in {DATA_DIR}", flush=True)
    ThreadingHTTPServer(("0.0.0.0", PORT), Handler).serve_forever()


if __name__ == "__main__":
    main()
