# 🚀 배포 가이드: Streamlit Community Cloud 1-Click 라이브 데모 배포

본 프로젝트는 클라우드 웹 배포에 100% 최적화되어 있습니다. 심사위원단이 별도 로컬 설치 없이 브라우저에서 즉시 체험할 수 있도록 배포할 수 있습니다.

---

## 1. 배포 전 체크리스트
- [x] `.env` 및 민감키는 `.gitignore`로 제외되어 공개 저장소에 올라가지 않음.
- [x] 정제 채용공고 데이터베이스(`data/postings.db`)가 저장소에 포함되어 즉시 동작.
- [x] `.streamlit/config.toml`에 기업용 UI 테마 및 보안 설정 내장.
- [x] `requirements.txt`에 모든 경량 의존성 명시.

---

## 2. Streamlit Community Cloud 배포 순서 (소요 시간: 1분)

1. **[share.streamlit.io](https://share.streamlit.io/)** 로그인 (GitHub 계정 연동).
2. **"New app"** 클릭:
   - **Repository**: `본인-GitHub-ID/liner_exethon_2026`
   - **Branch**: `master` (또는 `main`)
   - **Main file path**: `app.py`
3. **Advanced settings** 클릭 후 **Secrets** 등록:
   ```toml
   LINER_API_KEY = "발급받은_LINER_API_키"
   ```
4. **"Deploy!"** 버튼 클릭.
5. 배포 완료 후 발급된 공식 라이브 URL (예: `https://careerpath-liner-2026.streamlit.app`)을 대회 제출 폼 및 GitHub `README.md` 상단에 기재.

---

## 3. 로컬 데모 실행 방법 (심사용 로컬 구동)

```bash
# 가상환경 생성 및 의존성 설치
python -m venv venv
venv\Scripts\activate
pip install -r requirements.txt

# 테스트 스위트 전체 검증
python test_pipeline.py

# 로컬 웹 앱 실행 (포트 8599)
streamlit run app.py --server.port 8599
```
