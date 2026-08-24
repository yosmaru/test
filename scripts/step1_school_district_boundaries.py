"""
Step 1: 学区境界データの取得・抽出

国土数値情報「小学校区データ」(A27, 新潟県分)を GeoPandas で読み込み、
新潟市・対象5エリアに該当する学区ポリゴンだけを抽出する。

事前準備(このスクリプト自体はダウンロードを行わない):
  1. https://nlftp.mlit.go.jp/ksj/gml/datalist/KsjTmplt-A27.html を開き、
     利用規約に同意のうえ新潟県(15)分の SHAPE 形式データをダウンロードする。
     (このリモート実行環境は組織のアウトバウンドポリシーにより
      nlftp.mlit.go.jp への直接アクセスがブロックされているため、
      ダウンロードはこのスクリプトを実行する側のマシン/環境で行うこと)
  2. ダウンロードした zip を data/raw/ 以下に展開する
     (例: data/raw/A27-XX_15_GML/*.shp)

実行方法:
  python3 scripts/step1_school_district_boundaries.py --raw-dir data/raw

出力:
  data/processed/school_districts_candidates.geojson
    - 対象キーワードにヒットした全ポリゴン(目視確認用)
  標準出力に、エリア別のヒット件数・学区名一覧を表示する
    -> これを見て config.py の AREAS[...]["keywords"] や、
       実際に採用する学区名リストを人間が確定させること
       (自動抽出だけでは表記ゆれで漏れる可能性があるため、必ず目視確認する)
"""

import argparse
import sys
from pathlib import Path

import geopandas as gpd

sys.path.insert(0, str(Path(__file__).resolve().parent))
from config import AREAS, DATA_PROCESSED, DATA_RAW  # noqa: E402

NIIGATA_CITY_HINT = "新潟市"


def find_shapefiles(raw_dir: Path):
    return sorted(raw_dir.rglob("*.shp"))


def detect_name_column(gdf: gpd.GeoDataFrame) -> str:
    """学区名らしき列をヒューリスティックに検出する。

    国土数値情報 A27 の列名(A27_005 等)はバージョンにより変わることがあるため、
    値に「小学校」「学区」等の日本語文字列を含む列を優先的に採用する。
    確実性を優先し、複数候補がある場合は列名と件数を表示して人間の判断を促す。
    """
    candidates = []
    for col in gdf.columns:
        if col == gdf.geometry.name:
            continue
        sample = gdf[col].dropna().astype(str).head(50)
        if sample.empty:
            continue
        hits = sample.str.contains("小学校|学区|校区", regex=True).sum()
        if hits > 0:
            candidates.append((col, hits, len(sample)))

    if not candidates:
        print("[WARN] 学区名らしき列を自動検出できませんでした。全列を表示します:")
        print(gdf.columns.tolist())
        raise SystemExit(
            "name列を自動検出できません。列名を確認し、このスクリプトの"
            "detect_name_column() を修正するか、--name-col で明示指定してください。"
        )

    candidates.sort(key=lambda x: -x[1])
    print("[INFO] 学区名列の候補:")
    for col, hits, total in candidates:
        print(f"    {col}: サンプル{total}件中{hits}件が学区名らしき文字列")
    return candidates[0][0]


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--raw-dir", default=str(DATA_RAW))
    parser.add_argument("--name-col", default=None, help="学区名列を明示指定する場合")
    parser.add_argument(
        "--out",
        default=str(DATA_PROCESSED / "school_districts_candidates.geojson"),
    )
    args = parser.parse_args()

    raw_dir = Path(args.raw_dir)
    shapefiles = find_shapefiles(raw_dir)
    if not shapefiles:
        raise SystemExit(
            f"{raw_dir} 配下に .shp が見つかりません。"
            "国土数値情報A27(新潟県分)を展開してから再実行してください。"
        )

    print(f"[INFO] 見つかったシェープファイル: {[str(p) for p in shapefiles]}")

    gdfs = []
    for shp in shapefiles:
        gdf = gpd.read_file(shp, encoding="utf-8")
        gdfs.append(gdf)

    import pandas as pd

    gdf_all = gpd.GeoDataFrame(pd.concat(gdfs, ignore_index=True))
    print(f"[INFO] 全ポリゴン数: {len(gdf_all)}")
    print(f"[INFO] 列一覧: {gdf_all.columns.tolist()}")

    name_col = args.name_col or detect_name_column(gdf_all)
    print(f"[INFO] 学区名列として '{name_col}' を採用します")

    # 新潟市に該当する行だけに絞る(市区町村名を含む列があれば優先的に使う)
    city_mask = gdf_all.apply(
        lambda row: row.astype(str).str.contains(NIIGATA_CITY_HINT).any(), axis=1
    )
    gdf_niigata = gdf_all[city_mask].copy()
    print(f"[INFO] '{NIIGATA_CITY_HINT}' を含む行: {len(gdf_niigata)}")

    if gdf_niigata.empty:
        print(
            "[WARN] '新潟市' を含む行が見つかりませんでした。"
            "市区町村コード列で絞り込む必要があるかもしれません。全国データの可能性があります。"
        )
        gdf_niigata = gdf_all.copy()

    all_keywords = []
    for area, info in AREAS.items():
        all_keywords.extend(info["keywords"])
    pattern = "|".join(sorted(set(all_keywords)))

    hit_mask = gdf_niigata[name_col].astype(str).str.contains(pattern, regex=True, na=False)
    candidates = gdf_niigata[hit_mask].copy()

    print("\n=== エリア別ヒット結果(目視確認が必須) ===")
    for area, info in AREAS.items():
        area_pattern = "|".join(info["keywords"])
        area_hits = candidates[
            candidates[name_col].astype(str).str.contains(area_pattern, regex=True, na=False)
        ]
        names = area_hits[name_col].astype(str).unique().tolist()
        print(f"- {area} ({info['ward']}): {len(area_hits)}件 -> {names}")
        if len(area_hits) == 0:
            print(f"  [WARN] '{area}' に該当するポリゴンが見つかりませんでした。"
                  f" config.py の keywords ('{area_pattern}') を見直してください。")
        elif len(area_hits) > 1:
            print(f"  [NOTE] 複数学区がヒットしています。実在する校区と一致するか、"
                  f"表記ゆれによる重複でないか目視確認してください。")

    out_path = Path(args.out)
    if not candidates.empty:
        candidates.to_file(out_path, driver="GeoJSON")
        print(f"\n[INFO] 候補ポリゴンを出力しました: {out_path}")
    else:
        print("\n[WARN] 候補ポリゴンが0件のため出力をスキップしました。")

    print(
        "\n[NEXT STEP] 上記の一覧を必ず目視確認し、5エリアそれぞれに対応する"
        "学区ポリゴンを確定させてください。確定後、school_districts_candidates.geojson を"
        "手動で編集(不要な行を削除、area列を付与)して"
        "data/processed/school_districts_confirmed.geojson として保存し、"
        "Step3 の入力として使用してください。"
    )


if __name__ == "__main__":
    main()
