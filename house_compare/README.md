# house_compare — 家づくりの考え方を他社と比較する

ある住宅会社の YouTube チャンネルの全動画の文字起こしから「家づくりで重要だと考えているポイント」を抽出し、
それを質問に変換して別の会社にぶつけ、考え方の違いを比較します。

```
 A社チャンネル                                   B社チャンネル / B社へのインタビュー
      │                                                   │
  ① crawl ──► data/A/transcripts/*.txt            ① crawl ──► data/B/transcripts/*.txt
      │                                                   │
  ② extract ─► data/A/key_points.json                     │
      │         （動画ごと抽出 → 会社として集約）           │
  ③ questions ► data/A/questions.json / .md ──────────────┤
      │         （中立的な開いた質問に変換）               │
      │                                    ④ answer ──► data/B/answers_to_A.json
      │                                       （B社の動画から回答を組み立て）
      │                                    または questions.md で実際に B社に聞き、
      │                                       {"Q01": "回答", ...} の JSON にする
      ▼                                                   │
  ⑤ compare ◄─────────────────────────────────────────────┘
      └─► data/A/compare_A_vs_B.md（一致 / 部分的に一致 / 相違 / 比較不能）
```

## セットアップ

```bash
pip install -r requirements.txt
export ANTHROPIC_API_KEY=...   # Claude API のキー
```

## 実行例

```bash
# ① 字幕取得（手動字幕を優先、無ければ自動生成字幕。取得済みはスキップ）
python -m house_compare crawl https://www.youtube.com/@A社のハンドル data/A
python -m house_compare crawl https://www.youtube.com/@B社のハンドル data/B

# ② ③ A社の重要ポイント抽出 → 質問化
python -m house_compare extract data/A --max-points 20
python -m house_compare questions data/A

# ④ B社の動画から回答を作る
python -m house_compare answer data/A/questions.json data/B

# ⑤ 比較レポート（インタビュー回答を使う場合は --answers path/to/answers.json）
python -m house_compare compare data/A data/B
```

動画ごとの LLM 結果は `points_by_video/`・`mentions_A/` にキャッシュされるため、途中で止まっても同じコマンドで再開できます。
比較の向きを逆にしたい場合（B社の重要ポイントを A社にぶつける）は、A と B を入れ替えて ②〜⑤ を実行してください。

## 注意

- 字幕の無い動画はスキップされます（`videos.json` の `has_transcript` で確認できます）。
- 自動生成字幕は誤変換が多いため、抽出結果は人の目で確認してください。
- 取得した文字起こしは分析用です。再配布・公開はしないでください。
