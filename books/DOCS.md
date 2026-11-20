# Books

A book-collection catalogue that lives in your Home Assistant sidebar — a self-hosted
replacement for CLZ Books / Book Collector.

## Features

- **Add by ISBN**: type it, use a USB barcode scanner, or tap **📷 Scan** to use the phone camera.
  Details (title, authors, publisher, year, pages, language, description, cover) come from
  **Open Library** and **Google Books**; you see every match and pick the right one.
- **Add by author & title** when there's no barcode, or **manually**.
- **Author details**: click an author for biography, dates and photo (Open Library + Wikipedia
  in your language), plus every book of theirs that you own.
- **Fill missing from internet** in the edit screen fills only the empty fields of an existing book.
- Read / unread, rating, wishlist, location, owner, purchase info, tags, notes.
- **CLZ import**: ⋮ menu → *Import CLZ export (XML)*. Importing again updates the same books
  (matched on CLZ's per-copy ID) instead of creating duplicates. Note that it overwrites
  fields with CLZ's values, so stop editing in CLZ once you've moved over.
- Covers are **downloaded and stored locally**, so they keep working if CLZ links disappear.
- Export to CSV (opens in Excel) or JSON at any time.
- Everything is stored in the app's `/data` folder and is **included in Home Assistant backups**.

## Sensors

When *publish_sensors* is on, the app keeps these entities up to date (refreshed every 5 minutes
and after every change):

| Entity | State | Attributes |
|---|---|---|
| `sensor.books_total` | books in collection | read, unread, authors, pages, last_added |
| `sensor.books_unread` | unread books | |
| `sensor.books_wishlist` | books on wishlist | |
| `sensor.books_last_added` | "Title — Author" | |

These are set through the HA API, so they have no unique ID and can't be renamed in the UI.

## Options

| Option | Default | |
|---|---|---|
| `language` | `nl` | Wikipedia language used first for author biographies (`nl`, `fr`, `en`, `de`…) |
| `google_books_api_key` | empty | Optional. Only needed if you hit Google's anonymous rate limit |
| `publish_sensors` | `true` | Create the sensors above |
| `cache_covers` | `true` | Store a local copy of every cover |

## Barcode scanning tips

- In the **Home Assistant companion app** the live camera may be blocked inside the sidebar panel.
  The app then falls back to **taking a photo** of the barcode, which works everywhere.
- A USB / Bluetooth barcode scanner works out of the box: it types the ISBN and presses Enter.
