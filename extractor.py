"""PDF → 페이지 이미지 → Bedrock 비전 추출 → 정규화/검산.

핵심 제약: 대상 PDF들은 한글이 CID 폰트로 임베딩되어 텍스트 추출이 불가하므로
PDF 전체를 페이지 이미지로 렌더링해 LLM 비전(OCR)으로 판독한다.
"""
import re

import pymupdf as fitz  # PyMuPDF

from bedrock_client import extract_fields_from_images


# Bedrock Converse 는 요청당 이미지 최대 20장 → 페이지가 더 많으면 배치로 나눠 호출 후 병합
MAX_IMAGES_PER_CALL = 20
RENDER_DPI = 150
MAX_DIM_PX = 2200  # 한 변 최대 픽셀(초과 시 다운스케일)

CAPITAL_FIELDS = ["available_capital", "required_capital",
                  "tier1_capital", "tier2_capital"]

# 단위 → 억원 환산 계수
UNIT_TO_EOK = {
    "억원": 1.0, "억": 1.0,
    "백만원": 0.01, "백만": 0.01,
    "천원": 1e-5, "천": 1e-5,
    "원": 1e-8,
    "조원": 1e4, "조": 1e4,
}

# 표시용 단축명 규칙 (앞에 오는 규칙이 우선; 구체적인 것부터)
SHORT_NAME_RULES = [
    ("미래에셋", "미래에셋"),
    ("삼성", "삼성"),
    ("한화", "한화"),
    ("교보라이프플래닛", "교보라플"),
    ("교보", "교보"),
    ("신한", "신한"),
    ("동양", "동양"),
    ("KB라이프", "KB"),
    ("KB", "KB"),
    ("농협", "농협"),
    ("흥국", "흥국"),
    ("IBK", "IBK연금"),
    ("KDB", "KDB"),
    ("라이나", "라이나"),
    ("메트라이프", "메트라이프"),
    ("에이비엘", "ABL"),
    ("ABL", "ABL"),
    ("처브라이프", "처브"),
    ("하나", "하나"),
    ("iM라이프", "iM"),
    ("아이엠라이프", "iM"),
    ("AIA", "AIA"),
    ("BNP", "BNP카디프"),
    ("카디프", "BNP카디프"),
    ("푸본현대", "푸본현대"),
    ("푸본", "푸본현대"),
    # DB 는 다른 회사명에 흔히 포함되지 않도록 마지막에
    ("DB생명", "DB"),
    ("DB", "DB"),
]


def render_pdf_to_images(pdf_bytes, dpi=RENDER_DPI):
    """PDF 전체 페이지를 PNG 바이트 리스트로 렌더."""
    doc = fitz.open(stream=pdf_bytes, filetype="pdf")
    images = []
    try:
        zoom = dpi / 72.0
        for page in doc:
            mat = fitz.Matrix(zoom, zoom)
            pix = page.get_pixmap(matrix=mat, alpha=False)
            longest = max(pix.width, pix.height)
            if longest > MAX_DIM_PX:
                scale = MAX_DIM_PX / longest
                mat = fitz.Matrix(zoom * scale, zoom * scale)
                pix = page.get_pixmap(matrix=mat, alpha=False)
            images.append(pix.tobytes("png"))
    finally:
        doc.close()
    return images


def _chunks(seq, n):
    for i in range(0, len(seq), n):
        yield seq[i:i + n]


def to_number(value):
    """'240,415', '162.1%', -12,345 등을 float 로. 실패 시 None."""
    if value is None:
        return None
    if isinstance(value, (int, float)):
        return float(value)
    s = str(value).strip()
    if s == "" or s.lower() in ("null", "n/a", "na", "-"):
        return None
    s = s.replace(",", "").replace("%", "").replace(" ", "")
    m = re.search(r"-?\d+(?:\.\d+)?", s)
    return float(m.group()) if m else None


