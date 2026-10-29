# NBRI Resettlement Dashboard

A web-based progress dashboard for the **National Building Research Institute (NBRI)** — HSPTD Division, NLRP Site Investigation Unit. It provides real-time visualization and tracking of land resettlement applications across Sri Lanka.

## Features

- **Live Data** — Fetches data directly from Google Sheets (Resettlement & Dithwah 2026 sheets) with auto-refresh caching (2-min for data, 5-min for file links)
- **Overview Dashboard** — Metric cards (Total, Reports Issued, Inspected, Not Inspected, Approved, GPS Mapped) with click-through to filtered records
- **Interactive GIS Map** — Leaflet.js map with color-coded markers by approval status and popup details for each site location
- **Charts & Analytics** — Working status, approval status, district distribution, resettlement types, monthly timeline, DSD breakdown, LSSD report status, officer workload
- **Records Tables** — Two tabs (Resettlement / Dithwah 2026) with search, column sorting, pagination, and CSV export
- **Clickable Report Files** — File links resolve to actual PDFs in Google Drive
- **Dark / Light Theme** — Toggle with persistence via localStorage
- **Responsive Design** — Works on desktop, tablet, and mobile

## Tech Stack

- **Backend:** Python 3, Flask
- **Frontend:** HTML5, CSS3 (custom properties, grid, flexbox), JavaScript (ES6+)
- **Libraries:** Chart.js 4, Leaflet.js 1.9, Google Fonts (Inter)
- **Data Source:** Google Sheets (live fetch via CSV/HTML export)

## Project Structure

```
GISProject/
├── app.py                  # Flask application & API routes
├── requirements.txt        # Python dependencies
├── templates/
│   └── index.html          # Main dashboard page
└── static/
    ├── css/
    │   └── style.css       # All styles & theming
    ├── js/
    │   └── app.js          # Dashboard logic, charts, map, tables
    └── data/               # Local data cache (fallback)
        ├── nbro_data.csv
        ├── dithwah_2026.json
        └── report_links.json
```

## Setup & Run

### Prerequisites

- Python 3.10+
- Internet connection (for live Google Sheets data and CDN libraries)

### Install

```bash
pip install flask requests
```

### Run

```bash
python app.py
```

Open **http://127.0.0.1:5000/** in your browser.

## Data Source

The dashboard reads from this Google Sheet:

**Spreadsheet ID:** `10SXfXC4iaAPxgzVFdjDEhGDo8TB75Bhh_I9A3uCFXA0`

| Sheet Tab | GID | Description |
|---|---|---|
| Resettlement | 0 | Individual/group resettlement site investigation records |
| Dithwah 2026 | 1129733636 | 2026 Dithwah land assessment records with report files |

Changes made in the Google Sheet are reflected in the dashboard within 2 minutes.

## API Endpoints

| Endpoint | Description |
|---|---|
| `GET /` | Dashboard UI |
| `GET /api/data` | Resettlement records (JSON) |
| `GET /api/dithwah` | Dithwah 2026 records (JSON) |
| `GET /api/summary` | Aggregated statistics (JSON) |
