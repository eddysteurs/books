"""Online metadata lookups: Open Library, Google Books and Wikipedia.

Every public function returns plain dicts in the app's own "book" shape so the
UI never has to care which source a result came from.
"""
import json
import re
import urllib.parse
import urllib.request

USER_AGENT = "HA-Books/0.1 (+https://github.com/eddysteurs/books)"
TIMEOUT = 12

LANG_NAMES = {
    "nl": "Dutch", "dut": "Dutch", "nld": "Dutch", "nederlands": "Dutch",
    "en": "English", "eng": "English", "engels": "English",
    "fr": "French", "fre": "French", "fra": "French", "frans": "French",
    "de": "German", "ger": "German", "deu": "German", "duits": "German",
    "es": "Spanish", "spa": "Spanish", "it": "Italian", "ita": "Italian",
}


def norm_language(value):
    if not value:
        return ""
    v = str(value).strip()
    key = v.lower().rsplit("/", 1)[-1]
    return LANG_NAMES.get(key, v[:1].upper() + v[1:])


def _get_json(url, params=None):
    if params:
        url = url + "?" + urllib.parse.urlencode(params)
    req = urllib.request.Request(url, headers={"User-Agent": USER_AGENT, "Accept": "application/json"})
    with urllib.request.urlopen(req, timeout=TIMEOUT) as resp:
        return json.loads(resp.read().decode("utf-8"))


def _safe(fn, *args, warnings=None, **kwargs):
    try:
        return fn(*args, **kwargs)
    except Exception as exc:  # network errors must never break the UI
        print(f"[lookup] {fn.__name__} failed: {exc}", flush=True)
        if warnings is not None:
            src = "Google Books" if fn.__name__.startswith("_gb") else "Open Library"
            if getattr(exc, "code", None) == 429 and src == "Google Books":
                warnings.append("Google Books refused the lookup (rate limit). Add a free Google Books "
                                "API key in the app's Configuration tab to fix this.")
            else:
                warnings.append(f"{src} could not be reached ({exc}).")
        return None


# ---------------------------------------------------------------- ISBN helpers

def clean_isbn(value):
    return re.sub(r"[^0-9Xx]", "", value or "").upper()


def isbn10_to_13(isbn10):
    if len(isbn10) != 10:
        return None
    core = "978" + isbn10[:9]
    total = sum((1 if i % 2 == 0 else 3) * int(c) for i, c in enumerate(core))
    return core + str((10 - total % 10) % 10)


def isbn13_to_10(isbn13):
    if len(isbn13) != 13 or not isbn13.startswith("978"):
        return None
    core = isbn13[3:12]
    total = sum((10 - i) * int(c) for i, c in enumerate(core))
    check = (11 - total % 11) % 11
    return core + ("X" if check == 10 else str(check))


def isbn_variants(value):
    isbn = clean_isbn(value)
    out = [isbn]
    other = isbn10_to_13(isbn) if len(isbn) == 10 else isbn13_to_10(isbn)
    if other:
        out.append(other)
    return [i for i in out if i]


def _year(text):
    m = re.search(r"(\d{4})", text or "")
    return int(m.group(1)) if m else None


def _empty_book(source):
    return {
        "source": source, "title": "", "subtitle": "", "authors": [], "isbn": "",
        "publisher": "", "pub_year": None, "pub_date": "", "pages": None,
        "language": "", "subjects": [], "plot": "", "cover_url": "", "link": "",
    }


# ---------------------------------------------------------------- Open Library

