
from __future__ import annotations

import csv
import io
import json
import os
import re
import sqlite3
import unicodedata
from datetime import datetime, date, timedelta
import calendar
import math
from pathlib import Path
from werkzeug.utils import secure_filename
from flask import Flask, request, redirect, url_for, render_template_string, send_file, flash, session
from reportlab.lib import colors
from reportlab.lib.pagesizes import A4
from reportlab.lib.styles import getSampleStyleSheet, ParagraphStyle
from reportlab.lib.units import mm
from reportlab.pdfbase import pdfmetrics
from reportlab.pdfbase.ttfonts import TTFont
from reportlab.platypus import SimpleDocTemplate, Table, TableStyle, Paragraph, Spacer

APP_DIR = Path(__file__).resolve().parent
DB_PATH = APP_DIR / "go_partner.db"
UPLOAD_DIR = APP_DIR / "uploads" / "deposit_returns"
UPLOAD_DIR.mkdir(parents=True, exist_ok=True)
ALLOWED_RETURN_FILES = {".pdf", ".png", ".jpg", ".jpeg", ".webp"}

app = Flask(__name__)
app.secret_key = os.environ.get("SECRET_KEY", "go-partner-admin-test-secret")

BASE_HTML = """
<!doctype html>
<html lang="pl">
<head>
<meta charset="utf-8">
<meta name="viewport" content="width=device-width,initial-scale=1">
<title>GO PARTNER Manager 4.25 CYKLICZNE FIX</title>
<style>
:root{--bg:#f4f6fa;--panel:#fff;--line:#e5e7eb;--text:#111827;--muted:#6b7280;--blue:#2563eb;--red:#b91c1c;--green:#166534}
*{box-sizing:border-box}body{margin:0;font-family:-apple-system,BlinkMacSystemFont,"Segoe UI",sans-serif;background:var(--bg);color:var(--text)}
.app{display:grid;grid-template-columns:230px 1fr;min-height:100vh}.side{background:#0b1b33;color:#fff;padding:22px}.logo{font-weight:800;font-size:18px;margin-bottom:24px}
.side a{display:block;color:#dbeafe;text-decoration:none;padding:11px 12px;border-radius:9px;margin:4px 0}.side a:hover{background:#17345d}.main{padding:24px}
.card{background:#fff;border:1px solid var(--line);border-radius:14px;padding:16px;margin-bottom:14px}.grid{display:grid;gap:14px}.g4{grid-template-columns:repeat(4,1fr)}.g3{grid-template-columns:repeat(3,1fr)}.g2{grid-template-columns:repeat(2,1fr)}
.metric b{display:block;font-size:24px;margin-top:5px}.muted{color:var(--muted)}input,select,textarea{width:100%;padding:10px;border:1px solid var(--line);border-radius:9px}.field{display:flex;flex-direction:column;gap:6px}
.btn{display:inline-block;border:0;border-radius:9px;padding:10px 14px;text-decoration:none;cursor:pointer;background:#e5e7eb;color:#111}.primary{background:var(--blue);color:#fff}.danger{background:#fee2e2;color:#991b1b}
table{width:100%;border-collapse:collapse}th,td{padding:10px;border-bottom:1px solid var(--line);text-align:left;font-size:14px}th{background:#f8fafc}.right{text-align:right}
.badge{display:inline-block;padding:3px 8px;border-radius:999px;font-size:12px;font-weight:700}.on{background:#dcfce7;color:#166534}.off{background:#fee2e2;color:#991b1b}.arch{background:#e5e7eb;color:#374151}.login-wrap{max-width:420px;margin:8vh auto}.progress{height:10px;background:#e5e7eb;border-radius:999px;overflow:hidden}.progress span{display:block;height:100%;background:#2563eb}
.flash{padding:10px 14px;border-radius:9px;background:#dbeafe;margin-bottom:12px}.row{display:flex;gap:10px;align-items:center;flex-wrap:wrap}.tabs{display:flex;gap:8px;border-bottom:1px solid var(--line);margin:14px 0}.tabs a{padding:10px 12px;text-decoration:none;color:#374151}.tabs a.active{color:var(--blue);border-bottom:2px solid var(--blue);font-weight:700}.pos{color:#166534;font-weight:700}.neg{color:#b91c1c;font-weight:700}
@media(max-width:900px){.app{grid-template-columns:1fr}.g4,.g3,.g2{grid-template-columns:1fr}}
</style>
</head>
<body>
<div class="app">
<aside class="side">
<div class="logo">GO PARTNER<br><small>Manager 4.21 ING BANK</small></div>
<a href="/">Dashboard</a>
<a href="/drivers">Kierowcy</a>
<a href="/settlements/new">Nowe rozliczenie</a>
<a href="/history">Historia</a>
<a href="/logs">Logi</a>
<a href="/logout">Wyloguj</a>
</aside>
<main class="main">
{% with messages = get_flashed_messages() %}
  {% for message in messages %}<div class="flash">{{message}}</div>{% endfor %}
{% endwith %}
{{ content|safe }}
</main>
</div>
</body>
</html>
"""

def db():
    c = sqlite3.connect(
        DB_PATH,
        timeout=30.0,
        isolation_level="DEFERRED",
        check_same_thread=False,
    )
    c.row_factory = sqlite3.Row
    c.execute("PRAGMA busy_timeout=30000")
    c.execute("PRAGMA foreign_keys=ON")
    return c

def ensure_column(connection, table, name, definition):
    columns = {row[1] for row in connection.execute(f"PRAGMA table_info({table})")}
    if name not in columns:
        connection.execute(f"ALTER TABLE {table} ADD COLUMN {name} {definition}")


def init_db():
    with db() as c:
        c.execute("PRAGMA journal_mode=WAL")
        c.execute("PRAGMA synchronous=NORMAL")
        c.execute("PRAGMA wal_autocheckpoint=1000")
        c.executescript("""
        CREATE TABLE IF NOT EXISTS drivers(
          driver_key TEXT PRIMARY KEY,
          driver_name TEXT NOT NULL,
          phone TEXT DEFAULT '',
          email TEXT DEFAULT '',
          car TEXT DEFAULT '',
          partner_commission REAL DEFAULT 0,
          rental REAL DEFAULT 0,
          other REAL DEFAULT 0,
          deposit_amount REAL DEFAULT 0,
          accident_debt REAL DEFAULT 0,
          active INTEGER DEFAULT 1,
          notes TEXT DEFAULT '',
          updated_at TEXT NOT NULL
        );
        CREATE TABLE IF NOT EXISTS driver_costs(
          id INTEGER PRIMARY KEY AUTOINCREMENT,
          driver_key TEXT NOT NULL,
          entry_date TEXT NOT NULL,
          title TEXT NOT NULL,
          amount REAL NOT NULL,
          entry_type TEXT NOT NULL,
          apply_next INTEGER DEFAULT 1,
          applied_settlement_id INTEGER,
          note TEXT DEFAULT '',
          created_at TEXT NOT NULL
        );
        CREATE TABLE IF NOT EXISTS recurring_rules(
          id INTEGER PRIMARY KEY AUTOINCREMENT,
          driver_key TEXT NOT NULL,
          title TEXT NOT NULL,
          amount REAL NOT NULL,
          rule_type TEXT NOT NULL,
          active INTEGER DEFAULT 1,
          note TEXT DEFAULT '',
          created_at TEXT NOT NULL
        );
        CREATE TABLE IF NOT EXISTS installment_plans(
          id INTEGER PRIMARY KEY AUTOINCREMENT,
          driver_key TEXT NOT NULL,
          title TEXT NOT NULL,
          category TEXT NOT NULL,
          total_amount REAL NOT NULL,
          initial_paid REAL DEFAULT 0,
          paid_from_settlements REAL DEFAULT 0,
          weekly_amount REAL NOT NULL,
          active INTEGER DEFAULT 1,
          note TEXT DEFAULT '',
          created_at TEXT NOT NULL
        );
        CREATE TABLE IF NOT EXISTS installment_charges(
          id INTEGER PRIMARY KEY AUTOINCREMENT,
          plan_id INTEGER NOT NULL,
          settlement_id INTEGER NOT NULL,
          driver_key TEXT NOT NULL,
          amount REAL NOT NULL,
          created_at TEXT NOT NULL
        );
        CREATE TABLE IF NOT EXISTS settlement_drafts(
          id INTEGER PRIMARY KEY AUTOINCREMENT,
          week_start TEXT,
          week_end TEXT,
          created_at TEXT NOT NULL
        );
        CREATE TABLE IF NOT EXISTS settlement_draft_rows(
          id INTEGER PRIMARY KEY AUTOINCREMENT,
          draft_id INTEGER NOT NULL,
          driver_key TEXT NOT NULL,
          driver_name TEXT NOT NULL,
          platforms TEXT,
          gross REAL,
          transfer REAL,
          partner_commission REAL,
          rental REAL,
          recurring_total REAL DEFAULT 0,
          manual_adjustments REAL DEFAULT 0,
          fines REAL DEFAULT 0,
          other REAL DEFAULT 0,
          payable REAL DEFAULT 0
        );
        CREATE TABLE IF NOT EXISTS deposit_returns(
          id INTEGER PRIMARY KEY AUTOINCREMENT,
          driver_key TEXT NOT NULL,
          return_date TEXT NOT NULL,
          amount REAL NOT NULL,
          method TEXT NOT NULL,
          comment TEXT DEFAULT '',
          proof_filename TEXT DEFAULT '',
          proof_original_name TEXT DEFAULT '',
          created_at TEXT NOT NULL
        );
        CREATE TABLE IF NOT EXISTS scheduled_occurrences(
          id INTEGER PRIMARY KEY AUTOINCREMENT,
          kind TEXT NOT NULL,
          source_id INTEGER NOT NULL DEFAULT 0,
          driver_key TEXT NOT NULL,
          occurrence_date TEXT NOT NULL,
          cost_id INTEGER,
          UNIQUE(kind,source_id,driver_key,occurrence_date)
        );
        CREATE TABLE IF NOT EXISTS settlements(
          id INTEGER PRIMARY KEY AUTOINCREMENT,
          week_start TEXT,
          week_end TEXT,
          created_at TEXT,
          note TEXT,
          total_gross REAL,
          total_transfer REAL,
          total_payable REAL
        );
        CREATE TABLE IF NOT EXISTS settlement_rows(
          id INTEGER PRIMARY KEY AUTOINCREMENT,
          settlement_id INTEGER,
          driver_key TEXT,
          driver_name TEXT,
          platforms TEXT,
          gross REAL,
          transfer REAL,
          cash REAL,
          tips REAL,
          bonuses REAL,
          partner_commission REAL,
          rental REAL,
          recurring_total REAL DEFAULT 0,
          manual_adjustments REAL DEFAULT 0,
          fines REAL DEFAULT 0,
          other REAL DEFAULT 0,
          payable REAL,
          deduction_comment TEXT DEFAULT '',
          details TEXT
        );
        CREATE TABLE IF NOT EXISTS bank_export_settings(
          id INTEGER PRIMARY KEY CHECK (id=1),
          source_account TEXT DEFAULT '',
          payer_name TEXT DEFAULT '',
          payer_address1 TEXT DEFAULT '',
          payer_address2 TEXT DEFAULT '',
          default_title TEXT DEFAULT 'Rozliczenie kierowcy'
        );
        CREATE TABLE IF NOT EXISTS logs(
          id INTEGER PRIMARY KEY AUTOINCREMENT,
          created_at TEXT NOT NULL,
          action TEXT NOT NULL,
          details TEXT DEFAULT ''
        );
        """)
        ensure_column(c, "drivers", "scheme_type", "TEXT DEFAULT 'BRAK'")
        ensure_column(c, "drivers", "monthly_zus", "REAL DEFAULT 0")
        ensure_column(c, "drivers", "zus_day", "INTEGER DEFAULT 1")
        ensure_column(c, "drivers", "rental_start_date", "TEXT DEFAULT ''")
        ensure_column(c, "driver_costs", "source_label", "TEXT DEFAULT ''")
        ensure_column(c, "settlement_rows", "is_paid", "INTEGER DEFAULT 0")
        ensure_column(c, "settlement_rows", "paid_at", "TEXT DEFAULT ''")
        ensure_column(c, "settlements", "all_paid", "INTEGER DEFAULT 0")
        ensure_column(c, "settlements", "paid_at", "TEXT DEFAULT ''")
        ensure_column(c, "driver_costs", "installment_number", "INTEGER DEFAULT 0")
        ensure_column(c, "driver_costs", "installment_total", "INTEGER DEFAULT 0")
        ensure_column(c, "drivers", "uber_id", "TEXT DEFAULT ''")
        ensure_column(c, "drivers", "bolt_id", "TEXT DEFAULT ''")
        ensure_column(c, "settlement_rows", "b2b_fee", "REAL DEFAULT 0")
        ensure_column(c, "drivers", "bank_account", "TEXT DEFAULT ''")
        ensure_column(c, "drivers", "status", "TEXT DEFAULT 'AKTYWNY'")
        ensure_column(c, "installment_plans", "cancelled_at", "TEXT DEFAULT ''")
        ensure_column(c, "installment_plans", "cancel_comment", "TEXT DEFAULT ''")
        c.execute("""
        INSERT OR IGNORE INTO bank_export_settings(
          id,source_account,payer_name,payer_address1,payer_address2,default_title
        ) VALUES(1,'','','','','Rozliczenie kierowcy')
        """)


def render(content, **ctx):
    return render_template_string(BASE_HTML, content=render_template_string(content, **ctx))

def log(action, details="", connection=None):
    values = (
        datetime.now().isoformat(timespec="seconds"),
        action,
        details,
    )
    if connection is not None:
        connection.execute(
            "INSERT INTO logs(created_at,action,details) VALUES(?,?,?)",
            values,
        )
        return

    # Osobne połączenie jest używane tylko poza aktywną transakcją.
    with db() as c:
        c.execute(
            "INSERT INTO logs(created_at,action,details) VALUES(?,?,?)",
            values,
        )

def norm_name(v):
    v = unicodedata.normalize("NFKD", str(v))
    v = "".join(ch for ch in v if not unicodedata.combining(ch))
    v = re.sub(r"[^a-zA-Z0-9]+", " ", v).strip().lower()
    return " ".join(v.split())

def num(v):
    s = str(v or "").strip().replace("\u00a0","").replace(" ","").replace(",",".")
    s = re.sub(r"[^0-9.\-]","",s)
    try: return float(s or 0)
    except: return 0.0


def normalize_bank_account(value):
    text = re.sub(r"[^A-Za-z0-9]", "", str(value or "")).upper()
    if text.startswith("PL"):
        text = text[2:]
    return text


def valid_polish_account(value):
    nrb = normalize_bank_account(value)
    if len(nrb) != 26 or not nrb.isdigit():
        return False
    iban = "PL" + nrb
    rearranged = iban[4:] + iban[:4]
    numeric = "".join(str(ord(ch)-55) if ch.isalpha() else ch for ch in rearranged)
    return int(numeric) % 97 == 1


def bank_routing_number(value):
    nrb = normalize_bank_account(value)
    return nrb[2:10] if len(nrb) == 26 else ""


def pli_text(value, max_len):
    value = str(value or "").replace('"', "'").replace("\r", " ").replace("\n", " ")
    value = re.sub(r"\s+", " ", value).strip()
    return value[:max_len]


def pli_name_lines(name, address1="", address2=""):
    name = pli_text(name, 70)
    line1 = name[:35]
    line2 = name[35:70]
    line3 = pli_text(address1, 35)
    line4 = pli_text(address2, 35)
    return "|".join([line1, line2, line3, line4])


def pli_payment_title(title):
    title = pli_text(title, 140)
    parts = [title[i:i+35] for i in range(0, min(len(title), 140), 35)]
    while len(parts) < 4:
        parts.append("")
    return "|".join(parts[:4])


