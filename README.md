# Corn Basis Dashboard

Static GitHub Pages dashboard for ethanol corn basis data.

The browser reads prebuilt JSON files from Cloudflare R2. The Python exporter reads the local master SQLite database after the Monday scraper finishes and writes dashboard-ready JSON files.

## Files

- `docs/corn_basis_dashboard.html` - GitHub Pages entry point.
- `docs/js/corn_basis_dashboard.js` - Leaflet map, filters, summary cards, and history chart.
- `docs/css/corn_basis_dashboard.css` - dashboard styling.
- `scripts/export_corn_basis_dashboard_data.py` - SQLite to JSON exporter.
- `r2_upload/corn_basis/` - generated upload payload for Cloudflare R2.

## Export Data

Run from the `ethanolq` Conda environment after the basis scraper updates the master database:

```powershell
& "C:\Users\ehakm\anaconda3\Scripts\conda.exe" run --no-capture-output -n ethanolq python scripts\export_corn_basis_dashboard_data.py --mondays-only
```

For a small validation export:

```powershell
& "C:\Users\ehakm\anaconda3\Scripts\conda.exe" run --no-capture-output -n ethanolq python scripts\export_corn_basis_dashboard_data.py --max-snapshots 3
```

The exporter writes:

```text
r2_upload/
  corn_basis/
    index.json
    latest.json
    snapshots/
    history/
      all_basis_history.json
```

## Configure R2

Upload the contents of `r2_upload/corn_basis/` to the R2 bucket under the `corn_basis/` prefix.

The dashboard currently uses:

```js
const DATA_BASE_URL =
  "https://pub-e1ba77626f844f97953cd74102f37629.r2.dev/corn_basis";
```

This URL should work after upload:

```text
https://pub-e1ba77626f844f97953cd74102f37629.r2.dev/corn_basis/index.json
```
