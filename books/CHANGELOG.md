# Changelog

## 0.1.0
- First version: collection browser, add by ISBN / author & title / manual, barcode scanning,
  author details, CLZ XML import, local cover cache, CSV/JSON export, HA sensors.

## 0.1.1
- Show a clear message when Google Books or Open Library can't be reached
  (e.g. Google's anonymous rate limit), with a hint to add an API key.

## 0.1.2
- Covers are always served by the app itself (CLZ's image server blocks hotlinking), and a
  cover that isn't stored yet is fetched on the spot — no more blank covers right after import.
- Books without a cover get one from Open Library (by ISBN) when available.
