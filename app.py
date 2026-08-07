"""K-ICS 경영공시 PDF 파서 웹앱 (Flask).

실행:
  1) pip install -r requirements.txt
  2) .env.example 을 .env 로 복사하고 값(OOO)을 채움
  3) python app.py  →  http://127.0.0.1:5000
"""
import traceback

from dotenv import load_dotenv
load_dotenv()  # .env 의 AWS_BEARER_TOKEN_BEDROCK / AWS_REGION / BEDROCK_MODEL_ID 로드

from flask import Flask, render_template, request, jsonify, send_file

from extractor import extract_from_pdf
from excel_export import build_excel

app = Flask(__name__)
app.config["MAX_CONTENT_LENGTH"] = 100 * 1024 * 1024  # 파일당 최대 100MB


@app.route("/")
def index():
    return render_template("index.html")


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
