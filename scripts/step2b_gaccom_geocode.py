"""
Step 2-2: ガッコム安全ナビの不審者事案テキスト抽出 + ジオコーディング

https://www.gaccom.jp/safety/area/p15/ (新潟県) 配下の、対象区(東区/江南区/秋葉区)
の不審者事案ページから、町丁目レベルの発生場所テキストを抽出し、
国土地理院APIでジオコーディングして緯度経度を付与する。

注意: このリモート実行環境は組織のアウトバウンドポリシーにより
gaccom.jp / msearch.gsi.go.jp への直接アクセスがブロックされている
(egress proxyで403)。そのため本スクリプトはこの環境では実行できない。
外部アクセス可能な環境で実行すること。

ページのDOM構造は事前に確認できていないため、本スクリプトは
「厳密なCSSセレクタ」に依存せず、ページ本文テキストから
正規表現で住所らしき文字列(新潟市+区名+町丁目+丁目番号)を
拾う頑健な方式にしている。ヒット率が低い場合は
--selector オプションで事案リストのCSSセレクタを指定し、
extract_addresses_from_html() を実際のDOM構造に合わせて調整すること。

実行方法:
  python3 scripts/step2b_gaccom_geocode.py --ward 東区 --url <該当ページURL>

出力:
  data/processed/gaccom_suspicious_incidents.csv
    columns: ward, raw_text, address_guess, lat, lon, geocode_score
"""

import argparse
import re
import ssl
import sys
import time
from pathlib import Path

import requests
from requests.adapters import HTTPAdapter
from urllib3.util.ssl_ import create_urllib3_context

sys.path.insert(0, str(Path(__file__).resolve().parent))
from config import DATA_PROCESSED, WARDS  # noqa: E402

GSI_GEOCODE_URL = "https://msearch.gsi.go.jp/address-search/AddressSearch"


class LegacyDHAdapter(HTTPAdapter):
    """gaccom.jp はDH鍵長が短いサーバー証明書を使っており、OpenSSL 3.0の
    デフォルトセキュリティレベル(SECLEVEL=2)では接続できない。
    このアダプタはgaccom.jpへの接続時のみSECLEVEL=1に緩め、
    証明書検証自体は無効化しない(verifyはSessionの設定に従う)。
    """

    def init_poolmanager(self, *args, **kwargs):
        ctx = create_urllib3_context()
        ctx.set_ciphers("DEFAULT@SECLEVEL=1")
        kwargs["ssl_context"] = ctx
        return super().init_poolmanager(*args, **kwargs)

# 新潟市 + 区名 + 町丁目(丁目/番地を含む場合がある) を拾う正規表現。
# 例: "新潟市東区東出来島3丁目" 「新潟市江南区亀田" など。
ADDRESS_PATTERN = re.compile(
    r"新潟市(?:%s)[一-龠ぁ-んァ-ヶー0-9]{0,20}?(?:\d+丁目)?"
    % "|".join(WARDS)
)


def extract_addresses_from_html(html: str, selector: str | None = None) -> list[str]:
    from bs4 import BeautifulSoup

    soup = BeautifulSoup(html, "lxml")
    if selector:
        nodes = soup.select(selector)
        text = "\n".join(n.get_text(" ", strip=True) for n in nodes)
    else:
        text = soup.get_text("\n", strip=True)

    matches = ADDRESS_PATTERN.findall(text) if False else ADDRESS_PATTERN.finditer(text)
    addresses = sorted({m.group(0) for m in matches})
    return addresses


def geocode(address: str, session: requests.Session, sleep: float = 0.5):
    """国土地理院 住所検索API でジオコーディングする。"""
    try:
        resp = session.get(GSI_GEOCODE_URL, params={"q": address}, timeout=10)
        resp.raise_for_status()
        results = resp.json()
    except Exception as e:  # noqa: BLE001
        print(f"[WARN] geocode failed for '{address}': {e}")
        return None, None, None
    finally:
        time.sleep(sleep)

    if not results:
        return None, None, None

    top = results[0]
    lon, lat = top["geometry"]["coordinates"]
    score = top.get("properties", {}).get("title")
    return lat, lon, score


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--url", required=True, help="ガッコム安全ナビの対象区ページURL")
    parser.add_argument("--ward", required=True, choices=WARDS)
    parser.add_argument("--selector", default=None, help="事案リストのCSSセレクタ(任意)")
    parser.add_argument(
        "--out", default=str(DATA_PROCESSED / "gaccom_suspicious_incidents.csv")
    )
    args = parser.parse_args()

    session = requests.Session()
    session.headers.update({"User-Agent": "Mozilla/5.0 (research; niigata-safety-scoring)"})
    session.mount("https://www.gaccom.jp", LegacyDHAdapter())
    session.mount("https://gaccom.jp", LegacyDHAdapter())

    print(f"[INFO] Fetching {args.url}")
    resp = session.get(args.url, timeout=15)
    resp.raise_for_status()

    addresses = extract_addresses_from_html(resp.text, selector=args.selector)
    print(f"[INFO] {len(addresses)}件の住所らしき文字列を抽出しました")
    for a in addresses:
        print(f"  - {a}")

    if not addresses:
        print(
            "[WARN] 住所を抽出できませんでした。ページのDOM構造が想定と異なる可能性があります。"
            "--selector で事案要素を絞り込むか、ADDRESS_PATTERN を調整してください。"
        )
        return

    import csv

    out_path = Path(args.out)
    file_exists = out_path.exists()
    with out_path.open("a", newline="", encoding="utf-8") as f:
        writer = csv.writer(f)
        if not file_exists:
            writer.writerow(["ward", "raw_text", "address_guess", "lat", "lon", "geocode_score"])
        for addr in addresses:
            lat, lon, score = geocode(addr, session)
            writer.writerow([args.ward, addr, addr, lat, lon, score])
            print(f"  -> {addr}: lat={lat}, lon={lon}")

    print(f"[INFO] 出力(追記)しました: {out_path}")


if __name__ == "__main__":
    main()
