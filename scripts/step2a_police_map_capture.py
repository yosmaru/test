"""
Step 2-1: 新潟県警・事件事故マップ(SPA)のAPIエンドポイント特定と事案取得

https://map.police.niigata.dsvc.jp/ はJavaScriptで地図ピンを描画するSPAのため、
まずヘッドレスブラウザでページを開き、発生する全ネットワークリクエストを記録して
JSON/GeoJSONを返すエンドポイント(=地図ピンのデータソース)を特定する。

注意: このリモート実行環境は組織のアウトバウンドポリシーにより
map.police.niigata.dsvc.jp への直接アクセスがブロックされている
(egress proxyで403)。そのため本スクリプトはこの環境では実行できない。
外部アクセス可能な環境(ローカルPC等)で実行すること。

実行方法:
  playwright install chromium   # 初回のみ(このセッションではchromiumは/opt/pw-browsersに用意済み)
  python3 scripts/step2a_police_map_capture.py --url https://map.police.niigata.dsvc.jp/

動作:
  1. Playwrightでページを開き、全レスポンスを監視
  2. content-typeがjson系、またはURLに api/geojson/data 等を含むレスポンスを記録
  3. data/raw/police_map_captured/ 以下に
       responses_summary.json (URL・ステータス・サイズ・content-type一覧)
       各レスポンス本体(JSON)を個別ファイルで保存
  4. 地図を新潟市エリアまでズーム/パンする操作が必要な場合は
     --manual フラグで headless=False にし、手動操作してから
     Enterキーで記録を終了できるようにしている

取得したJSON/GeoJSONの構造を確認したら、事案の緯度経度・種別・発生日を
抽出する parse_captured_responses() を実データの構造に合わせて実装し、
data/processed/police_incidents.csv (columns: lat, lon, category, date, source)
として出力すること。
"""

import argparse
import asyncio
import json
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))
from config import DATA_RAW  # noqa: E402

CAPTURE_DIR = DATA_RAW / "police_map_captured"

JSON_LIKE_HINTS = ("json", "geojson")
URL_HINTS = ("api", "geojson", "data", "incident", "pin", "marker", "search")


async def capture(url: str, manual: bool, wait_seconds: int):
    try:
        from playwright.async_api import async_playwright
    except ImportError:
        raise SystemExit(
            "playwright がインストールされていません。"
            "`pip install playwright && playwright install chromium` を実行してください。"
        )

    CAPTURE_DIR.mkdir(parents=True, exist_ok=True)
    summary = []
    body_count = 0

    async with async_playwright() as p:
        browser = await p.chromium.launch(headless=not manual)
        context = await browser.new_context()
        page = await context.new_page()

        async def on_response(response):
            nonlocal body_count
            try:
                ctype = response.headers.get("content-type", "")
                url_l = response.url.lower()
                is_json_like = any(h in ctype for h in JSON_LIKE_HINTS)
                is_url_hint = any(h in url_l for h in URL_HINTS)
                if not (is_json_like or is_url_hint):
                    return
                entry = {
                    "url": response.url,
                    "status": response.status,
                    "content_type": ctype,
                }
                try:
                    body = await response.body()
                    entry["size"] = len(body)
                    if is_json_like or is_url_hint:
                        body_count += 1
                        fname = CAPTURE_DIR / f"response_{body_count:04d}.bin"
                        fname.write_bytes(body)
                        entry["saved_as"] = fname.name
                except Exception as e:  # noqa: BLE001
                    entry["body_error"] = str(e)
                summary.append(entry)
                print(f"[CAPTURED] {response.status} {response.url} ({ctype})")
            except Exception as e:  # noqa: BLE001
                print(f"[WARN] response handling failed: {e}")

        page.on("response", lambda r: asyncio.create_task(on_response(r)))

        print(f"[INFO] Navigating to {url}")
        await page.goto(url, wait_until="networkidle", timeout=60000)

        if manual:
            input(
                "[MANUAL] ブラウザ上で地図を対象エリア(東区/江南区/秋葉区)まで"
                "パン・ズームしてください。完了したらこのターミナルでEnterを押してください。"
            )
        else:
            await page.wait_for_timeout(wait_seconds * 1000)

        await browser.close()

    summary_path = CAPTURE_DIR / "responses_summary.json"
    summary_path.write_text(json.dumps(summary, ensure_ascii=False, indent=2), encoding="utf-8")
    print(f"\n[INFO] {len(summary)}件のレスポンスを記録しました -> {summary_path}")
    print(
        "[NEXT STEP] responses_summary.json を確認し、事案データを含む"
        "エンドポイントを特定してください。特定できたら、対応する"
        "response_XXXX.bin の中身を確認し、parse_captured_responses() を実装してください。"
    )


def parse_captured_responses(endpoint_url_substring: str) -> list[dict]:
    """特定したAPIエンドポイントのレスポンス群から事案データを抽出する。

    実際のレスポンス構造を確認してから実装すること(現時点ではプレースホルダー)。
    戻り値の各要素は {"lat": float, "lon": float, "category": str, "date": str} を想定。
    """
    summary_path = CAPTURE_DIR / "responses_summary.json"
    if not summary_path.exists():
        raise SystemExit("先に capture() を実行してレスポンスを記録してください。")
    summary = json.loads(summary_path.read_text(encoding="utf-8"))

    records = []
    for entry in summary:
        if endpoint_url_substring not in entry["url"]:
            continue
        saved = entry.get("saved_as")
        if not saved:
            continue
        raw = (CAPTURE_DIR / saved).read_bytes()
        try:
            data = json.loads(raw)
        except json.JSONDecodeError:
            continue
        # TODO: 実データ構造に合わせてパースを実装する。
        # 例(GeoJSONの場合):
        # for feature in data.get("features", []):
        #     lon, lat = feature["geometry"]["coordinates"]
        #     props = feature.get("properties", {})
        #     records.append({
        #         "lat": lat, "lon": lon,
        #         "category": props.get("category"),
        #         "date": props.get("date"),
        #     })
        print(f"[TODO] {saved} の構造を確認してパース処理を実装してください: "
              f"{str(data)[:200]}")

    return records


if __name__ == "__main__":
    parser = argparse.ArgumentParser()
    parser.add_argument("--url", default="https://map.police.niigata.dsvc.jp/")
    parser.add_argument("--manual", action="store_true", help="手動でブラウザ操作しながら記録する")
    parser.add_argument("--wait-seconds", type=int, default=15)
    args = parser.parse_args()
    asyncio.run(capture(args.url, args.manual, args.wait_seconds))