def build_ing_pli(rows, settings, execution_date):
    source_account = normalize_bank_account(settings["source_account"])
    source_routing = bank_routing_number(source_account)
    payer = pli_name_lines(
        settings["payer_name"],
        settings["payer_address1"],
        settings["payer_address2"],
    )

    records = []
    for row in rows:
        beneficiary_account = normalize_bank_account(row["bank_account"])
        beneficiary_routing = bank_routing_number(beneficiary_account)
        amount_grosz = int(round(float(row["payable"] or 0) * 100))
        title = (
            f"{settings['default_title']} "
            f"{row['week_start']}-{row['week_end']}"
        )
        beneficiary = pli_name_lines(row["driver_name"])
        reference = f"GP{row['settlement_id']}-{row['driver_key']}"[:32]

        fields = [
            "110",
            execution_date.strftime("%Y%m%d"),
            str(amount_grosz),
            source_routing,
            "0",
            f'"{source_account}"',
            f'"{beneficiary_account}"',
            f'"{payer}"',
            f'"{beneficiary}"',
            "0",
            beneficiary_routing,
            f'"{pli_payment_title(title)}"',
            '""',
            '""',
            '"51"',
            f'"{pli_text(reference, 32)}"',
        ]
        records.append(",".join(fields))

    return ("\r\n".join(records) + "\r\n").encode("cp1250", errors="replace")


def money(v):
    return f"{float(v or 0):,.2f} zł".replace(",", " ")

def ensure_driver(name):
    key = norm_name(name)
    with db() as c:
        if not c.execute("SELECT 1 FROM drivers WHERE driver_key=?", (key,)).fetchone():
            c.execute("""INSERT INTO drivers(driver_key,driver_name,updated_at)
                         VALUES(?,?,?)""",(key,name,datetime.now().isoformat(timespec="seconds")))
    return key


POLISH_MONTHS = {
    "sty": 1, "stycznia": 1,
    "lut": 2, "lutego": 2,
    "mar": 3, "marca": 3,
    "kwi": 4, "kwietnia": 4,
    "maj": 5, "maja": 5,
    "cze": 6, "czerwca": 6,
    "lip": 7, "lipca": 7,
    "sie": 8, "sierpnia": 8,
    "wrz": 9, "września": 9, "wrzesnia": 9,
    "paź": 10, "paz": 10, "października": 10, "pazdziernika": 10,
    "lis": 11, "listopada": 11,
    "gru": 12, "grudnia": 12,
}


def extract_period_from_filename(filename):
    """
    Zwraca (data_od, data_do, źródło) albo None.

    Obsługiwane formaty:
    - Uber: 20260706-20260713-payments_driver...
      Druga data Uber jest traktowana jako koniec wyłączny,
      dlatego zapisujemy 06.07.2026–12.07.2026.
    - Raport tygodniowy: Zarobki na kierowcę-2026W28-...
      Numer tygodnia ISO jest zamieniany na poniedziałek–niedzielę.
    - Bolt: ...-6 lip 2026-12 lip 2026-...
    """
    # Normalizacja Unicode usuwa różnicę między „ę” a „e” + znak łączący.
    name = unicodedata.normalize("NFC", filename).lower()

    iso_week_match = re.search(
        r"(?<!\d)(20\d{2})\s*[-_ ]?w\s*(\d{1,2})(?!\d)",
        name,
        flags=re.IGNORECASE,
    )
    if iso_week_match:
        year = int(iso_week_match.group(1))
        week = int(iso_week_match.group(2))
        try:
            start = date.fromisocalendar(year, week, 1)
            end = date.fromisocalendar(year, week, 7)
        except ValueError:
            raise ValueError(
                f"Nieprawidłowy numer tygodnia ISO w nazwie pliku: {filename}"
            )
        return start, end, "Tydzień ISO"

    uber_match = re.search(r"(?<!\d)(20\d{6})-(20\d{6})(?!\d)", name)
    if uber_match:
        start = datetime.strptime(uber_match.group(1), "%Y%m%d").date()
        end_exclusive = datetime.strptime(uber_match.group(2), "%Y%m%d").date()
        end = end_exclusive - timedelta(days=1)
        if end < start:
            raise ValueError(f"Nieprawidłowy zakres dat w nazwie pliku: {filename}")
        return start, end, "Uber"

    bolt_match = re.search(
        r"(?<!\d)(\d{1,2})\s+([a-ząćęłńóśźż]+)\s+(20\d{2})"
        r"\s*-\s*"
        r"(\d{1,2})\s+([a-ząćęłńóśźż]+)\s+(20\d{2})(?!\d)",
        name,
        flags=re.IGNORECASE,
    )
    if bolt_match:
        d1, m1_text, y1, d2, m2_text, y2 = bolt_match.groups()
        m1_key = m1_text.lower()
        m2_key = m2_text.lower()
        if m1_key not in POLISH_MONTHS or m2_key not in POLISH_MONTHS:
            raise ValueError(f"Nie rozpoznano polskiego miesiąca w nazwie pliku: {filename}")
        start = date(int(y1), POLISH_MONTHS[m1_key], int(d1))
        end = date(int(y2), POLISH_MONTHS[m2_key], int(d2))
        if end < start:
            raise ValueError(f"Nieprawidłowy zakres dat w nazwie pliku: {filename}")
        return start, end, "Bolt"

    return None


def detect_period(files):
    periods = []
    missing = []

    for file in files:
        period = extract_period_from_filename(file.filename)
        if period:
            periods.append((file.filename, *period))
        else:
            missing.append(file.filename)

    if missing:
        raise ValueError(
            "Nie udało się automatycznie odczytać okresu z nazwy pliku: "
            + ", ".join(missing)
            + ". Obsługiwane są nazwy z zakresem dat, np. "
            "20260706-20260713, albo z tygodniem ISO, np. 2026W28."
        )

    starts = {item[1] for item in periods}
    ends = {item[2] for item in periods}

    if len(starts) != 1 or len(ends) != 1:
        details = "; ".join(
            f"{name}: {start.strftime('%d.%m.%Y')}–{end.strftime('%d.%m.%Y')}"
            for name, start, end, _source in periods
        )
        raise ValueError(
            "Załadowane pliki dotyczą różnych okresów. "
            "Wgraj pliki Uber i Bolt za ten sam tydzień. "
            + details
        )

    return next(iter(starts)), next(iter(ends)), periods


def read_upload(file):
    data = file.read()
    for enc in ("utf-8-sig","utf-8","cp1250","latin1"):
        try: text = data.decode(enc)
        except: continue
        for delim in (",",";","\t"):
            rows = list(csv.DictReader(io.StringIO(text), delimiter=delim))
            if rows and len(rows[0]) > 1:
                return rows
    raise ValueError("Nie udało się odczytać CSV")

def normalize_header(value):
    value = unicodedata.normalize("NFKD", str(value or ""))
    value = "".join(ch for ch in value if not unicodedata.combining(ch))
    value = value.replace("\ufeff", "")
    value = re.sub(r"[^a-zA-Z0-9]+", " ", value).strip().lower()
    return " ".join(value.split())


def first_nonempty(row, candidates):
    # Exact match first.
    for candidate in candidates:
        value = row.get(candidate)
        if value is not None and str(value).strip():
            return str(value).strip()

    # Then normalized match, resistant to BOM, spaces, punctuation and accents.
    normalized = {normalize_header(key): key for key in row.keys()}
    for candidate in candidates:
        real_key = normalized.get(normalize_header(candidate))
        if real_key:
            value = row.get(real_key)
            if value is not None and str(value).strip():
                return str(value).strip()
    return ""


def detect_driver_platform_id(row, platform):
    explicit_candidates = UBER_ID_COLUMNS if platform == "Uber" else BOLT_ID_COLUMNS
    explicit = first_nonempty(row, explicit_candidates)
    if explicit:
        return explicit, "explicit"

    # Uber exports often use compound headers such as:
    # "Kierowca:UUID", "Driver:UUID", "Driver UUID", "Kierowca ID".
    excluded_tokens = {
        "trip", "przejazd", "order", "zamowienie", "payment", "platnosc",
        "transaction", "transakcja", "invoice", "faktura", "vehicle", "pojazd",
        "partner", "fleet", "week", "okres"
    }

    scored = []
    for key, raw_value in row.items():
        value = str(raw_value or "").strip()
        if not value:
            continue
        header = normalize_header(key)
        tokens = set(header.split())

        has_id_signal = (
            "uuid" in tokens
            or "guid" in tokens
            or "identyfikator" in tokens
            or "id" in tokens
        )
        has_driver_signal = (
            "driver" in tokens
            or "kierowca" in tokens
            or "kierowcy" in tokens
            or "courier" in tokens
        )
        platform_signal = platform.lower() in tokens
        excluded = bool(tokens & excluded_tokens)

        score = 0
        if has_id_signal:
            score += 3
        if has_driver_signal:
            score += 4
        if platform_signal:
            score += 1
        if "uuid" in tokens or "guid" in tokens:
            score += 3
        if excluded:
            score -= 6

        # IDs are usually compact strings, not money or names.
        compact = re.sub(r"\s+", "", value)
        if len(compact) >= 8:
            score += 1
        if re.fullmatch(r"[0-9.,\- ]+", value):
            score -= 2

        if score >= 5:
            scored.append((score, key, value))

    if not scored:
        return "", ""

    scored.sort(key=lambda item: (-item[0], normalize_header(item[1])))
    return scored[0][2], scored[0][1]


UBER_ID_COLUMNS = [
    "ID kierowcy", "Id kierowcy", "Driver ID", "driver_id",
    "UUID kierowcy", "Uber ID", "ID Uber",
    "Identyfikator kierowcy", "Numer kierowcy",
    "Driver UUID", "Partner Driver ID",
    "Kierowca UUID", "Kierowca:UUID", "Driver:UUID",
    "UUID Driver", "Driver GUID", "Kierowca GUID",
]

BOLT_ID_COLUMNS = [
    "ID kierowcy", "Id kierowcy", "Driver ID", "driver_id",
    "UUID kierowcy", "Bolt ID", "ID Bolt",
    "Identyfikator kierowcy", "Numer kierowcy",
    "Driver UUID", "Partner Driver ID",
    "Kierowca UUID", "Kierowca:UUID", "Driver:UUID",
    "UUID Driver", "Driver GUID", "Kierowca GUID",
]


def parse_files(files):
    out=[]
    for f in files:
        rows=read_upload(f)
        cols=set(rows[0].keys())
        if "Kierowca" in cols:
            for r in rows:
                name=(r.get("Kierowca") or "").strip()
                if not name: continue
                net=num(r.get("Zarobki netto|ZŁ")); cash=num(r.get("Pobrana gotówka|ZŁ"))
                platform_id, platform_id_column = detect_driver_platform_id(r, "Bolt")
                out.append(dict(driver=name,driver_key=norm_name(name),platform="Bolt",
                    platform_id=platform_id,
                    platform_id_column=platform_id_column,
                    gross=num(r.get("Zarobki brutto (ogółem)|ZŁ")),net=net,transfer=net-cash,
                    cash=cash,tips=num(r.get("Napiwki od pasażerów|ZŁ")),
                    bonuses=num(r.get("Zarobki z kampanii|ZŁ"))))
        elif "Imię kierowcy" in cols and "Nazwisko kierowcy" in cols:
            bank_col="Wypłacono Ci:Bilans przejazdu:Wypłaty:Przelano na konto bankowe"
            for r in rows:
                name=f"{r.get('Imię kierowcy','')} {r.get('Nazwisko kierowcy','')}".strip()
                if not name: continue
                total=num(r.get("Wypłacono Ci")); bank=num(r.get(bank_col))
                platform_id, platform_id_column = detect_driver_platform_id(r, "Uber")
                out.append(dict(driver=name,driver_key=norm_name(name),platform="Uber",
                    platform_id=platform_id,
                    platform_id_column=platform_id_column,
                    gross=num(r.get("Wypłacono Ci : Twój przychód")),net=total,transfer=bank or total,
                    cash=abs(num(r.get("Wypłacono Ci : Bilans przejazdu : Wypłaty : Odebrana gotówka"))),
                    tips=num(r.get("Wypłacono Ci:Twój przychód:Napiwek")),
                    bonuses=num(r.get("Wypłacono Ci:Twój przychód:Promocja:Opłata"))))
        else:
            raise ValueError(f"Nie rozpoznano pliku {f.filename}")
    return out

def aggregate(rows):
    m={}
    for r in rows:
        k=r["driver_key"]
        if k not in m:
            m[k]=dict(driver=r["driver"],driver_key=k,platforms=set(),gross=0,transfer=0,cash=0,tips=0,bonuses=0,uber_id="",bolt_id="",uber_id_column="",bolt_id_column="",details=[])
        x=m[k]; x["platforms"].add(r["platform"])
        for fld in ("gross","transfer","cash","tips","bonuses"): x[fld]+=r[fld]
        if r["platform"] == "Uber" and r.get("platform_id"):
            x["uber_id"] = r["platform_id"]
            x["uber_id_column"] = r.get("platform_id_column", "")
        if r["platform"] == "Bolt" and r.get("platform_id"):
            x["bolt_id"] = r["platform_id"]
            x["bolt_id_column"] = r.get("platform_id_column", "")
        x["details"].append(r)
    for x in m.values(): x["platforms"]=", ".join(sorted(x["platforms"]))
    return list(m.values())


@app.before_request
def require_login():
    if request.endpoint in {"login", "static"}:
        return None
    if not session.get("authenticated"):
        return redirect(url_for("login", next=request.path))

@app.route("/login", methods=["GET", "POST"])
def login():
    if request.method == "POST":
        if request.form.get("login") == "admin" and request.form.get("password") == "admin":
            session["authenticated"] = True
            return redirect(request.args.get("next") or "/")
        flash("Nieprawidłowy login lub hasło.")
    return render("""
    <div class="login-wrap"><div class="card">
      <h2>GO PARTNER</h2><p class="muted">Logowanie do systemu</p>
      <form method="post">
        <div class="field"><label>Login</label><input name="login" required></div>
        <div class="field"><label>Hasło</label><input type="password" name="password" required></div><br>
        <button class="btn primary" style="width:100%">Zaloguj</button>
      </form><p class="muted">Test: admin / admin</p>
    </div></div>
    """)

@app.route("/logout")
def logout():
    session.clear()
    return redirect("/login")

@app.route("/")
def dashboard():
    with db() as c:
        active=c.execute("SELECT COUNT(*) FROM drivers WHERE active=1").fetchone()[0]
        count=c.execute("SELECT COUNT(*) FROM settlements").fetchone()[0]
        payable=c.execute("SELECT COALESCE(SUM(total_payable),0) FROM settlements").fetchone()[0]
        fees=c.execute("SELECT COALESCE(SUM(partner_commission+rental+b2b_fee),0) FROM settlement_rows").fetchone()[0]
        recent=c.execute("SELECT * FROM settlements ORDER BY id DESC LIMIT 10").fetchall()
    return render("""
    <div class="row" style="justify-content:space-between"><h2>Dashboard</h2><a class="btn" href="/">Odśwież</a></div>
    <div class="grid g4">
      <div class="card metric"><span class="muted">Aktywni kierowcy</span><b>{{active}}</b></div>
      <div class="card metric"><span class="muted">Rozliczenia</span><b>{{count}}</b></div>
      <div class="card metric"><span class="muted">Do wypłaty razem</span><b>{{money(payable)}}</b></div>
      <div class="card metric"><span class="muted">Prowizje + wynajem</span><b>{{money(fees)}}</b></div>
    </div>
    <div class="card"><h3>Ostatnie rozliczenia</h3>
    {% if recent %}<table><tr><th>Okres</th><th>Brutto</th><th>Przelew</th><th>Do wypłaty</th></tr>
    {% for s in recent %}<tr><td>{{s.week_start}} – {{s.week_end}}</td><td>{{money(s.total_gross)}}</td><td>{{money(s.total_transfer)}}</td><td>{{money(s.total_payable)}}</td></tr>{% endfor %}</table>
    {% else %}<div class="muted">Brak danych.</div>{% endif %}</div>
    """, active=active,count=count,payable=payable,fees=fees,recent=recent,money=money)


