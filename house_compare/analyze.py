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
    question: str = Field(description="施主が打ち合わせでそのまま聞ける中立的な質問文")
    follow_ups: list[str] = Field(description="答えが曖昧だったときの深掘り質問（1〜2個）")
    listen_for: str = Field(description="回答を聞くときに注目すべき点（数値・根拠・実例など）")


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
    watch_outs: list[str] = Field(description="施主として注意したい点（回答が曖昧だった項目、根拠が示されなかった項目など）")
    follow_up_questions: list[str] = Field(description="次の打ち合わせで追加で聞くべき質問")


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
    """重要ポイントを、施主が他社との打ち合わせで聞ける中立的な質問に変換する。"""
    kp = KeyPoints.model_validate_json((company_dir / "key_points.json").read_text(encoding="utf-8"))
    result = ask(
        SYSTEM,
        "以下はA社が家づくりで重要だと考えているポイントです。\n\n"
        + "\n".join(f"- {p.id} ({p.theme}) {p.claim} ／理由: {p.reason}" for p in kp.key_points)
        + "\n\nこれから家を建てる施主が、別の住宅会社（B社）との打ち合わせでそのまま聞ける質問を、ポイントごとに1つずつ作ってください。条件:\n"
        "- A社の答えを前提にした誘導質問にしない（例: ×「高気密が大事ですよね？」 ○「気密性能はどの程度重視していて、どう確認していますか？」）\n"
        "- はい/いいえで終わらず、考え方と理由が引き出せる開いた質問にする\n"
        "- A社の社名や独自用語は使わず、専門知識のない施主でも口に出しやすい言葉にする\n"
        "- 営業トークでかわされたときのための深掘り質問と、回答で注目すべき点も添える",
        Questions,
    )
    _save(company_dir / "questions.json", result)
    points = {p.id: p for p in kp.key_points}

    # B社との打ち合わせに持っていく質問票（A社の考えは載せない）
    sheet = ["# 家づくりについての質問票", "", "打ち合わせ中に聞いた回答を「回答:」の下に書き込んでください。", ""]
    for q in result.questions:
        sheet += [f"## {q.id}（{q.theme}）", "", q.question, "", "回答:", "", ""]
    (company_dir / "questions.md").write_text("\n".join(sheet), encoding="utf-8")

    # 施主の手元用メモ（A社の考え・深掘り・聞きどころ）
    notes = ["# 質問票・手元用メモ（B社には見せない）", ""]
    for q in result.questions:
        p = points.get(q.point_id)
        notes += [f"## {q.id}（{q.theme}）", "", f"**質問:** {q.question}", ""]
        notes += [f"- 深掘り: {f}" for f in q.follow_ups]
        notes += [f"- 聞きどころ: {q.listen_for}"]
        if p:
            notes += [f"- A社の考え: {p.claim}（理由: {p.reason}）"]
        notes += [""]
    (company_dir / "questions_notes.md").write_text("\n".join(notes), encoding="utf-8")
    return result


def parse_answer_sheet(path: Path) -> dict[str, str]:
    """記入済みの questions.md から {"Q01": "回答", ...} を取り出す。"""
    answers: dict[str, str] = {}
    current, buf, in_answer = None, [], False
    for line in path.read_text(encoding="utf-8").splitlines() + ["## END"]:
        if line.startswith("## "):
            if current:
                answers[current] = "\n".join(buf).strip()
            current, buf, in_answer = line[3:].split("（")[0].strip(), [], False
        elif line.strip().startswith("回答"):
            in_answer = True
            rest = line.split(":", 1)[-1].split("：", 1)[-1].strip()
            if rest:
                buf.append(rest)
        elif in_answer:
            buf.append(line)
    return answers


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


def compare(a_dir: Path, answers_path: Path, b_name: str = "B社") -> Path:
    """A社の重要ポイントと B社の回答を突き合わせ、施主向けの比較レポート（Markdown）を出力する。

    answers_path は記入済みの questions.md、{"Q01": "回答", ...} の JSON、
    または answer コマンドの出力（answers_to_*.json）のいずれか。
    """
    kp = KeyPoints.model_validate_json((a_dir / "key_points.json").read_text(encoding="utf-8"))
    qs = Questions.model_validate_json((a_dir / "questions.json").read_text(encoding="utf-8"))
    if answers_path.suffix == ".md":
        ans = parse_answer_sheet(answers_path)
    else:
        raw = json.loads(answers_path.read_text(encoding="utf-8"))
        ans = ({a["question_id"]: a["answer"] if a["mentioned"] else "" for a in raw["answers"]}
               if "answers" in raw else raw)
    points = {p.id: p for p in kp.key_points}
    rows = []
    for q in qs.questions:
        p = points.get(q.point_id)
        rows.append(
            f"- {q.id} 質問: {q.question}\n"
            f"  聞きどころ: {q.listen_for}\n"
            f"  A社: {p.claim + ' ／理由: ' + p.reason if p else '不明'}\n"
            f"  B社の回答: {ans.get(q.id) or '（未回答）'}"
        )
    report = ask(
        SYSTEM,
        f"家を建てようとしている施主が、A社の考え方をもとに作った質問を {b_name} にぶつけました。"
        f"A社の総括: {kp.summary}\n\n" + "\n".join(rows) + "\n\n"
        "施主が会社を選ぶ判断材料になるよう、質問ごとに両社の考えを比べ、違いとそれが施主の住み心地・費用・リスクに"
        "どう影響しうるかを整理してください。どちらが正しいかを断定せず、施主が判断するための材料を示してください。"
        "未回答の質問は「比較不能」としてください。回答が抽象的で根拠や数値が無いものは watch_outs に挙げてください。",
        Report,
        effort="high",
    )
    out = a_dir / f"compare_{a_dir.name}_vs_{b_name}.md"
    md = [f"# {a_dir.name} × {b_name} 家づくりの考え方比較", "", report.overview, "",
          f"| # | 判定 | {a_dir.name} | {b_name} | 違いと施主への影響 |", "|---|---|---|---|---|"]
    md += [f"| {c.question_id} | {c.verdict} | {c.company_a} | {c.company_b} | {c.difference} |"
           for c in report.comparisons]
    md += ["", "## 注意したい点", ""] + [f"- {w}" for w in report.watch_outs]
    md += ["", "## 次の打ち合わせで聞きたいこと", ""] + [f"- {f}" for f in report.follow_up_questions]
    out.write_text("\n".join(md), encoding="utf-8")
    return out