def _merge_results(results):
    """배치별 추출 결과를 하나로 병합 (숫자/문자는 첫 유효값, 변동요인은 최장)."""
    merged = {}
    for key in ["company", "quarter", "unit", "kics_ratio"] + CAPITAL_FIELDS:
        val = None
        for r in results:
            v = r.get(key)
            if v not in (None, "", "null"):
                val = v
                break
        merged[key] = val

    change = ""
    for r in results:
        c = r.get("change_factors")
        if c and len(str(c)) > len(change):
            change = str(c)
    merged["change_factors"] = change or None
    return merged


def normalize_units(data):
    """자본 수치들을 억원 기준으로 환산하고 kics_ratio 를 숫자화."""
    unit = (data.get("unit") or "억원").strip()
    factor = UNIT_TO_EOK.get(unit, 1.0)

    for k in CAPITAL_FIELDS:
        num = to_number(data.get(k))
        data[k] = round(num * factor) if num is not None else None

    data["kics_ratio"] = to_number(data.get("kics_ratio"))
    data["unit"] = "억원"
    return data


def add_ratio_check(data, tolerance=1.0):
    """K-ICS 비율: 표시값은 '가용자본 / 요구자본 * 100' 계산값을 기본으로 사용.

    - kics_ratio         : 문서에서 추출한 값 (참고/검산용)
    - kics_ratio_calc    : 가용자본 / 요구자본 * 100 (계산값)
    - kics_ratio_display : 화면/엑셀에 표시할 값 = 계산값(없으면 문서값으로 폴백)
    - ratio_warning      : 계산값과 문서값이 허용오차 밖으로 다르면 True (빨간색 표시용)
    """
    a = data.get("available_capital")
    r = data.get("required_capital")
    ratio = data.get("kics_ratio")

    calc = None
    if isinstance(a, (int, float)) and isinstance(r, (int, float)) and r:
        calc = round(a / r * 100, 1)
    data["kics_ratio_calc"] = calc

    # 표시값: 계산값 우선, 계산 불가 시 문서 추출값으로 폴백
    data["kics_ratio_display"] = calc if calc is not None else ratio

    warning = False
    if calc is not None and isinstance(ratio, (int, float)):
        warning = abs(calc - ratio) > tolerance
    data["ratio_warning"] = warning
    return data


def company_from_filename(filename):
    """파일명에서 회사명 추정 (첫 괄호 안 내용 우선)."""
    name = re.sub(r"\.pdf$", "", filename, flags=re.IGNORECASE)
    m = re.search(r"[（(]([^）)]+)[）)]", name)
    if m:
        return m.group(1).strip()
    # 붙임/첨부/번호 등 접두 정리
    cleaned = re.sub(r"^[\s\d_.\-]*(붙임|첨부)?\s*\d*[_.\-\s]*", "", name).strip()
    return cleaned or name


def short_name(company, filename):
    hay = f"{filename} {company or ''}"
    low = hay.lower()
    for keyword, short in SHORT_NAME_RULES:
        if keyword.lower() in low:
            return short
    return (company or filename).split()[0][:8]


def extract_from_pdf(pdf_bytes, filename):
    """PDF 바이트 → 한 회사 행 dict."""
    images = render_pdf_to_images(pdf_bytes)
    if not images:
        raise RuntimeError("PDF 에서 페이지를 렌더링하지 못했습니다.")

    results = []
    for chunk in _chunks(images, MAX_IMAGES_PER_CALL):
        res = extract_fields_from_images(chunk)
        if res:
            results.append(res)

    if not results:
        raise RuntimeError("LLM 이 추출 결과를 반환하지 않았습니다.")

    data = _merge_results(results)
    data = normalize_units(data)

    company = data.get("company") or company_from_filename(filename)
    data["company"] = company
    data["display_name"] = short_name(company, filename)
    data["source_file"] = filename
    if not data.get("quarter"):
        data["quarter"] = "'26.03월"

    add_ratio_check(data)
    return data
