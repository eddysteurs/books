"""Parse a CLZ Books / Book Collector XML export into the app's book shape."""
import xml.etree.ElementTree as ET

from lookup import norm_language


def _t(el, path):
    v = el.findtext(path)
    return v.strip() if v else ""


def _date(el, path):
    """CLZ dates look like <x><date>1986/01/01</date>...</x>; return ISO yyyy-mm-dd."""
    d = _t(el, path + "/date")
    if d:
        return d.replace("/", "-")
    y = _t(el, path + "/year/displayname")
    return y


def _num(text, cast=int):
    try:
        v = cast(text)
        return v if v else None
    except (TypeError, ValueError):
        return None


def parse(xml_bytes):
    root = ET.fromstring(xml_bytes)
    books = []
    for b in root.iter("book"):
        if b.find("mainsection") is None:
            continue
        ms = b.find("mainsection")
        authors = [_t(c, "person/displayname") for c in ms.findall("credits/credit")
                   if _t(c, "roleid") in ("dfAuthor", "") and _t(c, "person/displayname")]
        others = [f"{_t(c, 'person/displayname')} ({_t(c, 'role')})" for c in ms.findall("credits/credit")
                  if _t(c, "roleid") not in ("dfAuthor", "")]
        subjects = [_t(s, "displayname") for s in b.findall("subjects/subject") if _t(s, "displayname")]
        genres = [_t(g, "displayname") for g in b.findall("genres/genre") if _t(g, "displayname")]
        tags = [_t(t, "displayname") for t in b.findall("tags/tag") if _t(t, "displayname")]
        status = _t(b, "collectionstatus").lower()
        read_dates = []
        for r in b.findall("readhistory/readdate"):
            y, m, d = _t(r, "date/year"), _t(r, "date/month"), _t(r, "date/day")
            if y:
                read_dates.append("-".join(p for p in (y, m.zfill(2) if m else "", d.zfill(2) if d else "") if p))
        read_date = _date(b, "readingdate") or (max(read_dates) if read_dates else "")
        rating = _num(_t(ms, "myrating"))
        pub_date = _date(b, "publicationdate")
        notes = _t(b, "notes")
        if others:
            notes = (notes + "\n" if notes else "") + "Other credits: " + ", ".join(others)
        books.append({
            "clz_id": _t(b, "clzbookid"),
            "clz_hash": _t(b, "hash"),
            "title": _t(ms, "title"),
            "subtitle": _t(ms, "subtitle"),
            "series": _t(b, "series/displayname"),
            "authors": authors,
            "isbn": _t(b, "isbn").replace("-", ""),
            "publisher": _t(b, "publisher/displayname"),
            "pub_date": pub_date,
            "pub_year": _num(_t(b, "publicationdate/year/displayname")),
            "pages": _num(_t(ms, "pagecount")),
            "language": norm_language(_t(b, "language/displayname")),
            "format": _t(b, "format/displayname"),
            "subjects": subjects + [g for g in genres if g not in subjects],
            "tags": tags,
            "plot": _t(ms, "plot"),
            "cover_url": _t(b, "coverfrontdefault"),
            "status": "wishlist" if "wish" in status else "collection",
            "read": 1 if _t(b, "readit").lower() in ("yes", "1", "true") else 0,
            "read_date": read_date,
            "rating": round(rating / 2) if rating else 0,  # CLZ uses 0-10, we use 0-5 stars
            "location": _t(b, "location/displayname"),
            "owner": _t(b, "owner/displayname"),
            "purchase_date": _date(b, "purchasedate"),
            "purchase_price": _t(b, "purchaseprice"),
            "store": _t(b, "store/displayname"),
            "cover_price": _t(b, "coverprice"),
            "quantity": _num(_t(b, "quantity")) or 1,
            "dewey": _t(b, "dewey"),
            "notes": notes,
            "added_at": _num(_t(b, "addeddate/timestamp")),
            "source": "CLZ import",
        })
    return books
