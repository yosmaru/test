# house_compare — A社の家づくりの考え方を B社にぶつけて比べる

施主が使うためのツールです。A社の YouTube チャンネルの全動画の文字起こしから「家づくりで重要だと考えているポイント」を抽出し、
それを質問票にして B社との打ち合わせで直接聞き、回答を比べます。

```
 A社チャンネル
     │
 ① crawl ────► data/A/transcripts/*.txt      全動画の字幕（手動字幕を優先、無ければ自動生成字幕）
     │
 ② extract ──► data/A/key_points.json        動画ごとに主張を拾い、会社としての重要ポイントに集約
     │
 ③ questions ─► data/A/questions.md          B社に持っていく質問票（A社の考えは載せない）
     │          data/A/questions_notes.md    手元用メモ（深掘り質問・聞きどころ・A社の考え）
     │
     │   ┌──────────────── 打ち合わせ ────────────────┐
     └──►│ questions.md を印刷 / 画面で見ながら B社に聞き、│
         │ 「回答:」の下に書き込む                       │
         └────────────────────┬─────────────────────────┘
                              ▼
 ④ compare ──► data/A/compare_A_vs_B社.md     一致 / 部分的に一致 / 相違 / 比較不能
                                              ＋注意したい点・次回聞くこと
```

## セットアップ

```bash
pip install -r requirements.txt
export ANTHROPIC_API_KEY=...   # Claude API のキー
```

## 実行例（もみの木ハウス新潟を A社にする場合）

```bash
python -m house_compare crawl https://www.youtube.com/@mominoki_house_niigata data/mominoki
python -m house_compare extract data/mominoki --max-points 20
python -m house_compare questions data/mominoki

# 打ち合わせ後、記入済みの質問票を保存して比較
cp data/mominoki/questions.md data/mominoki/answers_B社.md   # ここに回答を書き込む
python -m house_compare compare data/mominoki data/mominoki/answers_B社.md --name B社
```

- 動画本数が多い場合は `crawl --limit 30` のように新しい順に絞って試せます。
- 動画ごとの分析結果は `points_by_video/` にキャッシュされるため、途中で止まっても同じコマンドで再開できます。
- 複数社に聞く場合は、同じ質問票で回答ファイルを会社ごとに作り、`--name` を変えて compare を実行してください。
- B社にも YouTube チャンネルがある場合は、`answer` コマンドで B社の動画から回答を推定することもできます。

## 注意

- 字幕の無い動画はスキップされます（`videos.json` の `has_transcript` で確認できます）。
- 自動生成字幕は誤変換が多いため、`key_points.json` は一度目を通し、違和感のあるポイントは削ってから questions を実行してください。
- 取得した文字起こしは個人の検討用です。再配布・公開はしないでください。
