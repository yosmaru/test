"""Claude API 呼び出しの共通処理。"""
import anthropic
from pydantic import BaseModel

MODEL = "claude-opus-5-5"
_client = anthropic.Anthropic()


def ask(system: str, prompt: str, schema: type[BaseModel], effort: str = "medium") -> BaseModel:
    """スキーマ通りの JSON を返させる。安全判定で断られた場合は別モデルへ自動で切り替える。"""
    response = _client.messages.parse(
        model=MODEL,
        max_tokens=16000,
        system=system,
        messages=[{"role": "user", "content": prompt}],
        output_format=schema,
        output_config={"effort": effort},
        extra_headers={"anthropic-beta": "server-side-fallback-2026-07-01"},
        extra_body={"fallbacks": "default"},
    )
    if response.stop_reason == "refusal":
        raise RuntimeError(f"モデルが応答を拒否しました: {response.stop_details}")
    if response.stop_reason == "max_tokens":
        raise RuntimeError("出力が max_tokens で途切れました。入力を分割してください。")
    return response.parsed_output
