# K-ICS 경영공시 PDF 파서

보험사(생명·손해) 정기 경영공시 PDF를 여러 개 업로드하면, Bedrock Opus(비전)가
파일당 1회 호출로 지급여력 관련 수치와 주요 변동요인을 추출해 표로 보여주고
엑셀로 내려받는 웹 도구입니다.

## 추출 항목
| 항목 | 정의 |
|---|---|
| K-ICS 비율 | 지급여력비율(%) — 가용÷요구×100 으로 검산 |
| 가용자본 | 지급여력금액 (가) |
| 요구자본 | 지급여력기준금액 (나) |
| 기본자본 | [경과조치 적용전 지급여력비율세부] → 가.지급여력금액 → 기본자본 |
| 보완자본 | [경과조치 적용전 지급여력비율세부] → 가.지급여력금액 → 보완자본 |
| 주요 변동요인 | 텍스트 (표에서 행 클릭 시 펼침) |

- 표의 숫자 단위는 **억원**으로 통일됩니다.
- 분기 표기는 `'26.03월` 형식입니다.

## 왜 비전(OCR) 방식인가
대상 PDF들은 한글이 CID 폰트로 임베딩되어 있어 일반 텍스트 추출 시 **한글이 모두 유실**됩니다.
그래서 PDF 전체 페이지를 이미지로 렌더링(PyMuPDF)해 Opus 비전으로 판독합니다.

## 설치 & 실행
```bash
pip install -r requirements.txt

# .env 준비 (값의 OOO 를 실제 값으로 교체)
cp .env.example .env      # Windows PowerShell: Copy-Item .env.example .env

python app.py             # http://127.0.0.1:5000
```

## .env 설정
```
AWS_BEARER_TOKEN_BEDROCK=<Bedrock API 키>
AWS_REGION=<리전, 예: us-west-2>
BEDROCK_MODEL_ID=<비전 지원 Opus 모델 ID>
```

## 구성
- `app.py` — Flask 서버 (`/extract` 파일 1개 처리, `/download` 엑셀 생성)
- `extractor.py` — PDF→이미지 렌더, 단위 환산, K-ICS 검산, 회사명 처리
- `bedrock_client.py` — Bedrock Converse 호출(비전+JSON), 프롬프트
- `excel_export.py` — openpyxl 표 생성
- `templates/index.html` — 업로드 UI + 결과 표(펼침 행) + 다운로드
