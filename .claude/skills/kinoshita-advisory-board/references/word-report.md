# Word協議録と宿題ドリルの往復フロー

協議録の標準の納品形態は、チャット出力ではなくWordファイル(.docx)である。ファイルを送る手段がある環境（SendUserFile等）では、協議録は必ずWordで出力する。チャットには要点のみを短く添える。ファイル送付手段がない環境でだけ、チャットにMarkdownで全文を出す。

Wordにする理由は体裁ではない。宿題を「読むもの」から「書き込むもの」に変えるためである。協議録の後半に記入式の宿題ドリル表を置き、事業者が現場で調べた結果を書き込み、そのファイルをそのまま次回アップロードする。この往復が伴走の実体になる。

## 往復フローの全体像

1. 協議（初回診断または伴走レビュー）を行い、協議録Wordを生成して渡す
2. 事業者が宿題ドリルの記入欄を現場の数字で埋める（全部埋まらなくてよい）
3. 事業者が記入済みWordをアップロードする
4. アップロードされたWordを読み、(a)ドリルの記入内容 (b)文書内の前回スコア表 (c)前回リスク登録簿 を抽出する
5. それを宿題の提出として伴走レビューを行い、スコア再採点（前回比つきレーダー）・リスク状態更新・次の宿題ドリルを組み込んだ新しいWordを返す

重要: 協議録Wordには必ず完成度スコア表とリスク登録簿を含める。次回セッションが別の会話になっても、アップロードされたWord自体が前回状態のすべてを運ぶ。Wordが伴走の状態キャリアである。会話をまたいで記憶が残らない環境でも、このループは壊れない。

## 生成手順

1. 協議の内容（前提確認〜座長総評〜宿題）を通常どおり組み立てる
2. 完成度スコアを採点し、scores.json を作る（`references/scoring.md`）
3. レーダーチャートを生成する:
   - `python scripts/radar_chart.py --scores scores.json --output radar.svg`
   - PNGに変換する。cairosvgがあれば `python -c "import cairosvg; cairosvg.svg2png(url='radar.svg', write_to='radar.png', output_width=1440, output_height=1280)"`。なければ `pip install cairosvg`。それも不可なら rsvg-convert / inkscape / ImageMagick を試し、全滅ならPNGなしで進める（スコア表だけでも成立する）
   - 必須: 生成したPNGは、Wordに埋め込む前に必ず一度開いて目視する。日本語ラベルが豆腐（□）になっていたらCJKフォントの問題であり、そのまま埋め込んではならない。radar_chart.py はIPAゴシック等を明示指定済みだが、環境によりフォントが違う
   - 必須: radar_chart.py や scores.json を修正したら、必ずSVGとPNGの両方を再生成してからWordを組む。古いPNGが残っているとWordに豆腐版が埋め込まれる事故が起きる（実際に起きた失敗である）
4. report.json を作り、`python scripts/build_word_report.py --report report.json --output 協議録_案件名_第N回.docx` を実行する
   - python-docxがなければ `pip install python-docx`
   - それも不可でdocx-js（npm）が使える環境なら、下のreport.jsonの構成をdocx-jsで同じ形に組む
5. 生成したdocxは必ず一度検品する。LibreOfficeが使えれば `soffice --headless --convert-to pdf` → 画像化して目視する。LibreOfficeが壊れている・writerフィルタがない環境では、代替として (a)docxスキルの validate.py によるXSD検証 (b)`pip install mammoth` でHTML化し、表の数・画像の有無・主要セクション見出し・記入欄の数をプログラムで確認する。検品ゼロで渡さない
6. ファイルを渡すとき、チャットには座長総評の要点と「ドリルを埋めて再アップロードすれば伴走が続く」ことだけを短く書く

## report.json のスキーマ

