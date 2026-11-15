# CareerPath & Fair-Screening AI

## 답변 평가 수정 및 브라우저 검증 — 2026-11-14

- `core/interview_drill.py`: 문자열 반환 함수 대신 기존 `llm_json`으로 AI 평가를 읽도록 수정. 기존에는 응답 자료형 불일치로 규칙 기반 평가로 넘어갔다. 쉼표 포함 수치(`5,000건`, `1,234,567건`) 추출을 수정했다.
- 화면에서 AI 평가와 규칙 기반 평가를 구분하며, 답변 점수를 실제 경력·성과 입증으로 표현하지 않도록 조정했다.
- `python test_pipeline.py`: 35개 통과(외부 호출을 대체한 로컬 검사). 별도 실제 브라우저에서 동일 기본 답변 재분석: 약 10.5초, AI 평가 15점과 근거·꼬리 질문 2개 표시. 기존 규칙 기반 100점과 구분된다. 이 점수는 해당 실행 결과이며 고정값이 아니다.
- 선행 리허설 실측: Mode A 75.5초, 반환 공고 5건(진행 중 3건), 최고 요건 충족률 72%; Mode B 교차 검증 34.3초. 기존 영상 대본의 짧은 대기 시간·고정 점수는 실제 결과에 맞춰 재작성해야 한다. 새 영상은 촬영하지 않았다.

> **"경력은 부족하지 않습니다. 채용 시장의 언어로 증명되지 않았을 뿐입니다."**  
> 40+ 경력자의 현장 경험을 2026 최신 채용 공고(JD)와 연결하고, 기업 면접관에게는 근거 기반 포트폴리오·기여도 검증을 제공하는 2면 실행형 AI 에이전트

---

## 🏆 대회 출품 개요
- **대회명**: 과학기술정보통신부 전국민 AI 경진대회 × LINER .EXE-THON 2026
- **주최/주관**: 과학기술정보통신부, NIA(한국지능정보사회진흥원), LINER
- **참가 부문**: 만 40세 이상 시니어·베테랑 부문
- **팀 대표**: 윤두환 (Lainholic)

---

## 🚀 2면 핵심 워크플로 (Dual-Mode Architecture)

### 🧭 Mode A. 시니어 CareerPath (구직자 모드)
1. **로컬 개인정보 보호 (`LegalSanitizer`)**: 외부 API 호출 전 주민등록번호, 연락처, 이메일, 상세 주소를 로컬 정규식 엔진으로 우선 마스킹합니다.
2. **정제 채용공고 DB + 포털 상세 요강 + LINER 실시간 가중치 매칭**:
   - 원티드 v4 API 및 잡코리아 상세요강(`GI_Read_Comt_Ifrm`)에서 실제 기업명·근무지·상세 자격요건을 정밀 추출해 적재한 `data/postings.db`(301건, 모집 중 77건)와 LINER 웹 검색 API(`/api/v1/tools/search/web`)를 결합합니다.
   - 직무 동의어 매핑, 업종 미스매칭(`role_domain_penalty`) 방지, 비개발 경력 계열 필터링을 거친 뒤 필수(1.0) vs 우대(0.45) 가중치 매칭 엔진으로 공고 요건 충족률(`required_met_ratio`)과 1문장 맞춤 지원 전략(`tailored_advice`)을 산정합니다.
   - 상세 요건이 1줄 이하인 이미지/간이 공고는 가드(`low_detail=True`)를 발동해 왜곡된 점수 산정을 방지하고 원문 상세 확인을 권장합니다.
3. **PDF·DOCX·TXT 업로드, 구조화 프로필 추출, 정량 경력 현대화 번역 및 리포트 내보내기 (`CareerTranslator`, `doc_io.py`)**:
   - 이력서 파일 업로드 직후 로컬 PII 마스킹을 수행하고 경력 연수·만 나이·보유 자격증(기사·산업기사·ISO)·스킬을 자동 구조화 추출합니다.
   - 원문의 연차·비율·규격 수치를 보존한 완성형 경력 기술 문장으로 변환(허위 숫자 차단 게이트 적용)하며 Markdown 전환 리포트로 내려받을 수 있습니다.
4. **7일 실행 스프린트 & 3개월 국비지원 로드맵 (`RoadmapGenerator`, `LinerClient`)**:
   - 고용24(`work24.go.kr`)·HRD-Net(`hrd.go.kr`) 상세 페이지를 파싱해 실제 훈련기관·과정명·훈련기간·시간·NCS·비용 및 모집 정원 정보를 추출합니다.
   - 마감된 과거 회차 URL은 후속 회차(`tracseTme + 1..3`)로 자동 승급해 현재 "모집중"인 실제 과정을 추적하며, 마감 시 동일 NCS 및 차수 확인 행동을 안내합니다.

### 🛡️ Mode B. Fair-Screening Copilot (기업 면접관 모드)
1. **공개 포트폴리오 원문 대조 (`HRFactChecker`)**:
   - 허용된 공개 기술 플랫폼(GitHub, Velog, Medium, ArXiv 등) URL만 수집해 README·파일구조·의존성 매니페스트를 다층 수집하고, LINER Router로 주장을 대조하며 **실제 원문에 근거 인용구(`evidence_quote`)가 없으면 자동으로 `확인 불가`로 강등**합니다.
