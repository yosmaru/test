"""文字起こし → 重要ポイント → 質問 → 他社の回答 → 比較レポート。"""
import json
import sys
from pathlib import Path

from pydantic import BaseModel, Field

from .llm import ask

SYSTEM = (
    "あなたは住宅業界に詳しいアナリストです。工務店・ハウスメーカーの YouTube 動画の文字起こしを読み、"
    "その会社が家づくりで何を重視しているかを客観的に整理します。"
    "文字起こしは自動生成で誤字が多いので、文脈から意味を補って読んでください。"
    "文字起こしに書かれていないことを推測で付け加えないでください。"
)


# ---------- スキーマ ----------

class Point(BaseModel):
    theme: str = Field(description="テーマ（例: 断熱・気密、耐震、間取り、コスト、土地、アフター、会社選び）")
    claim: str = Field(description="その会社の主張・こだわりを1文で")
    reason: str = Field(description="なぜそう考えるのか（動画内で語られた理由）")
    evidence: str = Field(description="根拠となる発言の要約（40字程度。長い引用はしない）")


class VideoPoints(BaseModel):
    points: list[Point]


class KeyPoint(BaseModel):
    id: str = Field(description="P01 形式の連番")
    theme: str
    claim: str
    reason: str
    video_ids: list[str] = Field(description="この主張が出てくる動画 ID")


class KeyPoints(BaseModel):
    summary: str = Field(description="この会社の家づくり哲学を3〜5文で")
    key_points: list[KeyPoint]


class Question(BaseModel):
    id: str = Field(description="Q01 形式の連番")
    point_id: str = Field(description="元になった重要ポイントの ID")
    theme: str
    question: str = Field(description="他社にそのまま聞ける中立的な質問文")
    why_ask: str = Field(description="この質問で何の違いが見えるか")


class Questions(BaseModel):
    questions: list[Question]


class Mention(BaseModel):
    question_id: str
    stance: str = Field(description="その質問に対するこの会社の考え")
    evidence: str = Field(description="根拠となる発言の要約（40字程度）")


class VideoMentions(BaseModel):
    mentions: list[Mention]


class Answer(BaseModel):
    question_id: str
    mentioned: bool = Field(description="動画内で触れられていれば true")
    answer: str = Field(description="この会社の回答の要約。触れていなければ空文字")
    video_ids: list[str]


class Answers(BaseModel):
    answers: list[Answer]


class Comparison(BaseModel):
    question_id: str
    verdict: str = Field(description="一致 / 部分的に一致 / 相違 / 比較不能 のいずれか")
    company_a: str = Field(description="A社の考え（短く）")
    company_b: str = Field(description="B社の考え（短く）")
    difference: str = Field(description="違いのポイントと、施主にとっての意味")


class Report(BaseModel):
    overview: str = Field(description="両社の考え方の違いの総括（5文程度）")
    comparisons: list[Comparison]
    follow_up_questions: list[str] = Field(description="違いをさらに掘り下げるための追加質問")


# ---------- 入出力ユーティリティ ----------

def _load_transcripts(company_dir: Path) -> dict[str, str]:
    files = sorted((company_dir / "transcripts").glob("*.txt"))
    if not files:
        sys.exit(f"{company_dir}/transcripts に文字起こしがありません。先に crawl を実行してください。")
    return {f.stem: f.read_text(encoding="utf-8") for f in files}


def _titles(company_dir: Path) -> dict[str, str]:
    meta = company_dir / "videos.json"
    if not meta.exists():
        return {}
    return {v["id"]: v["title"] for v in json.loads(meta.read_text(encoding="utf-8"))["videos"]}


def _save(path: Path, model: BaseModel) -> None:
    path.write_text(model.model_dump_json(indent=2), encoding="utf-8")


def _per_video(company_dir: Path, cache_name: str, schema, build_prompt) -> dict[str, BaseModel]:
    """動画ごとに LLM を呼び、結果を cache_name/<id>.json に保存する（中断しても再開できる）。"""
    cache = company_dir / cache_name
    cache.mkdir(exist_ok=True)
    titles = _titles(company_dir)
    transcripts = _load_transcripts(company_dir)
    results = {}
    for i, (vid, text) in enumerate(transcripts.items(), 1):
        path = cache / f"{vid}.json"
        if path.exists():
            results[vid] = schema.model_validate_json(path.read_text(encoding="utf-8"))
            continue
        print(f"[{i}/{len(transcripts)}] {titles.get(vid, vid)}", file=sys.stderr)
        result = ask(SYSTEM, build_prompt(vid, titles.get(vid, ""), text), schema, effort="low")
        _save(path, result)
        results[vid] = result
    return results


# ---------- 各ステップ ----------

def extract(company_dir: Path, max_points: int = 20) -> KeyPoints:
    """全動画から主張を拾い、会社としての重要ポイントに集約する。"""
    def prompt(vid, title, text):
        return (
            f"動画タイトル: {title}\n動画ID: {vid}\n\n<transcript>\n{text}\n</transcript>\n\n"
            "この動画で語られている、この会社の家づくりに関する主張・こだわり・判断基準を抜き出してください。"
            "商品の宣伝や雑談ではなく、施主へのアドバイスや会社の方針として語られているものに絞ってください。"
            "該当がなければ空のリストを返してください。"
        )

    per_video = _per_video(company_dir, "points_by_video", VideoPoints, prompt)
    lines = [
        f"- [{vid}] ({p.theme}) {p.claim} ／理由: {p.reason}"
        for vid, r in per_video.items() for p in r.points
    ]
    result = ask(
        SYSTEM,
        "以下は、ある会社の全動画から抜き出した主張の一覧です。\n\n" + "\n".join(lines) + "\n\n"
        f"重複をまとめ、この会社が家づくりで特に重要だと考えているポイントを最大 {max_points} 個に集約してください。"
        "多くの動画で繰り返し語られているもの、他社との差別化として強調しているものを優先し、重要度の高い順に並べてください。",
        KeyPoints,
        effort="high",
    )
    _save(company_dir / "key_points.json", result)
    return result