@app.route("/drivers/new", methods=["GET", "POST"])
def new_driver():
    if request.method == "POST":
        name = f"{request.form.get('first_name','').strip()} {request.form.get('last_name','').strip()}".strip()
        if not name:
            flash("Wpisz imię i nazwisko kierowcy.")
            return redirect("/drivers/new")
        key = norm_name(name)
        with db() as c:
            if c.execute("SELECT 1 FROM drivers WHERE driver_key=?", (key,)).fetchone():
                flash("Kierowca już istnieje.")
                return redirect(url_for("driver", key=key))
            status=request.form.get("status","AKTYWNY")
            c.execute("""INSERT INTO drivers(driver_key,driver_name,phone,email,car,bank_account,status,active,partner_commission,rental,other,scheme_type,updated_at) VALUES(?,?,?,?,?,?,?,?,?,?,?,?,?)""",(key,name,request.form.get('phone',''),request.form.get('email',''),request.form.get('car',''),normalize_bank_account(request.form.get('bank_account','')),status,1 if status=='AKTYWNY' else 0,num(request.form.get('partner_commission')),num(request.form.get('rental')),num(request.form.get('other')),request.form.get('scheme_type','BRAK'),datetime.now().isoformat(timespec='seconds')))
            log("Dodano kierowcę ręcznie", name, connection=c)
        flash("Kierowca został dodany.")
        return redirect(url_for("driver", key=key))
    return render("""
    <div class="row" style="justify-content:space-between"><h2>Dodaj kierowcę ręcznie</h2><a class="btn" href="/drivers">Powrót</a></div>
    <div class="card"><form method="post"><div class="grid g3">
      <div class="field"><label>Imię</label><input name="first_name" required></div>
      <div class="field"><label>Nazwisko</label><input name="last_name" required></div>
      <div class="field"><label>Telefon</label><input name="phone"></div>
      <div class="field"><label>E-mail</label><input name="email"></div>
      <div class="field"><label>Samochód</label><input name="car"></div>
      <div class="field"><label>Numer konta / IBAN</label><input name="bank_account"></div>
      <div class="field"><label>Prowizja ręczna</label><input name="partner_commission" value="0"></div>
      <div class="field"><label>Wynajem tygodniowy</label><input name="rental" value="0"></div>
      <div class="field"><label>Inne potrącenia</label><input name="other" value="0"></div>
      <div class="field"><label>Status</label><select name="status"><option value="AKTYWNY">Aktywny</option><option value="NIEAKTYWNY">Nieaktywny</option><option value="ARCHIWALNY">Archiwalny</option></select></div>
      <div class="field"><label>Schemat</label><select name="scheme_type"><option value="BRAK">Brak</option><option value="UMOWA_ZLECENIA">Umowa zlecenia</option><option value="B2B">B2B</option></select></div>
    </div><br><button class="btn primary">Dodaj kierowcę</button></form></div>
    """)

@app.route("/drivers")
def drivers():
    q=request.args.get("q","").strip()
    status=request.args.get("status","all")
    sql="SELECT * FROM drivers WHERE 1=1"; params=[]
    if q:
        sql+=" AND (driver_name LIKE ? OR phone LIKE ? OR email LIKE ?)"; params += [f"%{q}%"]*3
    if status=="active": sql+=" AND status='AKTYWNY'"
    if status=="inactive": sql+=" AND status='NIEAKTYWNY'"
    if status=="archived": sql+=" AND status='ARCHIWALNY'"
    sql+=" ORDER BY driver_name"
    with db() as c: rows=c.execute(sql,params).fetchall()
    return render("""
    <div class="row" style="justify-content:space-between"><h2>Kierowcy</h2><div class="row"><a class="btn primary" href="/drivers/new">+ Dodaj kierowcę</a><a class="btn" href="/drivers">Odśwież</a></div></div>
    <div class="card"><form class="grid g3">
      <div class="field"><label>Szukaj</label><input name="q" value="{{q}}" placeholder="Imię, nazwisko, telefon, e-mail"></div>
      <div class="field"><label>Status</label><select name="status"><option value="all">Wszyscy</option><option value="active" {% if status=='active' %}selected{% endif %}>Aktywni</option><option value="inactive" {% if status=='inactive' %}selected{% endif %}>Nieaktywni</option><option value="archived" {% if status=='archived' %}selected{% endif %}>Archiwalni</option></select></div>
      <div class="field"><label>&nbsp;</label><button class="btn primary">Szukaj</button></div>
    </form></div>
    <div class="card"><table><tr><th>Kierowca</th><th>Telefon</th><th>E-mail</th><th>Samochód</th><th>Status</th><th></th></tr>
    {% for d in rows %}<tr><td><b>{{d.driver_name}}</b></td><td>{{d.phone}}</td><td>{{d.email}}</td><td>{{d.car}}</td><td>{% if d.status=='ARCHIWALNY' %}<span class="badge arch">Archiwalny</span>{% elif d.status=='NIEAKTYWNY' %}<span class="badge off">Nieaktywny</span>{% else %}<span class="badge on">Aktywny</span>{% endif %}</td><td><a class="btn" href="/drivers/{{d.driver_key}}">Otwórz</a></td></tr>{% endfor %}
    </table></div>
    """,rows=rows,q=q,status=status)


def pending_cost_balance(key):
    with db() as c:
        rows=c.execute("""
        SELECT * FROM driver_costs
        WHERE driver_key=? AND apply_next=1 AND applied_settlement_id IS NULL
        """,(key,)).fetchall()
    return sum((r["amount"] if r["entry_type"]=="BONUS" else -r["amount"]) for r in rows)


def installment_plans_for_driver(key, active_only=False):
    sql="SELECT * FROM installment_plans WHERE driver_key=?"
    if active_only:
        sql+=" AND active=1"
    sql+=" ORDER BY active DESC,id DESC"
    with db() as c:
        return c.execute(sql,(key,)).fetchall()


def plan_remaining(plan):
    return max(
        0.0,
        float(plan["total_amount"] or 0)
        - float(plan["initial_paid"] or 0)
        - float(plan["paid_from_settlements"] or 0)
    )


def damage_summary_for_driver(key):
    with db() as c:
        plans = c.execute("""
        SELECT * FROM installment_plans
        WHERE driver_key=? AND category IN ('SZKODA', 'DŁUG')
        ORDER BY id
        """, (key,)).fetchall()

    total = sum(float(plan["total_amount"] or 0) for plan in plans)
    initial_paid = sum(float(plan["initial_paid"] or 0) for plan in plans)
    paid_from_settlements = sum(
        float(plan["paid_from_settlements"] or 0) for plan in plans
    )
    paid = min(total, initial_paid + paid_from_settlements)
    remaining = max(0.0, total - paid)

    return {
        "total": total,
        "initial_paid": initial_paid,
        "paid_from_settlements": paid_from_settlements,
        "paid": paid,
        "remaining": remaining,
        "plans_count": len(plans),
    }


def deposit_summary_for_driver(key):
    with db() as c:
        plans = c.execute("""
        SELECT * FROM installment_plans
        WHERE driver_key=? AND category='KAUCJA'
        ORDER BY id
        """, (key,)).fetchall()
        returns = c.execute("""
        SELECT * FROM deposit_returns
        WHERE driver_key=?
        ORDER BY return_date DESC, id DESC
        """, (key,)).fetchall()

    total = sum(float(plan["total_amount"] or 0) for plan in plans)
    initial_paid = sum(float(plan["initial_paid"] or 0) for plan in plans)
    paid_from_settlements = sum(
        float(plan["paid_from_settlements"] or 0) for plan in plans
    )
    paid = min(total, initial_paid + paid_from_settlements)
    returned = sum(float(item["amount"] or 0) for item in returns)
    held = max(0.0, paid - returned)
    remaining = max(0.0, total - paid)

    return {
        "total": total,
        "initial_paid": initial_paid,
        "paid_from_settlements": paid_from_settlements,
        "paid": paid,
        "returned": returned,
        "held": held,
        "remaining": remaining,
        "plans_count": len(plans),
        "returns": returns,
    }


def installment_preview_for_driver(key):
    charges=[]
    for plan in installment_plans_for_driver(key, active_only=True):
        remaining=plan_remaining(plan)
        if remaining <= 0:
            continue
        amount=min(float(plan["weekly_amount"] or 0),remaining)
        if amount > 0:
            charges.append({
                "plan_id": plan["id"],
                "title": plan["title"],
                "category": plan["category"],
                "amount": amount,
                "remaining_before": remaining,
            })
    return charges


def latest_draft_for_driver(key):
    with db() as c:
        return c.execute("""
        SELECT dr.*, d.week_start, d.week_end, d.created_at
        FROM settlement_draft_rows dr
        JOIN settlement_drafts d ON d.id=dr.draft_id
        WHERE dr.driver_key=?
        ORDER BY d.id DESC
        LIMIT 1
        """,(key,)).fetchone()


def latest_saved_settlement_for_driver(key):
    with db() as c:
        return c.execute("""
        SELECT sr.*, s.week_start, s.week_end, s.created_at
        FROM settlement_rows sr
        JOIN settlements s ON s.id=sr.settlement_id
        WHERE sr.driver_key=?
        ORDER BY s.id DESC
        LIMIT 1
        """,(key,)).fetchone()


def next_installment_total(key):
    return sum(item["amount"] for item in installment_preview_for_driver(key))


def current_driver_balance(key):
    """
    Aktualne saldo pokazuje kwotę bieżącego rozliczenia, a nie cały pozostały dług.

    Priorytet:
    1. najnowszy podgląd po imporcie CSV,
    2. ostatnie zapisane rozliczenie,
    3. same oczekujące korekty.

    Do salda doliczamy tylko następne raty tygodniowe, nie całą pozostałą kwotę długu.
    """
    draft=latest_draft_for_driver(key)
    if draft:
        return float(draft["payable"] or 0)

    latest=latest_saved_settlement_for_driver(key)
    if latest:
        latest_value = float(latest["payable"] or 0)
        if int(latest["is_paid"] or 0) == 1:
            # Po wypłacie dodatnie saldo jest zamknięte do zera.
            # Ujemne saldo pozostaje jako zadłużenie kierowcy.
            base = latest_value if latest_value < 0 else 0.0
        else:
            base = latest_value
        return base + pending_cost_balance(key)

    return pending_cost_balance(key)




def iter_dates(start_date, end_date):
    current = start_date
    while current <= end_date:
        yield current
        current += timedelta(days=1)


def add_scheduled_cost(connection, kind, source_id, driver_key, occurrence_date,
                       title, amount, entry_type="POTRĄCENIE", note="",
                       installment_number=0, installment_total=0):
    exists = connection.execute("""
    SELECT id FROM scheduled_occurrences
    WHERE kind=? AND source_id=? AND driver_key=? AND occurrence_date=?
    """, (kind, source_id, driver_key, occurrence_date.isoformat())).fetchone()
    if exists:
        return None

    cursor = connection.execute("""
    INSERT INTO driver_costs(
      driver_key,entry_date,title,amount,entry_type,apply_next,
      applied_settlement_id,note,created_at,source_label,
      installment_number,installment_total
    ) VALUES(?,?,?,?,?,?,?,?,?,?,?,?)
    """, (
        driver_key, occurrence_date.isoformat(), title, float(amount), entry_type,
        1, None, note, datetime.now().isoformat(timespec="seconds"), kind,
        int(installment_number or 0), int(installment_total or 0)
    ))
    cost_id = cursor.lastrowid
    connection.execute("""
    INSERT INTO scheduled_occurrences(
      kind,source_id,driver_key,occurrence_date,cost_id
    ) VALUES(?,?,?,?,?)
    """, (kind, source_id, driver_key, occurrence_date.isoformat(), cost_id))
    return cost_id


def exact_daily_rental(weekly_rate, weekday):
    """
    Rozdziela tygodniową cenę dokładnie na 7 dni.
    Dla 850 zł: pon-sob 121,43 zł, niedziela 121,42 zł.
    Suma zawsze wynosi dokładnie 850,00 zł.
    """
    cents = int(round(float(weekly_rate or 0) * 100))
    base = cents // 7
    remainder = cents % 7
    daily_cents = base + (1 if weekday < remainder else 0)
    return daily_cents / 100.0


def ensure_scheduled_costs_for_period(start_date, end_date, driver_keys=None):
    with db() as c:
        params = []
        sql = "SELECT * FROM drivers WHERE active=1 AND status='AKTYWNY'"
        if driver_keys:
            placeholders = ",".join("?" for _ in driver_keys)
            sql += f" AND driver_key IN ({placeholders})"
            params.extend(driver_keys)
        drivers = c.execute(sql, params).fetchall()

        # Dzienny wynajem samochodu.
        for driver in drivers:
            weekly = float(driver["rental"] or 0)
            if weekly > 0:
                rental_start = start_date
                if driver["rental_start_date"]:
                    try:
                        rental_start = max(
                            rental_start,
                            datetime.strptime(driver["rental_start_date"], "%Y-%m-%d").date()
                        )
                    except ValueError:
                        pass
                for day in iter_dates(rental_start, end_date):
                    amount = exact_daily_rental(weekly, day.weekday())
                    add_scheduled_cost(
                        c, "WYNAJEM_DZIENNY", 0, driver["driver_key"], day,
                        "Wynajem auta — naliczenie dzienne", amount,
                        "POTRĄCENIE",
                        f"Stawka tygodniowa {weekly:.2f} zł"
                    )

            # ZUS raz w miesiącu dla umowy zlecenia.
            if driver["scheme_type"] == "UMOWA_ZLECENIA" and float(driver["monthly_zus"] or 0) > 0:
                month_cursor = date(start_date.year, start_date.month, 1)
                last_month = date(end_date.year, end_date.month, 1)
                while month_cursor <= last_month:
                    last_day = calendar.monthrange(month_cursor.year, month_cursor.month)[1]
                    charge_day = min(max(int(driver["zus_day"] or 1), 1), last_day)
                    occurrence = date(month_cursor.year, month_cursor.month, charge_day)
                    if start_date <= occurrence <= end_date:
                        add_scheduled_cost(
                            c, "ZUS_MIESIECZNY", 0, driver["driver_key"], occurrence,
                            "ZUS — umowa zlecenia",
                            float(driver["monthly_zus"]),
                            "POTRĄCENIE",
                            f"Automatyczne naliczenie miesięczne, dzień {charge_day}"
                        )
                    if month_cursor.month == 12:
                        month_cursor = date(month_cursor.year + 1, 1, 1)
                    else:
                        month_cursor = date(month_cursor.year, month_cursor.month + 1, 1)

        # Zwykłe pozycje cykliczne — każdy poniedziałek.
        rules = c.execute("""
        SELECT * FROM recurring_rules WHERE active=1
        """).fetchall()
        for rule in rules:
            if driver_keys and rule["driver_key"] not in driver_keys:
                continue
            created = datetime.fromisoformat(rule["created_at"]).date()
            first = max(start_date, created)
            monday = first + timedelta(days=(7 - first.weekday()) % 7)
            if first.weekday() == 0:
                monday = first
            while monday <= end_date:
                add_scheduled_cost(
                    c, "CYKLICZNE_TYGODNIOWE", rule["id"], rule["driver_key"], monday,
                    rule["title"], float(rule["amount"]), rule["rule_type"],
                    rule["note"] or "Automatyczne naliczenie w poniedziałek"
                )
                monday += timedelta(days=7)

        # Plany ratalne — dokładnie jedna rata za każdy rozliczany tydzień.
        # Ważne: jeżeli plan utworzono np. we wtorek, a CSV dotyczy tego samego
        # tygodnia (poniedziałek–niedziela), rata nadal musi zostać naliczona.
        plans = c.execute("""
        SELECT * FROM installment_plans
        WHERE active=1 AND COALESCE(cancelled_at,'')=''
        """).fetchall()
        for plan in plans:
            if driver_keys and plan["driver_key"] not in driver_keys:
                continue

            created = datetime.fromisoformat(plan["created_at"]).date()
            if created > end_date:
                # Plan powstał dopiero po rozliczanym okresie.
                continue

            pending_amount = c.execute("""
            SELECT COALESCE(SUM(dc.amount),0)
            FROM scheduled_occurrences so
            JOIN driver_costs dc ON dc.id=so.cost_id
            WHERE so.kind='RATA_TYGODNIOWA'
              AND so.source_id=?
              AND dc.applied_settlement_id IS NULL
            """, (plan["id"],)).fetchone()[0]
            available = max(0.0, plan_remaining(plan) - float(pending_amount or 0))

            weekly_amount = max(float(plan["weekly_amount"] or 0), 0.01)
            total_installments = max(
                1,
                math.ceil(
                    max(
                        0.0,
                        float(plan["total_amount"] or 0)
                        - float(plan["initial_paid"] or 0)
                    ) / weekly_amount
                )
            )
            existing_count = c.execute("""
            SELECT COUNT(*) FROM scheduled_occurrences
            WHERE kind='RATA_TYGODNIOWA' AND source_id=?
            """, (plan["id"],)).fetchone()[0]

            # Rozliczenie może obejmować więcej niż tydzień, dlatego iterujemy
            # po poniedziałkach należących do okresu. Dla standardowego CSV
            # tygodniowego powstanie dokładnie jedna rata.
            week_monday = start_date - timedelta(days=start_date.weekday())
            while week_monday <= end_date and available > 0:
                week_sunday = week_monday + timedelta(days=6)
                if created <= week_sunday:
                    amount = min(weekly_amount, available)
                    installment_number = existing_count + 1
                    created_cost = add_scheduled_cost(
                        c, "RATA_TYGODNIOWA", plan["id"], plan["driver_key"], week_monday,
                        f"{plan['title']} — rata {installment_number}/{total_installments}",
                        amount,
                        "POTRĄCENIE",
                        (
                            f"{plan['category']} {amount:.2f} zł "
                            f"{installment_number}/{total_installments}"
                            + (f" — {plan['note']}" if plan['note'] else "")
                        ),
                        installment_number=installment_number,
                        installment_total=total_installments,
                    )
                    if created_cost:
                        available -= amount
                        existing_count += 1
                week_monday += timedelta(days=7)


