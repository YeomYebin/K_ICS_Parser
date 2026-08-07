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


SYSTEM_PROMPT = (
    "당신은 한국 보험회사(생명·손해보험)의 정기 경영공시 PDF에서 "
    "K-ICS(지급여력) 관련 수치를 정확히 추출하는 전문가입니다. "
    "제공된 페이지 이미지를 꼼꼼히 OCR 하여 숫자를 정확히 읽으세요. "
    "반드시 지정된 JSON 객체 하나만 출력하고, 설명 문장이나 코드펜스(```)는 절대 쓰지 마세요."
)

USER_PROMPT = (
    "아래 페이지 이미지들에서 다음 항목을 추출해 JSON 객체로만 출력하세요. "
    "찾을 수 없는 값은 null 로 두세요.\n\n"
    "- company: 회사 정식 명칭 (문서에 표기된 대로)\n"
    "- quarter: 공시 기준 분기를 \"'YY.MM월\" 형식 문자열로. "
    "예) 2026년 1분기 → \"'26.03월\", 2025년 4분기 → \"'25.12월\", "
    "2025년 3분기 → \"'25.09월\", 2025년 2분기 → \"'25.06월\"\n"
    "- kics_ratio: K-ICS 비율(지급여력비율), 숫자(%) 소수 첫째자리. "
    "경과조치 적용 후(대표로 공시되는) 비율 기준.\n"
    "- available_capital: 가용자본 = \"가. 지급여력금액\" 항목의 금액\n"
    "- required_capital: 요구자본 = \"나. 지급여력기준금액 (I - II + III)\" 로 표기된 "
    "항목의 금액. 반드시 이 '(I - II + III)' 수식이 붙은 '나. 지급여력기준금액' 값을 사용하세요. "
    "하위 구성항목(I 기본요구자본, II 법인세조정금액, III 기타 등)이나 다른 표의 "
    "지급여력기준금액과 혼동하지 마세요.\n"
    "- tier1_capital: [경과조치 적용전 지급여력비율 세부] 표의 "
    "\"가. 지급여력금액\" 하위 항목인 \"기본자본\" 의 금액\n"
    "- tier2_capital: [경과조치 적용전 지급여력비율 세부] 표의 "
    "\"가. 지급여력금액\" 하위 항목인 \"보완자본\" 의 금액\n"
    "- unit: 위 자본 금액들의 단위. 표 제목의 (단위: ...) 표기를 보고 "
    "\"억원\" / \"백만원\" / \"천원\" / \"원\" 중 하나로.\n"
    "- change_factors: K-ICS 비율(또는 지급여력)의 '주요 변동요인' 서술 텍스트 "
    "(직전 분기 대비 증감 원인). 표가 아니라 설명 문단에서 가져오세요. 없으면 null.\n\n"
    "주의사항:\n"
    "1) 숫자는 콤마·공백·단위기호를 제거한 순수 숫자(정수 또는 소수)로 출력. 음수는 부호 유지.\n"
    "2) tier1_capital / tier2_capital 은 반드시 '경과조치 적용전' 세부표에서 가져올 것 (적용 후 아님).\n"
    "3) 여러 분기가 함께 나오면 가장 최근(당기) 분기 값을 사용.\n"
    "4) 오직 JSON 객체 하나만 출력.\n\n"
    "출력 예시:\n"
    "{\"company\":\"OO생명보험\",\"quarter\":\"'26.03월\",\"kics_ratio\":162.1,"
    "\"available_capital\":240415,\"required_capital\":148294,"
    "\"tier1_capital\":87193,\"tier2_capital\":153222,\"unit\":\"억원\","
    "\"change_factors\":\"...\"}"
)


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
