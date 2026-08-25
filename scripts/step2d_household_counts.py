"""
Step 2-4(実データ版): 対象5エリアの世帯数を新潟市公式統計から集計する

新潟市が公表する「年齢(5歳ごと)町丁別人口統計」(住民基本台帳、世帯数列を含む)を
ダウンロードし、各エリアに対応する町丁目リスト(AREA_CHOME、新潟市公式の通学区域
ページから人間が確認して書き起こしたもの)で世帯数を合算する。

町丁目の一部(「x」表記=国の基準により極少数のため非公表、または表記ゆれで
自動マッチできないもの)は集計から漏れる可能性がある。実行時に警告として表示する。

実行方法:
  python3 scripts/step2d_household_counts.py

出力:
  data/processed/households.csv
"""

import re
import sys
from pathlib import Path

import requests

sys.path.insert(0, str(Path(__file__).resolve().parent))
from config import DATA_PROCESSED, DATA_RAW  # noqa: E402

# 新潟市: 年齢(5歳ごと)町丁別人口統計(最新: 令和8年3月末時点)
STATS_XLSX_URL = (
    "https://www.city.niigata.lg.jp/shisei/gaiyo/profile/00_01jinkou/"
    "jyuuki5saigoto.files/260331kutyoumeinennrei.xlsx"
)

CITY_BASE = "https://www.city.niigata.lg.jp/kosodate/gakko/sho_chu_school/tsugakukuiki/sub02"

# 新潟市公式サイトの通学区域ページ(目視確認済み)。手打ちの町丁目リストは
# 転記ミスの原因になるため、各学校の通学区域ページを直接取得して
# 「町名」列を抽出する(extract_chome_names)。
AREA_SCHOOL_PAGES = {
    "越後石山": {"江南小学校": f"{CITY_BASE}/02higashi_ku/10higashi_ku.html"},
    "亀田": {
        "亀田小学校": f"{CITY_BASE}/04konan_ku/11konan_ku.html",
        "亀田東小学校": f"{CITY_BASE}/04konan_ku/12konan_ku.html",
        "亀田西小学校": f"{CITY_BASE}/04konan_ku/14konan_ku.html",
    },
    "曽野木": {
        "曽野木小学校": f"{CITY_BASE}/04konan_ku/05konan_ku.html",
        "東曽野木小学校": f"{CITY_BASE}/04konan_ku/06konan_ku.html",
    },
    "新津": {
        "新津第一小学校": f"{CITY_BASE}/05akiha_ku/06akiha_ku.html",
        "新津第二小学校": f"{CITY_BASE}/05akiha_ku/10akiha_ku.html",
        "新津第三小学校": f"{CITY_BASE}/05akiha_ku/07akiha_ku.html",
    },
    "荻川": {"荻川小学校": f"{CITY_BASE}/05akiha_ku/09akiha_ku.html"},
}
AREA_WARD = {"越後石山": "東区", "亀田": "江南区", "曽野木": "江南区", "新津": "秋葉区", "荻川": "秋葉区"}

_NOISE_TOKENS = {"全部", "（一部中央区）", "（中央区）", "（一部東区）"}


def extract_chome_names(html: str) -> list[str]:
    """通学区域ページの本文から「町名」列の町丁目名を抽出する。

    ページはプレーンな表(町名/地番等の2列)なので、HTMLタグを除去した
    テキスト行のうち、番地・号・「／」を含まない(=全域が対象の)行だけを
    町丁目名として拾う。一部地番のみが対象の町丁目(例:「石山2丁目 1番〜7番」)は、
    地番情報が失われるため厳密には過大集計になり得るが、これは世帯数集計における
    既知の近似(brief記載の「学区境界は参考値」の範囲内)として許容する。
    """
    text = re.sub("<[^>]+>", "\n", html)
    lines = [l.strip() for l in text.splitlines() if l.strip()]
    try:
        start = lines.index("町名")
        end = lines.index("このページの作成担当")
    except ValueError:
        return []
    names = []
    for l in lines[start + 2:end]:
        if re.search(r"[番号／]", l) or l in _NOISE_TOKENS:
            continue
        if re.fullmatch(r"[一-龠ぁ-んァ-ヶー0-9０-９・～()（）]{1,16}", l):
            names.append(l)
    return sorted(set(names))