def save_current_draft(rows, week_start, week_end):
    with db() as c:
        c.execute("DELETE FROM settlement_draft_rows")
        c.execute("DELETE FROM settlement_drafts")
        cur=c.execute("""
        INSERT INTO settlement_drafts(week_start,week_end,created_at)
        VALUES(?,?,?)
        """,(week_start,week_end,datetime.now().isoformat(timespec="seconds")))
        draft_id=cur.lastrowid
        for r in rows:
            c.execute("""
            INSERT INTO settlement_draft_rows(
              draft_id,driver_key,driver_name,platforms,gross,transfer,
              partner_commission,rental,recurring_total,manual_adjustments,
              fines,other,payable
            ) VALUES(?,?,?,?,?,?,?,?,?,?,?,?,?)
            """,(
                draft_id,r["driver_key"],r["driver"],r["platforms"],r["gross"],
                r["transfer"],r["commission"],r["rental"],r["recurring_total"],
                r["manual_adjustments"],r["fines"],r["other"],r["payable"]
            ))


def clear_current_draft():
    with db() as c:
        c.execute("DELETE FROM settlement_draft_rows")
        c.execute("DELETE FROM settlement_drafts")


@app.route("/drivers/<key>", methods=["GET","POST"])
def driver(key):
    tab=request.args.get("tab","profile")

    if request.method=="POST":
        with db() as c:
            c.execute("""
            UPDATE drivers SET
              phone=?,email=?,car=?,bank_account=?,
              partner_commission=?,rental=?,other=?,
              deposit_amount=?,accident_debt=?,active=?,status=?,notes=?,
              scheme_type=?,monthly_zus=?,zus_day=?,rental_start_date=?,
              updated_at=?
            WHERE driver_key=?
            """,(
                request.form.get("phone",""),
                request.form.get("email",""),
                request.form.get("car",""),
                normalize_bank_account(request.form.get("bank_account","")),
                num(request.form.get("partner_commission")),
                num(request.form.get("rental")),
                num(request.form.get("other")),
                num(request.form.get("deposit_amount")),
                num(request.form.get("accident_debt")),
                1 if request.form.get("status","AKTYWNY") == "AKTYWNY" else 0,
                request.form.get("status","AKTYWNY"),
                request.form.get("notes",""),
                request.form.get("scheme_type","BRAK"),
                num(request.form.get("monthly_zus")),
                int(request.form.get("zus_day") or 1),
                request.form.get("rental_start_date",""),
                datetime.now().isoformat(timespec="seconds"),
                key,
            ))
        log("Zapisano profil kierowcy",key)
        flash("Profil zapisano.")
        return redirect(url_for("driver",key=key,tab="profile"))

    monday_today = date.today() - timedelta(days=date.today().weekday())
    ensure_scheduled_costs_for_period(monday_today, date.today(), [key])

    with db() as c:
        d=c.execute("SELECT * FROM drivers WHERE driver_key=?",(key,)).fetchone()
        history=c.execute("""
        SELECT sr.*, s.week_start, s.week_end, s.created_at AS settlement_created
        FROM settlement_rows sr
        JOIN settlements s ON s.id=sr.settlement_id
        WHERE sr.driver_key=?
        ORDER BY s.week_start DESC, s.id DESC
        """,(key,)).fetchall()
        costs=c.execute("""
        SELECT * FROM driver_costs
        WHERE driver_key=?
        ORDER BY id DESC
        """,(key,)).fetchall()

    if not d:
        flash("Nie znaleziono kierowcy.")
        return redirect("/drivers")

    plans=installment_plans_for_driver(key)
    balance=current_driver_balance(key)
    active_plan_remaining=sum(plan_remaining(p) for p in plans if p["active"])
    deposit_summary=deposit_summary_for_driver(key)
    damage_summary=damage_summary_for_driver(key)
    current_draft=latest_draft_for_driver(key)
    latest_saved=latest_saved_settlement_for_driver(key)
    next_installment=next_installment_total(key)
    collision_remaining=sum(plan_remaining(p) for p in plans if p["category"] in ("SZKODA","DŁUG") and not p["cancelled_at"])

    return render("""
    <div class="row" style="justify-content:space-between">
      <div>
        <h2 style="margin-bottom:5px">{{d.driver_name}}</h2>
        <div class="muted">{{d.phone or "brak telefonu"}} · {{d.email or "brak e-mail"}} · {{d.car or "brak samochodu"}}</div>
        <div class="muted">Uber ID: {{d.uber_id or "brak"}} · Bolt ID: {{d.bolt_id or "brak"}}</div>
      </div>
      <div class="card metric" style="min-width:230px;margin:0">
        <span class="muted">Aktualne saldo</span>
        <b class="{{'pos' if balance >= 0 else 'neg'}}">{{money(balance)}}</b>
        <small class="muted">Korekty oczekujące minus pozostałe raty</small>
      </div>
    </div>

    <div class="grid g4" style="margin-top:14px">
      <div class="card metric"><span class="muted">Status</span><b style="font-size:18px">{{d.status}}</b></div>
      <div class="card metric"><span class="muted">Aktualne saldo</span><b>{{money(balance)}}</b></div>
      <div class="card metric"><span class="muted">Kaucja zatrzymana</span><b>{{money(deposit_summary.held)}}</b></div>
      <div class="card metric"><span class="muted">Kolizje / długi</span><b>{{money(collision_remaining)}}</b></div>
      <div class="card metric"><span class="muted">Samochód</span><b style="font-size:18px">{{d.car or "Brak"}}</b></div>
      <div class="card metric"><span class="muted">Schemat</span><b style="font-size:18px">{{d.scheme_type}}</b></div>
      <div class="card metric"><span class="muted">Ostatnie rozliczenie</span><b style="font-size:18px">{% if latest_saved %}{{latest_saved.week_end}}{% else %}Brak{% endif %}</b></div>
      <div class="card metric"><span class="muted">Do wypłaty</span><b>{{money(current_draft.payable if current_draft else (latest_saved.payable if latest_saved else 0))}}</b></div>
    </div>

    <div class="tabs">
      <a class="{{'active' if tab=='profile' else ''}}" href="/drivers/{{d.driver_key}}?tab=profile">Profil</a>
      <a class="{{'active' if tab=='settlements' else ''}}" href="/drivers/{{d.driver_key}}?tab=settlements">Rozliczenia</a>
      <a class="{{'active' if tab=='costs' else ''}}" href="/drivers/{{d.driver_key}}?tab=costs">Koszty</a>
      <a class="{{'active' if tab=='recurring' else ''}}" href="/drivers/{{d.driver_key}}?tab=recurring">Cykliczne</a>
      <a class="{{'active' if tab=='schemes' else ''}}" href="/drivers/{{d.driver_key}}?tab=schemes">Schematy</a>
    </div>

    {% if tab=='profile' %}
    <div class="grid g4">
      <div class="card metric">
        <span class="muted">Aktualne saldo</span>
        <b class="{{'pos' if balance >= 0 else 'neg'}}">{{money(balance)}}</b>
        <small class="muted">
          {% if current_draft %}Bieżący podgląd {{current_draft.week_start}}–{{current_draft.week_end}}
          {% elif latest_saved %}Ostatnie zapisane rozliczenie
          {% else %}Brak rozliczenia{% endif %}
        </small>
      </div>
      <div class="card metric"><span class="muted">Oczekujące bonusy / potrącenia</span><b>{{money(pending_balance)}}</b></div>
      <div class="card metric"><span class="muted">Następna rata tygodniowa</span><b>{{money(next_installment)}}</b></div>
      <div class="card metric"><span class="muted">Pozostało w aktywnych ratach</span><b>{{money(active_plan_remaining)}}</b></div>
    </div>
    <div class="grid g3">
      <div class="card metric">
        <span class="muted">Kaucja — aktualnie zatrzymana</span>
        <b class="pos">{{money(deposit_summary.held)}}</b>
        <small class="muted">
          Wpłacono: {{money(deposit_summary.paid)}} ·
          Zwrócono: {{money(deposit_summary.returned)}}
        </small>
      </div>
      <div class="card metric">
        <span class="muted">Szkody / długi — pozostało</span>
        <b class="{{'neg' if damage_summary.remaining > 0 else 'pos'}}">{{money(damage_summary.remaining)}}</b>
        <small class="muted">
          Cała kwota: {{money(damage_summary.total)}} ·
          Zapłacono: {{money(damage_summary.paid)}}
        </small>
      </div>
    </div>
    <div class="card"><form method="post">
      <div class="grid g3">
        <div class="field"><label>Telefon</label><input name="phone" value="{{d.phone}}"></div>
        <div class="field"><label>E-mail</label><input name="email" value="{{d.email}}"></div>
        <div class="field"><label>Samochód</label><input name="car" value="{{d.car}}"></div>
        <div class="field">
          <label>Numer konta do wypłaty / IBAN</label>
          <input name="bank_account" value="{{d.bank_account}}"
                 placeholder="PL00 0000 0000 0000 0000 0000 0000">
          <small class="muted">
            Konto używane do pliku przelewów ING. Program zapisuje numer bez spacji.
          </small>
        </div>
        <div class="field">
          <label>ID Uber</label>
          <input value="{{d.uber_id or 'Brak ID w zaimportowanym CSV'}}" readonly>
          <small class="muted">Pobierane automatycznie z CSV i blokowane po pierwszym zapisie.</small>
        </div>
        <div class="field">
          <label>ID Bolt</label>
          <input value="{{d.bolt_id or 'Brak ID w zaimportowanym CSV'}}" readonly>
          <small class="muted">Pobierane automatycznie z CSV i blokowane po pierwszym zapisie.</small>
        </div>
        <div class="field">
          <label>Prowizja partnera ręczna, zł</label>
          <input name="partner_commission" value="{{d.partner_commission}}">
          <small class="muted">
            Używana tylko wtedy, gdy nie wybrano schematu B2B.
            Dla B2B program nalicza automatycznie 50 zł + 1% od brutto.
          </small>
        </div>
        <div class="field"><label>Wynajem auta za tydzień, zł</label><input name="rental" value="{{d.rental}}"></div>
        <div class="field"><label>Wynajem naliczać od</label><input type="date" name="rental_start_date" value="{{d.rental_start_date}}"></div>
        <div class="field"><label>Inne stałe potrącenia, zł</label><input name="other" value="{{d.other}}"></div>
        <div class="field">
          <label>Kaucja aktualnie zatrzymana, zł</label>
          <input value="{{'%.2f'|format(deposit_summary.held)}}" readonly>
          <small class="muted">
            Wpłacono: {{money(deposit_summary.paid)}} ·
            Zwrócono: {{money(deposit_summary.returned)}}
          </small>
        </div>
        <div class="field">
          <label>Zadłużenie za szkodę — pozostało, zł</label>
          <input value="{{'%.2f'|format(damage_summary.remaining)}}" readonly>
          <small class="muted">
            Cała kwota: {{money(damage_summary.total)}} ·
            Zapłacono: {{money(damage_summary.paid)}} ·
            Z rozliczeń: {{money(damage_summary.paid_from_settlements)}}
          </small>
        </div>
        <input type="hidden" name="accident_debt" value="{{damage_summary.remaining}}">
        <input type="hidden" name="deposit_amount" value="{{deposit_summary.paid}}">
      </div>
      <div class="field"><label>Notatki</label><textarea name="notes">{{d.notes}}</textarea></div>
      <div class="field"><label>Status kierowcy</label><select name="status"><option value="AKTYWNY" {% if d.status=='AKTYWNY' %}selected{% endif %}>Aktywny</option><option value="NIEAKTYWNY" {% if d.status=='NIEAKTYWNY' %}selected{% endif %}>Nieaktywny</option><option value="ARCHIWALNY" {% if d.status=='ARCHIWALNY' %}selected{% endif %}>Archiwalny</option></select></div><br><button class="btn primary">Zapisz profil</button>
    </form></div>

    {% endif %}

    {% if tab=='settlements' %}
    <div class="card">
      <div class="row" style="justify-content:space-between">
        <h3>Rozliczenia za cały okres pracy</h3>
        <a class="btn" href="/drivers/{{d.driver_key}}/settlements/export">Eksport CSV</a>
      </div>
      {% if history %}
      <div class="grid g4">
        <div class="card metric"><span class="muted">Liczba rozliczeń</span><b>{{history|length}}</b></div>
        <div class="card metric"><span class="muted">Przychód brutto</span><b>{{money(total_gross)}}</b></div>
        <div class="card metric"><span class="muted">Przelewy platform</span><b>{{money(total_transfer)}}</b></div>
        <div class="card metric"><span class="muted">Łącznie do wypłaty</span><b>{{money(total_payable)}}</b></div>
      </div>
      <table>
        <tr><th>Okres</th><th>Platformy</th><th>Brutto</th><th>Przelew</th><th>Prowizja ręczna</th><th>B2B: 50 zł + 1%</th><th>Wynajem</th><th>Korekty / raty</th><th>Do wypłaty</th><th>Status</th><th></th></tr>
        {% for r in history %}
        <tr>
          <td>{{r.week_start}} – {{r.week_end}}</td>
          <td>{{r.platforms}}</td>
          <td>{{money(r.gross)}}</td>
          <td>{{money(r.transfer)}}</td>
          <td>{{money(r.partner_commission)}}</td>
          <td>{{money(r.b2b_fee)}}</td>
          <td>{{money(r.rental)}}</td>
          <td>{{money((r.recurring_total or 0)+(r.manual_adjustments or 0))}}</td>
          <td><b>{{money(r.payable)}}</b></td>
          <td>{% if r.is_paid %}<span class="badge on">Rozliczono</span>{% else %}<span class="badge off">Oczekuje</span>{% endif %}</td>
          <td><a class="btn" href="/drivers/{{d.driver_key}}/settlements/{{r.settlement_id}}">Szczegóły</a></td>
        </tr>
        {% endfor %}
      </table>
      {% else %}<div class="muted">Brak historii rozliczeń tego kierowcy.</div>{% endif %}
    </div>
    {% endif %}

    {% if tab=='costs' %}
    <div class="grid g4">
      <div class="card metric">
        <span class="muted">Aktualnie do wypłaty</span>
        <b class="{{'pos' if current_draft else ''}}">
          {% if current_draft %}{{money(current_draft.payable)}}{% else %}Brak bieżącego CSV{% endif %}
        </b>
        {% if current_draft %}<small class="muted">{{current_draft.week_start}}–{{current_draft.week_end}}</small>{% endif %}
      </div>
      <div class="card metric"><span class="muted">Oczekujące bonusy / potrącenia</span><b>{{money(pending_balance)}}</b></div>
      <div class="card metric"><span class="muted">Kaucja zatrzymana</span><b>{{money(deposit_summary.held)}}</b></div>
      <div class="card metric"><span class="muted">Kaucja zwrócona</span><b>{{money(deposit_summary.returned)}}</b></div>
    </div>
    <div class="card">
      <h3>Dodaj bonus lub potrącenie</h3>
      <form method="post" action="/drivers/{{d.driver_key}}/costs/add">
        <div class="grid g3">
          <div class="field"><label>Nazwa</label><input name="title" placeholder="np. nadpłata z poprzedniego tygodnia" required></div>
          <div class="field"><label>Kwota, zł</label><input name="amount" type="number" min="0" step="0.01" required></div>
          <div class="field"><label>Rodzaj</label><select name="entry_type"><option value="POTRĄCENIE">POTRĄCENIE</option><option value="BONUS">BONUS</option></select></div>
        </div>
        <div class="field"><label>Komentarz</label><textarea name="note"></textarea></div>
        <p><label><input type="checkbox" name="apply_next" checked> Zastosuj w następnym rozliczeniu</label></p>
        <button class="btn primary">Dodaj wpis</button>
      </form>
    </div>
    <div class="card">
      <h3>Zwrot kaucji</h3>
      <p class="muted">
        Dostępne do zwrotu: <b>{{money(deposit_summary.held)}}</b>.
        Możesz wskazać przelew lub gotówkę, dodać komentarz i załączyć potwierdzenie.
      </p>
      <form method="post" enctype="multipart/form-data"
            action="/drivers/{{d.driver_key}}/deposit-return/add">
        <div class="grid g3">
          <div class="field">
            <label>Kwota zwrotu, zł</label>
            <input type="number" name="amount" min="0.01" step="0.01"
                   max="{{deposit_summary.held}}" required>
          </div>
          <div class="field">
            <label>Sposób zwrotu</label>
            <select name="method" required>
              <option value="PRZELEW">Przelew</option>
              <option value="GOTÓWKA">Gotówka</option>
            </select>
          </div>
          <div class="field">
            <label>Data zwrotu</label>
            <input type="date" name="return_date" value="{{today}}" required>
          </div>
        </div>
        <div class="field">
          <label>Komentarz</label>
          <textarea name="comment" placeholder="np. zwrot po oddaniu samochodu"></textarea>
        </div>
        <div class="field">
          <label>Potwierdzenie przelewu (opcjonalnie)</label>
          <input type="file" name="proof" accept=".pdf,.png,.jpg,.jpeg,.webp">
        </div>
        <br>
        <button class="btn primary">Zapisz zwrot kaucji</button>
      </form>
    </div>

    <div class="card">
      <h3>Historia zwrotów kaucji</h3>
      {% if deposit_summary.returns %}
      <table>
        <tr>
          <th>Data</th><th>Typ</th><th>Kwota</th><th>Sposób</th>
          <th>Komentarz</th><th>Potwierdzenie</th><th></th>
        </tr>
        {% for item in deposit_summary.returns %}
        <tr>
          <td>{{item.return_date}}</td>
          <td>ZWROT KAUCJI</td>
          <td class="neg">-{{money(item.amount)}}</td>
          <td>{{item.method}}</td>
          <td>{{item.comment}}</td>
          <td>
            {% if item.proof_filename %}
              <a class="btn" href="/deposit-return-proof/{{item.id}}">Pobierz</a>
            {% else %}Brak{% endif %}
          </td>
          <td>
            <form method="post"
                  action="/drivers/{{d.driver_key}}/deposit-return/{{item.id}}/delete"
                  onsubmit="return confirm('Usunąć zapis zwrotu kaucji?')">
              <button class="btn danger">Usuń</button>
            </form>
          </td>
        </tr>
        {% endfor %}
      </table>
      {% else %}
      <div class="muted">Brak zapisanych zwrotów kaucji.</div>
      {% endif %}
    </div>

    <div class="card">
      <h3>Historia kosztów i bonusów</h3>
      {% if costs %}
      <table><tr><th>Data</th><th>Nazwa</th><th>Rata</th><th>Rodzaj</th><th>Kwota</th><th>Status</th><th>Komentarz</th><th></th></tr>
      {% for c in costs %}
      <tr>
        <td>{{c.entry_date}}</td><td>{{c.title}}</td>
        <td>{% if c.installment_number %}{{c.installment_number}} / {{c.installment_total}}{% else %}—{% endif %}</td>
        <td>{{c.entry_type}}</td>
        <td class="{{'pos' if c.entry_type=='BONUS' else 'neg'}}">{{'+' if c.entry_type=='BONUS' else '-'}}{{money(c.amount)}}</td>
        <td>{{'Rozliczone' if c.applied_settlement_id else 'Oczekuje'}}</td>
        <td>{{c.note}}</td>
        <td>{% if not c.applied_settlement_id %}<form method="post" action="/drivers/{{d.driver_key}}/costs/{{c.id}}/delete" onsubmit="return confirm('Usunąć ten wpis?')"><button class="btn danger">Usuń</button></form>{% endif %}</td>
      </tr>
      {% endfor %}</table>
      {% else %}<div class="muted">Brak wpisów.</div>{% endif %}
    </div>
    {% endif %}

    {% if tab=='recurring' %}
    <div class="card">
      <h3>Nowa rata cykliczna</h3>
      <p class="muted">Przykład: kaucja 1500 zł, wpłacono gotówką 500 zł, pozostałe 1000 zł po 200 zł tygodniowo.</p>
      <form method="post" action="/drivers/{{d.driver_key}}/installments/add">
        <div class="grid g3">
          <div class="field"><label>Nazwa</label><input name="title" placeholder="np. Kaucja" required></div>
          <div class="field"><label>Kategoria</label><select name="category"><option value="KAUCJA">KAUCJA</option><option value="SZKODA">KOLIZJA / SZKODA</option><option value="DŁUG">INNY DŁUG</option></select></div>
          <div class="field"><label>Cała kwota, zł</label><input name="total_amount" type="number" min="0.01" step="0.01" required></div>
          <div class="field"><label>Wpłacono wcześniej / gotówką, zł</label><input name="initial_paid" type="number" min="0" step="0.01" value="0"></div>
          <div class="field"><label>Rata tygodniowa, zł</label><input name="weekly_amount" type="number" min="0.01" step="0.01" required></div>
          <div class="field"><label>Komentarz</label><input name="note"></div>
        </div>
        <button class="btn primary">Dodaj plan ratalny</button>
      </form>
    </div>

    <div class="card">
      <h3>Aktywne i zakończone plany</h3>
      {% if plans %}
      <table><tr><th>Nazwa</th><th>Kategoria</th><th>Cała kwota</th><th>Wpłata początkowa</th><th>Pobrano z rozliczeń</th><th>Pozostało</th><th>Rata tygodniowa</th><th>Status</th><th></th></tr>
      {% for p in plans %}
      <tr>
        <td>{{p.title}}</td><td>{{p.category}}</td><td>{{money(p.total_amount)}}</td>
        <td>{{money(p.initial_paid)}}</td><td>{{money(p.paid_from_settlements)}}</td>
        <td><b>{{money(plan_remaining(p))}}</b></td><td>{{money(p.weekly_amount)}}</td>
        <td>{% if p.cancelled_at %}Anulowany{% elif p.active and plan_remaining(p)>0 %}Aktywny{% elif plan_remaining(p)<=0 %}Spłacony{% else %}Wstrzymany{% endif %}</td>
        <td>
          <div class="row">{% if p.active and plan_remaining(p)>0 %}<form method="post" action="/drivers/{{d.driver_key}}/installments/{{p.id}}/toggle"><button class="btn">Wstrzymaj</button></form>{% elif plan_remaining(p)>0 and not p.cancelled_at %}<form method="post" action="/drivers/{{d.driver_key}}/installments/{{p.id}}/toggle"><button class="btn primary">Wznów</button></form>{% endif %}{% if not p.cancelled_at and plan_remaining(p)>0 %}<form method="post" action="/drivers/{{d.driver_key}}/installments/{{p.id}}/cancel" onsubmit="return confirm('Anulować ten plan?')"><button class="btn danger">Anuluj</button></form>{% endif %}</div>
        </td>
      </tr>
      {% endfor %}</table>
      {% else %}<div class="muted">Brak planów ratalnych.</div>{% endif %}
    </div>
    {% endif %}

    {% if tab=='schemes' %}
    <div class="card">
      <h3>Schemat zatrudnienia</h3>
      <form method="post">
        <input type="hidden" name="phone" value="{{d.phone}}">
        <input type="hidden" name="email" value="{{d.email}}">
        <input type="hidden" name="car" value="{{d.car}}">
        <input type="hidden" name="bank_account" value="{{d.bank_account}}">
        <input type="hidden" name="partner_commission" value="{{d.partner_commission}}">
        <input type="hidden" name="rental" value="{{d.rental}}">
        <input type="hidden" name="other" value="{{d.other}}">
        <input type="hidden" name="deposit_amount" value="{{d.deposit_amount}}">
        <input type="hidden" name="accident_debt" value="{{d.accident_debt}}">
        <input type="hidden" name="notes" value="{{d.notes}}">
        <input type="hidden" name="rental_start_date" value="{{d.rental_start_date}}">
        <input type="hidden" name="status" value="{{d.status}}">
        <div class="grid g3">
          <div class="field">
            <label>Rodzaj umowy</label>
            <select name="scheme_type">
              <option value="BRAK" {% if d.scheme_type=='BRAK' %}selected{% endif %}>Brak schematu</option>
              <option value="UMOWA_ZLECENIA" {% if d.scheme_type=='UMOWA_ZLECENIA' %}selected{% endif %}>Umowa zlecenia</option>
              <option value="B2B" {% if d.scheme_type=='B2B' %}selected{% endif %}>B2B — 50 zł tygodniowo + 1% od obrotu brutto</option>
            </select>
          </div>
          <div class="field"><label>ZUS miesięcznie, zł</label><input name="monthly_zus" value="{{d.monthly_zus}}"></div>
          <div class="field"><label>Dzień naliczenia ZUS (1–28)</label><input type="number" min="1" max="28" name="zus_day" value="{{d.zus_day or 1}}"></div>
        </div>
        <p class="muted">
          Umowa zlecenia: ZUS jest naliczany automatycznie raz w miesiącu.<br>
          B2B: w każdym tygodniowym rozliczeniu automatycznie pobierane jest 50 zł + 1% od łącznego obrotu brutto Uber i Bolt.<br>
          Jeżeli schemat nie jest wybrany, program używa ręcznej prowizji zapisanej w profilu kierowcy.
        </p>
        <button class="btn primary">Zapisz schemat</button>
      </form>
    </div>
    {% endif %}
    """,
    d=d,tab=tab,history=history,costs=costs,plans=plans,money=money,
    plan_remaining=plan_remaining,balance=balance,
    pending_balance=pending_cost_balance(key),
    active_plan_remaining=active_plan_remaining,
    deposit_summary=deposit_summary,
    damage_summary=damage_summary,
    today=date.today().isoformat(),
    current_draft=current_draft,
    latest_saved=latest_saved,
    next_installment=next_installment,
    collision_remaining=collision_remaining,
    total_gross=sum(float(r["gross"] or 0) for r in history),
    total_transfer=sum(float(r["transfer"] or 0) for r in history),
    total_payable=sum(float(r["payable"] or 0) for r in history)
    )


