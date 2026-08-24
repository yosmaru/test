"""
合成データを使ったStep3パイプラインの回帰テスト。
外部ネットワークアクセスを使わずに、空間結合・正規化・重み付けロジックが
正しく動作することを検証する。

実行方法:
  python3 scripts/generate_synthetic_fixtures.py
  python3 scripts/test_pipeline_synthetic.py
"""

import subprocess
import sys
from pathlib import Path

import pandas as pd

sys.path.insert(0, str(Path(__file__).resolve().parent))
from config import ROOT  # noqa: E402

SAMPLE_DATA_DIR = ROOT / "data" / "sample_synthetic"
SAMPLE_OUTPUT_DIR = ROOT / "output" / "sample_synthetic"


def run_pipeline():
    cmd = [
        sys.executable,
        str(ROOT / "scripts" / "step3_spatial_join_scoring.py"),
        "--districts", str(SAMPLE_DATA_DIR / "school_districts_confirmed.geojson"),
        "--crime", str(SAMPLE_DATA_DIR / "crime_points.csv"),
        "--suspicious", str(SAMPLE_DATA_DIR / "suspicious_points.csv"),
        "--traffic", str(SAMPLE_DATA_DIR / "traffic_points.csv"),
        "--streetlight", str(SAMPLE_DATA_DIR / "streetlight_points.csv"),
        "--hazard", str(SAMPLE_DATA_DIR / "hazard_polygons.geojson"),
        "--households", str(SAMPLE_DATA_DIR / "households.csv"),
        "--out-prefix", str(SAMPLE_OUTPUT_DIR / "school_district_safety_scores"),
    ]
    subprocess.run(cmd, check=True, cwd=str(ROOT))


def main():
    if not (SAMPLE_DATA_DIR / "school_districts_confirmed.geojson").exists():
        raise SystemExit(
            "合成フィクスチャがありません。先に "
            "`python3 scripts/generate_synthetic_fixtures.py` を実行してください。"
        )

    run_pipeline()

    result = pd.read_csv(SAMPLE_OUTPUT_DIR / "school_district_safety_scores.csv", index_col="area")

    assert len(result) == 5, f"5エリア分の結果が必要です: {result.index.tolist()}"
    assert set(result.index) == {"越後石山", "亀田", "曽野木", "荻川", "新津"}

    # 空間結合が正しく機能していれば、事案を多く仕込んだ「新津」のcrime_countが最大になるはず
    assert result.loc["新津", "crime_count"] == 20, "新津のcrime_countが期待値と不一致(空間結合の不具合の疑い)"
    assert result.loc["曽野木", "crime_count"] == 3, "曽野木のcrime_countが期待値と不一致"

    # ハザード重複は荻川・新津のみ0.5、他は0のはず
    for area in ["荻川", "新津"]:
        assert abs(result.loc[area, "hazard_score"] - 0.5) < 0.01, f"{area}のhazard_scoreが期待値とズレています"
    for area in ["越後石山", "亀田", "曽野木"]:
        assert result.loc[area, "hazard_score"] == 0.0, f"{area}のhazard_scoreが期待値とズレています"

    # safety_scoreは0-100の範囲
    assert result["safety_score"].between(0, 100).all(), "safety_scoreが0-100の範囲外です"

    # 最も事案密度が高い新津が最も safety_score が低い(=リスクが高い)はず
    assert result["safety_score"].idxmin() == "新津", "リスクが最も高いはずの新津が最下位になっていません"

    print("[OK] 合成データによるパイプライン回帰テストに成功しました")
    print(result[["ward", "safety_score", "crime_count", "hazard_score"]].to_string())


if __name__ == "__main__":
    main()
