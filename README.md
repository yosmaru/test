# 新潟市 学区別 総合安全スコアリング プロジェクト

対象5エリア(越後石山・亀田・曽野木・荻川・新津)の住宅候補地について、
学区単位での相対的な安全性(犯罪発生率・不審者事案率・交通事故率・ハザードリスク・
防犯灯密度)を比較するためのパイプライン。

犯罪統計は「区」単位でしか公式集計がないため、学区単位の指標を作るには
① 学区境界のポリゴンデータ と ② 個別事案の緯度経度 を自前で空間結合
(Point-in-Polygon)する必要がある。詳細な設計は `PROJECT_BRIEF.md` の内容に準拠している。

## 重要な注意: このリポジトリで実行した環境について

**このパイプラインを開発したリモート実行環境(Claude Code on the web の
サンドボックス)は、組織のアウトバウンドネットワークポリシーにより、
以下の外部サイトへの直接アクセスがすべてブロックされている**
(egress proxy で 403 応答を確認済み):

- `nlftp.mlit.go.jp` (国土数値情報 - 学区境界データ)
- `map.police.niigata.dsvc.jp` (新潟県警・事件事故マップ)
- `www.gaccom.jp` (ガッコム安全ナビ)
- `msearch.gsi.go.jp` (国土地理院 ジオコーディングAPI)
- `www.pref.niigata.lg.jp` / `www.city.niigata.lg.jp` (区単位統計)

そのため、**このセッションでは実データの取得・実際のスコア算出を行うことができなかった**。
代わりに以下を実施した:

1. Step1〜Step4 すべての処理を行う **実行可能なスクリプト一式** を実装
2. 外部アクセスを必要としない Step3(空間結合・正規化・重み付けスコアリング)
   ロジックについては、合成(ダミー)データで **回帰テストを実施し、正しく動作することを検証済み**
   (`scripts/generate_synthetic_fixtures.py` → `scripts/test_pipeline_synthetic.py`)
3. Step1/Step2 は、外部サイトへアクセス可能な環境(ローカルPC等)で
   実行する必要がある旨をスクリプト内のdocstringに明記

外部アクセス可能な環境でこのリポジトリを clone し、以下の手順で実データを投入すれば、
そのままパイプラインを完走できる設計になっている。

## セットアップ

```bash
pip install -r requirements.txt
playwright install chromium   # Step2-1で使用
```

## 実行手順

### Step 1: 学区境界データの取得

1. https://nlftp.mlit.go.jp/ksj/gml/datalist/KsjTmplt-A27.html から
   新潟県分の小学校区データ(SHAPE形式)をダウンロードし、
   `data/raw/` 以下に展開する
2. 抽出・目視確認用スクリプトを実行:
   ```bash
   python3 scripts/step1_school_district_boundaries.py --raw-dir data/raw
   ```
3. 出力された `data/processed/school_districts_candidates.geojson` と
   コンソールのヒット一覧を **必ず目視確認**し、5エリアと学区名の対応関係を確定する
   (自動抽出だけでは学区名の表記ゆれで漏れる可能性があるため)
4. 確定後、`area` 列(5エリア名のいずれか)を付与して
   `data/processed/school_districts_confirmed.geojson` として保存する

### Step 2: 事案データの収集

- **2-1 新潟県警・事件事故マップ**(SPA):
  ```bash
  python3 scripts/step2a_police_map_capture.py --url https://map.police.niigata.dsvc.jp/ --manual
  ```
  ブラウザの通信を記録し、地図ピンのAPIエンドポイントを特定する。
  特定後、`parse_captured_responses()` を実データ構造に合わせて実装し、
  `data/processed/crime_points.csv` (columns: lat, lon) を出力する。

- **2-2 ガッコム安全ナビ**:
  ```bash
  python3 scripts/step2b_gaccom_geocode.py --ward 東区 --url <対象区ページURL>
  ```
  区ごとに実行し、`data/processed/suspicious_points.csv` へ追記する。
  国土地理院APIで自動ジオコーディングまで行う。

- **2-3 区単位ベースライン(妥当性チェック用)**:
  ```bash
  python3 scripts/step2c_ward_baseline.py --url https://www.pref.niigata.lg.jp/site/kenkei/anzen-ansin-shityouson08.html
  ```
  表がPDF/画像の場合は手動でのテーブル抽出が必要な旨を出力する。

- **交通事故データ・ハザードデータ・防犯灯データ**:
  ブリーフには具体的な取得元の指定がないため未実装。取得後、
  それぞれ `data/processed/traffic_points.csv`,
  `data/processed/hazard_polygons.geojson`,
  `data/processed/streetlight_points.csv` として配置すれば
  Step3でそのまま利用できる(一部が無くても、その指標は自動でスキップされる)。

- **世帯数**(国勢調査・町丁目別を学区単位に集計):
  `data/processed/households.csv` (columns: area, households) として配置する。

### Step 3: 空間結合とスコアリング

```bash
python3 scripts/step3_spatial_join_scoring.py
```

GeoPandasで Point-in-Polygon 結合し、学区ごとの件数を世帯数で正規化して発生率に変換、
5エリア間で0-1に正規化したうえで重み付け合算する。
入力データが揃っていない指標は自動的にスキップされ、警告が表示される。

初期重み(`scripts/config.py` の `WEIGHTS` で調整可能):

| 指標 | 重み |
|---|---|
| 犯罪発生率 | 0.25 |
| 不審者事案率 | 0.15 |
| 交通事故率(通学路周辺) | 0.25 |
| 浸水/土砂災害ハザード | 0.25 |
| 防犯灯密度 | 0.10 |

### Step 4: 出力

Step3の実行により以下が出力される:

- `output/school_district_safety_scores.csv`
- `output/school_district_safety_scores.md`

## 動作検証(合成データによる回帰テスト)

外部データなしでパイプラインのロジック(空間結合・正規化・重み付け)を検証できる:

```bash
python3 scripts/generate_synthetic_fixtures.py
python3 scripts/test_pipeline_synthetic.py
```

`data/sample_synthetic/` と `output/sample_synthetic/` に生成される内容は
**実データではなく検証用のダミーデータ**であり、実際のスコアリングには使用しないこと。

## ディレクトリ構成

```
scripts/
  config.py                          対象エリア・区マッピング・重み定義
  step1_school_district_boundaries.py
  step2a_police_map_capture.py
  step2b_gaccom_geocode.py
  step2c_ward_baseline.py
  step3_spatial_join_scoring.py
  generate_synthetic_fixtures.py     検証用ダミーデータ生成
  test_pipeline_synthetic.py         パイプライン回帰テスト
data/
  raw/                               ダウンロードした生データ置き場
  processed/                         各Stepの中間・最終データ置き場
  sample_synthetic/                  検証用ダミーデータ(実データではない)
output/
  school_district_safety_scores.{csv,md}   最終成果物(実データ投入後に生成)
  sample_synthetic/                  検証用ダミー出力(実データではない)
```

## 注意事項(ブリーフより)

- 個々の事案の詳細(被害者情報等)は集計目的以外に使用・保存しない
- 学区境界は自治体の公式回答ではないため、実際の物件購入時は必ず教育委員会に
  番地単位で確認すること
- スコアの解釈は「絶対的な安全/危険」ではなく「候補地間の相対順位」に留めること
- サンプル数が少ない学区の指標は「参考値」である旨を出力に注記している
