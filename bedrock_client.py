"""Bedrock Converse 호출 모듈.

- 인증: Bedrock API 키(단일 베어러 토큰). 환경변수 AWS_BEARER_TOKEN_BEDROCK 를
  설정하면 boto3(botocore>=1.35)가 자동으로 베어러 인증을 사용합니다.
- 입력: PDF 페이지 PNG 이미지 리스트 → 비전(OCR)으로 판독.
- 출력: 지정한 JSON 스키마 문자열.
"""
import os
import json
import re

import boto3
from botocore.config import Config

# 프롬프트는 prompts.py 로 분리되어 있습니다 (추출 규칙 수정은 그 파일에서).
from prompts import SYSTEM_PROMPT, USER_PROMPT


_client = None


def get_client():
    global _client
    if _client is None:
        region = os.environ.get("AWS_REGION")
        _client = boto3.client(
            "bedrock-runtime",
            region_name=region,
            config=Config(read_timeout=600, connect_timeout=30,
                          retries={"max_attempts": 4, "mode": "adaptive"}),
        )
    return _client


def _extract_json(text):
    """모델 응답 문자열에서 JSON 객체를 견고하게 파싱."""
    if not text:
        return None
    # 코드펜스 제거
    text = re.sub(r"```(?:json)?", "", text).strip()
    # 첫 '{' 부터 마지막 '}' 까지
    start = text.find("{")
    end = text.rfind("}")
    if start == -1 or end == -1 or end < start:
        return None
    snippet = text[start:end + 1]
    try:
        return json.loads(snippet)
    except json.JSONDecodeError:
        # 흔한 오류(후행 콤마) 정리 후 재시도
        cleaned = re.sub(r",\s*([}\]])", r"\1", snippet)
        try:
            return json.loads(cleaned)
        except json.JSONDecodeError:
            return None


def extract_fields_from_images(image_bytes_list):
    """PNG 이미지 바이트 리스트 → 추출 JSON dict (실패 시 None)."""
    model_id = os.environ.get("BEDROCK_MODEL_ID")
    if not model_id:
        raise RuntimeError("환경변수 BEDROCK_MODEL_ID 가 설정되지 않았습니다. .env 를 확인하세요.")

    content = [{"image": {"format": "png", "source": {"bytes": b}}}
               for b in image_bytes_list]
    content.append({"text": USER_PROMPT})

    resp = get_client().converse(
        modelId=model_id,
        system=[{"text": SYSTEM_PROMPT}],
        messages=[{"role": "user", "content": content}],
        inferenceConfig={"maxTokens": 3000, "temperature": 0.0},
    )

    blocks = resp.get("output", {}).get("message", {}).get("content", [])
    text = "".join(b.get("text", "") for b in blocks)
    return _extract_json(text)
