"""
Step 3: 空間結合(Point-in-Polygon)とスコアリング

Step1で確定した学区ポリゴンと、Step2で収集した各種事案(緯度経度)を
GeoPandasで空間結合し、学区ごとの件数を集計。世帯数で正規化して発生率に変換し、
複数指標を重み付け合算して総合安全スコアを算出する。

入力(すべて data/processed/ 配下を想定。無いものはその指標をスキップし、
NEXT STEPで案内する):
  school_districts_confirmed.geojson
      columns: area (5エリア名のいずれか), school_district_name, geometry(Polygon)
      -> Step1の出力を人間が目視確認・編集して作成する
  crime_points.csv            columns: lat, lon [, category, date]
  suspicious_points.csv       columns: lat, lon [, category, date]   (gaccom由来)
  traffic_points.csv          columns: lat, lon [, category, date]
  streetlight_points.csv      columns: lat, lon
  hazard_polygons.geojson     浸水/土砂災害ハザードエリアのポリゴン(geometry)
  households.csv              columns: area, households  (国勢調査 町丁目別を学区に集計したもの)

出力:
  output/school_district_safety_scores.csv
  output/school_district_safety_scores.md
"""

import argparse
import sys
from pathlib import Path

import geopandas as gpd
import pandas as pd

sys.path.insert(0, str(Path(__file__).resolve().parent))
from config import AREAS, DATA_PROCESSED, MIN_SAMPLE_SIZE, OUTPUT_DIR, WEIGHTS  # noqa: E402

# 新潟県(第VIII系)平面直角座標系。面積・密度計算のための投影座標系。
PROJECTED_CRS = "EPSG:6676"
WGS84 = "EPSG:4326"


def load_school_districts(path: Path) -> gpd.GeoDataFrame:
    if not path.exists():
        raise SystemExit(
            f"{path} が見つかりません。Step1の出力を人間が目視確認・編集して"
            "作成してください(area列に5エリア名のいずれかを付与すること)。"
        )
    gdf = gpd.read_file(path)
    if "area" not in gdf.columns:
        raise SystemExit(f"{path} に 'area' 列がありません。エリア名を付与してください。")
    missing = set(AREAS) - set(gdf["area"].unique())
    if missing:
        print(f"[WARN] 学区ポリゴンが未確定のエリアがあります: {missing}")
    if gdf.crs is None:
        print("[WARN] CRSが未設定です。WGS84として扱います。")
        gdf = gdf.set_crs(WGS84)
    return gdf


def compute_area_km2(gdf: gpd.GeoDataFrame) -> pd.Series:
    projected = gdf.to_crs(PROJECTED_CRS)
    return projected.geometry.area / 1_000_000  # m^2 -> km^2


def load_points(path: Path) -> gpd.GeoDataFrame | None:
    if not path.exists():
        print(f"[SKIP] {path} が無いためこの指標はスキップします。")
        return None
    df = pd.read_csv(path)
    df = df.dropna(subset=["lat", "lon"])
    gdf = gpd.GeoDataFrame(
        df, geometry=gpd.points_from_xy(df["lon"], df["lat"]), crs=WGS84
    )
    return gdf


def count_points_per_area(districts: gpd.GeoDataFrame, points: gpd.GeoDataFrame | None) -> pd.Series:
    if points is None:
        return pd.Series({a: None for a in districts["area"].unique()})
    joined = gpd.sjoin(points, districts[["area", "geometry"]], how="inner", predicate="within")
    counts = joined.groupby("area").size()
    return counts.reindex(districts["area"].unique(), fill_value=0)


def hazard_overlap_ratio(districts: gpd.GeoDataFrame, hazard_path: Path) -> pd.Series:
    if not hazard_path.exists():
        print(f"[SKIP] {hazard_path} が無いためハザード指標はスキップします。")
        return pd.Series({a: None for a in districts["area"].unique()})
    hazard = gpd.read_file(hazard_path)
    if hazard.crs is None:
        hazard = hazard.set_crs(WGS84)

    districts_proj = districts.to_crs(PROJECTED_CRS)
    hazard_proj = hazard.to_crs(PROJECTED_CRS)
    hazard_union = hazard_proj.geometry.union_all()

    ratios = {}
    for _, row in districts_proj.iterrows():
        district_area = row.geometry.area
        if district_area == 0:
            ratios[row["area"]] = 0.0
            continue
        overlap_area = row.geometry.intersection(hazard_union).area
        ratios[row["area"]] = overlap_area / district_area
    return pd.Series(ratios)


