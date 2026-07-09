# Corn Basis Dashboard

Static GitHub Pages dashboard for ethanol corn basis data.

The browser reads prebuilt JSON files from a configurable static data URL, intended for Cloudflare R2 in production. The Python exporter reads the local master SQLite database after the Monday scraper finishes and writes dashboard-ready JSON files.

## Files

- `docs/corn_basis_dashboard.html` - GitHub Pages entry point.
- `docs/js/corn_basis_dashboard.js` - Leaflet map, filters, summary cards, and history chart.
- `docs/css/corn_basis_dashboard.css` - dashboard styling.
- `scripts/export_corn_basis_dashboard_data.py` - SQLite to JSON exporter.
- `docs/data/corn_basis/` - small sample dataset for local smoke testing.

## Export Data

Run from the `ethanolq` Conda environment after the basis scraper updates the master database:

```powershell
& "C:\Users\ehakm\anaconda3\Scripts\conda.exe" run --no-capture-output -n ethanolq python scripts\export_corn_basis_dashboard_data.py --output-dir data\corn_basis --mondays-only
```

For a small validation export:

```powershell
& "C:\Users\ehakm\anaconda3\Scripts\conda.exe" run --no-capture-output -n ethanolq python scripts\export_corn_basis_dashboard_data.py --output-dir data\corn_basis --max-snapshots 3
```

## Configure R2

Upload `data/corn_basis/` to the R2 bucket, then update the top of `docs/js/corn_basis_dashboard.js`:

```js
DATA_BASE_URL: "https://your-public-r2-url/data/corn_basis"
```

The sample `docs/data/corn_basis/` folder is only for local development and GitHub Pages smoke tests before R2 is wired up.
