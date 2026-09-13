"""
Turkiye Su Seffaflik Platformu - Veri Entegrasyonu Case Study
Kaynak: IBB Acik Veri Portali - Istanbul Barajlari Gunluk Doluluk Oranlari (ISKI)

Kullanim:
    py main.py                      # canli API'den ceker
    py main.py --fixture fixtures/sample_response.json   # offline test
"""

import argparse
import json
import sqlite3
import sys
import urllib.request
import urllib.error
from datetime import datetime, timezone

SOURCE_NAME = "IBB Acik Veri Portali - Istanbul Barajlari Gunluk Doluluk Oranlari"
SOURCE_URL = (
    "https://data.ibb.gov.tr/dataset/istanbul-barajlari-gunluk-doluluk-oranlari/"
    "resource/af0b3902-cfd9-4096-85f7-e2c3017e4f21"
)
RESOURCE_ID = "af0b3902-cfd9-4096-85f7-e2c3017e4f21"
API_BASE = "https://data.ibb.gov.tr/api/3/action/datastore_search"
PAGE_SIZE = 1000
REQUEST_TIMEOUT = 15

# Kaynaktaki sutun adi -> normalize edilmis baraj adi
DAM_COLUMNS = {
    "Omerli": "Omerli Baraji",
    "Darlik": "Darlik Baraji",
    "Elmali": "Elmali Baraji",
    "Terkos": "Terkos Baraji",
    "Alibey": "Alibey Baraji",
    "Buyukcekmece": "Buyukcekmece Baraji",
    "Sazlidere": "Sazlidere Baraji",
    "Kazandere": "Kazandere Baraji",
    "Pabucdere": "Pabucdere Baraji",
    "Istrancalar": "Istrancalar Baraji",
}
METRIC_TYPE = "baraj_doluluk_orani"
UNIT = "%"
LOCATION = "Istanbul"

DDL = """
CREATE TABLE IF NOT EXISTS water_metrics (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    source_name TEXT NOT NULL,
    source_url TEXT NOT NULL,
    fetched_at TEXT NOT NULL,
    observed_at TEXT NOT NULL,
    location TEXT NOT NULL,
    entity_name TEXT NOT NULL,
    metric_type TEXT NOT NULL,
    value REAL NOT NULL,
    unit TEXT NOT NULL,
    UNIQUE(entity_name, observed_at, metric_type)
);
"""


def fetch_live(limit_pages=None):
    """CKAN datastore_search API'sinden sayfalayarak tum kayitlari ceker."""
    records = []
    offset = 0
    page = 0
    while True:
        url = f"{API_BASE}?resource_id={RESOURCE_ID}&limit={PAGE_SIZE}&offset={offset}"
        try:
            with urllib.request.urlopen(url, timeout=REQUEST_TIMEOUT) as resp:
                payload = json.loads(resp.read().decode("utf-8"))
        except (urllib.error.URLError, TimeoutError) as exc:
            raise RuntimeError(f"API'ye erisilemedi: {exc}") from exc

        if not payload.get("success"):
            raise RuntimeError(f"API basarisiz yanit dondu: {payload}")

        batch = payload["result"]["records"]
        records.extend(batch)
        page += 1

        if len(batch) < PAGE_SIZE:
            break
        if limit_pages and page >= limit_pages:
            break
        offset += PAGE_SIZE

    return records


def fetch_fixture(path):
    with open(path, encoding="utf-8") as f:
        payload = json.load(f)
    return payload["result"]["records"]


def parse_value(raw):
    """Kaynak sutun tipi 'text'; virgullu ondalik veya bosluk gibi durumlari isle."""
    if raw is None:
        return None
    s = str(raw).strip()
    if s == "" or s in ("-", "NA", "N/A", "null"):
        return None
    s = s.replace(",", ".")
    try:
        return float(s)
    except ValueError:
        return None


def parse_date(raw):
    """Kaynak tarih formatlari degisebilir; birden fazla format dener."""
    if raw is None:
        return None
    s = str(raw).strip()
    for fmt in ("%Y-%m-%d", "%Y-%m-%dT%H:%M:%S", "%d.%m.%Y", "%d/%m/%Y"):
        try:
            return datetime.strptime(s[:19] if "T" in s else s, fmt).date().isoformat()
        except ValueError:
            continue
    return None


