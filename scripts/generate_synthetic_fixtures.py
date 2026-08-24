"""
合成(ダミー)データを生成し、Step3パイプラインの動作確認を行うためのスクリプト。

**重要**: ここで生成されるポリゴン・事案データは実データではなく、
パイプラインのロジック(空間結合・正規化・重み付け)を検証するための
テストフィクスチャである。実際のスコアリングには使用しないこと。

出力先: data/sample_synthetic/ , output/sample_synthetic/
"""

import sys
from pathlib import Path

import geopandas as gpd
import numpy as np
import pandas as pd
from shapely.geometry import box

sys.path.insert(0, str(Path(__file__).resolve().parent))
from config import ROOT  # noqa: E402

SAMPLE_DATA_DIR = ROOT / "data" / "sample_synthetic"

# 実際の学区形状とは無関係な、検証用のダミー矩形ポリゴン
AREA_BOXES = {
    "越後石山": (139.10, 37.90, 139.12, 37.92),
    "亀田": (139.12, 37.90, 139.14, 37.92),
    "曽野木": (139.14, 37.90, 139.16, 37.92),
    "荻川": (139.10, 37.92, 139.12, 37.94),
    "新津": (139.12, 37.92, 139.14, 37.94),
}


def main():
    SAMPLE_DATA_DIR.mkdir(parents=True, exist_ok=True)
    rng = np.random.default_rng(42)

    rows = [
        {
            "area": area,
            "school_district_name": f"{area}小学校区(synthetic)",
            "geometry": box(*bounds),
        }
        for area, bounds in AREA_BOXES.items()
    ]
    gdf = gpd.GeoDataFrame(rows, crs="EPSG:4326")
    gdf.to_file(SAMPLE_DATA_DIR / "school_districts_confirmed.geojson", driver="GeoJSON")

    def random_points_in(area_key, n):
        minx, miny, maxx, maxy = AREA_BOXES[area_key]
        lons = rng.uniform(minx, maxx, n)
        lats = rng.uniform(miny, maxy, n)
        return lons, lats

    def make_points_csv(name, counts):
        lats, lons = [], []
        for area, n in counts.items():
            lo, la = random_points_in(area, n)
            lons.extend(lo)
            lats.extend(la)
        pd.DataFrame({"lat": lats, "lon": lons}).to_csv(SAMPLE_DATA_DIR / name, index=False)

    make_points_csv(
        "crime_points.csv", {"越後石山": 8, "亀田": 15, "曽野木": 3, "荻川": 6, "新津": 20}
    )
    make_points_csv(
        "suspicious_points.csv", {"越後石山": 2, "亀田": 5, "曽野木": 1, "荻川": 2, "新津": 7}
    )
    make_points_csv(
        "traffic_points.csv", {"越後石山": 4, "亀田": 9, "曽野木": 2, "荻川": 3, "新津": 12}
    )
    make_points_csv(
        "streetlight_points.csv", {"越後石山": 50, "亀田": 80, "曽野木": 60, "荻川": 40, "新津": 30}
    )

    # 荻川・新津にまたがるダミーハザードエリア
    hazard = gpd.GeoDataFrame(
        {"geometry": [box(139.10, 37.925, 139.14, 37.935)]}, crs="EPSG:4326"
    )
    hazard.to_file(SAMPLE_DATA_DIR / "hazard_polygons.geojson", driver="GeoJSON")

    pd.DataFrame(
        {
            "area": list(AREA_BOXES.keys()),
            "households": [1200, 2500, 900, 1100, 3000],
        }
    ).to_csv(SAMPLE_DATA_DIR / "households.csv", index=False)

    print(f"[INFO] 合成フィクスチャを生成しました: {SAMPLE_DATA_DIR}")


if __name__ == "__main__":
    main()