def _ol_isbn(isbn):
    data = _get_json("https://openlibrary.org/api/books",
                     {"bibkeys": f"ISBN:{isbn}", "format": "json", "jscmd": "data"})
    rec = (data or {}).get(f"ISBN:{isbn}")
    if not rec:
        return None
    b = _empty_book("Open Library")
    b["title"] = rec.get("title", "")
    b["subtitle"] = rec.get("subtitle", "")
    b["authors"] = [a.get("name", "") for a in rec.get("authors", []) if a.get("name")]
    b["publisher"] = ", ".join(p.get("name", "") for p in rec.get("publishers", [])[:2])
    b["pub_date"] = rec.get("publish_date", "")
    b["pub_year"] = _year(b["pub_date"])
    b["pages"] = rec.get("number_of_pages")
    b["subjects"] = [s.get("name") for s in rec.get("subjects", [])[:8] if s.get("name")]
    cover = rec.get("cover") or {}
    b["cover_url"] = cover.get("large") or cover.get("medium") or ""
    b["link"] = rec.get("url", "")
    ids = rec.get("identifiers", {})
    b["isbn"] = (ids.get("isbn_13") or [isbn])[0]
    # description + language live on the edition/work records
    ed = _safe(_get_json, f"https://openlibrary.org/isbn/{isbn}.json") or {}
    langs = ed.get("languages") or []
    if langs:
        b["language"] = norm_language(langs[0].get("key", ""))
    desc = ed.get("description")
    if not desc and ed.get("works"):
        work = _safe(_get_json, f"https://openlibrary.org{ed['works'][0]['key']}.json") or {}
        desc = work.get("description")
    if isinstance(desc, dict):
        desc = desc.get("value")
    b["plot"] = desc or ""
    return b


def _ol_search(title="", author="", q="", limit=10):
    params = {"limit": limit, "fields": "key,title,subtitle,author_name,first_publish_year,isbn,"
              "cover_i,publisher,language,number_of_pages_median,subject"}
    if q:
        params["q"] = q
    if title:
        params["title"] = title
    if author:
        params["author"] = author
    data = _get_json("https://openlibrary.org/search.json", params) or {}
    out = []
    for d in data.get("docs", []):
        b = _empty_book("Open Library")
        b["title"] = d.get("title", "")
        b["subtitle"] = d.get("subtitle", "")
        b["authors"] = d.get("author_name", [])[:4]
        isbns = d.get("isbn") or []
        isbn13 = [i for i in isbns if len(i) == 13]
        b["isbn"] = (isbn13 or isbns or [""])[0]
        b["publisher"] = (d.get("publisher") or [""])[0]
        b["pub_year"] = d.get("first_publish_year")
        b["pages"] = d.get("number_of_pages_median")
        b["language"] = norm_language((d.get("language") or [""])[0])
        b["subjects"] = (d.get("subject") or [])[:8]
        if d.get("cover_i"):
            b["cover_url"] = f"https://covers.openlibrary.org/b/id/{d['cover_i']}-L.jpg"
        b["link"] = "https://openlibrary.org" + d.get("key", "")
        out.append(b)
    return out


# ---------------------------------------------------------------- Google Books

def _gb_item(item):
    v = item.get("volumeInfo", {})
    b = _empty_book("Google Books")
    b["title"] = v.get("title", "")
    b["subtitle"] = v.get("subtitle", "")
    b["authors"] = v.get("authors", [])
    ids = {i.get("type"): i.get("identifier") for i in v.get("industryIdentifiers", [])}
    b["isbn"] = ids.get("ISBN_13") or ids.get("ISBN_10") or ""
    b["publisher"] = v.get("publisher", "")
    b["pub_date"] = v.get("publishedDate", "")
    b["pub_year"] = _year(b["pub_date"])
    b["pages"] = v.get("pageCount")
    b["language"] = norm_language(v.get("language", ""))
    b["subjects"] = v.get("categories", [])
    b["plot"] = re.sub(r"<[^>]+>", "", v.get("description", ""))
    imgs = v.get("imageLinks", {})
    cover = imgs.get("thumbnail") or imgs.get("smallThumbnail") or ""
    if cover:
        cover = cover.replace("http://", "https://").replace("&edge=curl", "")
    b["cover_url"] = cover
    b["link"] = v.get("infoLink", "")
    return b


def _gb_query(query, api_key="", limit=10):
    params = {"q": query, "maxResults": limit, "printType": "books"}
    if api_key:
        params["key"] = api_key
    data = _get_json("https://www.googleapis.com/books/v1/volumes", params) or {}
    return [_gb_item(i) for i in data.get("items", [])]