def normalize(raw_records, fetched_at):
    """Genis formati (tarih + her baraj bir sutun) uzun formata (bir satir = bir baraj+tarih) cevirir."""
    normalized = []
    skipped = []

    for row in raw_records:
        observed_at = parse_date(row.get("Tarih"))

        for src_col, entity_name in DAM_COLUMNS.items():
            if src_col not in row:
                continue

            value = parse_value(row.get(src_col))
            rec = {
                "source_name": SOURCE_NAME,
                "source_url": SOURCE_URL,
                "fetched_at": fetched_at,
                "observed_at": observed_at,
                "location": LOCATION,
                "entity_name": entity_name,
                "metric_type": METRIC_TYPE,
                "value": value,
                "unit": UNIT,
            }

            ok, reason = validate(rec)
            if ok:
                normalized.append(rec)
            else:
                skipped.append((rec, reason))

    return normalized, skipped


def validate(rec):
    required = ["observed_at", "entity_name", "metric_type", "value", "unit"]
    for field in required:
        if rec.get(field) is None or rec.get(field) == "":
            return False, f"zorunlu alan eksik: {field}"

    if not isinstance(rec["value"], float):
        return False, "sayisal deger degil"

    if rec["metric_type"] == METRIC_TYPE and not (0 <= rec["value"] <= 100):
        return False, f"0-100 araligi disinda: {rec['value']}"

    return True, None


def dedupe(records):
    seen = set()
    unique = []
    duplicate_count = 0
    for rec in records:
        key = (rec["entity_name"], rec["observed_at"], rec["metric_type"])
        if key in seen:
            duplicate_count += 1
            continue
        seen.add(key)
        unique.append(rec)
    return unique, duplicate_count


def load_to_sqlite(records, db_path):
    conn = sqlite3.connect(db_path)
    conn.execute(DDL)
    conn.executemany(
        """
        INSERT OR IGNORE INTO water_metrics
        (source_name, source_url, fetched_at, observed_at, location,
         entity_name, metric_type, value, unit)
        VALUES (:source_name, :source_url, :fetched_at, :observed_at, :location,
                :entity_name, :metric_type, :value, :unit)
        """,
        records,
    )
    conn.commit()
    inserted = conn.total_changes
    conn.close()
    return inserted


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--fixture", help="Canli API yerine bu JSON dosyasini kullan")
    parser.add_argument("--db", default="output/water_data.db")
    parser.add_argument("--limit-pages", type=int, default=None)
    args = parser.parse_args()

    fetched_at = datetime.now(timezone.utc).isoformat()

    try:
        if args.fixture:
            print(f"[bilgi] Fixture kullaniliyor: {args.fixture}")
            raw_records = fetch_fixture(args.fixture)
        else:
            print("[bilgi] Canli API'den cekiliyor...")
            raw_records = fetch_live(limit_pages=args.limit_pages)
    except RuntimeError as exc:
        print(f"[hata] {exc}")
        print("[bilgi] fixtures/sample_response.json ile devam etmeyi deneyebilirsiniz.")
        sys.exit(1)

    read_count = len(raw_records)
    normalized, skipped = normalize(raw_records, fetched_at)
    deduped, duplicate_count = dedupe(normalized)

    inserted = load_to_sqlite(deduped, args.db)

    print("\n--- Ozet ---")
    print(f"Okunan kaynak satiri:      {read_count}")
    print(f"Uretilen (baraj x tarih):  {len(normalized) + len(skipped)}")
    print(f"Islenen (gecerli):         {len(deduped)}")
    print(f"Atlanan (hatali):          {len(skipped)}")
    print(f"Atlanan (duplicate):       {duplicate_count}")
    print(f"DB'ye eklenen yeni satir:  {inserted}")

    if skipped:
        print("\nHatali kayit nedenleri (ilk 5):")
        for rec, reason in skipped[:5]:
            print(f"  - {rec.get('entity_name')} / {rec.get('observed_at')}: {reason}")


if __name__ == "__main__":
    main()