def normalize_minmax(series: pd.Series) -> pd.Series:
    s = series.astype(float)
    if s.max() == s.min():
        return pd.Series(0.0, index=s.index)
    return (s - s.min()) / (s.max() - s.min())


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--districts", default=str(DATA_PROCESSED / "school_districts_confirmed.geojson"))
    parser.add_argument("--crime", default=str(DATA_PROCESSED / "crime_points.csv"))
    parser.add_argument("--suspicious", default=str(DATA_PROCESSED / "suspicious_points.csv"))
    parser.add_argument("--traffic", default=str(DATA_PROCESSED / "traffic_points.csv"))
    parser.add_argument("--streetlight", default=str(DATA_PROCESSED / "streetlight_points.csv"))
    parser.add_argument("--hazard", default=str(DATA_PROCESSED / "hazard_polygons.geojson"))
    parser.add_argument("--households", default=str(DATA_PROCESSED / "households.csv"))
    parser.add_argument("--out-prefix", default=str(OUTPUT_DIR / "school_district_safety_scores"))
    args = parser.parse_args()

    districts = load_school_districts(Path(args.districts))
    districts["area_km2"] = compute_area_km2(districts)

    households_path = Path(args.households)
    if households_path.exists():
        households = pd.read_csv(households_path).set_index("area")["households"]
    else:
        print(f"[WARN] {households_path} が無いため世帯数正規化ができません。件数のみで比較します。")
        households = pd.Series({a: None for a in districts["area"].unique()})

    crime_pts = load_points(Path(args.crime))
    suspicious_pts = load_points(Path(args.suspicious))
    traffic_pts = load_points(Path(args.traffic))
    streetlight_pts = load_points(Path(args.streetlight))

    crime_count = count_points_per_area(districts, crime_pts)
    suspicious_count = count_points_per_area(districts, suspicious_pts)
    traffic_count = count_points_per_area(districts, traffic_pts)
    streetlight_count = count_points_per_area(districts, streetlight_pts)
    hazard_ratio = hazard_overlap_ratio(districts, Path(args.hazard))

    result = pd.DataFrame({
        "area": districts["area"].unique(),
    }).set_index("area")

    result["ward"] = [AREAS[a]["ward"] for a in result.index]
    result["area_km2"] = districts.groupby("area")["area_km2"].sum()
    result["households"] = households
    result["crime_count"] = crime_count
    result["suspicious_count"] = suspicious_count
    result["traffic_count"] = traffic_count
    result["streetlight_count"] = streetlight_count
    result["hazard_overlap_ratio"] = hazard_ratio

    def rate_per_1000_households(count_col):
        if households.isna().all():
            return result[count_col].astype(float)
        return (result[count_col].astype(float) / result["households"].astype(float)) * 1000

    result["crime_rate"] = rate_per_1000_households("crime_count")
    result["suspicious_rate"] = rate_per_1000_households("suspicious_count")
    result["traffic_rate"] = rate_per_1000_households("traffic_count")
    result["streetlight_density"] = result["streetlight_count"].astype(float) / result["area_km2"]
    result["hazard_score"] = result["hazard_overlap_ratio"].astype(float)

    # 各指標を5エリア間で0-1に正規化(相対比較)。値が全て欠損の場合は0.5(中立)で埋める。
    norm = pd.DataFrame(index=result.index)
    for col in ["crime_rate", "suspicious_rate", "traffic_rate", "hazard_score"]:
        if result[col].isna().all():
            norm[col] = 0.5
            print(f"[WARN] '{col}' のデータが無いため中立値(0.5)で埋めています。")
        else:
            norm[col] = normalize_minmax(result[col].fillna(result[col].mean()))

    if result["streetlight_density"].isna().all():
        norm["streetlight_density"] = 0.5
    else:
        norm["streetlight_density"] = normalize_minmax(
            result["streetlight_density"].fillna(result["streetlight_density"].mean())
        )

    # リスクスコア = 重み付け合算(防犯灯密度は高いほど安全なので反転)
    risk = (
        WEIGHTS["crime_rate"] * norm["crime_rate"]
        + WEIGHTS["suspicious_rate"] * norm["suspicious_rate"]
        + WEIGHTS["traffic_rate"] * norm["traffic_rate"]
        + WEIGHTS["hazard_score"] * norm["hazard_score"]
        + WEIGHTS["streetlight_density"] * (1 - norm["streetlight_density"])
    )
    result["risk_score"] = risk
    result["safety_score"] = (1 - risk) * 100  # 0-100、高いほど相対的に安全

    for col, count_col in [
        ("crime_rate", "crime_count"),
        ("suspicious_rate", "suspicious_count"),
        ("traffic_rate", "traffic_count"),
    ]:
        result[f"{col}_note"] = result[count_col].apply(
            lambda c: "参考値(サンプル数少)" if pd.notna(c) and c < MIN_SAMPLE_SIZE else ""
        )

    result = result.sort_values("safety_score", ascending=False)

    out_csv = Path(f"{args.out_prefix}.csv")
    out_csv.parent.mkdir(parents=True, exist_ok=True)
    result.to_csv(out_csv, encoding="utf-8-sig")
    print(f"[INFO] CSVを出力しました: {out_csv}")

    md_lines = [
        "# 新潟市 学区別 総合安全スコア(5エリア相対比較)",
        "",
        "**注意**: このスコアは絶対的な安全/危険を表すものではなく、"
        "対象5エリア間の相対順位です。サンプル数が少ない指標には「参考値」の注記があります。",
        "",
        "| エリア | 区 | safety_score | crime_rate | suspicious_rate | traffic_rate | "
        "hazard_score(重複率) | streetlight_density | 元データ件数(crime/suspicious/traffic) |",
        "|---|---|---|---|---|---|---|---|---|",
    ]
    for area, row in result.iterrows():
        counts = f"{row['crime_count']}/{row['suspicious_count']}/{row['traffic_count']}"
        md_lines.append(
            f"| {area} | {row['ward']} | {row['safety_score']:.1f} | "
            f"{row['crime_rate']:.3f}{row['crime_rate_note']} | "
            f"{row['suspicious_rate']:.3f}{row['suspicious_rate_note']} | "
            f"{row['traffic_rate']:.3f}{row['traffic_rate_note']} | "
            f"{row['hazard_score']:.3f} | {row['streetlight_density']:.2f} | {counts} |"
        )
    md_lines.append("")
    md_lines.append("## 使用した重み")
    for k, v in WEIGHTS.items():
        md_lines.append(f"- {k}: {v}")

    out_md = Path(f"{args.out_prefix}.md")
    out_md.write_text("\n".join(md_lines), encoding="utf-8")
    print(f"[INFO] Markdownを出力しました: {out_md}")

    print("\n" + result[["ward", "safety_score"]].to_string())


if __name__ == "__main__":
    main()