# ---------------------------------------------------------------- public API

FIELDS_TO_MERGE = ["title", "subtitle", "authors", "isbn", "publisher", "pub_year", "pub_date",
                   "pages", "language", "subjects", "plot", "cover_url"]


def merge(primary, *others):
    """Fill empty fields of `primary` from the other results."""
    out = dict(primary)
    for o in others:
        for f in FIELDS_TO_MERGE:
            if not out.get(f) and o.get(f):
                out[f] = o[f]
    return out


def lookup_isbn(isbn, api_key="", warnings=None):
    """Look a book up by ISBN. Returns a list: merged best result first, then per-source results."""
    results = []
    for variant in isbn_variants(isbn):
        ol = _safe(_ol_isbn, variant, warnings=warnings)
        if ol:
            results.append(ol)
            break
    gb = _safe(_gb_query, f"isbn:{clean_isbn(isbn)}", api_key, 3, warnings=warnings) or []
    results.extend(gb[:1])
    if not results:
        return []
    best = merge(*results)
    best["source"] = " + ".join(r["source"] for r in results)
    if not best.get("isbn"):
        best["isbn"] = clean_isbn(isbn)
    return [best] + (results if len(results) > 1 else [])


def search(title="", author="", q="", api_key="", warnings=None):
    """Free-text / title+author search across both sources, interleaved."""
    gb_query = q or " ".join(filter(None, [f"intitle:{title}" if title else "",
                                           f"inauthor:{author}" if author else ""]))
    gb = (_safe(_gb_query, gb_query, api_key, 10, warnings=warnings) or []) if gb_query else []
    ol = _safe(_ol_search, title, author, q, 10, warnings=warnings) or []
    out, seen = [], set()
    for i in range(max(len(gb), len(ol))):
        for lst in (gb, ol):
            if i < len(lst):
                b = lst[i]
                key = (b["title"].lower().strip(), b["isbn"])
                if key not in seen:
                    seen.add(key)
                    out.append(b)
    return out


def author_details(name, lang="nl"):
    """Biography, dates and photo for an author (Open Library + Wikipedia)."""
    info = {"name": name, "bio": "", "bio_source": "", "birth_date": "", "death_date": "",
            "photo_url": "", "links": [], "work_count": None, "top_work": ""}
    data = _safe(_get_json, "https://openlibrary.org/search/authors.json", {"q": name, "limit": 1}) or {}
    docs = data.get("docs") or []
    if docs:
        d = docs[0]
        key = d.get("key", "")
        info.update(birth_date=d.get("birth_date", ""), death_date=d.get("death_date", ""),
                    work_count=d.get("work_count"), top_work=d.get("top_work", ""))
        if key:
            info["links"].append({"label": "Open Library", "url": f"https://openlibrary.org/authors/{key}"})
            rec = _safe(_get_json, f"https://openlibrary.org/authors/{key}.json") or {}
            bio = rec.get("bio")
            if isinstance(bio, dict):
                bio = bio.get("value")
            if bio:
                info["bio"], info["bio_source"] = bio, "Open Library"
            photos = [p for p in rec.get("photos", []) if isinstance(p, int) and p > 0]
            if photos:
                info["photo_url"] = f"https://covers.openlibrary.org/a/id/{photos[0]}-M.jpg"
    for wl in dict.fromkeys([lang or "en", "en"]):
        title = urllib.parse.quote(name.replace(" ", "_"))
        wiki = _safe(_get_json, f"https://{wl}.wikipedia.org/api/rest_v1/page/summary/{title}")
        if wiki and wiki.get("type") != "disambiguation" and wiki.get("extract"):
            page = (wiki.get("content_urls") or {}).get("desktop", {}).get("page", "")
            if page:
                info["links"].append({"label": f"Wikipedia ({wl})", "url": page})
            if not info["bio"] or wl == lang:
                info["bio"], info["bio_source"] = wiki["extract"], f"Wikipedia ({wl})"
            if not info["photo_url"]:
                info["photo_url"] = (wiki.get("thumbnail") or {}).get("source", "")
            break
    return info