def make_questions(company_dir: Path) -> Questions:
    """重要ポイントを、他社に投げられる中立的な質問に変換する。"""
    kp = KeyPoints.model_validate_json((company_dir / "key_points.json").read_text(encoding="utf-8"))
    result = ask(
        SYSTEM,
        "以下はA社が家づくりで重要だと考えているポイントです。\n\n"
        + "\n".join(f"- {p.id} ({p.theme}) {p.claim} ／理由: {p.reason}" for p in kp.key_points)
        + "\n\n各ポイントについて、他の住宅会社にそのまま投げかけられる質問を1つずつ作ってください。条件:\n"
        "- A社の答えを前提にした誘導質問にしない（例: ×「高気密が大事ですよね？」 ○「気密性能はどの程度重視し、どう担保していますか？」）\n"
        "- はい/いいえで終わらず、考え方と理由が引き出せる開いた質問にする\n"
        "- A社の社名や独自用語は使わない",
        Questions,
    )
    _save(company_dir / "questions.json", result)
    md = ["# 家づくりの考え方に関する質問票", ""]
    md += [f"## {q.id}（{q.theme}）\n\n{q.question}\n\n回答:\n\n" for q in result.questions]
    (company_dir / "questions.md").write_text("\n".join(md), encoding="utf-8")
    return result


def answer_from_videos(questions_path: Path, company_dir: Path) -> Answers:
    """B社の動画の文字起こしから、各質問への B社の回答を組み立てる。"""
    qs = Questions.model_validate_json(questions_path.read_text(encoding="utf-8"))
    q_text = "\n".join(f"- {q.id}: {q.question}" for q in qs.questions)

    def prompt(vid, title, text):
        return (
            f"動画タイトル: {title}\n動画ID: {vid}\n\n<transcript>\n{text}\n</transcript>\n\n"
            f"質問リスト:\n{q_text}\n\n"
            "この動画の中で、上の質問のどれかに答えている発言があれば、質問ごとにこの会社の考えを抜き出してください。"
            "触れていない質問は含めないでください。"
        )

    per_video = _per_video(company_dir, f"mentions_{questions_path.parent.name}", VideoMentions, prompt)
    lines = [
        f"- {m.question_id} [{vid}] {m.stance}"
        for vid, r in per_video.items() for m in r.mentions
    ]
    result = ask(
        SYSTEM,
        f"質問リスト:\n{q_text}\n\nある会社の動画から集めた、各質問に関連する発言:\n"
        + ("\n".join(lines) or "（なし）")
        + "\n\nすべての質問について、この会社の回答を要約してください。発言が無い質問は mentioned=false にしてください。",
        Answers,
        effort="high",
    )
    _save(company_dir / f"answers_to_{questions_path.parent.name}.json", result)
    return result


def compare(a_dir: Path, b_dir: Path, b_answers: Path | None = None) -> Path:
    """A社の重要ポイントと B社の回答を突き合わせ、比較レポート（Markdown）を出力する。"""
    kp = KeyPoints.model_validate_json((a_dir / "key_points.json").read_text(encoding="utf-8"))
    qs = Questions.model_validate_json((a_dir / "questions.json").read_text(encoding="utf-8"))
    b_answers = b_answers or b_dir / f"answers_to_{a_dir.name}.json"
    raw = json.loads(b_answers.read_text(encoding="utf-8"))
    # 動画から作った Answers 形式のほか、インタビュー結果を {"Q01": "回答", ...} で渡すこともできる
    answers = raw["answers"] if "answers" in raw else [
        {"question_id": k, "mentioned": bool(v), "answer": v} for k, v in raw.items()
    ]
    points = {p.id: p for p in kp.key_points}
    ans = {a["question_id"]: a for a in answers}
    rows = []
    for q in qs.questions:
        p = points.get(q.point_id)
        a = ans.get(q.id, {})
        rows.append(
            f"- {q.id} 質問: {q.question}\n"
            f"  A社: {p.claim + ' ／理由: ' + p.reason if p else '不明'}\n"
            f"  B社: {a.get('answer') if a.get('mentioned') else '（言及なし）'}"
        )
    report = ask(
        SYSTEM,
        f"A社とB社の家づくりの考え方を比較します。A社の総括: {kp.summary}\n\n" + "\n".join(rows) + "\n\n"
        "質問ごとに両社の考えを比べ、違いと、それが施主にとって何を意味するかを整理してください。"
        "B社が言及していない質問は「比較不能」とし、言及していないこと自体が示唆するもの（重視度の違いなど）があれば difference に書いてください。",
        Report,
        effort="high",
    )
    out = a_dir / f"compare_{a_dir.name}_vs_{b_dir.name}.md"
    md = [f"# {a_dir.name} × {b_dir.name} 家づくりの考え方比較", "", report.overview, "",
          "| # | 判定 | " + a_dir.name + " | " + b_dir.name + " | 違い |", "|---|---|---|---|---|"]
    md += [f"| {c.question_id} | {c.verdict} | {c.company_a} | {c.company_b} | {c.difference} |"
           for c in report.comparisons]
    md += ["", "## 追加で聞いてみたい質問", ""] + [f"- {f}" for f in report.follow_up_questions]
    out.write_text("\n".join(md), encoding="utf-8")
    return out
