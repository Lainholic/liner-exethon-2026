# System Design & Architecture — CareerPath & Fair-Screening AI

## 1. System Overview & Architecture

```
                      [Web UI: Streamlit Desktop App]
                                     │
                 ┌───────────────────┴───────────────────┐
                 ▼                                       ▼
       [Track A: Job Seeker]                   [Track B: HR Screening]
        (Senior CareerPath)                     (Portfolio Fact-Check)
                 │                                       │
                 ▼                                       ▼
       [ProfileAnalyzer.py]                   [HRFactChecker.py]
                 │                                       │
                 └───────────────────┬───────────────────┘
                                     │
                                     ▼
                          [LegalSanitizer.py]
                   (PII Filter / Bias Masking Gate)
                                     │
                                     ▼
                           [LinerClient.py]
              (Liner Platform Search & Agent REST API)
                                     │
               ┌─────────────────────┼─────────────────────┐
               ▼                     ▼                     ▼
     [2026 Live Jobs]        [MOEL HRD-Net]        [Public Profiles]
    (Saramin/Wanted/Job)  (HRD-Net Subsidized)   (GitHub/Tech Blogs)
```

---

## 2. Core Component Specifications

### 2.1 `core/liner_client.py` (Liner Platform Gateway)
- **Base Endpoint**: `https://platform.liner.com/api/v1/tools/search/web`
- **Method**: `POST` with `Bearer <LINER_API_KEY>`
- **Methods**:
  - `search_jobs(job_title, senior_friendly)`: Retrieves live 2026 job postings.
  - `search_government_courses(job_title, missing_skills)`: Retrieves MOEL HRD-Net courses.
  - `verify_candidate_portfolio(candidate_name, target_job, public_urls, project_keywords)`: Performs targeted web verification against submitted public URLs.
  - `get_market_benchmark(target_job, experience_years)`: Gathers current 2026 market standards for the target role.

### 2.2 `core/legal_sanitizer.py` (Compliance Gate)
- **Purpose**: Strict adherence to 개인정보보호법 and 채용절차법 제4조의3.
- **Operations**:
  - `sanitize_candidate_input(data)`: Masks age/gender/marital/family signals before external search queries.
  - `filter_search_results(results)`: Drops any search snippets referencing personal non-job aspects (family, appearance, private social media).
  - Enforces that only submitted URLs or explicitly allowed professional domains (`github.com`, `velog.io`, `tistory.com`, `medium.com`, `linkedin.com`, academic portals) are ingested.

### 2.3 `core/hr_fact_checker.py` (HR Candidate Evaluation Engine)
- **Inputs**:
  - Candidate Name, Target Role, Experience Years.
  - Resume Summary / Project Descriptions.
  - Submitted Public Portfolio URLs (GitHub, Blog, Portfolio Site).
- **Outputs**:
  - `VerificationCard`:
    - **Portfolio Authenticity Score** (0~100): Validates actual codebase/article existence.
    - **Verified Achievements**: Projects backed by verifiable web traces.
    - **Verification Gaps / Overstatement Warnings**: Unverified or exaggerated claims.
  - `MarketBenchmarkCard`: Candidate skills vs 2026 market average requirements.
  - `InterviewQuestions`: 5 tailored deep-dive questions with answer evaluation rubrics.

### 2.4 `core/analyzer.py`, `core/roadmap.py` & `core/doc_io.py` (Job Seeker & Document Track)
- `fetcher.py`: 포털 네이티브 수집(Wanted API v4 / JobKorea 상세요강 iframe)으로 실제 기업명·근무지·마감상태·상세요강을 추출하며, GitHub 다층 구조(README·최상위 파일목록·의존성 매니페스트)를 병렬 수집한다.
- `store.py` & `analyzer.py`:
  - 293건 SQLite 저장소에서 직무 동의어 매핑 및 도메인 패널티를 적용하고, 1줄 이하 저상세/이미지 공고 가드(`low_detail=True`, `scored=False`)를 적용한다.
  - 필수 요건(1.0 / generic 0.35 / logistics 0.20)과 우대 사항(0.45 / logistics 0.15)을 차등 가중치로 채점하며, `required_met_ratio` 및 1문장 맞춤 지원 전략(`tailored_advice`)을 산정한다.
- `roadmap.py` & `liner_client.py`:
  - 고용24(work24.go.kr) 상세 페이지에서 훈련기관·과정명·기간·시간·NCS·비용 및 모집 정원(`quota`)을 실시간 파싱한다.
  - 마감된 회차는 후속 회차(`tracseTme + 1..3`)로 자동 승급하여 현재 "모집중"인 실제 과정을 추적하며, 마감 시 동일 NCS 및 차수 확인 행동을 안내한다.
- `doc_io.py`:
  - PDF·DOCX·TXT 업로드 시 로컬 PII 마스킹과 함께 경력 연수·만 나이·보유 자격증(기사·산업기사·ISO)·스킬을 자동 구조화 추출한다.
  - 정량 성과 보존 Markdown 전환 리포트 및 면접관 채점표(UTF-8-SIG CSV) 내보내기를 지원한다.
- `github_verifier.py` & `hr_fact_checker.py`:
  - 지원자의 실제 커밋 건수, 코드 변경량(+additions/-deletions), 최근 커밋 메시지, 파일 확장자·언어 비중을 대조한다.
  - 문서 파일 1건만 수정한 경미한 기여나 Git 이메일 미연동 소유자 커밋을 정밀 감지하고, LINER Scholar 및 공공 특허(KIPRIS / Google Patents)를 교차 대조하여 실무 면접 질문을 자동 설계한다.

---

## 3. Data Models (Pydantic Specifications)

```python
class CandidateVerificationRequest(BaseModel):
    name: str
    target_job: str
    experience_years: int
    submitted_urls: List[str]  # e.g., ["https://github.com/...", "https://velog.io/@..."]
    key_projects: List[str]
    resume_text: str

class VerifiedProjectItem(BaseModel):
    project_name: str
    claimed_role: str
    verification_status: str  # "VERIFIED", "PARTIALLY_VERIFIED", "UNCONFIRMED"
    evidence_url: str
    evidence_snippet: str
    notes: str

class HRVerificationReport(BaseModel):
    candidate_name: str
    target_job: str
    overall_trust_score: int  # 0 to 100
    market_fit_score: int     # 0 to 100
    verified_projects: List[VerifiedProjectItem]
    overstatement_warnings: List[str]
    market_benchmark_summary: str
    interview_questions: List[Dict[str, str]]  # {"question": "...", "intent": "...", "check_criteria": "..."}
```

---

## 4. Correctness & Deterministic Guarantees

1. **Exact URL Attribution**: All verification statements in the HR report must explicitly cite the `evidence_url` retrieved from Liner Search. No ungrounded claims.
2. **Graceful Fallback**: If Liner Search returns empty results for a niche URL, the status is explicitly downgraded to `UNCONFIRMED (추가 서류 요청 필요)` rather than hallucinating validation.
3. **Execution Safety**: Streamlit UI executes locally; zero remote telemetry or unprompted file transfers.
4. **Harness Verification**: 30 deterministic unit tests in `test_pipeline.py` validate all gates without network dependencies.
