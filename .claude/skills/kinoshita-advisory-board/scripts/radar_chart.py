#!/usr/bin/env python3
"""事業計画の完成度スコアからレーダーチャート(SVG)を生成する。

外部ライブラリに依存しない。標準ライブラリのみでSVGを直接書き出す。

使い方:
    python radar_chart.py --scores scores.json --output radar.svg

scores.json の形式は references/scoring.md を参照。
各軸は current（今回・必須）と previous（前回・任意）を持つ。
previous があれば点線で重ね、進捗を可視化する。
"""

import argparse
import json
import math
import sys


def _point(cx, cy, radius, angle_rad):
    return (cx + radius * math.cos(angle_rad), cy + radius * math.sin(angle_rad))


def _polygon_points(cx, cy, max_r, values, n, max_value=100.0):
    pts = []
    for i in range(n):
        # 12時方向を起点に時計回り
        angle = -math.pi / 2 + 2 * math.pi * i / n
        r = max_r * (max(0.0, min(max_value, values[i])) / max_value)
        pts.append(_point(cx, cy, r, angle))
    return pts


def _fmt(pts):
    return " ".join(f"{x:.1f},{y:.1f}" for x, y in pts)


def _esc(s):
    return (
        str(s)
        .replace("&", "&amp;")
        .replace("<", "&lt;")
        .replace(">", "&gt;")
    )


def build_svg(data):
    axes = data.get("axes", [])
    n = len(axes)
    if n < 3:
        raise ValueError("レーダーチャートには最低3軸が必要です")

    title = data.get("title", "")
    names = [a["name"] for a in axes]
    current = [float(a.get("current", 0)) for a in axes]
    has_prev = any("previous" in a and a["previous"] is not None for a in axes)
    previous = [float(a.get("previous", 0) or 0) for a in axes]

    width, height = 720, 640
    cx, cy = width / 2, height / 2 + 10
    max_r = 210.0

    # 日本語ラベルの豆腐化を防ぐため、CJKフォントを明示的に先頭へ置く。
    # 環境により存在するフォントが違うので、代表的な候補を列挙する。
    # 注意: cairosvgは引用符付きのフォント名を解決できないことがあるため、
    # 引用符なしのカンマ区切りで書く。
    font_stack = (
        "IPAPGothic, IPAGothic, Noto Sans CJK JP, IPAexGothic, "
        "Hiragino Sans, Yu Gothic, Meiryo, sans-serif"
    )
    parts = []
    parts.append(
        f'<svg xmlns="http://www.w3.org/2000/svg" width="{width}" height="{height}" '
        f'viewBox="0 0 {width} {height}" font-family="{font_stack}">'
    )
    parts.append(f'<rect width="{width}" height="{height}" fill="#ffffff"/>')

    if title:
        parts.append(
            f'<text x="{cx:.0f}" y="34" text-anchor="middle" font-size="22" '
            f'font-weight="bold" fill="#1a1a1a">{_esc(title)}</text>'
        )

    # 同心の目盛りリング（25/50/75/100）
    for level in (25, 50, 75, 100):
        ring = _polygon_points(cx, cy, max_r, [level] * n, n)
        parts.append(
            f'<polygon points="{_fmt(ring)}" fill="none" stroke="#dddddd" stroke-width="1"/>'
        )

    # 各軸の線とラベル
    for i in range(n):
        angle = -math.pi / 2 + 2 * math.pi * i / n
        ex, ey = _point(cx, cy, max_r, angle)
        parts.append(
            f'<line x1="{cx:.1f}" y1="{cy:.1f}" x2="{ex:.1f}" y2="{ey:.1f}" '
            f'stroke="#cccccc" stroke-width="1"/>'
        )
        lx, ly = _point(cx, cy, max_r + 30, angle)
        # 左右で寄せを変えて重なりを避ける
        if abs(lx - cx) < 8:
            anchor = "middle"
        elif lx < cx:
            anchor = "end"
        else:
            anchor = "start"
        score_txt = f"{current[i]:.0f}"
        parts.append(
            f'<text x="{lx:.1f}" y="{ly:.1f}" text-anchor="{anchor}" '
            f'dominant-baseline="middle" font-size="14" fill="#333333">'
            f'{_esc(names[i])}<tspan font-weight="bold" fill="#0b6"> {score_txt}</tspan></text>'
        )

    # 前回（点線）
    if has_prev:
        prev_pts = _polygon_points(cx, cy, max_r, previous, n)
        parts.append(
            f'<polygon points="{_fmt(prev_pts)}" fill="none" stroke="#f0a020" '
            f'stroke-width="2" stroke-dasharray="6 4"/>'
        )

    # 今回（塗り）
    cur_pts = _polygon_points(cx, cy, max_r, current, n)
    parts.append(
        f'<polygon points="{_fmt(cur_pts)}" fill="#00bb66" fill-opacity="0.25" '
        f'stroke="#00aa55" stroke-width="2.5"/>'
    )
    for x, y in cur_pts:
        parts.append(f'<circle cx="{x:.1f}" cy="{y:.1f}" r="3.5" fill="#00aa55"/>')

    # 総合スコア
    overall = sum(current) / n
    stage = _stage(overall)
    parts.append(
        f'<text x="{cx:.0f}" y="{cy:.0f}" text-anchor="middle" font-size="30" '
        f'font-weight="bold" fill="#00aa55">{overall:.0f}</text>'
    )
    parts.append(
        f'<text x="{cx:.0f}" y="{cy + 22:.0f}" text-anchor="middle" font-size="12" '
        f'fill="#666666">総合 / 100</text>'
    )

    # 凡例
    ly = height - 24
    parts.append(
        f'<rect x="40" y="{ly - 10}" width="16" height="10" fill="#00bb66" '
        f'fill-opacity="0.4" stroke="#00aa55"/>'
    )
    parts.append(
        f'<text x="62" y="{ly}" font-size="13" fill="#333">今回</text>'
    )
    if has_prev:
        prev_overall = sum(previous) / n
        delta = overall - prev_overall
        sign = "+" if delta >= 0 else ""
        parts.append(
            f'<line x1="120" y1="{ly - 5}" x2="150" y2="{ly - 5}" stroke="#f0a020" '
            f'stroke-width="2" stroke-dasharray="6 4"/>'
        )
        parts.append(
            f'<text x="156" y="{ly}" font-size="13" fill="#333">'
            f'前回 {prev_overall:.0f}（{sign}{delta:.0f}）</text>'
        )
    parts.append(
        f'<text x="{width - 40}" y="{ly}" text-anchor="end" font-size="13" '
        f'fill="#666">{_esc(stage)}</text>'
    )

    parts.append("</svg>")
    return "\n".join(parts)


def _stage(overall):
    if overall <= 25:
        return "骨格段階"
    if overall <= 50:
        return "収支検証段階"
    if overall <= 75:
        return "資金調達段階"
    return "計画書化可能段階"


def main(argv=None):
    ap = argparse.ArgumentParser(description="完成度スコアからレーダーチャートSVGを生成")
    ap.add_argument("--scores", required=True, help="スコアJSONのパス")
    ap.add_argument("--output", required=True, help="出力SVGのパス")
    args = ap.parse_args(argv)

    with open(args.scores, encoding="utf-8") as f:
        data = json.load(f)

    svg = build_svg(data)
    with open(args.output, "w", encoding="utf-8") as f:
        f.write(svg)

    overall = sum(float(a.get("current", 0)) for a in data["axes"]) / len(data["axes"])
    print(f"生成: {args.output}（総合 {overall:.0f}点 / {_stage(overall)}）")


if __name__ == "__main__":
    sys.exit(main())