@app.route("/drivers/<key>/costs/add", methods=["POST"])
def add_driver_cost(key):
    with db() as c:
        c.execute("""
        INSERT INTO driver_costs(
          driver_key,entry_date,title,amount,entry_type,apply_next,
          applied_settlement_id,note,created_at
        ) VALUES(?,?,?,?,?,?,?,?,?)
        """,(
            key,date.today().isoformat(),request.form.get("title","").strip(),
            num(request.form.get("amount")),request.form.get("entry_type","POTRĄCENIE"),
            1 if request.form.get("apply_next") else 0,None,
            request.form.get("note",""),datetime.now().isoformat(timespec="seconds")
        ))
    log("Dodano koszt / bonus",f"{key}: {request.form.get('title','')}")
    flash("Wpis został dodany.")
    return redirect(url_for("driver",key=key,tab="costs"))


@app.route("/drivers/<key>/costs/<int:cost_id>/delete", methods=["POST"])
def delete_driver_cost(key,cost_id):
    deleted = False
    with db() as c:
        row = c.execute(
            "SELECT * FROM driver_costs WHERE id=? AND driver_key=?",
            (cost_id, key),
        ).fetchone()
        if row and not row["applied_settlement_id"]:
            c.execute("DELETE FROM driver_costs WHERE id=?", (cost_id,))
            log(
                "Usunięto koszt / bonus",
                f"{key}: {row['title']}",
                connection=c,
            )
            deleted = True

    if deleted:
        flash("Wpis usunięto.")
    else:
        flash("Nie można usunąć wpisu: nie istnieje albo został już rozliczony.")
    return redirect(url_for("driver",key=key,tab="costs"))


@app.route("/drivers/<key>/installments/add", methods=["POST"])
def add_installment_plan(key):
    total=num(request.form.get("total_amount"))
    initial=num(request.form.get("initial_paid"))
    weekly=num(request.form.get("weekly_amount"))
    if total<=0 or weekly<=0 or initial<0 or initial>total:
        flash("Sprawdź kwotę całkowitą, wpłatę początkową i ratę.")
        return redirect(url_for("driver",key=key,tab="recurring"))
    with db() as c:
        c.execute("""
        INSERT INTO installment_plans(
          driver_key,title,category,total_amount,initial_paid,
          paid_from_settlements,weekly_amount,active,note,created_at
        ) VALUES(?,?,?,?,?,?,?,?,?,?)
        """,(
            key,request.form.get("title","").strip(),
            request.form.get("category","DŁUG"),total,initial,0,weekly,1,
            request.form.get("note",""),datetime.now().isoformat(timespec="seconds")
        ))
    log("Dodano plan ratalny",f"{key}: {request.form.get('title','')}, {total} zł")
    flash("Plan ratalny został dodany.")
    return redirect(url_for("driver",key=key,tab="recurring"))



@app.route("/drivers/<key>/installments/<int:plan_id>/cancel", methods=["POST"])
def cancel_installment_plan(key, plan_id):
    with db() as c:
        plan=c.execute("SELECT * FROM installment_plans WHERE id=? AND driver_key=?",(plan_id,key)).fetchone()
        if not plan:
            flash("Nie znaleziono planu.")
            return redirect(url_for("driver",key=key,tab="recurring"))
        c.execute("UPDATE installment_plans SET active=0,cancelled_at=?,cancel_comment=? WHERE id=?",(datetime.now().isoformat(timespec="seconds"),"Anulowano ręcznie",plan_id))
        pending=c.execute("""SELECT dc.id FROM scheduled_occurrences so JOIN driver_costs dc ON dc.id=so.cost_id WHERE so.kind='RATA_TYGODNIOWA' AND so.source_id=? AND dc.applied_settlement_id IS NULL""",(plan_id,)).fetchall()
        for row in pending: c.execute("DELETE FROM driver_costs WHERE id=?",(row['id'],))
        log("Anulowano plan ratalny",f"{key}: {plan['title']}",connection=c)
    flash("Plan został anulowany.")
    return redirect(url_for("driver",key=key,tab="recurring"))

@app.route("/drivers/<key>/installments/<int:plan_id>/toggle", methods=["POST"])
def toggle_installment_plan(key,plan_id):
    with db() as c:
        plan=c.execute("SELECT * FROM installment_plans WHERE id=? AND driver_key=?",(plan_id,key)).fetchone()
        if plan:
            c.execute("UPDATE installment_plans SET active=? WHERE id=?",(0 if plan["active"] else 1,plan_id))
    flash("Status planu został zmieniony.")
    return redirect(url_for("driver",key=key,tab="recurring"))



