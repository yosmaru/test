"""共通設定: 対象エリア、区マッピング、スコア重み、パス定義。"""

from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
DATA_RAW = ROOT / "data" / "raw"
DATA_PROCESSED = ROOT / "data" / "processed"
OUTPUT_DIR = ROOT / "output"

# 対象5エリアと所属区。
# 学区名(school district name)は Step1 で国土数値情報A27データから
# 目視確認のうえ確定させること。ここに列挙する KEYWORDS は
# ポリゴン名の絞り込み用の候補キーワードであり、最終的な学区名の
# 正解ではない(表記ゆれ・複数学区にまたがる可能性があるため)。
AREAS = {
    "越後石山": {
        "ward": "東区",
        "keywords": ["越後石山", "石山"],
    },
    "亀田": {
        "ward": "江南区",
        "keywords": ["亀田"],
    },
    "曽野木": {
        "ward": "江南区",
        "keywords": ["曽野木"],
    },
    "荻川": {
        "ward": "秋葉区",
        "keywords": ["荻川"],
    },
    "新津": {
        "ward": "秋葉区",
        # 新津地区は 新津第一〜第四小学校区 等、複数の学区に
        # またがっている可能性が高い。Step1 で候補を全て列挙し、
        # 目視確認後にこのキーワードリストを確定させること。
        "keywords": ["新津"],
    },
}

WARDS = sorted({info["ward"] for info in AREAS.values()})

# スコアリング重み(初期値。Step3で調整可能)
WEIGHTS = {
    "crime_rate": 0.25,       # 犯罪発生率
    "suspicious_rate": 0.15,  # 不審者事案率
    "traffic_rate": 0.25,     # 交通事故率(通学路周辺)
    "hazard_score": 0.25,     # 浸水/土砂災害ハザード
    "streetlight_density": 0.10,  # 防犯灯密度
}

assert abs(sum(WEIGHTS.values()) - 1.0) < 1e-9, "重みの合計は1.0である必要があります"

# サンプル数が「参考値」とみなされる閾値(この件数未満は注記を付与)
MIN_SAMPLE_SIZE = 5

for d in (DATA_RAW, DATA_PROCESSED, OUTPUT_DIR):
    d.mkdir(parents=True, exist_ok=True)
