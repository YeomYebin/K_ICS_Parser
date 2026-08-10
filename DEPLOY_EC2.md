# EC2 배포 가이드 (전부 AWS)

Flask 앱을 EC2에서 gunicorn + nginx 로 돌리고, **IAM 인스턴스 역할**로 Bedrock에 붙습니다.
(EC2에서는 API 키/베어러 토큰이 필요 없습니다.)

구성: 사용자 → EC2(nginx+gunicorn+Flask) → Bedrock(Opus 4.6, us-east-1)

---

## 1. IAM 역할 만들기 (Bedrock 호출 권한)

1. IAM → 역할 → 역할 만들기 → 신뢰 주체: **AWS 서비스 / EC2**
2. 권한: 인라인 정책으로 `deploy/bedrock-iam-policy.json` 내용 붙여넣기
   (모델을 바꾸면 정책의 모델 ID도 함께 수정)
3. 역할 이름: 예) `kics-ec2-bedrock` → 생성

## 2. EC2 인스턴스 생성

- AMI: **Amazon Linux 2023**
- 타입: **t3.medium** (메모리 4GB — 큰 PDF 렌더에 필요. t3.small은 부족할 수 있음)
- 리전: **us-east-1** (Bedrock 모델과 동일)
- 스토리지: 20GB
- **IAM 인스턴스 프로파일: 위에서 만든 `kics-ec2-bedrock` 역할 지정**
- 보안 그룹:
  - SSH(22): 내 IP
  - HTTP(80): 내 IP 또는 사내망 (공개하려면 0.0.0.0/0 — 단 아래 basic auth 필수)
- (권장) **탄력적 IP(Elastic IP)** 할당해 고정 주소 부여

## 3. 서버 세팅 (SSH 접속 후)

```bash
sudo dnf update -y
sudo dnf install -y git python3.11 python3.11-pip nginx

# 코드 받기 (공개 레포)
cd ~
git clone https://github.com/YeomYebin/K_ICS_Parser.git
cd K_ICS_Parser

# 가상환경 + 의존성
python3.11 -m venv .venv
.venv/bin/pip install -U pip
.venv/bin/pip install -r requirements.txt
```

## 4. .env 작성 (키 없이 리전/모델만)

```bash
cat > ~/K_ICS_Parser/.env <<'EOF'
AWS_REGION=us-east-1
BEDROCK_MODEL_ID=us.anthropic.claude-opus-4-6-v1
EOF
```
> IAM 인스턴스 역할을 쓰므로 `AWS_BEARER_TOKEN_BEDROCK` 는 넣지 않습니다.
> (boto3가 인스턴스 역할 자격증명을 자동으로 사용)

동작 확인:
```bash
cd ~/K_ICS_Parser
.venv/bin/python list_bedrock_models.py   # 모델 목록이 나오면 역할 연결 정상
```

## 5. gunicorn 을 systemd 서비스로 등록

```bash
sudo cp ~/K_ICS_Parser/deploy/kics.service /etc/systemd/system/kics.service
# (User/경로가 다르면 파일 수정: Ubuntu는 User=ubuntu)
sudo systemctl daemon-reload
sudo systemctl enable --now kics
sudo systemctl status kics        # active (running) 확인
```

## 6. nginx + 비밀번호(basic auth)

```bash
# 비밀번호 파일 생성 (사용자명 admin)
sudo dnf install -y httpd-tools
sudo htpasswd -c /etc/nginx/.htpasswd admin   # 비밀번호 입력

# 프록시 설정 배치
sudo cp ~/K_ICS_Parser/deploy/nginx-kics.conf /etc/nginx/conf.d/kics.conf
sudo nginx -t && sudo systemctl enable --now nginx
sudo systemctl restart nginx
```

이제 브라우저에서 `http://<EC2 퍼블릭 IP>/` 접속 → 아이디/비밀번호 입력 후 사용.

## 7. (선택) HTTPS

도메인이 있으면:
```bash
sudo dnf install -y certbot python3-certbot-nginx
sudo certbot --nginx -d kics.example.com
```
도메인 없이 IP만 쓰면 http로 접속 (내부용이면 충분).

---

## 코드 업데이트 시 (재배포)
```bash
cd ~/K_ICS_Parser && git pull
.venv/bin/pip install -r requirements.txt   # 의존성 바뀐 경우만
sudo systemctl restart kics
```

## 문제 해결
- 로그: `sudo journalctl -u kics -f`
- Bedrock AccessDenied: IAM 역할 정책의 모델 ARN 확인 (`deploy/bedrock-iam-policy.json`)
- 업로드 413 오류: nginx `client_max_body_size` 확인 (기본 50m 설정됨)
- 502/타임아웃: 큰 PDF 처리 지연 → nginx `proxy_read_timeout`, gunicorn `--timeout` 이미 600s