@app.route("/drivers/<key>/deposit-return/add", methods=["POST"])
def add_deposit_return(key):
    summary = deposit_summary_for_driver(key)
    amount = num(request.form.get("amount"))
    if amount <= 0:
        flash("Kwota zwrotu musi być większa od zera.")
        return redirect(url_for("driver", key=key, tab="costs"))
    if amount > float(summary["held"] or 0) + 0.001:
        flash("Kwota zwrotu jest większa niż aktualnie zatrzymana kaucja.")
        return redirect(url_for("driver", key=key, tab="costs"))

    method = request.form.get("method", "PRZELEW")
    return_date = request.form.get("return_date") or date.today().isoformat()
    comment = request.form.get("comment", "").strip()
    proof = request.files.get("proof")
    stored_name = ""
    original_name = ""

    if proof and proof.filename:
        original_name = proof.filename
        extension = Path(proof.filename).suffix.lower()
        if extension not in ALLOWED_RETURN_FILES:
            flash("Dozwolone potwierdzenia: PDF, PNG, JPG, JPEG, WEBP.")
            return redirect(url_for("driver", key=key, tab="costs"))
        safe = secure_filename(proof.filename)
        stored_name = (
            f"{key.replace(' ', '_')}_{datetime.now().strftime('%Y%m%d_%H%M%S_%f')}_{safe}"
        )
        proof.save(UPLOAD_DIR / stored_name)

    with db() as c:
        cursor = c.execute("""
        INSERT INTO deposit_returns(
          driver_key,return_date,amount,method,comment,
          proof_filename,proof_original_name,created_at
        ) VALUES(?,?,?,?,?,?,?,?)
        """, (
            key, return_date, amount, method, comment,
            stored_name, original_name,
            datetime.now().isoformat(timespec="seconds"),
        ))
        log(
            "Zapisano zwrot kaucji",
            f"{key}: {amount:.2f} zł, {method}, ID {cursor.lastrowid}",
            connection=c,
        )

    flash("Zwrot kaucji został zapisany.")
    return redirect(url_for("driver", key=key, tab="costs"))


@app.route("/deposit-return-proof/<int:return_id>")
def download_deposit_return_proof(return_id):
    with db() as c:
        item = c.execute(
            "SELECT * FROM deposit_returns WHERE id=?",
            (return_id,)
        ).fetchone()
    if not item or not item["proof_filename"]:
        flash("Nie znaleziono potwierdzenia.")
        return redirect("/drivers")
    path = UPLOAD_DIR / item["proof_filename"]
    if not path.exists():
        flash("Plik potwierdzenia nie istnieje.")
        return redirect(url_for("driver", key=item["driver_key"], tab="profile"))
    return send_file(
        path,
        as_attachment=True,
        download_name=item["proof_original_name"] or path.name,
    )


@app.route("/drivers/<key>/deposit-return/<int:return_id>/delete", methods=["POST"])
def delete_deposit_return(key, return_id):
    proof_path = None
    deleted = False
    with db() as c:
        item = c.execute("""
        SELECT * FROM deposit_returns
        WHERE id=? AND driver_key=?
        """, (return_id, key)).fetchone()
        if item:
            if item["proof_filename"]:
                proof_path = UPLOAD_DIR / item["proof_filename"]
            c.execute("DELETE FROM deposit_returns WHERE id=?", (return_id,))
            log(
                "Usunięto zwrot kaucji",
                f"{key}: {float(item['amount'] or 0):.2f} zł, ID {return_id}",
                connection=c,
            )
            deleted = True

    if proof_path and proof_path.exists():
        proof_path.unlink(missing_ok=True)

    flash("Zapis zwrotu usunięto." if deleted else "Nie znaleziono zwrotu.")
    return redirect(url_for("driver", key=key, tab="costs"))


@app.route("/drivers/<key>/settlements/<int:sid>")
def driver_settlement_detail(key, sid):
    with db() as c:
        d=c.execute("SELECT * FROM drivers WHERE driver_key=?",(key,)).fetchone()
        s=c.execute("SELECT * FROM settlements WHERE id=?",(sid,)).fetchone()
        r=c.execute("""
        SELECT * FROM settlement_rows
        WHERE settlement_id=? AND driver_key=?
        """,(sid,key)).fetchone()
        costs=c.execute("""
        SELECT * FROM driver_costs
        WHERE applied_settlement_id=? AND driver_key=?
        ORDER BY entry_date,id
        """,(sid,key)).fetchall()
    if not d or not s or not r:
        flash("Nie znaleziono rozliczenia kierowcy.")
        return redirect(url_for("driver",key=key))

    details=json.loads(r["details"] or "[]")
    uber=next((x for x in details if x.get("platform")=="Uber"),None)
    bolt=next((x for x in details if x.get("platform")=="Bolt"),None)

    rental_daily = [
        cost for cost in costs
        if cost["source_label"] == "WYNAJEM_DZIENNY"
    ]
    rental_total = sum(float(cost["amount"] or 0) for cost in rental_daily)
    total_costs = float(r["transfer"] or 0) - float(r["payable"] or 0)

    return render("""
    <div class="row" style="justify-content:space-between">
      <h2>{{d.driver_name}} — {{s.week_start}} – {{s.week_end}}</h2>
      {% if r.is_paid %}
        <span class="badge on">Wypłata rozliczona {{r.paid_at}}</span>
      {% else %}
        <span class="badge off">Wypłata oczekuje</span>
      {% endif %}
    </div>
    <div class="grid g2">
      <div class="card">
        <h3>Uber</h3>
        {% if uber %}
        <p>Brutto: <b>{{money(uber.gross)}}</b></p>
        <p>Netto: <b>{{money(uber.net)}}</b></p>
        <p>Gotówka: {{money(uber.cash)}}</p>
        <p>Napiwki: {{money(uber.tips)}}</p>
        <p>Bonusy: {{money(uber.bonuses)}}</p>
        <p>Do rozliczenia: <b>{{money(uber.transfer)}}</b></p>
        {% else %}<div class="muted">Brak danych Uber.</div>{% endif %}
      </div>
      <div class="card">
        <h3>Bolt</h3>
        {% if bolt %}
        <p>Brutto: <b>{{money(bolt.gross)}}</b></p>
        <p>Netto: <b>{{money(bolt.net)}}</b></p>
        <p>Gotówka: {{money(bolt.cash)}}</p>
        <p>Napiwki: {{money(bolt.tips)}}</p>
        <p>Bonusy: {{money(bolt.bonuses)}}</p>
        <p>Do rozliczenia: <b>{{money(bolt.transfer)}}</b></p>
        <p class="muted">{{money(bolt.net)}} - {{money(bolt.cash)}} = {{money(bolt.transfer)}}</p>
        {% else %}<div class="muted">Brak danych Bolt.</div>{% endif %}
      </div>
    </div>

    <div class="card">
      <h3>Podsumowanie rozliczenia — szczegóły wewnętrzne</h3>
      <div class="grid g4">
        <div class="card metric"><span class="muted">Przychód brutto</span><b>{{money(r.gross)}}</b></div>
        <div class="card metric"><span class="muted">Przelew platform</span><b>{{money(r.transfer)}}</b></div>
        <div class="card metric"><span class="muted">Koszty i korekty</span><b>{{money(total_costs)}}</b></div>
        <div class="card metric"><span class="muted">Do wypłaty</span><b>{{money(r.payable)}}</b></div>
      </div>

      <h4>Wszystkie koszty zastosowane w tym rozliczeniu</h4>
      <table>
        <tr><th>Data</th><th>Pozycja</th><th>Rata</th><th>Źródło</th><th>Rodzaj</th><th>Kwota</th><th>Komentarz</th></tr>
        <tr>
          <td>—</td><td>Prowizja partnera</td><td>—</td><td>STAŁE</td><td>POTRĄCENIE</td>
          <td>-{{money(r.partner_commission)}}</td><td></td>
        </tr>
        {% if r.b2b_fee %}
        <tr>
          <td>—</td><td>B2B — obsługa tygodniowa</td><td>—</td><td>SCHEMAT</td><td>POTRĄCENIE</td>
          <td>-{{money(r.b2b_fee)}}</td>
          <td>50,00 zł + 1% od obrotu brutto {{money(r.gross)}}</td>
        </tr>
        {% endif %}
        {% if r.other %}
        <tr>
          <td>—</td><td>Inne stałe potrącenia</td><td>—</td><td>STAŁE</td><td>POTRĄCENIE</td>
          <td>-{{money(r.other)}}</td><td></td>
        </tr>
        {% endif %}
        {% for cost in costs %}
        <tr>
          <td>{{cost.entry_date}}</td>
          <td>{{cost.title}}</td>
          <td>{% if cost.installment_number %}{{cost.installment_number}} / {{cost.installment_total}}{% else %}—{% endif %}</td>
          <td>{{cost.source_label or "RĘCZNE"}}</td>
          <td>{{cost.entry_type}}</td>
          <td>{{'+' if cost.entry_type=='BONUS' else '-'}}{{money(cost.amount)}}</td>
          <td>{{cost.note}}</td>
        </tr>
        {% endfor %}
      </table>

      {% if rental_daily %}
      <details style="margin-top:14px">
        <summary><b>Dzienne naliczenia wynajmu — razem {{money(rental_total)}}</b></summary>
        <table style="margin-top:10px">
          <tr><th>Data</th><th>Kwota</th><th>Komentarz</th></tr>
          {% for cost in rental_daily %}
          <tr><td>{{cost.entry_date}}</td><td>{{money(cost.amount)}}</td><td>{{cost.note}}</td></tr>
          {% endfor %}
        </table>
      </details>
      {% endif %}

      <p style="margin-top:14px"><b>Komentarz do rozliczenia:</b> {{r.deduction_comment or "Brak"}}</p>
    </div>
    <div class="row">
      <a class="btn primary" href="/drivers/{{d.driver_key}}/settlements/{{s.id}}/report">Raport dla kierowcy</a>
      <a class="btn" href="/drivers/{{d.driver_key}}">Powrót do kierowcy</a>
    </div>
    """,
    d=d,s=s,r=r,uber=uber,bolt=bolt,costs=costs,
    rental_daily=rental_daily,rental_total=rental_total,
    total_costs=total_costs,money=money
    )



@app.route("/drivers/<key>/settlements/<int:sid>/report")
def driver_settlement_report(key, sid):
    with db() as c:
        d=c.execute("SELECT * FROM drivers WHERE driver_key=?",(key,)).fetchone()
        s=c.execute("SELECT * FROM settlements WHERE id=?",(sid,)).fetchone()
        r=c.execute("""
        SELECT * FROM settlement_rows
        WHERE settlement_id=? AND driver_key=?
        """,(sid,key)).fetchone()
        costs=c.execute("""
        SELECT * FROM driver_costs
        WHERE applied_settlement_id=? AND driver_key=?
        ORDER BY entry_date,id
        """,(sid,key)).fetchall()

    rental_total = sum(
        float(cost["amount"] or 0)
        for cost in costs
        if cost["source_label"] == "WYNAJEM_DZIENNY"
    )
    public_costs = [
        cost for cost in costs
        if cost["source_label"] != "WYNAJEM_DZIENNY"
    ]

    if not d or not s or not r:
        flash("Nie znaleziono raportu.")
        return redirect(url_for("driver",key=key,tab="settlements"))

    details=json.loads(r["details"] or "[]")
    return render("""
    <div class="row" style="justify-content:space-between">
      <div><h2>Rozliczenie kierowcy</h2><div class="muted">{{d.driver_name}} · {{s.week_start}}–{{s.week_end}}</div></div>
      <a class="btn primary" href="/drivers/{{d.driver_key}}/settlements/{{s.id}}/report.pdf">Generuj PDF</a>
    </div>

    <div class="card">
      <h3>Przychody z aplikacji</h3>
      <table><tr><th>Aplikacja</th><th>Brutto</th><th>Netto</th><th>Gotówka</th><th>Napiwki</th><th>Bonusy</th><th>Do rozliczenia</th></tr>
      {% for item in details %}
      <tr><td>{{item.platform}}</td><td>{{money(item.gross)}}</td><td>{{money(item.net)}}</td><td>{{money(item.cash)}}</td><td>{{money(item.tips)}}</td><td>{{money(item.bonuses)}}</td><td><b>{{money(item.transfer)}}</b></td></tr>
      {% endfor %}</table>
    </div>

    <div class="card">
      <h3>Koszty i korekty</h3>
      <table><tr><th>Pozycja</th><th>Rata</th><th>Rodzaj</th><th>Kwota</th><th>Komentarz</th></tr>
      <tr><td>Prowizja partnera</td><td>—</td><td>POTRĄCENIE</td><td>-{{money(r.partner_commission)}}</td><td></td></tr>
      {% if r.b2b_fee %}
      <tr>
        <td>B2B — obsługa Uber i Bolt</td><td>—</td><td>POTRĄCENIE</td>
        <td>-{{money(r.b2b_fee)}}</td>
        <td>50,00 zł tygodniowo + 1% od obrotu brutto {{money(r.gross)}}</td>
      </tr>
      {% endif %}
      {% if rental_total > 0 %}
      <tr><td>Wynajem samochodu za tydzień</td><td>—</td><td>POTRĄCENIE</td><td>-{{money(rental_total)}}</td><td></td></tr>
      {% endif %}
      <tr><td>Inne stałe potrącenia</td><td>—</td><td>POTRĄCENIE</td><td>-{{money(r.other)}}</td><td></td></tr>
      {% for cost in public_costs %}
      <tr>
        <td>{{cost.title}}</td>
        <td>{% if cost.installment_number %}{{cost.installment_number}} / {{cost.installment_total}}{% else %}—{% endif %}</td>
        <td>{{cost.entry_type}}</td>
        <td>{{'+' if cost.entry_type=='BONUS' else '-'}}{{money(cost.amount)}}</td><td>{{cost.note}}</td>
      </tr>
      {% endfor %}</table>
    </div>

    <div class="grid g3">
      <div class="card metric"><span class="muted">Przelew platform</span><b>{{money(r.transfer)}}</b></div>
      <div class="card metric"><span class="muted">Koszty i korekty</span><b>{{money(r.transfer-r.payable)}}</b></div>
      <div class="card metric"><span class="muted">Do wypłaty</span><b>{{money(r.payable)}}</b></div>
    </div>
    <p class="muted">Raport wygenerowany {{generated_at}}.</p>
    """,d=d,s=s,r=r,costs=costs,public_costs=public_costs,
       rental_total=rental_total,details=details,money=money,
       generated_at=datetime.now().strftime("%d.%m.%Y %H:%M"))



def _pdf_font_name():
    candidates = [
        "/System/Library/Fonts/Supplemental/Arial Unicode.ttf",
        "/System/Library/Fonts/Supplemental/Arial.ttf",
        "/usr/share/fonts/truetype/dejavu/DejaVuSans.ttf",
    ]
    for font_path in candidates:
        if Path(font_path).exists():
            try:
                pdfmetrics.registerFont(TTFont("GPFont", font_path))
                return "GPFont"
            except Exception:
                continue
    return "Helvetica"


def _pdf_money(value):
    return f"{float(value or 0):,.2f} zl".replace(",", " ")


