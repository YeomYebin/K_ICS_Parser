"""이 계정/리전에서 실제로 호출 가능한 Anthropic 모델 ID를 확인하는 진단 스크립트.

사용: python list_bedrock_models.py
결과에서 Opus 모델의 '호출용 ID'(추론 프로파일 ID 우선)를 골라
.env 의 BEDROCK_MODEL_ID 에 넣으세요.
"""
import os

from dotenv import load_dotenv
load_dotenv()

import boto3
from botocore.exceptions import ClientError, EndpointConnectionError

region = os.environ.get("AWS_REGION") or "us-east-1"
print(f"[리전] AWS_REGION = {region}\n")

bedrock = boto3.client("bedrock", region_name=region)

# 1) 파운데이션 모델(온디맨드) 목록 — Anthropic 만
print("=== Anthropic Foundation Models (온디맨드 호출 지원 여부) ===")
try:
    resp = bedrock.list_foundation_models(byProvider="anthropic")
    for m in resp.get("modelSummaries", []):
        types = m.get("inferenceTypesSupported", [])
        print(f"  {m['modelId']:55s}  {types}")
except ClientError as e:
    print("  (조회 실패)", e.response["Error"]["Code"], "-", e.response["Error"]["Message"])
except EndpointConnectionError as e:
    print("  (리전 연결 실패)", e)

# 2) 추론 프로파일(cross-region) 목록 — 최신 모델은 대개 이 ID 로 호출
print("\n=== Inference Profiles (이 ID 로 호출하는 것을 권장) ===")
try:
    resp = bedrock.list_inference_profiles(maxResults=1000)
    for p in resp.get("inferenceProfileSummaries", []):
        pid = p.get("inferenceProfileId", "")
        if "anthropic" in pid or "claude" in pid.lower():
            print(f"  {pid:55s}  status={p.get('status')}")
except ClientError as e:
    print("  (조회 실패)", e.response["Error"]["Code"], "-", e.response["Error"]["Message"])
except EndpointConnectionError as e:
    print("  (리전 연결 실패)", e)

print("\n힌트: 'us.anthropic.claude-opus-...' 같은 추론 프로파일 ID 를 .env 의 BEDROCK_MODEL_ID 에 넣으세요.")
print("      목록에 Opus 가 없으면 콘솔 > Amazon Bedrock > Model access 에서 접근 신청이 필요합니다.")
