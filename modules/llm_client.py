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


def _get_api_key() -> Optional[str]:
    try:
        import streamlit as st
        key = st.secrets.get("OPENAI_API_KEY")
        if key:
            return key
    except Exception:
        pass
    return os.getenv("OPENAI_API_KEY")


def _encode_image(image_path: str) -> str:
    with open(image_path, "rb") as f:
        return base64.b64encode(f.read()).decode("utf-8")


def _encode_image_bytes(image_bytes: bytes) -> str:
    return base64.b64encode(image_bytes).decode("utf-8")


class LLMClient:
    def __init__(self, api_key: Optional[str] = None):
        self.api_key = api_key or _get_api_key()
        if not self.api_key:
            raise ValueError(
                "OPENAI_API_KEYが設定されていません。"
                "Streamlit CloudのSecrets、または.envファイル(環境変数)を確認してください。"
            )
        self.client = OpenAI(api_key=self.api_key)
        self.model = "gpt-4o"

    def analyze_images_and_description(
        self,
        image_data_list: list[bytes],
        description: str,
        system_prompt: str,
    ) -> str:
        from core.logger import log_gpt_call, log_error
        content = []
        content.append({
            "type": "text",
            "text": f"【営業担当の説明】\n{description}"
        })
        for i, img_bytes in enumerate(image_data_list[:30]):
            b64 = _encode_image_bytes(img_bytes)
            content.append({
                "type": "image_url",
                "image_url": {
                    "url": f"data:image/jpeg;base64,{b64}",
                    "detail": "high"
                }
            })

        try:
            response = self.client.chat.completions.create(
                model=self.model,
                messages=[
                    {"role": "system", "content": system_prompt},
                    {"role": "user",   "content": content}
                ],
                max_tokens=4000,
                temperature=0.1,
            )
            result_text = response.choices[0].message.content
            usage = response.usage
            log_gpt_call(
                func_name="analyze_images_and_description",
                model=self.model,
                system_prompt=system_prompt,
                user_message_summary=f"[写真{len(image_data_list)}枚] {description[:300]}",
                response_text=result_text,
                tokens_prompt=usage.prompt_tokens if usage else None,
                tokens_completion=usage.completion_tokens if usage else None,
                tokens_total=usage.total_tokens if usage else None,
            )
            return result_text
        except Exception as e:
            log_error("GPTエラー: analyze_images_and_description", e, "GPT")
            raise

    def ask_followup(
        self,
        conversation_history: list[dict],
        new_message: str,
        system_prompt: str,
    ) -> str:
        from core.logger import log_gpt_call, log_error
        messages = [{"role": "system", "content": system_prompt}]
        messages.extend(conversation_history)
        messages.append({"role": "user", "content": new_message})

        try:
            response = self.client.chat.completions.create(
                model=self.model,
                messages=messages,
                max_tokens=2000,
                temperature=0.1,
            )
            result_text = response.choices[0].message.content
            usage = response.usage
            log_gpt_call(
                func_name="ask_followup",
                model=self.model,
                system_prompt=system_prompt,
                user_message_summary=new_message[:400],
                response_text=result_text,
                tokens_prompt=usage.prompt_tokens if usage else None,
                tokens_completion=usage.completion_tokens if usage else None,
                tokens_total=usage.total_tokens if usage else None,
            )
            return result_text
        except Exception as e:
            log_error("GPTエラー: ask_followup", e, "GPT")
            raise

    def generate_final_estimation(
        self,
        project_data: dict,
        unit_prices: dict,
        system_prompt: str,
    ) -> str:
        from core.logger import log_gpt_call, log_error
        user_message = f"""
以下の案件情報と単価表をもとに、詳細な積算結果をJSON形式で出力してください。

【案件情報】
{json.dumps(project_data, ensure_ascii=False, indent=2)}

【使用単価表】
{json.dumps(unit_prices, ensure_ascii=False, indent=2)}
"""
        try:
            response = self.client.chat.completions.create(
                model=self.model,
                messages=[
                    {"role": "system", "content": system_prompt},
                    {"role": "user",   "content": user_message}
                ],
                max_tokens=4000,
                temperature=0.1,
            )
            result_text = response.choices[0].message.content
            usage = response.usage
            log_gpt_call(
                func_name="generate_final_estimation",
                model=self.model,
                system_prompt=system_prompt,
                user_message_summary=f"案件情報キー: {list(project_data.keys())}",
                response_text=result_text,
                tokens_prompt=usage.prompt_tokens if usage else None,
                tokens_completion=usage.completion_tokens if usage else None,
                tokens_total=usage.total_tokens if usage else None,
            )
            return result_text
        except Exception as e:
            log_error("GPTエラー: generate_final_estimation", e, "GPT")
            raise

    def transcribe_audio(self, audio_bytes: bytes, filename: str = "audio.webm") -> str:
        from core.logger import log_whisper, log_error
        import io
        audio_file = io.BytesIO(audio_bytes)
        audio_file.name = filename
        try:
            transcript = self.client.audio.transcriptions.create(
                model="whisper-1",
                file=audio_file,
                language="ja",
            )
            result_text = transcript.text
            log_whisper(
                transcript=result_text,
                audio_size_bytes=len(audio_bytes),
            )
            return result_text
        except Exception as e:
            log_whisper(transcript="", audio_size_bytes=len(audio_bytes), error=str(e))
            log_error("Whisperエラー", e, "WHISPER")
            raise