def fetch_area_chome(area: str, school_pages: dict) -> list[str]:
    cache_dir = DATA_RAW / "niigata_city_district"
    cache_dir.mkdir(parents=True, exist_ok=True)
    all_names = []
    for school, url in school_pages.items():
        cache_path = cache_dir / (url.rsplit("/", 1)[-1])
        if cache_path.exists():
            html = cache_path.read_text(encoding="utf-8", errors="ignore")
        else:
            resp = requests.get(url, timeout=20)
            resp.raise_for_status()
            resp.encoding = "utf-8"  # requestsの自動判定がこのサイトでは誤るため明示指定
            html = resp.text
            cache_path.write_text(html, encoding="utf-8")
        names = extract_chome_names(html)
        print(f"  {area}/{school}: {len(names)}町丁 {names}")
        all_names.extend(names)
    return sorted(set(all_names))

HALF2FULL = str.maketrans("0123456789", "０１２３４５６７８９")


def expand_chome(name: str) -> list[str]:
    base_chars = r"一-龠ぁ-んァ-ヶー()（）"
    m = re.fullmatch(rf"([{base_chars}]+)(\d+)～(\d+)丁目", name)
    if m:
        base, x, y = m.group(1), int(m.group(2)), int(m.group(3))
        return [f"{base}{str(i).translate(HALF2FULL)}丁目" for i in range(x, y + 1)]
    m = re.fullmatch(rf"([{base_chars}]+)([\d・]+)丁目", name)
    if m:
        base, nums = m.group(1), m.group(2)
        return [f"{base}{n.translate(HALF2FULL)}丁目" for n in nums.split("・")]
    return [name.translate(HALF2FULL)]


def load_household_lookup(xlsx_path: Path) -> dict:
    import openpyxl

    wb = openpyxl.load_workbook(xlsx_path, data_only=True)
    ws = wb.active
    lookup = {}
    for row in ws.iter_rows(min_row=6, values_only=True):
        ward, town, households, gender = row[0], row[2], row[3], row[4]
        if gender == "計" and ward and town:
            lookup[(ward, town.strip())] = households
    return lookup


def main():
    xlsx_path = DATA_RAW / "niigata_city_district" / "kutyoumeinennrei.xlsx"
    xlsx_path.parent.mkdir(parents=True, exist_ok=True)
    if not xlsx_path.exists():
        print(f"[INFO] Downloading {STATS_XLSX_URL}")
        resp = requests.get(STATS_XLSX_URL, timeout=30)
        resp.raise_for_status()
        xlsx_path.write_bytes(resp.content)

    lookup = load_household_lookup(xlsx_path)

    import csv

    with (DATA_PROCESSED / "households.csv").open("w", newline="", encoding="utf-8") as f:
        writer = csv.writer(f)
        writer.writerow(["area", "households"])
        for area, school_pages in AREA_SCHOOL_PAGES.items():
            print(f"[INFO] {area}: 通学区域ページを取得中...")
            chome_list = fetch_area_chome(area, school_pages)
            ward = AREA_WARD[area]
            total = 0
            seen, unmatched, suppressed = set(), [], []
            for name in chome_list:
                for expanded in expand_chome(name):
                    if expanded in seen:
                        continue
                    seen.add(expanded)
                    val = lookup.get((ward, expanded))
                    if val is None:
                        unmatched.append(expanded)
                    elif val == "x":
                        suppressed.append(expanded)
                    else:
                        total += val
            writer.writerow([area, total])
            print(f"[INFO] {area}({ward}): {total}世帯  "
                  f"unmatched={unmatched}  suppressed(x)={suppressed}")

    print(f"\n[INFO] 出力しました: {DATA_PROCESSED / 'households.csv'}")


if __name__ == "__main__":
    main()
