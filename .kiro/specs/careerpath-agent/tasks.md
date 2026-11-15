# Task Breakdown & Implementation Roadmap — CareerPath & Fair-Screening AI

## Phase 1: Specification & Compliance Infrastructure (COMPLETED)
- [x] 1.1 Kiro Specification Structure (`.kiro/specs/careerpath-agent/` with requirements, design, tasks)
- [x] 1.2 Legal & Compliance Gate definition (개인정보보호법 & 채용절차법 제4조의3 준수 규격)
- [x] 1.3 Liner Search API live integration check (`https://platform.liner.com/api/v1/tools/search/web` 200 OK verified)

---

## Phase 2: Dual-Mode Engine Implementation (COMPLETED)
- [x] 2.1 Implement `core/legal_sanitizer.py`
  - Input sanitization (masking non-job personal signals)
  - Search query scoping (restricting to submitted URLs and professional domains)
- [x] 2.2 Implement `core/hr_fact_checker.py` & `core/github_verifier.py`
  - Candidate portfolio verification against public links with anti-hallucination quote gate
  - GitHub real commit & file extension attribution check (`GitHubVerifier`)
  - LINER Scholar citation & author-match cross-check
  - Targeted interview rubric generator
- [x] 2.3 Extend `core/liner_client.py` & `core/llm.py`
  - LINER Router LLM integration (`https://platform.liner.com/api/v1/chat/completions`)
  - LINER Web Search & Scholar integration with hybrid `PostingStore` (`data/postings.db`)
  - Deterministic test suite in `test_pipeline.py`

---

## Phase 3: Streamlit UI Dual-Mode Expansion (COMPLETED)
- [x] 3.1 Refactor `app.py` navigation to support:
  - **Tab/Mode 1: 🧭 시니어 구직자 모드 (CareerPath)**: 공고 매칭 & 역량 갭 & 3개월 국비 로드맵
  - **Tab/Mode 2: 🛡️ 기업 인사담당자 모드 (Fair-Screening)**: 포트폴리오 팩트체크 & GitHub 기여 & Scholar 저자 대조 & 면접 질문지
- [x] 3.2 Add 1-click presets for both Mode A and Mode B
- [x] 3.3 Verify UI responsiveness, badge rendering, and senior-friendly styling via live browser check

---

## Phase 4: Contest Deliverables Kit (Deadline 11/25)
- [ ] 4.1 Finalize & render 1~2 Page PDF Proposal (`official_proposal.md` -> PDF)
- [ ] 4.2 Record & upload 5-minute Demo Video highlighting LINER 3-API live workflow (`docs/DEMO_VIDEO_SCRIPT.md`)
- [x] 4.3 Update `README.md` with full architecture, LINER 3-API usage documentation, and execution guide
- [ ] 4.4 Final clean local Git checkpoint commit
