"""
Step 1(実データ版): 国土数値情報A27から対象5エリアの学区ポリゴンを構築する

新潟県分のA27(小学校区)には「2021年度版」は存在せず、以下2版のみが公開されている
(2026年時点でnlftp.mlit.go.jpを確認):
  - A27-10 (平成22年/2010年): 新潟市を含む
  - A27-16 (平成28年/2016年): 新潟市を含まない(他市町村のみ)
そのため新潟市の学区にはA27-10を使用する。

対象5エリアと学区の対応関係は、KSJデータの学区名だけでは特定できなかったため、
新潟市公式サイトの通学区域ページ(目視確認)で以下の通り確認した:
  - 越後石山: 「越後石山小学校」という学校は存在しない。市の通学区域ページで
    石山1・2丁目が「江南小学校」区に属することを確認し、江南小学校区を採用。
  - 亀田: 亀田小学校・亀田東小学校・亀田西小学校の3校区の合算(union)。
  - 曽野木: 曽野木小学校・東曽野木小学校の2校区の合算。
  - 新津: 新津第一小学校・新津第二小学校・新津第三小学校の3校区の合算。
  - 荻川: A27-10にも「荻川小学校」は収録されていない(データ自体に存在しない)。
    市公式ページで対象町丁目(あおば通1・2丁目, 市之瀬, 荻野町, 覚路津, 車場・
    車場1〜5丁目, こがね町, 中野4・5丁目)を特定し、各町丁目の代表点を
    国土地理院APIでジオコーディングして、その凸包(convex hull)で近似した。
    **これは公式境界ではない参考値**であり、実際の物件購入時は必ず
    教育委員会に番地単位で確認すること。

実行方法:
  python3 scripts/step1b_build_confirmed_districts.py

出力:
  data/processed/school_districts_confirmed.geojson
"""

import sys
import time
import zipfile
from pathlib import Path

import geopandas as gpd
import requests
from shapely.geometry import MultiPoint
from shapely.ops import unary_union

sys.path.insert(0, str(Path(__file__).resolve().parent))
from config import DATA_PROCESSED, DATA_RAW  # noqa: E402

A27_10_URL = "https://nlftp.mlit.go.jp/ksj/gml/data/A27/A27-10/A27-10_15_GML.zip"
GSI_GEOCODE_URL = "https://msearch.gsi.go.jp/address-search/AddressSearch"
KSJ_CRS = "EPSG:4612"  # JGD2000 経緯度(国土数値情報の標準測地系)

AREA_SCHOOLS = {
    "越後石山": {"ward": "東区", "schools": ["江南小学校"]},
    "亀田": {"ward": "江南区", "schools": ["亀田小学校", "亀田東小学校", "亀田西小学校"]},
    "曽野木": {"ward": "江南区", "schools": ["曽野木小学校", "東曽野木小学校"]},
    "新津": {"ward": "秋葉区", "schools": ["新津第一小学校", "新津第二小学校", "新津第三小学校"]},
}

OGIGAWA_CHOME = [
    "新潟市秋葉区あおば通1丁目", "新潟市秋葉区あおば通2丁目", "新潟市秋葉区市之瀬",
    "新潟市秋葉区荻野町", "新潟市秋葉区覚路津", "新潟市秋葉区車場",
    "新潟市秋葉区こがね町", "新潟市秋葉区中野4丁目", "新潟市秋葉区中野5丁目",
]


def fetch_and_extract_a27_10() -> Path:
    zip_path = DATA_RAW / "A27" / "A27-10_15_GML.zip"
    extract_dir = DATA_RAW / "A27-10_extracted"
    shp_path = extract_dir / "A27-10_15-g_SchoolDistrict.shp"
    if shp_path.exists():
        return shp_path

    zip_path.parent.mkdir(parents=True, exist_ok=True)
    print(f"[INFO] Downloading {A27_10_URL}")
    resp = requests.get(A27_10_URL, timeout=60)
    resp.raise_for_status()
    zip_path.write_bytes(resp.content)

    extract_dir.mkdir(parents=True, exist_ok=True)
    with zipfile.ZipFile(zip_path) as zf:
        zf.extractall(extract_dir)
    if not shp_path.exists():
        raise SystemExit(
            f"{shp_path} が見つかりません。A27-10のファイル構成が変わった可能性があります。"
            f"{extract_dir} の中身を確認してください。"
        )
    return shp_path


def geocode(address: str, session: requests.Session):
    resp = session.get(GSI_GEOCODE_URL, params={"q": address}, timeout=10)
    resp.raise_for_status()
    results = resp.json()
    if not results:
        return None
    lon, lat = results[0]["geometry"]["coordinates"]
    return lat, lon


def build_ogigawa_polygon():
    session = requests.Session()
    session.headers.update({"User-Agent": "Mozilla/5.0 (research; niigata-safety-scoring)"})
    points = []
    for addr in OGIGAWA_CHOME:
        result = geocode(addr, session)
        if result is None:
            print(f"[WARN] geocode failed for {addr}")
            continue
        lat, lon = result
        points.append((lon, lat))
        time.sleep(0.3)
    if len(points) < 3:
        raise SystemExit("荻川小学校区の近似に必要な地点数が不足しています(3点以上必要)")
    hull = MultiPoint(points).convex_hull.buffer(0.003)
    return hull


def main():
    shp_path = fetch_and_extract_a27_10()
    gdf = gpd.read_file(shp_path, encoding="cp932").set_crs(KSJ_CRS, allow_override=True)

    rows = []
    for area, info in AREA_SCHOOLS.items():
        sub = gdf[gdf["A27_007"].isin(info["schools"])]
        found = sub["A27_007"].unique().tolist()
        missing = set(info["schools"]) - set(found)
        if missing:
            print(f"[WARN] {area}: 見つからなかった学校区 {missing}(A27-10データ内で名称が変わった可能性)")
        if sub.empty:
            print(f"[WARN] {area}: ポリゴンが1件も見つかりませんでした。スキップします。")
            continue
        rows.append({
            "area": area,
            "ward": info["ward"],
            "school_district_name": "/".join(found),
            "source": "KSJ_A27-10_2010(official, unioned by school)",
            "geometry": unary_union(sub.geometry.values),
        })

    print("[INFO] 荻川小学校区を近似構築中(GSIジオコーディング)...")
    ogigawa_geom = build_ogigawa_polygon()
    rows.append({
        "area": "荻川",
        "ward": "秋葉区",
        "school_district_name": "荻川小学校(KSJ非収録のためGSIジオコーディング9地点の凸包で近似)",
        "source": "APPROXIMATED_convex_hull_of_geocoded_chome_centroids(NOT official boundary)",
        "geometry": ogigawa_geom,
    })

    out = gpd.GeoDataFrame(rows, crs=KSJ_CRS).to_crs("EPSG:4326")
    out_path = DATA_PROCESSED / "school_districts_confirmed.geojson"
    out.to_file(out_path, driver="GeoJSON")
    print(f"[INFO] 出力しました: {out_path}")
    print(out[["area", "ward", "school_district_name", "source"]].to_string())


if __name__ == "__main__":
    main()
