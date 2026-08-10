"""K-ICS 경영공시 PDF 파서 웹앱 (Flask).

실행:
  1) pip install -r requirements.txt
  2) .env.example 을 .env 로 복사하고 값(OOO)을 채움
  3) python app.py  →  http://127.0.0.1:5000
"""
import os
import secrets
import traceback

from dotenv import load_dotenv
load_dotenv()  # .env 의 AWS_REGION / BEDROCK_MODEL_ID / APP_PASSWORD / SECRET_KEY 로드

from flask import (Flask, render_template, request, jsonify, send_file,
                   session, redirect)

from extractor import extract_from_pdf
from excel_export import build_excel

app = Flask(__name__)
app.config["MAX_CONTENT_LENGTH"] = 100 * 1024 * 1024  # 파일당 최대 100MB
# 세션 키: .env 의 SECRET_KEY 사용(없으면 임시 생성 — 재시작 시 재로그인 필요)
app.secret_key = os.environ.get("SECRET_KEY") or secrets.token_hex(32)
app.config.update(SESSION_COOKIE_HTTPONLY=True, SESSION_COOKIE_SAMESITE="Lax")

# 접속 비밀번호 (.env 의 APP_PASSWORD). 비어 있으면 보호하지 않음.
APP_PASSWORD = os.environ.get("APP_PASSWORD", "")


@app.before_request
def require_login():
    """APP_PASSWORD 가 설정돼 있으면 로그인 페이지를 통과해야만 접근 허용."""
    if not APP_PASSWORD:
        return  # 비밀번호 미설정 → 보호 안 함
    if request.path == "/login" or session.get("authed"):
        return
    return redirect("/login")


@app.route("/login", methods=["GET", "POST"])
def login():
    if request.method == "POST":
        if request.form.get("password") == APP_PASSWORD:
            session["authed"] = True
            return redirect("/")
        return render_template("login.html", error=True), 401
    return render_template("login.html", error=False)


@app.route("/logout")
def logout():
    session.clear()
    return redirect("/login")


@app.route("/")
def index():
    return render_template("index.html")


@app.route("/pageinfo", methods=["POST"])
def pageinfo():
    """PDF 페이지 수만 빠르게 반환 (LLM 호출 없음, 목록 정렬용)."""
    import pymupdf
    file = request.files.get("file")
    if file is None or file.filename == "":
        return jsonify({"error": "파일이 없습니다."}), 400
    try:
        doc = pymupdf.open(stream=file.read(), filetype="pdf")
        pages = doc.page_count
        doc.close()
        return jsonify({"pages": pages})
    except Exception as exc:  # noqa: BLE001
        return jsonify({"error": str(exc)}), 500


@app.route("/extract", methods=["POST"])
def extract():
    """PDF 1개를 받아 추출 결과 한 행(JSON)을 반환."""
    file = request.files.get("file")
    if file is None or file.filename == "":
        return jsonify({"error": "파일이 없습니다."}), 400
    try:
        pdf_bytes = file.read()
        row = extract_from_pdf(pdf_bytes, file.filename)
        return jsonify(row)
    except Exception as exc:  # noqa: BLE001 - 사용자에게 원인 전달
        traceback.print_exc()
        return jsonify({"error": str(exc), "source_file": file.filename}), 500


@app.route("/download", methods=["POST"])
def download():
    """프론트가 보관한 행들을 받아 xlsx 로 반환."""
    payload = request.get_json(silent=True) or {}
    rows = payload.get("rows", [])
    quarter = payload.get("quarter") or "'26.03월"
    if not rows:
        return jsonify({"error": "다운로드할 데이터가 없습니다."}), 400
    bio = build_excel(rows, quarter)
    return send_file(
        bio,
        mimetype="application/vnd.openxmlformats-officedocument.spreadsheetml.sheet",
        as_attachment=True,
        download_name="K-ICS_현황.xlsx",
    )


if __name__ == "__main__":
    app.run(host="127.0.0.1", port=5000, debug=True)
