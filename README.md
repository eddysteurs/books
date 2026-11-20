# Books — Home Assistant app

A self-hosted book collection catalogue for Home Assistant, as an alternative to CLZ Books.
Add books by ISBN (with barcode scanning) or by author and title, with details looked up on
Open Library and Google Books; author biographies from Open Library and Wikipedia; CLZ XML import.

## Install

1. In Home Assistant: **Settings → Apps → App store → ⋮ → Repositories**
2. Add `https://github.com/eddysteurs/books`
3. Find **Books** in the store, install it, enable **Show in sidebar**, and start it.
4. Open **Books** in the sidebar → ⋮ → **Import CLZ export (XML)**.

See [books/DOCS.md](books/DOCS.md) for features, options and sensors.

## Layout

```
repository.yaml        app repository manifest
books/                 the app
  config.yaml          app configuration (ingress, options)
  Dockerfile           Alpine base + Python 3 (standard library only)
  app/server.py        HTTP server, SQLite storage, CLZ import, covers, HA sensors
  app/lookup.py        Open Library / Google Books / Wikipedia lookups
  app/clz.py           CLZ XML parser
  app/static/          web UI (zxing-js 0.21.3 for barcode scanning, MIT/Apache-2.0)
```

## Develop locally

```
BOOKS_DATA=/tmp/books python3 books/app/server.py   # → http://localhost:8099
```
