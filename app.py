from flask import Flask, render_template, jsonify
import csv
import io
import json
import os
import time
import urllib.parse
from datetime import datetime
from html.parser import HTMLParser

import requests

app = Flask(__name__)

SPREADSHEET_ID = '10SXfXC4iaAPxgzVFdjDEhGDo8TB75Bhh_I9A3uCFXA0'
RESETTLEMENT_GID = '0'
DITHWAH_GID = '1129733636'

# Cache: { key: (data, timestamp) }
_cache = {}
CACHE_TTL = 120  # 2 minutes for CSV data
LINK_CACHE_TTL = 300  # 5 minutes for HTML-parsed links

DISTRICT_MAP = {
    'BAD': 'Badulla',
    'KDY': 'Kandy',
    'GAL': 'Galle',
    'KAL': 'Kalutara',
    'RAT': 'Ratnapura',
    'MTL': 'Matale',
    'KEG': 'Kegalle',
    'NUE': 'Nuwara Eliya',
    'MAT': 'Matara',
}


def parse_gps(coord_str):
    if not coord_str or not coord_str.strip():
        return None
    coord_str = coord_str.strip().replace('\u00b0', '')
    try:
        if ',' in coord_str and 'N' not in coord_str.upper() and 'E' not in coord_str.upper():
            parts = coord_str.split(',')
            if len(parts) == 2:
                return [float(parts[0].strip()), float(parts[1].strip())]
        parts = coord_str.split()
        if len(parts) >= 2:
            lat_str = parts[0]
            lng_str = parts[1]
            lat = float(lat_str.rstrip('NSns'))
            if lat_str[-1] in 'Ss':
                lat = -lat
            lng = float(lng_str.rstrip('EWew'))
            if lng_str[-1] in 'Ww':
                lng = -lng
            return [lat, lng]
    except (ValueError, IndexError):
        pass
    return None


# ── Live Google Sheets fetching ──────────────────────────────────────

def _fetch_csv(gid):
    """Fetch a sheet tab as CSV from Google Sheets."""
    url = (f'https://docs.google.com/spreadsheets/d/{SPREADSHEET_ID}'
           f'/gviz/tq?tqx=out:csv&gid={gid}')
    resp = requests.get(url, timeout=15)
    resp.raise_for_status()
    return resp.text


def _cached(key, loader, ttl):
    """Return cached value or call loader to refresh."""
    entry = _cache.get(key)
    if entry and (time.time() - entry[1]) < ttl:
        return entry[0]
    try:
        data = loader()
        _cache[key] = (data, time.time())
        return data
    except Exception as e:
        # If fetch fails, return stale cache if available
        if entry:
            print(f'[cache] fetch failed for {key}, using stale: {e}')
            return entry[0]
        raise


def fetch_resettlement():
    def loader():
        text = _fetch_csv(RESETTLEMENT_GID)
        reader = csv.DictReader(io.StringIO(text))
        return [row for row in reader if row.get('  Serial No.', row.get('Serial No.', '')).strip()]
    return _cached('resettlement', loader, CACHE_TTL)


def fetch_dithwah_csv():
    def loader():
        text = _fetch_csv(DITHWAH_GID)
        reader = csv.DictReader(io.StringIO(text))
        return [row for row in reader if row.get(' ', row.get('', '')).strip()]
    return _cached('dithwah_csv', loader, CACHE_TTL)


# ── HTML parsing for hyperlinks ──────────────────────────────────────

class _LinkParser(HTMLParser):
    """Extract cell text + hyperlinks from a Google Sheets HTML export."""
    def __init__(self):
        super().__init__()
        self.in_table = False
        self.in_tr = False
        self.in_td = False
        self.current_link = None
        self.current_text = ''
        self.rows = []
        self.current_row = []

    def handle_starttag(self, tag, attrs):
        ad = dict(attrs)
        if tag == 'table':
            self.in_table = True
        elif tag == 'tr' and self.in_table:
            self.in_tr = True
            self.current_row = []
        elif tag == 'td' and self.in_tr:
            self.in_td = True
            self.current_link = None
            self.current_text = ''
        elif tag == 'a' and self.in_td:
            self.current_link = ad.get('href', '')

    def handle_data(self, data):
        if self.in_td:
            self.current_text += data.strip()

    def handle_endtag(self, tag):
        if tag == 'td' and self.in_td:
            self.in_td = False
            self.current_row.append({'text': self.current_text.strip(), 'link': self.current_link})
        elif tag == 'tr' and self.in_tr:
            self.in_tr = False
            if self.current_row:
                self.rows.append(self.current_row)