2. **GitHub 다층 기여도·문서 전용 기여 탐지 (`GitHubVerifier`)**:
   - `README.md` 유무만 보지 않고 공개 GitHub API로 **지원자 ID의 실제 커밋 건수, 코드 변경량(+additions/-deletions), 최근 커밋 메시지, 변경 파일 확장자·언어 비중**을 조회합니다.
   - 문서 파일만 1건 수정한 경미한 기여나 Git 이메일 미연동 소유자 커밋을 정밀 감지해 실무 압박 면접 질문을 자동 생성합니다.
3. **LINER Scholar 학술·특허(KIPRIS / Google Patents) 교차 검증 및 저자명 일치 게이트**:
   - LINER Scholar API(`/api/v1/tools/search/scholar`) 및 공공 특허 검색으로 논문·특허 서지, 등록/피인용 수 및 저자/발명자를 교차 대조합니다.
   - **검색된 저자 목록과 지원자 성명(한글·영문 별칭)을 대조해 `저자 불일치` 시 타인 실적 기재 의심 질문을 즉시 생성**합니다.
4. **4대 영역 요약, 면접 질문지 & 채점표 내보내기**:
   - AI의 일방적 자동 탈락 판정 없이 주장 대조·GitHub 프로필/커밋·학술 검증·면접 질문을 분리 집계하며, 면접관용 교차 검증 리포트(`.md`) 및 현장 채점표(`UTF-8-SIG .csv`) 다운로드를 지원합니다.

---

## 🛠️ LINER Platform 3종 API 및 시스템 구조

| 구분 | 엔드포인트 / 데이터원 | 활용 목적 |
| :--- | :--- | :--- |
| **LINER Router LLM** | `POST https://platform.liner.com/api/v1/chat/completions` | 공고 요건 추출·매칭, 경력 번역, 포트폴리오 인용 검증 및 면접 질문 설계 |
| **LINER Web Search** | `POST https://platform.liner.com/api/v1/tools/search/web` | 2026년 최신 채용 공고 및 고용24(HRD-Net) 국민내일배움카드 훈련과정 실시간 탐색 |
| **LINER Scholar** | `POST https://platform.liner.com/api/v1/tools/search/scholar` | 지원자 제출 R&D·논문·특허 서지, 피인용 수 및 저자명 일치 여부 교차 검증 |
| **정제 채용공고 DB** | `data/postings.db` (SQLite, 301건 / 모집 중 77건) | 직무 관련성·중복 제거·직무 계열 태깅이 완료된 실시간 하이브리드 매칭 저장소 |

---

## 🏁 빠른 실행 방법 (Quick Start)

### 1. 환경 설정 (.env)
```bash
pip install -r requirements.txt
cp .env.example .env
# .env 파일에 LINER_API_KEY (필수) 및 GITHUB_TOKEN (선택) 입력
```

### 2. 결정론적 하네스 검증 테스트
```bash
python test_pipeline.py
```

### 3. 인터랙티브 웹 UI 실행 (포트 8599)
```bash
python -m streamlit run app.py --server.port 8599
```

---

## 📁 주요 디렉토리 구조
```
liner_exethon_2026/
├── core/
│   ├── liner_client.py     # LINER Web Search & Scholar REST API 클라이언트
│   ├── llm.py              # LINER Platform API Router 클라이언트 (liner-gpt/claude-router + 폴백)
│   ├── store.py            # SQLite 정제 공고 저장소, 기업명 정제·도메인 패널티·마감 판별
│   ├── analyzer.py         # 하이브리드 공고 수집 및 병렬 요건 충족률 분석 엔진
│   ├── translator.py       # Liner Router 기반 정량 성과 보존 경력 번역기 (수치 날조 차단)
│   ├── roadmap.py          # 고용24 상세 파싱 연계 맞춤형 3개월 로드맵 & 7일 스프린트
│   ├── doc_io.py           # PDF·DOCX·TXT 로컬 PII 파싱 및 Markdown·CSV 리포트 내보내기
│   ├── legal_sanitizer.py  # 로컬 PII 마스킹 엔진 (주민번호·연락처·이메일·주소)
│   ├── hr_fact_checker.py  # 포트폴리오 인용 강등, Scholar 저자 일치 게이트, 면접 질문 설계
│   ├── github_verifier.py  # GitHub 프로필·커밋·확장자 기반 실제 기여도 및 타인 저장소 탐지
│   ├── fetcher.py          # 원티드 v4·잡코리아 상세요강·공개 기술 도메인 본문 수집기
│   └── curate.py           # 채용공고 중복 탐지·직무 관련성·계열 정제 도구
├── data/
│   └── postings.db         # 정제 완료 채용공고 SQLite DB (클론 즉시 실행 지원)
├── docs/
│   ├── DEMO_VIDEO_SCRIPT.md # 5분 시연 영상 구성 및 대본
│   └── WORK_ORDER.md       # 단계별 개발·제출 작업지시서
├── .kiro/specs/careerpath-agent/
│   ├── requirements.md     # Kiro 요구사항 명세서 (EARS 형식, 법률 준수 게이트)
│   ├── design.md           # Kiro 아키텍처 및 데이터 모델 명세서
│   └── tasks.md            # Kiro 개발 태스크 체크리스트
├── app.py                  # Streamlit 2면 인터랙티브 웹 애플리케이션
└── test_pipeline.py        # 30종 결정론적 하네스 검증 스위트
```
