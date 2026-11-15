# Requirements Specification — CareerPath & Fair-Screening AI (.EXE-THON 2026)

## 1. Introduction & Executive Summary

**CareerPath & Fair-Screening AI** is an executable AI agent built for **과학기술정보통신부 전국민 AI 경진대회 × LINER .EXE-THON 2026** (만 40세 이상 시니어·베테랑 대상 해커톤).

The product transforms a one-sided job seeker utility into a **high-value 2-sided Recruitment Intelligence Platform**:
1. **Track A (시니어 구직자 모드 - CareerPath)**: 구직자의 복잡한 이력서와 희망 직무를 분석하여 정제 채용DB 및 라이너 실시간 Search·Router API로 최신 공고를 매칭하고, 부족한 역량(Gap)을 고용노동부 HRD-Net 국비지원 과정(국민내일배움카드, 자부담·지원 한도는 과정별 확인) 3개월 로드맵으로 연결.
2. **Track B (기업 인사담당자 모드 - Fair-Screening Copilot)**: 지원자가 제출한 공개 포트폴리오(GitHub, 기술 블로그, 논문·특허)의 실체를 본문 수집, GitHub 커밋 기여도 검증, LINER Search·Scholar·Router API로 교차 팩트체크하고, 근거 기반 심층 면접 질문지를 자동 발행.

---

## 2. Legal & Compliance Constraints (법률 준수 게이트)

All features must strictly adhere to 대한민국 개인정보보호법 and 채용절차법:

- **Constraint 1 (Scope of Data Collection)**: 에이전트는 지원자의 비공개 SNS(페이스북, 인스타그램, 개인 카톡 등)나 사생활 영역을 무단 탐색하지 않는다. 지원자가 이력서/지원서에 **자발적으로 기재한 공개 링크(GitHub, 기술 블로그, 공개 포트폴리오, 공개 논문) 및 지원자가 동의한 직무 데이터**에 한해서만 검증을 수행한다.
- **Constraint 2 (채용절차법 제4조의3 준수)**: 용모, 키, 체중, 출신지역, 혼인여부, 가족관계, 재산 등 직무와 무관한 개인 신상 정보는 검색 결과에서 필터링(Masking)하며 채점 요소에 일절 포함하지 않는다.
- **Constraint 3 (No Automated Decision-Making)**: 에이전트는 단독으로 지원자의 서류 합격/불합격을 결정(Automated Rejection)하지 않는다. 에이전트의 산출물은 **"인사담당자와 면접관의 공정한 평가를 보조하는 객관적 데이터 리포트(Copilot)"**로 명시된다.

---

## 3. Functional Requirements (EARS Format)

### [Track A: 시니어 구직자 모드]

#### Requirement A-1: 실시간 2026 채용 공고 탐색 및 역량 매칭
- **WHEN** 구직자가 자신의 연령(만 40세 이상), 총 경력 연차, 희망 직무, 보유 자격증, 이력서 요약을 입력하면,
- **THE SYSTEM SHALL** 라이너 Search API(`/api/v1/tools/search/web`)를 호출하여 해당 직무의 2026년 최신 채용 공고(경력직/시니어 우대 조건 포함)를 실시간 수집하고,
- **THE SYSTEM SHALL** 구직자의 보유 역량과 공고 자격요건을 대조하여 0~100점의 적합도 점수와 함께 TOP 3 맞춤 공고를 추천해야 한다.

#### Requirement A-2: 결격 리스크 탐지 및 고용노동부 국비 로드맵 설계
- **WHEN** 공고 매칭 후 구직자에게 미보유 요건(특정 자격증, 최신 툴, 실무 데이터 경험 등)이 식별되면,
- **THE SYSTEM SHALL** 라이너 Search API를 통해 해당 부족 역량을 채울 수 있는 고용노동부 HRD-Net 국민내일배움카드 국비지원 교육과정을 실시간 탐색하고,
- **THE SYSTEM SHALL** 1개월차(기초/자격증), 2개월차(실무 프로젝트/AI 도구), 3개월차(맞춤 이력서 실전 지원)로 이어지는 3개월 단기 실행 로드맵을 구조화하여 출력해야 한다.

---

### [Track B: 기업 인사담당자 모드 (Fair-Screening)]

#### Requirement B-1: 제출된 공개 포트폴리오 진위 팩트체크
- **WHEN** 채용 담당자가 지원자의 이력서 텍스트와 제출된 공개 링크(GitHub 프로필, 기술 블로그, 프로젝트 URL 등)를 입력하면,
- **THE SYSTEM SHALL** 라이너 Search API로 해당 링크의 실존 여부, 프로젝트 코드 기여 내역, 기술 포스팅의 원저작성 및 활동 시기를 실시간 수집·대조하고,
- **THE SYSTEM SHALL** 지원자의 이력서 내용 중 웹 데이터와 일치하는 검증 성과와 과장/미확인 의심 영역을 명확히 분류한 팩트체크 요약표를 제공해야 한다.

#### Requirement B-2: 2026년 채용 시장 벤치마크 및 객관적 역량 채점
- **WHEN** 직무와 연차가 지정되면,
- **THE SYSTEM SHALL** 라이너 Search API로 2026년 동일 직무 합격자들의 평균 요구 스펙(자격증 수준, 필수 기술 스택, 프로젝트 볼륨)을 수집하고,
- **THE SYSTEM SHALL** 지원자의 역량을 시장 기준선과 비교하여 직무 적합도 점수(0~100점)와 백분위 추정치를 계산해야 한다.

#### Requirement B-3: 면접관 맞춤형 심층 검증 질문지 생성
- **WHEN** 팩트체크 및 역량 분석이 완료되면,
- **THE SYSTEM SHALL** 지원자의 프로젝트 성과 중 기술적 깊이 확인이 필요한 항목과 과장 의심 지점에 대해 면접관이 현장에서 즉시 활용할 수 있는 **'맞춤형 실무 검증 질문 5선'**을 모범 답변 체크포인트와 함께 출력해야 한다.

---

## 4. Non-Functional Requirements & Performance

- **Scoring Rubric & Weighting (적합도 및 신뢰도 산정 기준)**:
  - **직무 적합도 점수 (0~100점)**: 필수 자격요건 부합도(40%) + 유관 실무 연차(30%) + 포트폴리오 공개 검증도(20%) + 디지털/AI 생산성 툴 역량(10%) 가중치 합산.
  - **백분위 산정**: 2026 동일 직무 시장 공고 요구 스펙(중앙값) 대비 충족 항목 비율로 표준화.
- **Response Latency & API Budget (8초 응답 보장)**:
  - 라이너 Search API 호출을 세션당 최대 2회(1차: 시장공고/벤치마크, 2차: 국비과정/포트폴리오)로 제한하여 병렬 또는 단일 파이프라인으로 4~6초 내 완료.
- **Fail-Safe Mechanism & Mock Fallback Scope**:
  - 라이너 API 장애 또는 네트워크 단절 시 사전에 구축된 3대 직군(스마트 데이터 공정, IT/소프트웨어, B2B 솔루션 기획)의 2026 검증 샘플 데이터셋으로 0.1초 무중단 폴백.
- **Security & Privacy**:
  - 모든 API 키와 지원자 PII는 `.env` 및 로컬 세션 메모리에서만 처리되며, 코드 저장소나 외부 로그로 유출되지 않아야 한다.