def _clean_drive_link(raw_link):
    """Extract clean Google Drive URL from Google redirect wrapper."""
    if not raw_link:
        return ''
    if 'google.com/url' in raw_link:
        parsed = urllib.parse.urlparse(raw_link)
        params = urllib.parse.parse_qs(parsed.query)
        raw_link = urllib.parse.unquote(params.get('q', [''])[0])
    if 'drive.google.com/file/d/' in raw_link:
        parts = raw_link.split('/file/d/')
        if len(parts) > 1:
            file_id = parts[1].split('/')[0].split('?')[0]
            return f'https://drive.google.com/file/d/{file_id}/view'
    return raw_link


def _parse_sheet_links(gid, header_match, link_col_name, key_col_idx=0):
    """Fetch HTML version of a sheet and extract hyperlinks from a specific column."""
    url = (f'https://docs.google.com/spreadsheets/d/{SPREADSHEET_ID}'
           f'/htmlview/sheet?headers=true&gid={gid}')
    resp = requests.get(url, timeout=30)
    resp.raise_for_status()

    parser = _LinkParser()
    parser.feed(resp.text)

    header_row = None
    for i, row in enumerate(parser.rows):
        texts = [c['text'] for c in row]
        if header_match in texts:
            header_row = i
            break
    if header_row is None:
        return {}

    headers = [c['text'] for c in parser.rows[header_row]]
    link_idx = headers.index(link_col_name) if link_col_name in headers else -1
    if link_idx < 0:
        return {}

    result = {}
    for row in parser.rows[header_row + 1:]:
        if len(row) <= max(link_idx, key_col_idx):
            continue
        key = row[key_col_idx]['text'].strip()
        if not key:
            continue
        link_text = row[link_idx]['text'].strip()
        link_url = _clean_drive_link(row[link_idx]['link'])
        if link_text:
            result[key] = {'name': link_text, 'link': link_url}
    return result


def fetch_resettlement_links():
    def loader():
        return _parse_sheet_links(RESETTLEMENT_GID, 'Report', 'Report', key_col_idx=0)
    return _cached('resettlement_links', loader, LINK_CACHE_TTL)


def fetch_dithwah_links():
    def loader():
        return _parse_sheet_links(DITHWAH_GID, 'File', 'File', key_col_idx=0)
    return _cached('dithwah_links', loader, LINK_CACHE_TTL)


# ── Routes ───────────────────────────────────────────────────────────

@app.route('/')
def index():
    return render_template('index.html')


@app.route('/api/data')
def api_data():
    records = fetch_resettlement()
    report_links = fetch_resettlement_links()
    result = []
    for r in records:
        serial_key = r.get('  Serial No.', r.get('Serial No.', '')).strip()
        gps = parse_gps(r.get('GPS Coordinate', ''))
        link_info = report_links.get(serial_key, {})
        dist_code = r.get('Dist. Code', '').strip()
        result.append({
            'serial': serial_key,
            'ref': r.get('Ref. No.', ''),
            'year': r.get('Year', ''),
            'distCode': dist_code,
            'district': DISTRICT_MAP.get(dist_code, r.get('RS District', '')),
            'dsd': r.get('RS DSD', ''),
            'status': r.get('Working Status', ''),
            'officer': r.get('Officer Attended', ''),
            'beneficiary': r.get('Name of the Beneficiary', ''),
            'plots': r.get('Number of Plots', ''),
            'approval': r.get('Approval Status', ''),
            'report': r.get('Report', ''),
            'reportLink': link_info.get('link', ''),
            'coverDate': r.get('Date on Cover Letter', ''),
            'receivedDate': r.get('Date Received to NBRO Head Office', ''),
            'lssdReceived': r.get('LSSD Report Recieved', r.get('LSSD Report Received', '')),
            'lssdDate': r.get('LSSD Report Recieved Date', r.get('LSSD Report Received Date', '')),
            'inspectionDate': r.get('Site Inspection Date', ''),
            'issuedDate': r.get('Report Issued Date', ''),
            'gps': gps,
            'gpsRaw': r.get('GPS Coordinate', ''),
            'resettlementType': r.get('Resettlement Type', ''),
            'contact': r.get('Contact No.', ''),
            'remarks': r.get('Remarks', ''),
            'uploadStatus': r.get('Upload to Database', ''),
        })
    return jsonify(result)