```json
{
  "title": "伴走型稼ぐまちづくりアドバイザリーボード 協議録（第1回）",
  "case_name": "案件名",
  "session": 1,
  "date": "YYYY-MM-DD",
  "radar_png": "radar.png",
  "overall": {"score": 18, "stage": "骨格段階", "delta": null},
  "sections": [
    {"heading": "前提確認", "level": 1, "paragraphs": ["…", "…"]},
    {"heading": "各視点からの協議", "level": 1, "paragraphs": []},
    {"heading": "マーケティング（佐々木恭介）", "level": 2, "paragraphs": ["…"], "bullets": ["問い…", "次の一手…"], "score_line": "（佐々木の評点：顧客・需要 15点／実在の顧客の裏付けがゼロ。需要実証レベル0）"}
  ],
  "score_table": [{"axis": "顧客・需要", "score": 15, "basis": "…"}],
  "risk_table": [{"id": "R1", "risk": "…", "severity": "致命的", "status": "未対応", "action": "…"}],
  "homework": [
    {"no": 1, "axis": "顧客・需要", "title": "宿題の内容（誰に会って何を聞くか）", "how": "具体的なやり方"}
  ],
  "premise_questions": ["回答してほしい前提情報の質問", "…"]
}
```

- sections はコンサル型のサマリー先行順で並べる（`SKILL.md` の協議録テンプレート）。エグゼクティブサマリー → 重要論点3点 → 領域別評価サマリー（table）→ scorecardマーカー → 論点の衝突 → 成功に向けた重要ポイント → いまの事業の完成度 → riskマーカー → 領域別詳細分析（各専門家）→ homeworkマーカー → 前提確認 → premiseマーカー
- 完成度スコア・リスク・宿題ドリル・前提回答シートは `{"type": "scorecard"}` `{"type": "risk"}` `{"type": "homework"}` `{"type": "premise"}` のマーカー section を sections の任意位置に置くと、そこで描画される。マーカーを省くと従来どおり末尾にまとまる（後方互換）。中身は従来どおり score_table / risk_table / homework / premise_questions フィールドから取る
- 領域別評価サマリーは通常の table 付き section で組む（header: ["領域","担当","評点","要点"]）。各専門家の詳細セクションは後半の「領域別詳細分析」に置く
- 各専門家の詳細セクションには `score_line` を付ける。担当軸の評点を一行で書くと、その末尾に淡い強調ボックスで表示される。この個別評点の集計が、領域別評価サマリー表と完成度スコア（レーダー）に一致する
- delta は2回目以降のみ（前回総合点との差）。radar.svgの生成時も scores.json に previous を入れて前回比を重ねる
- homework の fields は省略すると標準の記入欄（実施日／やったこと・会った相手／わかった数字・事実／出典・裏付け／詰まった点）になる。宿題の性質に応じて差し替えてよい（例: 競合調査なら「施設名」「客単価」「品揃えの特徴」の列）

## 記入済みWordの読み方（ステップ4の実務）

アップロードされた .docx は次のいずれかで読む。

- `pandoc -t markdown 記入済み.docx` が最速。表がMarkdownテーブルで出る
- pandocがなければ unzip して `word/document.xml` を読む（docxはZIP）。`<w:t>` のテキストを拾う

抽出するもの:

1. 宿題ドリルの記入欄。「（ここに記入してください）」のまま残っている欄は未実施と判定する。書き換えられている欄が提出物である
2. 前提情報回答シートの回答
3. 文書内の完成度スコア表（前回の点数として scores.json の previous に入れる）
4. 文書内のリスク登録簿（前回状態として引き継ぎ、記入内容に応じて 未対応→対応中→解消 を動かす）

伴走レビューの原則はSKILL.md本文どおり。埋まった宿題は先に認め、数字の中身を協議し、未記入の宿題は理由を問う。記入が感想レベル（「良さそうだった」等）の場合は、それを受け取ったうえで「数字と固有名詞で書き直す」ことを次回宿題に含める。

## 事業計画書のWord出力

総合スコア80点超で「事業計画書にまとめて」と依頼されたら、同じ build_word_report.py で生成する。report.json に `"doc_type": "plan"` を指定すると、協議録用の「使い方」ブロックと末尾の再アップロード案内が自動で省かれる。sections には `references/business-plan-template.md` の11章＋付録＋未確定事項を入れ、homework と premise_questions は空にする。収支計画・投資内訳・スケジュールの表は、各 section の `table` フィールド（`{"header": [...], "rows": [[...]], "widths": [...]}`）で組める。さらに精緻な収支表が必要な場合はxlsxスキルで別ファイルにしてもよい。