@app.route("/drivers/<key>/settlements/<int:sid>/report.pdf")
def driver_settlement_pdf(key, sid):
    with db() as c:
        d = c.execute(
            "SELECT * FROM drivers WHERE driver_key=?",
            (key,)
        ).fetchone()
        s = c.execute(
            "SELECT * FROM settlements WHERE id=?",
            (sid,)
        ).fetchone()
        r = c.execute("""
        SELECT * FROM settlement_rows
        WHERE settlement_id=? AND driver_key=?
        """, (sid, key)).fetchone()
        costs = c.execute("""
        SELECT * FROM driver_costs
        WHERE applied_settlement_id=? AND driver_key=?
        ORDER BY entry_date,id
        """, (sid, key)).fetchall()

    if not d or not s or not r:
        flash("Nie znaleziono raportu PDF.")
        return redirect(url_for("driver", key=key, tab="settlements"))

    details = json.loads(r["details"] or "[]")
    rental_total = sum(
        float(cost["amount"] or 0)
        for cost in costs
        if cost["source_label"] == "WYNAJEM_DZIENNY"
    )
    public_costs = [
        cost for cost in costs
        if cost["source_label"] != "WYNAJEM_DZIENNY"
    ]

    font_name = _pdf_font_name()
    output = io.BytesIO()
    doc = SimpleDocTemplate(
        output,
        pagesize=A4,
        rightMargin=14 * mm,
        leftMargin=14 * mm,
        topMargin=14 * mm,
        bottomMargin=14 * mm,
        title=f"Rozliczenie {d['driver_name']} {s['week_start']} - {s['week_end']}",
    )
    styles = getSampleStyleSheet()
    title_style = ParagraphStyle(
        "GPTitle",
        parent=styles["Title"],
        fontName=font_name,
        fontSize=18,
        leading=22,
        spaceAfter=8,
    )
    heading_style = ParagraphStyle(
        "GPHeading",
        parent=styles["Heading2"],
        fontName=font_name,
        fontSize=12,
        leading=15,
        spaceBefore=8,
        spaceAfter=6,
    )
    body_style = ParagraphStyle(
        "GPBody",
        parent=styles["BodyText"],
        fontName=font_name,
        fontSize=8,
        leading=10,
    )

    story = [
        Paragraph("GO PARTNER - Rozliczenie kierowcy", title_style),
        Paragraph(
            f"{d['driver_name']}<br/>{s['week_start']} - {s['week_end']}",
            body_style,
        ),
        Spacer(1, 5 * mm),
        Paragraph("Przychody z aplikacji", heading_style),
    ]

    income_data = [[
        "Aplikacja", "Brutto", "Netto", "Gotowka",
        "Napiwki", "Bonusy", "Do rozliczenia"
    ]]
    for item in details:
        income_data.append([
            str(item.get("platform", "")),
            _pdf_money(item.get("gross")),
            _pdf_money(item.get("net")),
            _pdf_money(item.get("cash")),
            _pdf_money(item.get("tips")),
            _pdf_money(item.get("bonuses")),
            _pdf_money(item.get("transfer")),
        ])
    income_table = Table(
        income_data,
        repeatRows=1,
        colWidths=[23*mm, 24*mm, 24*mm, 24*mm, 22*mm, 22*mm, 27*mm],
    )
    income_table.setStyle(TableStyle([
        ("FONTNAME", (0,0), (-1,-1), font_name),
        ("FONTSIZE", (0,0), (-1,-1), 7),
        ("BACKGROUND", (0,0), (-1,0), colors.HexColor("#E5E7EB")),
        ("GRID", (0,0), (-1,-1), 0.4, colors.HexColor("#9CA3AF")),
        ("VALIGN", (0,0), (-1,-1), "MIDDLE"),
        ("ALIGN", (1,1), (-1,-1), "RIGHT"),
    ]))
    story.extend([income_table, Spacer(1, 5 * mm), Paragraph("Koszty i korekty", heading_style)])

    cost_data = [["Pozycja", "Rata", "Rodzaj", "Kwota", "Komentarz"]]
    cost_data.append([
        "Prowizja partnera", "-", "POTRACENIE",
        "-" + _pdf_money(r["partner_commission"]), ""
    ])
    if float(r["b2b_fee"] or 0) > 0:
        cost_data.append([
            "B2B - obsluga Uber i Bolt", "-", "POTRACENIE",
            "-" + _pdf_money(r["b2b_fee"]),
            "50 zl tygodniowo + 1% od brutto " + _pdf_money(r["gross"])
        ])
    if rental_total > 0:
        cost_data.append([
            "Wynajem samochodu za tydzien", "-", "POTRACENIE",
            "-" + _pdf_money(rental_total), ""
        ])
    if float(r["other"] or 0) != 0:
        cost_data.append([
            "Inne stale potracenia", "-", "POTRACENIE",
            "-" + _pdf_money(r["other"]), ""
        ])
    for cost in public_costs:
        installment = "-"
        if int(cost["installment_number"] or 0) > 0:
            installment = (
                f"{cost['installment_number']} / "
                f"{cost['installment_total']}"
            )
        sign = "+" if cost["entry_type"] == "BONUS" else "-"
        cost_data.append([
            str(cost["title"] or ""),
            installment,
            str(cost["entry_type"] or ""),
            sign + _pdf_money(cost["amount"]),
            str(cost["note"] or ""),
        ])

    cost_table = Table(
        cost_data,
        repeatRows=1,
        colWidths=[48*mm, 18*mm, 25*mm, 25*mm, 60*mm],
    )
    cost_table.setStyle(TableStyle([
        ("FONTNAME", (0,0), (-1,-1), font_name),
        ("FONTSIZE", (0,0), (-1,-1), 7),
        ("BACKGROUND", (0,0), (-1,0), colors.HexColor("#E5E7EB")),
        ("GRID", (0,0), (-1,-1), 0.4, colors.HexColor("#9CA3AF")),
        ("VALIGN", (0,0), (-1,-1), "TOP"),
        ("ALIGN", (3,1), (3,-1), "RIGHT"),
    ]))
    story.extend([cost_table, Spacer(1, 6 * mm)])

    summary_data = [
        ["Przelew platform", "Koszty i korekty", "Do wyplaty"],
        [
            _pdf_money(r["transfer"]),
            _pdf_money(float(r["transfer"] or 0) - float(r["payable"] or 0)),
            _pdf_money(r["payable"]),
        ],
    ]
    summary_table = Table(summary_data, colWidths=[58*mm, 58*mm, 58*mm])
    summary_table.setStyle(TableStyle([
        ("FONTNAME", (0,0), (-1,-1), font_name),
        ("FONTSIZE", (0,0), (-1,0), 8),
        ("FONTSIZE", (0,1), (-1,1), 13),
        ("BACKGROUND", (0,0), (-1,0), colors.HexColor("#F3F4F6")),
        ("GRID", (0,0), (-1,-1), 0.4, colors.HexColor("#D1D5DB")),
        ("ALIGN", (0,0), (-1,-1), "CENTER"),
        ("VALIGN", (0,0), (-1,-1), "MIDDLE"),
        ("TOPPADDING", (0,0), (-1,-1), 8),
        ("BOTTOMPADDING", (0,0), (-1,-1), 8),
    ]))
    story.extend([
        summary_table,
        Spacer(1, 5 * mm),
        Paragraph(
            f"Raport wygenerowany {datetime.now().strftime('%d.%m.%Y %H:%M')}.",
            body_style,
        ),
    ])

    doc.build(story)
    output.seek(0)
    safe_name = re.sub(r"[^a-zA-Z0-9_-]+", "_", d["driver_name"]).strip("_")
    return send_file(
        output,
        as_attachment=True,
        download_name=(
            f"rozliczenie_{safe_name}_{s['week_start']}_{s['week_end']}.pdf"
        ),
        mimetype="application/pdf",
    )


@app.route("/drivers/<key>/settlements/export")
def export_driver_settlements(key):
    with db() as c:
        d=c.execute("SELECT * FROM drivers WHERE driver_key=?",(key,)).fetchone()
        rows=c.execute("""
        SELECT sr.*, s.week_start, s.week_end
        FROM settlement_rows sr
        JOIN settlements s ON s.id=sr.settlement_id
        WHERE sr.driver_key=?
        ORDER BY s.week_start DESC, s.id DESC
        """,(key,)).fetchall()
    if not d:
        flash("Nie znaleziono kierowcy.")
        return redirect("/drivers")

    output=io.StringIO()
    writer=csv.writer(output,delimiter=";")
    writer.writerow([
        "Okres od","Okres do","Platformy","Brutto","Przelew platform",
        "Prowizja partnera ręczna","B2B 50 zł + 1%","Wynajem","Cykliczne","Korekty jednorazowe",
        "Mandaty / szkody","Inne","Do wypłaty","Komentarz"
    ])
    for r in rows:
        writer.writerow([
            r["week_start"],r["week_end"],r["platforms"],r["gross"],r["transfer"],
            r["partner_commission"],r["b2b_fee"],r["rental"],r["recurring_total"],
            r["manual_adjustments"],r["fines"],r["other"],r["payable"],
            r["deduction_comment"]
        ])
    data=io.BytesIO(output.getvalue().encode("utf-8-sig"))
    return send_file(
        data,
        as_attachment=True,
        download_name=f"historia_{key}.csv",
        mimetype="text/csv"
    )


@app.route("/settlements/new", methods=["GET","POST"])
def new_settlement():
    if request.method=="POST":
        files=request.files.getlist("files")
        if not files or not any(f.filename for f in files):
            flash("Wybierz plik CSV Bolt i/lub Uber.")
            return redirect("/settlements/new")

        try:
            week_start, week_end, detected_files = detect_period(files)
            for f in files:
                f.stream.seek(0)
            rows=aggregate(parse_files(files))
        except ValueError as exc:
            flash(str(exc))
            return redirect("/settlements/new")

        for r in rows:
            ensure_driver(r["driver"])
            with db() as c:
                if r.get("uber_id"):
                    cursor = c.execute("""
                    UPDATE drivers
                    SET uber_id=?
                    WHERE driver_key=? AND COALESCE(uber_id,'')=''
                    """, (r["uber_id"], r["driver_key"]))
                    if cursor.rowcount:
                        log(
                            "Automatycznie zapisano Uber ID",
                            f"{r['driver']}: {r['uber_id']} "
                            f"(kolumna: {r.get('uber_id_column') or 'wykryta automatycznie'})",
                            connection=c,
                        )
                if r.get("bolt_id"):
                    cursor = c.execute("""
                    UPDATE drivers
                    SET bolt_id=?
                    WHERE driver_key=? AND COALESCE(bolt_id,'')=''
                    """, (r["bolt_id"], r["driver_key"]))
                    if cursor.rowcount:
                        log(
                            "Automatycznie zapisano Bolt ID",
                            f"{r['driver']}: {r['bolt_id']} "
                            f"(kolumna: {r.get('bolt_id_column') or 'wykryta automatycznie'})",
                            connection=c,
                        )
        ensure_scheduled_costs_for_period(
            week_start,
            week_end,
            [r["driver_key"] for r in rows],
        )

        with db() as c:
            drivers={x["driver_key"]:x for x in c.execute("SELECT * FROM drivers").fetchall()}
            calculated=[]
            for r in rows:
                d=drivers[r["driver_key"]]
                if not d["active"] or d["status"] != "AKTYWNY":
                    continue
                pending=c.execute(
                    "SELECT * FROM driver_costs "
                    "WHERE driver_key=? AND apply_next=1 AND applied_settlement_id IS NULL",
                    (r["driver_key"],)
                ).fetchall()
                manual=sum(
                    (x["amount"] if x["entry_type"]=="BONUS" else -x["amount"])
                    for x in pending
                )
                recurring_total=0.0
                installment_charges=[]
                is_b2b = d["scheme_type"] == "B2B"
                b2b_percent_fee = (
                    round(float(r["gross"] or 0) * 0.01, 2)
                    if is_b2b
                    else 0.0
                )
                b2b_fixed_fee = 50.0 if is_b2b else 0.0
                b2b_fee = round(b2b_percent_fee + b2b_fixed_fee, 2)
                partner_commission = (
                    0.0 if is_b2b else float(d["partner_commission"] or 0)
                )
                r.update(
                    commission=partner_commission,
                    rental=0.0,
                    other=d["other"],
                    b2b_percent_fee=b2b_percent_fee,
                    b2b_fixed_fee=b2b_fixed_fee,
                    b2b_fee=b2b_fee,
                    fines=0,
                    manual_adjustments=manual,
                    recurring_total=recurring_total,
                    installment_charges=installment_charges,
                    payable=(
                        r["transfer"]
                        - partner_commission
                        - d["other"]
                        - b2b_fee
                        + manual
                    ),
                )
                calculated.append(r)

        save_current_draft(
            calculated,
            week_start.isoformat(),
            week_end.isoformat(),
        )
        return save_preview(
            calculated,
            week_start.isoformat(),
            week_end.isoformat(),
            detected_files,
        )

    return render("""
    <h2>Nowe rozliczenie</h2>
    <div class="card">
      <p><b>Okres rozliczeniowy zostanie odczytany automatycznie z plików.</b></p>
      <p class="muted">
        Nie wpisujesz dat ręcznie. Zachowaj oryginalne nazwy pobranych plików Uber i Bolt.
      </p>
      <form method="post" enctype="multipart/form-data">
        <div class="field">
          <label>CSV Bolt i/lub Uber</label>
          <input type="file" name="files" multiple accept=".csv" required>
        </div>
        <br>
        <button class="btn primary">Wczytaj i przelicz</button>
      </form>
    </div>
    """)

def save_preview(rows, week_start, week_end, detected_files):
    token=json.dumps(rows,ensure_ascii=False)
    return render("""
    <h2>Podgląd rozliczenia</h2>
    <div class="card">
      <h3>Identyfikatory kierowców wykryte w CSV</h3>
      <table>
        <tr><th>Kierowca</th><th>Uber ID</th><th>Kolumna Uber</th><th>Bolt ID</th><th>Kolumna Bolt</th></tr>
        {% for r in rows %}
        <tr>
          <td>{{r.driver}}</td>
          <td>{{r.uber_id or "NIE ZNALEZIONO"}}</td>
          <td>{{r.uber_id_column or "—"}}</td>
          <td>{{r.bolt_id or "NIE ZNALEZIONO"}}</td>
          <td>{{r.bolt_id_column or "—"}}</td>
        </tr>
        {% endfor %}
      </table>
      <p class="muted">
        Jeżeli Uber ID ma status „NIE ZNALEZIONO”, plik nie zawiera rozpoznawalnej
        kolumny identyfikatora kierowcy. Wtedy potrzebny jest oryginalny CSV Uber
        do dodania dokładnej nazwy kolumny.
      </p>
    </div>
    <div class="card">
      <h3>Automatycznie wykryty okres</h3>
      <p><b>{{week_start}} – {{week_end}}</b></p>
      <div class="muted">
        {% for filename, start, end, source in detected_files %}
          {{source}}: {{filename}} → {{start.strftime('%d.%m.%Y')}}–{{end.strftime('%d.%m.%Y')}}<br>
        {% endfor %}
      </div>
    </div>
    <div class="card"><table><tr><th>Kierowca</th><th>Platformy</th><th>Brutto</th><th>Przelew</th><th>Prowizja ręczna</th><th>B2B 50 zł + 1%</th><th>Wynajem</th><th>Korekty</th><th>Do wypłaty</th></tr>
    {% for r in rows %}<tr><td>{{r.driver}}</td><td>{{r.platforms}}</td><td>{{money(r.gross)}}</td><td>{{money(r.transfer)}}</td><td>{{money(r.commission)}}</td><td>{{money(r.b2b_fee)}}</td><td>{{money(r.rental)}}</td><td>{{money(r.manual_adjustments+r.recurring_total)}}</td><td><b>{{money(r.payable)}}</b></td></tr>{% endfor %}</table></div>
    <form method="post" action="/settlements/save">
      <input type="hidden" name="week_start" value="{{week_start}}">
      <input type="hidden" name="week_end" value="{{week_end}}">
      <textarea name="rows_json" style="display:none">{{token}}</textarea>
      <button class="btn primary">Zapisz w historii</button>
      <a class="btn" href="/settlements/draft/cancel">Anuluj podgląd</a>
    </form>
    """,
    rows=rows,
    week_start=week_start,
    week_end=week_end,
    detected_files=detected_files,
    token=token,
    money=money
    )


@app.route("/settlements/draft/cancel")
def cancel_settlement_draft():
    clear_current_draft()
    flash("Podgląd rozliczenia został anulowany. Aktualne salda wróciły do ostatniego zapisanego stanu.")
    return redirect("/settlements/new")


