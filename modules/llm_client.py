"""
LLMクライアントモジュール
- OpenAI GPT-4o（現在）
- 将来：ローカルLLM（Ollama/Gemma等）へ切り替え可能な設計
"""

import base64
import json
import os
from pathlib import Path
from typing import Optional

from openai import OpenAI


def _encode_image(image_path: str) -> str:
    """画像ファイルをbase64エンコード"""
    with open(image_path, "rb") as f:
        return base64.b64encode(f.read()).decode("utf-8")


def _encode_image_bytes(image_bytes: bytes) -> str:
    """バイトデータをbase64エンコード"""
    return base64.b64encode(image_bytes).decode("utf-8")


class LLMClient:
    """
    LLMクライアント。
    将来的にローカルLLMへ切り替える場合は、このクラスの実装を差し替えるだけでOK。
    """

    def __init__(self, api_key: Optional[str] = None):
        self.api_key = api_key or os.getenv("OPENAI_API_KEY")
        if not self.api_key:
            raise ValueError("OPENAI_API_KEYが設定されていません。.envファイルを確認してください。")
        self.client = OpenAI(api_key=self.api_key)
        self.model = "gpt-4o"

    def analyze_images_and_description(
        self,
        image_data_list: list[bytes],
        description: str,
        system_prompt: str,
    ) -> str:
        """
        複数の現場写真＋テキスト説明をLLMに渡して解析する。
        Returns: LLMの応答テキスト（JSON文字列を想定）
        """
        content = []

        # テキスト説明を最初に追加
        content.append({
            "type": "text",
            "text": f"【営業担当の説明】\n{description}"
        })

        # 画像を追加（最大30枚）
        for i, img_bytes in enumerate(image_data_list[:30]):
            b64 = _encode_image_bytes(img_bytes)
            content.append({
                "type": "image_url",
                "image_url": {
                    "url": f"data:image/jpeg;base64,{b64}",
                    "detail": "high"
                }
            })

        response = self.client.chat.completions.create(
            model=self.model,
            messages=[
                {"role": "system", "content": system_prompt},
                {"role": "user",   "content": content}
            ],
            max_tokens=4000,
            temperature=0.1,  # 積算は再現性重視で低温度
        )

        return response.choices[0].message.content

    def ask_followup(
        self,
        conversation_history: list[dict],
        new_message: str,
        system_prompt: str,
    ) -> str:
        """
        会話履歴を保ちながら追加質問に答える（不足情報収集フェーズ用）
        """
        messages = [{"role": "system", "content": system_prompt}]
        messages.extend(conversation_history)
        messages.append({"role": "user", "content": new_message})

        response = self.client.chat.completions.create(
            model=self.model,
            messages=messages,
            max_tokens=2000,
            temperature=0.1,
        )

        return response.choices[0].message.content

    def generate_final_estimation(
        self,
        project_data: dict,
        unit_prices: dict,
        system_prompt: str,
    ) -> str:
        """
        収集した案件情報と単価表から最終積算を生成する
        """
        user_message = f"""
以下の案件情報と単価表をもとに、詳細な積算結果をJSON形式で出力してください。

【案件情報】
{json.dumps(project_data, ensure_ascii=False, indent=2)}

【使用単価表】
{json.dumps(unit_prices, ensure_ascii=False, indent=2)}
"""
        response = self.client.chat.completions.create(
            model=self.model,
            messages=[
                {"role": "system", "content": system_prompt},
                {"role": "user",   "content": user_message}
            ],
            max_tokens=4000,
            temperature=0.1,
        )

        return response.choices[0].message.content
