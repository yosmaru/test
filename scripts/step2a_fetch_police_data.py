"""
Step 2-1(実データ版): 新潟県警・事件事故マップから犯罪/交通事故/不審者データを取得する

当初はSPA(JavaScript動的描画)としてPlaywright等でのAPI調査を想定していたが
(`step2a_police_map_capture.py` 参照)、実際にJSバンドル(`/assets/index-*.js`)を
直接取得して解析したところ、地図ピンのデータソースは以下の**静的TSV/JSONファイル**
であることが判明した(ヘッドレスブラウザは不要):

  /data/tsv/criminal_full.tsv             犯罪(緯度経度あり)
  /data/tsv/traffic_accident_full.tsv     交通事故(緯度経度あり)
  /data/tsv/suspicious_person_full.tsv    不審者事案(緯度経度なし、住所テキストのみ)
  /data/json/cities.json                  市区町村コード一覧

犯罪・交通事故は緯度経度が付与済みのためそのまま使用できる。
不審者事案は緯度経度が無いため、町丁目の住所テキストを国土地理院APIで
ジオコーディングしている(brief記載のガッコム安全ナビと同種のデータだが、
県警公式データの方が網羅的・構造化されているためこちらを採用し、
ガッコムは今回未使用とした)。

TSVの列にはヘッダー行が無いため、本スクリプトの COLUMNS_* 定数で
列位置を明示している(2026年時点の実データから逆算して確定させたもの。
サイト側の仕様変更で列が増減した場合はズレる可能性があるため、
実行時に列数をチェックしている)。

実行方法:
  python3 scripts/step2a_fetch_police_data.py

出力:
  data/processed/crime_points.csv
  data/processed/traffic_points.csv
  data/processed/suspicious_points.csv
"""

import csv
import sys
import time
from pathlib import Path

import requests

sys.path.insert(0, str(Path(__file__).resolve().parent))
from config import AREAS, DATA_PROCESSED, DATA_RAW, WARDS  # noqa: E402

BASE_URL = "https://map.police.niigata.dsvc.jp"
GSI_GEOCODE_URL = "https://msearch.gsi.go.jp/address-search/AddressSearch"
RAW_DIR = DATA_RAW / "police_map_data"

TARGET_WARDS = [f"新潟市{w}" for w in WARDS]

COLUMNS_CRIME = [
    "id", "category_code", "category_name", "lat", "lon", "city_code", "city_name",
    "address_code", "town_name", "police_code", "police_name",
    "date_from", "time_from", "date_to", "time_to",
]
COLUMNS_TRAFFIC = [
    "id", "severity_code", "severity_name", "lat", "lon", "city_code", "city_name",
    "town_name", "datetime", "police_code", "police_name", "weather",
    "time_code", "time_name", "road_code", "road_name", "cause_code", "cause_name",
    "attr_codes", "attr_names",
]
COLUMNS_SUSPICIOUS = [
    "id", "city_code", "address_code", "address_text", "category_code", "category_name",
    "status_code", "status_name", "age_code", "age_name", "gender_code", "gender_name",
    "location_type", "police_code", "police_name", "description", "suspect_description",
    "c18", "c19", "c20", "c21", "c22", "date", "time", "c25", "c26",
]


def fetch_tsv(name: str) -> Path:
    RAW_DIR.mkdir(parents=True, exist_ok=True)
    dest = RAW_DIR / name
    print(f"[INFO] Fetching {BASE_URL}/data/tsv/{name}")
    resp = requests.get(f"{BASE_URL}/data/tsv/{name}", timeout=30)
    resp.raise_for_status()
    dest.write_bytes(resp.content)
    return dest


def parse_tsv(path: Path, columns: list[str]):
    with path.open(encoding="utf-8") as f:
        for row in csv.reader(f, delimiter="\t"):
            if len(row) < len(columns):
                continue
            yield dict(zip(columns, row))


def write_crime_and_traffic():
    crime_path = fetch_tsv("criminal_full.tsv")
    traffic_path = fetch_tsv("traffic_accident_full.tsv")

    with (DATA_PROCESSED / "crime_points.csv").open("w", newline="", encoding="utf-8") as f:
        writer = csv.writer(f)
        writer.writerow(["lat", "lon", "category", "date", "city_name", "town_name"])
        n_hit = 0
        for rec in parse_tsv(crime_path, COLUMNS_CRIME):
            if rec["city_name"] in TARGET_WARDS:
                n_hit += 1
                writer.writerow([rec["lat"], rec["lon"], rec["category_name"],
                                  rec["date_from"], rec["city_name"], rec["town_name"]])
        print(f"[INFO] crime_points.csv: {n_hit}件")

    with (DATA_PROCESSED / "traffic_points.csv").open("w", newline="", encoding="utf-8") as f:
        writer = csv.writer(f)
        writer.writerow(["lat", "lon", "category", "date", "city_name", "town_name"])
        n_hit = 0
        for rec in parse_tsv(traffic_path, COLUMNS_TRAFFIC):
            if rec["city_name"] in TARGET_WARDS:
                n_hit += 1
                writer.writerow([rec["lat"], rec["lon"], rec["severity_name"],
                                  rec["datetime"], rec["city_name"], rec["town_name"]])
        print(f"[INFO] traffic_points.csv: {n_hit}件")


def write_suspicious():
    susp_path = fetch_tsv("suspicious_person_full.tsv")
    session = requests.Session()
    session.headers.update({"User-Agent": "Mozilla/5.0 (research; niigata-safety-scoring)"})

    rows = []
    for rec in parse_tsv(susp_path, COLUMNS_SUSPICIOUS):
        addr = rec["address_text"]
        matched_ward = next((w for w in TARGET_WARDS if addr.startswith(w)), None)
        if matched_ward:
            rows.append(rec)
    print(f"[INFO] 対象区の不審者事案: {len(rows)}件。ジオコーディング中...")

    out_path = DATA_PROCESSED / "suspicious_points.csv"
    with out_path.open("w", newline="", encoding="utf-8") as f:
        writer = csv.DictWriter(f, fieldnames=["lat", "lon", "category", "date", "ward", "address_text"])
        writer.writeheader()
        n_ok = 0
        for rec in rows:
            addr = rec["address_text"]
            ward = next(w for w in TARGET_WARDS if addr.startswith(w))
            try:
                resp = session.get(GSI_GEOCODE_URL, params={"q": addr}, timeout=10)
                resp.raise_for_status()
                results = resp.json()
            except Exception as e:  # noqa: BLE001
                print(f"[WARN] geocode failed for {addr}: {e}")
                results = []
            if results:
                lon, lat = results[0]["geometry"]["coordinates"]
                n_ok += 1
            else:
                lat = lon = None
                print(f"[WARN] no geocode result for {addr}")
            writer.writerow({
                "lat": lat, "lon": lon, "category": rec["category_name"],
                "date": rec["date"], "ward": ward, "address_text": addr,
            })
            time.sleep(0.3)
    print(f"[INFO] suspicious_points.csv: {n_ok}/{len(rows)}件ジオコーディング成功")


def main():
    write_crime_and_traffic()
    write_suspicious()


if __name__ == "__main__":
    main()
