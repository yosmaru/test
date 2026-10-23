"""使い方は README.md を参照。"""
import argparse
from pathlib import Path


def main() -> None:
    parser = argparse.ArgumentParser(prog="python -m house_compare")
    sub = parser.add_subparsers(dest="cmd", required=True)

    p = sub.add_parser("crawl", help="チャンネルの全動画の字幕を取得")
    p.add_argument("channel_url")
    p.add_argument("company_dir", type=Path)
    p.add_argument("--limit", type=int, help="新しい順に何本まで取得するか")

    p = sub.add_parser("extract", help="重要ポイントを抽出")
    p.add_argument("company_dir", type=Path)
    p.add_argument("--max-points", type=int, default=20)

    p = sub.add_parser("questions", help="重要ポイントを質問に変換")
    p.add_argument("company_dir", type=Path)

    p = sub.add_parser("answer", help="別の会社の動画から質問への回答を作る")
    p.add_argument("questions_json", type=Path, help="A社の questions.json")
    p.add_argument("other_company_dir", type=Path)

    p = sub.add_parser("compare", help="比較レポートを作る")
    p.add_argument("company_a_dir", type=Path)
    p.add_argument("company_b_dir", type=Path)
    p.add_argument("--answers", type=Path, help="インタビュー等で集めた B社の回答 JSON")

    args = parser.parse_args()
    if args.cmd == "crawl":
        from .crawl import crawl
        crawl(args.channel_url, args.company_dir, args.limit)
        return

    from . import analyze
    if args.cmd == "extract":
        print(analyze.extract(args.company_dir, args.max_points).model_dump_json(indent=2))
    elif args.cmd == "questions":
        for q in analyze.make_questions(args.company_dir).questions:
            print(f"{q.id} {q.question}")
    elif args.cmd == "answer":
        analyze.answer_from_videos(args.questions_json, args.other_company_dir)
    elif args.cmd == "compare":
        print(analyze.compare(args.company_a_dir, args.company_b_dir, args.answers))


if __name__ == "__main__":
    main()
