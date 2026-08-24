"""
Step 2-3: 区単位ベースライン統計の取得(妥当性チェック用)

新潟県警「市町村別犯罪発生状況」および新潟市「犯罪発生状況」ページから、
区単位の犯罪発生件数をベースラインとして取得する。
学区別スコア(Step3)がこの区の相場観と大きくズレていないかの
妥当性チェックに使う。

注意: このリモート実行環境は組織のアウトバウンドポリシーにより
pref.niigata.lg.jp / city.niigata.lg.jp への直接アクセスがブロックされている
(egress proxyで403)。そのため本スクリプトはこの環境では実行できない。
外部アクセス可能な環境で実行すること。

ページ内の表がPDF/画像の場合はpandas.read_htmlで取得できないため、
その場合はPDFを手動ダウンロードし、data/raw/ward_baseline/ に格納したうえで
tabula-py 等でテーブル抽出するか、手動でCSV化して
data/processed/ward_baseline.csv (columns: ward, category, count, year) を
作成すること。

実行方法:
  python3 scripts/step2c_ward_baseline.py \
      --url https://www.pref.niigata.lg.jp/site/kenkei/anzen-ansin-shityouson08.html \
      --out data/raw/ward_baseline/pref_page_tables
"""

import argparse
import sys
from pathlib import Path

import pandas as pd
import requests

sys.path.insert(0, str(Path(__file__).resolve().parent))
from config import DATA_RAW  # noqa: E402


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--url", required=True)
    parser.add_argument("--out-prefix", default=str(DATA_RAW / "ward_baseline" / "table"))
    args = parser.parse_args()

    out_prefix = Path(args.out_prefix)
    out_prefix.parent.mkdir(parents=True, exist_ok=True)

    headers = {"User-Agent": "Mozilla/5.0 (research; niigata-safety-scoring)"}
    resp = requests.get(args.url, headers=headers, timeout=15)
    resp.raise_for_status()

    try:
        tables = pd.read_html(resp.text)
    except ValueError:
        tables = []

    if not tables:
        raw_html_path = out_prefix.with_suffix(".html")
        raw_html_path.write_text(resp.text, encoding="utf-8")
        print(
            f"[WARN] 表を自動抽出できませんでした(PDF/画像で提供されている可能性)。"
            f"生HTMLを保存しました: {raw_html_path}"
        )
        print(
            "[NEXT STEP] ページ内のPDFリンクを手動で確認し、ダウンロードして"
            "tabula-py 等でテーブル抽出するか、手動でCSV化してください。"
        )
        return

    for i, table in enumerate(tables):
        out_path = Path(f"{out_prefix}_{i}.csv")
        table.to_csv(out_path, index=False)
        print(f"[INFO] 表{i}を保存しました: {out_path} (shape={table.shape})")

    print(
        "\n[NEXT STEP] 保存された表を確認し、区別の件数を"
        "data/processed/ward_baseline.csv (columns: ward, category, count, year) に整形してください。"
    )


if __name__ == "__main__":
    main()