@app.route('/api/dithwah')
def api_dithwah():
    records = fetch_dithwah_csv()
    file_links = fetch_dithwah_links()
    result = []
    for r in records:
        serial = r.get(' ', r.get('', '')).strip()
        loc = r.get('Location', '')
        gps = parse_gps(loc)
        dist = r.get('District ', r.get('District', '')).strip()
        link_info = file_links.get(serial, {})
        result.append({
            'serial': serial,
            'ref': r.get('Ref. No.', ''),
            'year': r.get('Year', ''),
            'issuedDate': r.get('Issued Date', ''),
            'landName': r.get('Land Name', ''),
            'file': r.get('File', ''),
            'fileLink': link_info.get('link', ''),
            'distCode': dist,
            'district': DISTRICT_MAP.get(dist, dist),
            'reportStatus': r.get('Status of Report', ''),
            'requestDate': r.get('Request Date', ''),
            'receivedDate': r.get('Recieved Date', ''),
            'letterRef': r.get('Letter Ref.', ''),
            'dsd': r.get('DSD', ''),
            'gnd': r.get('GND', ''),
            'gps': gps,
            'gpsRaw': loc,
            'area': r.get('Area (Acres)', ''),
            'expectedBlocks': r.get('Expected Blocks', ''),
            'workingStatus': r.get('Working Status', ''),
            'inspectionDate': r.get('Inspection Date', ''),
            'approval': r.get('Status of Approval', ''),
            'remarks': r.get('Remaks ', r.get('Remaks', '')),
            'uploadStatus': r.get('Upload to Database', ''),
        })
    return jsonify(result)


@app.route('/api/summary')
def api_summary():
    records = fetch_resettlement()
    total = len(records)

    status_counts = {}
    approval_counts = {}
    district_counts = {}
    type_counts = {}
    dsd_counts = {}
    monthly_issued = {}
    officer_counts = {}

    for r in records:
        ws = r.get('Working Status', '').strip()
        if ws:
            status_counts[ws] = status_counts.get(ws, 0) + 1

        ap = r.get('Approval Status', '').strip()
        if ap:
            approval_counts[ap] = approval_counts.get(ap, 0) + 1

        dc = r.get('Dist. Code', '').strip()
        dist_name = DISTRICT_MAP.get(dc, dc)
        if dist_name:
            district_counts[dist_name] = district_counts.get(dist_name, 0) + 1

        rt = r.get('Resettlement Type', '').strip()
        if rt:
            type_counts[rt] = type_counts.get(rt, 0) + 1

        dsd = r.get('RS DSD', '').strip()
        if dsd:
            dsd_counts[dsd] = dsd_counts.get(dsd, 0) + 1

        issued = r.get('Report Issued Date', '').strip()
        if issued:
            try:
                dt = datetime.strptime(issued, '%m/%d/%Y')
                key = dt.strftime('%Y-%m')
                monthly_issued[key] = monthly_issued.get(key, 0) + 1
            except ValueError:
                pass

        off = r.get('Officer Attended', '').strip()
        if off and '@' not in off:
            officer_counts[off] = officer_counts.get(off, 0) + 1

    with_gps = sum(1 for r in records if r.get('GPS Coordinate', '').strip())
    lssd_key = 'LSSD Report Recieved' if 'LSSD Report Recieved' in (records[0] if records else {}) else 'LSSD Report Received'
    lssd_true = sum(1 for r in records if r.get(lssd_key, '').strip().upper() == 'TRUE')

    sorted_monthly = dict(sorted(monthly_issued.items()))

    return jsonify({
        'total': total,
        'statusCounts': status_counts,
        'approvalCounts': approval_counts,
        'districtCounts': district_counts,
        'typeCounts': type_counts,
        'dsdCounts': dsd_counts,
        'monthlyIssued': sorted_monthly,
        'officerCounts': officer_counts,
        'withGps': with_gps,
        'lssdReceived': lssd_true,
    })


if __name__ == '__main__':
    app.run(debug=True, port=5000)