@app.route("/settlements/save", methods=["POST"])
def save_settlement():
    rows=json.loads(request.form["rows_json"])
    ws=request.form["week_start"]; we=request.form["week_end"]
    with db() as c:
        cur=c.execute("""INSERT INTO settlements(week_start,week_end,created_at,note,total_gross,total_transfer,total_payable) VALUES(?,?,?,?,?,?,?)""",
        (ws,we,datetime.now().isoformat(timespec="seconds"),"",sum(r["gross"] for r in rows),sum(r["transfer"] for r in rows),sum(r["payable"] for r in rows)))
        sid=cur.lastrowid
        for r in rows:
            c.execute("""INSERT INTO settlement_rows(settlement_id,driver_key,driver_name,platforms,gross,transfer,cash,tips,bonuses,partner_commission,rental,b2b_fee,recurring_total,manual_adjustments,fines,other,payable,deduction_comment,details) VALUES(?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?)""",
            (sid,r["driver_key"],r["driver"],r["platforms"],r["gross"],r["transfer"],r["cash"],r["tips"],r["bonuses"],r["commission"],r["rental"],r.get("b2b_fee",0),r["recurring_total"],r["manual_adjustments"],r["fines"],r["other"],r["payable"],"",json.dumps(r["details"],ensure_ascii=False)))
            pending_installments=c.execute("""
            SELECT so.source_id AS plan_id, dc.amount
            FROM scheduled_occurrences so
            JOIN driver_costs dc ON dc.id=so.cost_id
            WHERE so.kind='RATA_TYGODNIOWA'
              AND so.driver_key=?
              AND dc.applied_settlement_id IS NULL
            """,(r["driver_key"],)).fetchall()
            c.execute("UPDATE driver_costs SET applied_settlement_id=? WHERE driver_key=? AND apply_next=1 AND applied_settlement_id IS NULL",(sid,r["driver_key"]))
            for scheduled_charge in pending_installments:
                c.execute("""
                INSERT INTO installment_charges(
                  plan_id,settlement_id,driver_key,amount,created_at
                ) VALUES(?,?,?,?,?)
                """,(
                    scheduled_charge["plan_id"],sid,r["driver_key"],
                    scheduled_charge["amount"],datetime.now().isoformat(timespec="seconds")
                ))
                c.execute("""
                UPDATE installment_plans
                SET paid_from_settlements=paid_from_settlements+?
                WHERE id=?
                """,(scheduled_charge["amount"],scheduled_charge["plan_id"]))
                plan=c.execute("SELECT * FROM installment_plans WHERE id=?",(scheduled_charge["plan_id"],)).fetchone()
                if plan and plan_remaining(plan)<=0:
                    c.execute("UPDATE installment_plans SET active=0 WHERE id=?",(scheduled_charge["plan_id"],))
            for charge in r.get("installment_charges",[]):
                c.execute("""
                INSERT INTO installment_charges(
                  plan_id,settlement_id,driver_key,amount,created_at
                ) VALUES(?,?,?,?,?)
                """,(
                    charge["plan_id"],sid,r["driver_key"],charge["amount"],
                    datetime.now().isoformat(timespec="seconds")
                ))
                c.execute("""
                UPDATE installment_plans
                SET paid_from_settlements=paid_from_settlements+?
                WHERE id=?
                """,(charge["amount"],charge["plan_id"]))
                plan=c.execute("SELECT * FROM installment_plans WHERE id=?",(charge["plan_id"],)).fetchone()
                if plan and plan_remaining(plan)<=0:
                    c.execute("UPDATE installment_plans SET active=0 WHERE id=?",(charge["plan_id"],))
        log(
            "Zapisano rozliczenie",
            f"#{sid} {ws} – {we}",
            connection=c,
        )
    clear_current_draft()
    flash("Rozliczenie zapisano. Aktualne saldo kierowcy zostało zaktualizowane.")
    return redirect("/history")

@app.route("/history")
def history():
    with db() as c: rows=c.execute("SELECT * FROM settlements ORDER BY id DESC").fetchall()
    return render("""
    <div class="row" style="justify-content:space-between"><h2>Historia</h2><a class="btn" href="/history">Odśwież</a></div>
    <div class="card">{% if rows %}<table><tr><th>ID</th><th>Okres</th><th>Brutto</th><th>Przelew</th><th>Do wypłaty</th><th>Status wypłat</th><th>Akcje</th></tr>
    {% for s in rows %}<tr>
      <td>#{{s.id}}</td>
      <td>{{s.week_start}} – {{s.week_end}}</td>
      <td>{{money(s.total_gross)}}</td>
      <td>{{money(s.total_transfer)}}</td>
      <td>{{money(s.total_payable)}}</td>
      <td>
        {% if s.all_paid %}
          <span class="badge on">Rozliczono</span>
        {% else %}
          <span class="badge off">Oczekuje</span>
        {% endif %}
      </td>
      <td>
        <div class="row">
          <a class="btn" href="/history/{{s.id}}/ing-bank-file">Plik do ING</a>
          {% if not s.all_paid %}
          <form method="post" action="/history/{{s.id}}/pay-all"
                onsubmit="return confirm('Potwierdzić wysłanie wypłat wszystkim kierowcom? Dodatnie salda zostaną wyzerowane, a ujemne pozostaną.')">
            <button class="btn primary">Rozlicz wszystkich kierowców</button>
          </form>
          {% endif %}
          <form method="post" action="/history/{{s.id}}/delete"
                onsubmit="return confirm('Usunąć to rozliczenie? Korekty wrócą do następnego rozliczenia.')">
            <button class="btn danger">Usuń</button>
          </form>
        </div>
      </td>
    </tr>{% endfor %}</table>{% else %}<div class="muted">Brak historii.</div>{% endif %}</div>
    """,rows=rows,money=money)



@app.route("/history/<int:sid>/ing-bank-file", methods=["GET", "POST"])
def ing_bank_file(sid):
    with db() as c:
        settlement = c.execute(
            "SELECT * FROM settlements WHERE id=?",
            (sid,)
        ).fetchone()
        settings = c.execute(
            "SELECT * FROM bank_export_settings WHERE id=1"
        ).fetchone()
        rows = c.execute("""
        SELECT sr.*, d.bank_account
        FROM settlement_rows sr
        JOIN drivers d ON d.driver_key=sr.driver_key
        WHERE sr.settlement_id=?
        ORDER BY sr.driver_name
        """, (sid,)).fetchall()

    if not settlement:
        flash("Nie znaleziono rozliczenia.")
        return redirect("/history")

    payable_rows = [row for row in rows if float(row["payable"] or 0) > 0]
    missing_accounts = [
        row for row in payable_rows
        if not normalize_bank_account(row["bank_account"])
    ]
    invalid_accounts = [
        row for row in payable_rows
        if normalize_bank_account(row["bank_account"])
        and not valid_polish_account(row["bank_account"])
    ]

    if request.method == "POST":
        source_account = normalize_bank_account(request.form.get("source_account", ""))
        payer_name = request.form.get("payer_name", "").strip()
        payer_address1 = request.form.get("payer_address1", "").strip()
        payer_address2 = request.form.get("payer_address2", "").strip()
        default_title = request.form.get("default_title", "Rozliczenie kierowcy").strip()
        execution_date_text = request.form.get("execution_date", date.today().isoformat())

        with db() as c:
            c.execute("""
            UPDATE bank_export_settings SET
              source_account=?,payer_name=?,payer_address1=?,
              payer_address2=?,default_title=?
            WHERE id=1
            """, (
                source_account, payer_name, payer_address1,
                payer_address2, default_title,
            ))
            settings = c.execute(
                "SELECT * FROM bank_export_settings WHERE id=1"
            ).fetchone()

        errors = []
        if not valid_polish_account(source_account):
            errors.append("Numer rachunku firmowego jest nieprawidłowy.")
        if not payer_name:
            errors.append("Wpisz nazwę firmy / zleceniodawcy.")
        if not payable_rows:
            errors.append("Brak dodatnich wypłat w tym rozliczeniu.")
        if missing_accounts:
            errors.append(
                "Brak numeru konta: "
                + ", ".join(row["driver_name"] for row in missing_accounts)
            )
        if invalid_accounts:
            errors.append(
                "Nieprawidłowy numer konta: "
                + ", ".join(row["driver_name"] for row in invalid_accounts)
            )

        try:
            execution_date = datetime.strptime(
                execution_date_text, "%Y-%m-%d"
            ).date()
        except ValueError:
            execution_date = date.today()
            errors.append("Nieprawidłowa data realizacji.")

        if errors:
            for error in errors:
                flash(error)
            return redirect(url_for("ing_bank_file", sid=sid))

        content = build_ing_pli(payable_rows, settings, execution_date)
        output = io.BytesIO(content)
        output.seek(0)

        with db() as c:
            log(
                "Wygenerowano plik ING PLI",
                f"Rozliczenie #{sid}, przelewów: {len(payable_rows)}, "
                f"suma: {sum(float(row['payable']) for row in payable_rows):.2f} zł",
                connection=c,
            )

        return send_file(
            output,
            as_attachment=True,
            download_name=(
                f"ING_przelewy_{settlement['week_start']}_"
                f"{settlement['week_end']}.pli"
            ),
            mimetype="text/plain",
        )

    return render("""
    <h2>Plik przelewów do ING</h2>
    <div class="card">
      <h3>Rozliczenie #{{settlement.id}}</h3>
      <p>{{settlement.week_start}} – {{settlement.week_end}}</p>
      <p>
        Dodatnich wypłat: <b>{{payable_rows|length}}</b> ·
        Suma: <b>{{money(total_amount)}}</b>
      </p>
      <p class="muted">
        Generowany format: Multicash PLI (Elixir 0), przelewy krajowe PLN.
        Ujemne i zerowe salda nie trafiają do pliku.
      </p>
    </div>

    {% if missing_accounts or invalid_accounts %}
    <div class="card">
      <h3>Dane wymagające poprawy</h3>
      {% if missing_accounts %}
      <p><b>Brak numeru konta:</b></p>
      <ul>
        {% for row in missing_accounts %}
        <li><a href="/drivers/{{row.driver_key}}">{{row.driver_name}}</a></li>
        {% endfor %}
      </ul>
      {% endif %}
      {% if invalid_accounts %}
      <p><b>Nieprawidłowy numer konta:</b></p>
      <ul>
        {% for row in invalid_accounts %}
        <li>
          <a href="/drivers/{{row.driver_key}}">{{row.driver_name}}</a>
          — {{row.bank_account}}
        </li>
        {% endfor %}
      </ul>
      {% endif %}
    </div>
    {% endif %}

    <div class="card">
      <h3>Dane zleceniodawcy</h3>
      <form method="post">
        <div class="grid g2">
          <div class="field">
            <label>Rachunek firmowy ING</label>
            <input name="source_account" value="{{settings.source_account}}"
                   placeholder="PL00 0000 0000 0000 0000 0000 0000" required>
          </div>
          <div class="field">
            <label>Nazwa firmy</label>
            <input name="payer_name" value="{{settings.payer_name}}" required>
          </div>
          <div class="field">
            <label>Adres firmy — linia 1</label>
            <input name="payer_address1" value="{{settings.payer_address1}}">
          </div>
          <div class="field">
            <label>Adres firmy — linia 2</label>
            <input name="payer_address2" value="{{settings.payer_address2}}">
          </div>
          <div class="field">
            <label>Tytuł przelewu</label>
            <input name="default_title" value="{{settings.default_title}}" required>
          </div>
          <div class="field">
            <label>Data realizacji</label>
            <input type="date" name="execution_date" value="{{today}}" required>
          </div>
        </div>
        <br>
        <button class="btn primary"
                {% if missing_accounts or invalid_accounts or not payable_rows %}disabled{% endif %}>
          Generuj plik ING
        </button>
      </form>
    </div>

    <div class="card">
      <h3>Przelewy w pliku</h3>
      <table>
        <tr><th>Kierowca</th><th>Numer konta</th><th>Kwota</th><th>Status</th></tr>
        {% for row in payable_rows %}
        <tr>
          <td>{{row.driver_name}}</td>
          <td>{{row.bank_account or "BRAK"}}</td>
          <td>{{money(row.payable)}}</td>
          <td>
            {% if not row.bank_account %}
              <span class="badge off">Brak konta</span>
            {% elif not valid_polish_account(row.bank_account) %}
              <span class="badge off">Błędne konto</span>
            {% else %}
              <span class="badge on">Gotowy</span>
            {% endif %}
          </td>
        </tr>
        {% endfor %}
      </table>
    </div>
    """,
    settlement=settlement,
    settings=settings,
    payable_rows=payable_rows,
    missing_accounts=missing_accounts,
    invalid_accounts=invalid_accounts,
    total_amount=sum(float(row["payable"] or 0) for row in payable_rows),
    money=money,
    today=date.today().isoformat(),
    valid_polish_account=valid_polish_account,
    )


@app.route("/history/<int:sid>/pay-all", methods=["POST"])
def pay_all_drivers(sid):
    paid_at = datetime.now().isoformat(timespec="seconds")
    with db() as c:
        settlement = c.execute(
            "SELECT * FROM settlements WHERE id=?",
            (sid,)
        ).fetchone()
        if not settlement:
            flash("Nie znaleziono rozliczenia.")
            return redirect("/history")

        c.execute("""
        UPDATE settlement_rows
        SET is_paid=1, paid_at=?
        WHERE settlement_id=?
        """, (paid_at, sid))

        c.execute("""
        UPDATE settlements
        SET all_paid=1, paid_at=?
        WHERE id=?
        """, (paid_at, sid))

        positive_count = c.execute("""
        SELECT COUNT(*) FROM settlement_rows
        WHERE settlement_id=? AND payable>=0
        """, (sid,)).fetchone()[0]

        negative_count = c.execute("""
        SELECT COUNT(*) FROM settlement_rows
        WHERE settlement_id=? AND payable<0
        """, (sid,)).fetchone()[0]

        log(
            "Rozliczono wszystkich kierowców",
            f"Rozliczenie #{sid}: dodatnie salda wyzerowane {positive_count}, "
            f"ujemne salda pozostawione {negative_count}",
            connection=c,
        )

    clear_current_draft()
    flash(
        "Wypłaty oznaczono jako wysłane. "
        "Dodatnie salda kierowców zostały wyzerowane, "
        "a ujemne salda pozostały jako zadłużenie."
    )
    return redirect("/history")


@app.route("/history/<int:sid>/delete", methods=["POST"])
def delete_settlement(sid):
    with db() as c:
        s=c.execute("SELECT * FROM settlements WHERE id=?",(sid,)).fetchone()
        if not s:
            flash("Nie znaleziono rozliczenia."); return redirect("/history")
        c.execute("UPDATE driver_costs SET applied_settlement_id=NULL WHERE applied_settlement_id=?",(sid,))
        charges=c.execute("SELECT * FROM installment_charges WHERE settlement_id=?",(sid,)).fetchall()
        for charge in charges:
            c.execute("""
            UPDATE installment_plans
            SET paid_from_settlements=MAX(0,paid_from_settlements-?),active=1
            WHERE id=?
            """,(charge["amount"],charge["plan_id"]))
        c.execute("DELETE FROM installment_charges WHERE settlement_id=?",(sid,))
        c.execute("DELETE FROM settlement_rows WHERE settlement_id=?",(sid,))
        c.execute("DELETE FROM settlements WHERE id=?",(sid,))
        log(
            "Usunięto rozliczenie",
            f"#{sid} {s['week_start']} – {s['week_end']}",
            connection=c,
        )
    flash("Rozliczenie usunięto. Jednorazowe korekty i raty wróciły do następnego rozliczenia.")
    return redirect("/history")

@app.route("/logs")
def logs():
    with db() as c: rows=c.execute("SELECT * FROM logs ORDER BY id DESC LIMIT 500").fetchall()
    return render("""
    <h2>Logi</h2><div class="card"><table><tr><th>Data</th><th>Akcja</th><th>Szczegóły</th></tr>
    {% for r in rows %}<tr><td>{{r.created_at}}</td><td>{{r.action}}</td><td>{{r.details}}</td></tr>{% endfor %}</table></div>
    """,rows=rows)

@app.route("/backup")
def backup():
    return send_file(DB_PATH, as_attachment=True, download_name="go_partner.db")

init_db()

if __name__=="__main__":
    app.run(host="0.0.0.0", port=8501, debug=False, threaded=False)
