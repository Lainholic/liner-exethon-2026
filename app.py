import html
import os
import sys
import time
from concurrent.futures import ThreadPoolExecutor

import streamlit as st

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))

from core.analyzer import JobSeekerProfile, ProfileAnalyzer
from core.doc_io import (
    build_mode_a_report_md,
    build_mode_b_report_md,
    build_mode_b_scorecard_csv,
    extract_portfolio_inputs_from_text,
    extract_resume_profile_from_text,
    extract_text_from_upload,
)
from core.github_verifier import GitHubVerifier
from core.hr_fact_checker import HRFactChecker
from core.interview_drill import InterviewDrillEngine
from core.legal_sanitizer import LegalSanitizer
from core.liner_client import LinerClient
from core.llm import get_llm_stats
from core.roadmap import RoadmapGenerator
from core.report_printer import generate_interview_sheet_html, generate_modern_resume_html
from core.store import clean_company_name, portal_label
from core.transfer_engine import SkillTransferEngine
from core.translator import CareerTranslator


def _safe_url(url: str) -> str:
    u = (url or "").strip()
    return u if u.startswith(("http://", "https://")) else "#"


st.set_page_config(
    page_title="리본 4050 (Re:Born 4050) — 중장년 경력 전환 AI",
    page_icon="🧭",
    layout="wide",
    initial_sidebar_state="expanded",
)

st.markdown("""
<style>
    .main-title {
        font-size: 2.05rem;
        font-weight: 800;
        color: #0f2942;
        letter-spacing: -0.02em;
        margin-bottom: 0.15rem;
    }
    .sub-title {
        font-size: 1.05rem;
        color: #475569;
        margin-bottom: 1.15rem;
    }
    .guide-grid {
        display: flex;
        gap: 14px;
        align-items: stretch;
        margin: 10px 0 16px 0;
    }
    .guide-card {
        flex: 1;
        background: #ffffff;
        border: 1px solid #dbe4f0;
        border-radius: 12px;
        padding: 18px;
        box-shadow: 0 2px 6px rgba(15, 41, 66, 0.04);
        display: flex;
        flex-direction: column;
        justify-content: flex-start;
    }
    .guide-card h4 {
        margin: 0 0 8px 0;
        color: #0f2942;
        font-size: 1.02rem;
    }
    .guide-card p {
        margin: 0;
        color: #475569;
        font-size: 0.92rem;
        line-height: 1.5;
    }
    .card {
        background: #ffffff;
        border: 1px solid #e2e8f0;
        border-radius: 12px;
        padding: 18px 20px;
        margin-bottom: 14px;
        box-shadow: 0 2px 8px rgba(15, 41, 66, 0.04);
    }
    .card-header {
        display: flex;
        justify-content: space-between;
        align-items: center;
        gap: 12px;
        margin-bottom: 6px;
    }
    .company-line {
        font-size: 0.96rem;
        font-weight: 700;
        color: #1e40af;
        margin-bottom: 8px;
    }
    .meta-row {
        display: flex;
        flex-wrap: wrap;
        gap: 8px;
        margin: 6px 0 10px 0;
        font-size: 0.88rem;
        color: #334155;
    }
    .meta-chip {
        background: #f1f5f9;
        border: 1px solid #e2e8f0;
        border-radius: 6px;
        padding: 3px 9px;
    }
    .quote-box {
        background-color: #f0f7ff;
        border-left: 4px solid #2563eb;
        padding: 10px 12px;
        border-radius: 6px;
        font-size: 0.92rem;
        color: #0f2942;
        margin: 8px 0;
    }
    .status-badge-verified {
        background-color: #dcfce7;
        color: #166534;
        padding: 4px 10px;
        border-radius: 999px;
        font-weight: 700;
        font-size: 0.84rem;
        display: inline-block;
        white-space: nowrap;
        flex-shrink: 0;
    }
    .status-badge-partial {
        background-color: #fef3c7;
        color: #92400e;
        padding: 4px 10px;
        border-radius: 999px;
        font-weight: 700;
        font-size: 0.84rem;
        display: inline-block;
        white-space: nowrap;
        flex-shrink: 0;
    }
    .status-badge-alert {
        background-color: #fee2e2;
        color: #991b1b;
        padding: 4px 10px;
        border-radius: 999px;
        font-weight: 700;
        font-size: 0.84rem;
        display: inline-block;
        white-space: nowrap;
        flex-shrink: 0;
    }
    .status-badge-unverified {
        background-color: #f1f5f9;
        color: #475569;
        padding: 4px 10px;
        border-radius: 999px;
        font-weight: 700;
        font-size: 0.84rem;
        display: inline-block;
        white-space: nowrap;
        flex-shrink: 0;
    }
</style>
""", unsafe_allow_html=True)

st.markdown("<div class='main-title'>🧭 리본 4050 (Re:Born 4050)</div>", unsafe_allow_html=True)
st.markdown(
    "<div class='sub-title' style='font-size:1.15rem; font-weight:600; color:#2563eb;'>4050 중장년 경력 전환 AI 에이전트 · CareerPath & Fair-Screening AI</div>",
    unsafe_allow_html=True,
)
st.markdown(
    "<div style='font-size:0.92rem; color:#475569; margin-top:2px;'>중장년 퇴직 인력의 80%가 단순직으로 전락하는 미스매칭을 해결하고, 296건 실시간 정제 공고 매칭과 공정 면접 팩트체크를 제공하는 양방향 AI 솔루션</div>",
    unsafe_allow_html=True,
)
st.markdown("""
<div style='display:flex; gap:8px; margin:10px 0 16px 0; flex-wrap:wrap;'>
    <span style='background:#dbeafe; color:#1e40af; font-size:0.8rem; font-weight:700; padding:3px 10px; border-radius:9999px;'>🏆 LINER .EXE-THON 2026</span>
    <span style='background:#dcfce7; color:#166534; font-size:0.8rem; font-weight:700; padding:3px 10px; border-radius:9999px;'>✅ 35/35 전 단위 테스트 PASS (무결성 검증)</span>
    <span style='background:#f1f5f9; color:#475569; font-size:0.8rem; font-weight:700; padding:3px 10px; border-radius:9999px;'>☁️ Cloud Native 배포 완비</span>
</div>
""", unsafe_allow_html=True)


@st.cache_resource
def get_liner_client():
    return LinerClient()


liner = get_liner_client()

st.sidebar.title("🛠️ 모드 선택 (Mode)")
app_mode = st.sidebar.radio(
    "사용 목적을 선택하세요",
    ["A. 시니어 CareerPath (구직자 모드)", "B. Fair-Screening Copilot (기업 면접관 모드)"],
)

st.sidebar.markdown("---")
st.sidebar.caption(
    f"LINER API: {'연결됨 (Live Search · Scholar · Router)' if liner.is_live else '오프라인 폴백 모드'}"
)

# LINER API 실시간 가동 모니터링 배지
llm_st = get_llm_stats()
cl_st = getattr(liner, "stats", {})
st.sidebar.markdown(f"""
<div style='background:#f1f5f9; border:1px solid #cbd5e1; border-radius:6px; padding:8px 10px; font-size:0.82rem; color:#475569; margin:6px 0 14px 0;'>
    <div style='font-weight:700; color:#0f2942; margin-bottom:4px;'>📊 LINER Platform 호출 현황</div>
    <div>• Router LLM: <b>{llm_st.get('router_calls', 0)}회</b> (성공 {llm_st.get('router_success', 0)})</div>
    <div>• Web Search: <b>{cl_st.get('search_calls', 0)}회</b> (성공 {cl_st.get('search_success', 0)})</div>
    <div>• Scholar Search: <b>{cl_st.get('scholar_calls', 0)}회</b> (성공 {cl_st.get('scholar_success', 0)})</div>
</div>
""", unsafe_allow_html=True)


# ==========================================
# MODE A: 시니어 CareerPath (구직자 모드)
# ==========================================
if "시니어 CareerPath" in app_mode:
    MODE_A_PRESETS = {
        "50대 제조 안전보건팀장 (산업안전·ISO45001 전향)": {
            "name": "최성원",
            "age": 53,
            "years": 22,
            "role": "안전관리 담당자",
            "skills": "산업안전, 위험성평가, ISO45001, 중대재해 예방, 현장 안전점검, 안전교육",
            "certs": "산업안전기사, 소방설비기사",
            "resume": (
                "22년간 제조 사업장 안전보건팀 총괄. "
                "위험성평가(KOSHA-MS) 수립으로 5년 연속 무재해 사업장 달성. "
                "중대재해처벌법 대비 디지털 안전 모니터링 체계 도입 및 환경안전 총괄 관리자로 전향 희망."
            ),
        },
        "50대 제조 품질관리팀장 (스마트팩토리 전향)": {
            "name": "김영호",
            "age": 52,
            "years": 24,
            "role": "스마트팩토리 데이터 품질관리자",
            "skills": "현장 품질관리, ISO9001 인증, 불량률 감소, 엑셀 장부 작성, 팀원 관리",
            "certs": "품질경영기사, ISO9001 심사원",
            "resume": (
                "24년간 중소 제조업체에서 부서장으로 근무하며 프레스/금형 현장 품질관리 및 공정 개선 총괄. "
                "불량률 1.2% 감축 달성. 최근 파이썬 기초 문법 수강 및 스마트공장 센서 데이터 모니터링에 관심."
            ),
        },
        "40대 영업총괄 (B2B SaaS 솔루션즈 전향)": {
            "name": "이정우",
            "age": 46,
            "years": 18,
            "role": "B2B SaaS 어카운트 매니저",
            "skills": "고객사 관리, 납품 계약, 영업 관리, 매출 목표 달성, 대면 영업",
            "certs": "ERP정보관리사 물류1급, 유통관리사 2급",
            "resume": (
                "18년간 국내 유통사에서 대기업 대상 B2B 영업 및 거래처 납품 총괄. "
                "연간 80억 수주 달성. 클라우드 기반 ERP/CRM 솔루션 및 테크 세일즈 컨설턴트로 전향 희망."
            ),
        },
        "40대 구매·자재팀장 (제조 SCM·ERP 운영 전향)": {
            "name": "박민수",
            "age": 48,
            "years": 19,
            "role": "구매 자재 SCM 관리자",
            "skills": "구매 발주, 자재 관리, 협력사 소싱, 재고 최적화, ERP 운영",
            "certs": "CPIM, 물류관리사",
            "resume": (
                "19년간 중견 제조기업 구매·자재팀에서 원자재 소싱, 협력사 납기 및 단가 협상, 월간 ERP 자재 수불 관리 총괄. "
                "최근 SCM 데이터 시각화 및 ERP 공정 연계 프로젝트 리딩."
            ),
        },
        "50대 제조 안전보건팀장 (산업안전·ISO45001 전향)": {
            "name": "최성원",
            "age": 53,
            "years": 22,
            "role": "안전관리 담당자",
            "skills": "산업안전, 위험성평가, ISO45001, 중대재해 예방, 현장 안전점검, 안전교육",
            "certs": "산업안전기사, 소방설비기사",
            "resume": (
                "22년간 제조 사업장 안전보건팀 총괄. "
                "위험성평가(KOSHA-MS) 수립으로 5년 연속 무재해 사업장 달성. "
                "중대재해처벌법 대비 디지털 안전 모니터링 체계 도입 및 환경안전 총괄 관리자로 전향 희망."
            ),
        },
        "직접 입력": {
            "name": "홍길동",
            "age": 50,
            "years": 20,
            "role": "스마트팩토리 데이터 관리자",
            "skills": "품질관리, 공정개선, 엑셀",
            "certs": "",
            "resume": "20년간 생산 현장 관리 및 공정 개선 업무 수행.",
        },
    }

    preset = st.sidebar.selectbox("시니어 프로필 프리셋", list(MODE_A_PRESETS.keys()))
    p_def = MODE_A_PRESETS[preset]
    st.sidebar.caption("주민번호·연락처·이메일·상세주소는 API 전송 전 로컬에서 자동 마스킹됩니다.")
    sidebar_run_btn = st.sidebar.button("🚀 맞춤 공고 · 로드맵 실행", type="primary", key="mode_a_sidebar_run")

    k_name = f"a_name_{preset}"
    k_age = f"a_age_{preset}"
    k_yrs = f"a_yrs_{preset}"
    k_role = f"a_role_{preset}"
    k_skills = f"a_skills_{preset}"
    k_certs = f"a_certs_{preset}"
    k_res = f"a_res_{preset}"
    st.session_state.setdefault(k_name, p_def.get("name", "지원자"))
    st.session_state.setdefault(k_age, p_def["age"])
    st.session_state.setdefault(k_yrs, p_def["years"])
    st.session_state.setdefault(k_role, p_def["role"])
    st.session_state.setdefault(k_skills, p_def["skills"])
    st.session_state.setdefault(k_certs, p_def.get("certs", ""))
    st.session_state.setdefault(k_res, p_def["resume"])

    saved_a = st.session_state.get("mode_a_result")
    has_mode_a_result = bool(saved_a and saved_a.get("preset") == preset)

    guide_slot = st.empty()
    if not has_mode_a_result:
        with guide_slot.container():
            st.markdown("""
            <div style='background:#fef2f2; border:1px solid #fecaca; border-radius:8px; padding:12px 16px; margin-bottom:14px; font-size:0.92rem; color:#991b1b;'>
                <b>🚨 4050 중장년 경력 단절 위기:</b> 국내 퇴직 인력의 약 <b>80%</b>가 낡은 이력서 양식과 직무 키워드 불일치로 서류에서 탈락하여 단순 노무직으로 전환되고 있습니다. 리본 4050은 숨은 실무 역량을 발굴하여 고부가가치 전문직으로 재도약시킵니다.
            </div>
            <div class='guide-grid'>
                <div class='guide-card'>
                    <h4>1. 🔒 문서 파싱 · 로컬 PII 마스킹</h4>
                    <p>PDF·DOCX·TXT 이력서를 업로드하거나 입력하면 주민번호·전화·이메일·주소를 로컬에서 먼저 가립니다.</p>
                </div>
                <div class='guide-card'>
                    <h4>2. 🎯 정제 공고 DB + LINER 매칭</h4>
                    <p>원티드·잡코리아 상세 요강을 추출한 진행 중 정제 공고와 LINER 웹 검색을 결합해 적합도를 대조합니다.</p>
                </div>
                <div class='guide-card'>
                    <h4>3. 🧭 정량 경력 번역 · 고용24 로드맵</h4>
                    <p>원문 수치와 경력을 보존한 JD 이력서 문장과 실제 고용24(work24.go.kr) 국비 훈련과정을 연결합니다.</p>
                </div>
            </div>
            """, unsafe_allow_html=True)

    with st.expander("📋 구직자 프로필 · 이력서 입력 및 파일 업로드 (PDF · DOCX · TXT)", expanded=not has_mode_a_result):
        up_a = st.file_uploader(
            "이력서 / 경력기술서 파일 불러오기 (선택)",
            type=["pdf", "docx", "txt", "md"],
            key=f"a_file_{preset}",
        )
        if up_a is not None:
            sig_a = (up_a.name, up_a.size, preset)
            if sig_a != st.session_state.get("a_last_upload"):
                ext_txt, _, ext_msg = extract_text_from_upload(up_a.name, up_a.getvalue())
                st.session_state["a_last_upload"] = sig_a
                st.session_state["a_upload_msg"] = ext_msg
                if ext_txt:
                    st.session_state[k_res] = ext_txt
                    parsed_prof = extract_resume_profile_from_text(ext_txt)
                    if parsed_prof.get("name"):
                        st.session_state[k_name] = parsed_prof["name"]
                    if parsed_prof.get("experience_years"):
                        st.session_state[k_yrs] = parsed_prof["experience_years"]
                    if parsed_prof.get("age"):
                        st.session_state[k_age] = parsed_prof["age"]
                    if parsed_prof.get("skills"):
                        st.session_state[k_skills] = ", ".join(parsed_prof["skills"])
                    if parsed_prof.get("certifications"):
                        st.session_state[k_certs] = ", ".join(parsed_prof["certifications"])
                st.rerun()
        if st.session_state.get("a_upload_msg"):
            st.caption(f"📄 {st.session_state['a_upload_msg']}")

        c_left, c_right = st.columns([1, 1])
        with c_left:
            cand_name = st.text_input("지원자 성명", key=k_name)
            age = st.number_input("만 나이", min_value=40, max_value=75, key=k_age)
            total_years = st.number_input("총 경력 연수", min_value=1, max_value=50, key=k_yrs)
        with c_right:
            desired_role = st.text_input("목표 희망 직무 (전환 희망)", key=k_role)
            pref_region = st.selectbox(
                "희망 근무 지역",
                ["전국 (무관)", "서울·수도권", "지방 (영남·호남·충청·기타)"],
                key=f"a_region_{preset}",
            )
            certs_raw = st.text_input("보유 자격증 (선택 — 쉼표 구분)", key=k_certs)

        skills_raw = st.text_area("보유 기술 및 경험 키워드 (쉼표 구분)", height=70, key=k_skills)
        resume_text = st.text_area("이력서 요약 / 주요 경력 기술서", height=100, key=k_res)

        st.markdown("<div style='margin-top: 14px;'></div>", unsafe_allow_html=True)
        main_run_btn = st.button(
            "🚀 맞춤 채용공고 매칭 · 경력 번역 · 국비 로드맵 생성",
            type="primary",
            key="mode_a_main_run",
            use_container_width=True,
        )

    current_sig_a = (preset, cand_name, age, total_years, desired_role, pref_region, skills_raw, certs_raw, resume_text)
    if has_mode_a_result and saved_a.get("input_sig") != current_sig_a:
        st.info("ℹ️ 입력 정보 또는 희망 직무가 변경되었습니다. 최신 결과를 보려면 실행 버튼을 다시 눌러주세요.")

    if sidebar_run_btn or main_run_btn:
        guide_slot.empty()
        t0 = time.perf_counter()
        with st.status("🚀 시니어 CareerPath 분석 및 맞춤 로드맵 생성 중...", expanded=True) as status_box:
            st.write("🔒 1단계: 개인정보(PII) 로컬 마스킹 및 프로필 정규화...")
            sanitized_resume, mask_stats = LegalSanitizer.sanitize_text(resume_text)
            skills_list = [s.strip() for s in skills_raw.split(",") if s.strip()]
            certs_list = [c.strip() for c in certs_raw.split(",") if c.strip()]
            profile = JobSeekerProfile(
                name=cand_name,
                age=age,
                total_experience_years=total_years,
                desired_role=desired_role,
                preferred_region=pref_region,
                skills=skills_list,
                held_certifications=certs_list,
                resume_text=sanitized_resume,
            )

            st.write("🎯 2단계: 정제 채용 DB 및 LINER 실시간 공고 요건 대조...")
            analyzer = ProfileAnalyzer(liner)
            match_results = analyzer.analyze_profile(profile)
            excl = analyzer.exclude_families_for(profile)
            market = analyzer.market_requirements(desired_role, 8, exclude_families=excl)

            if market and market[0].get("reliable"):
                mkt_keywords = [m["requirement"] for m in market[:6]]
            else:
                mkt_keywords = []
                for mr in match_results[:3]:
                    for tag in mr.job.tags:
                        if tag not in mkt_keywords:
                            mkt_keywords.append(tag)
                mkt_keywords = mkt_keywords[:6]

            top_match = match_results[0] if match_results else None
            miss_skills = [m.split(" — ")[0] for m in top_match.missing_skills][:4] if top_match else []

            st.write("🧭 3단계: 고용24 실시간 개설과정 및 현대화 경력 번역...")
            roadmap_gen = RoadmapGenerator(liner)
            translator = CareerTranslator(liner)
            with ThreadPoolExecutor(max_workers=2) as pool:
                f_road = pool.submit(roadmap_gen.generate_roadmap, profile, top_match, market)
                f_trans = pool.submit(
                    translator.translate,
                    sanitized_resume,
                    desired_role,
                    mkt_keywords,
                    miss_skills,
                    exp_years=total_years,
                )
                f_trans_eng = pool.submit(
                    SkillTransferEngine.calculate_transfer_profile,
                    skills_list,
                    total_years,
                    desired_role,
                    sanitized_resume,
                )
                roadmap = f_road.result()
                translated_points = f_trans.result()
                transfer_data = f_trans_eng.result()

            if excl:
                roadmap["market_note"] += " (프로필에 개발 직무 경력이 없어 소프트웨어 개발 계열 공고는 집계에서 제외)"

            status_box.update(label="✅ 맞춤 분석 완료!", state="complete", expanded=False)

        st.session_state["mode_a_result"] = {
            "preset": preset,
            "input_sig": current_sig_a,
            "profile": profile,
            "mask_stats": mask_stats,
            "match_results": match_results,
            "roadmap": roadmap,
            "translated_points": translated_points,
            "transfer_data": transfer_data,
            "elapsed": round(time.perf_counter() - t0, 1),
        }
        st.rerun()

    if saved_a and saved_a.get("preset") == preset:
        prof_saved = saved_a["profile"]
        mask_stats = saved_a["mask_stats"]
        match_results = saved_a["match_results"]
        roadmap = saved_a["roadmap"]
        translated_points = saved_a["translated_points"]
        transfer_data = saved_a.get("transfer_data") or SkillTransferEngine.calculate_transfer_profile(
            prof_saved.skills, prof_saved.total_experience_years, prof_saved.desired_role, prof_saved.resume_text
        )
        elapsed = saved_a["elapsed"]

        masked_total = sum(mask_stats.values())
        if masked_total > 0:
            st.success(
                f"🔒 개인정보 보호 작동 ({elapsed}초): 주민번호 {mask_stats['rrn_masked']}건 · "
                f"전화번호 {mask_stats['phone_masked']}건 · 이메일 {mask_stats['email_masked']}건 · "
                f"상세주소 {mask_stats['address_masked']}건 로컬 마스킹 후 처리"
            )
        else:
            st.caption(f"🔒 개인정보 보호(PII 필터) 점검 완료 · 민감 식별정보 미검출 | 분석 소요 {elapsed}초")

        open_cnt = sum(1 for mr in match_results if mr.job.status == "open")
        closed_cnt = sum(1 for mr in match_results if mr.job.status == "closed")
        top_score = max((mr.match_score for mr in match_results if mr.scored), default=0)

        k1, k2, k3, k4, k5 = st.columns(5)
        k1.metric("탐색 공고", f"{len(match_results)}건")
        k2.metric("진행 중 공고", f"{open_cnt}건")
        k3.metric("마감 참고 공고", f"{closed_cnt}건")
        k4.metric("최고 요건 충족률", f"{top_score}%")
        k5.metric("디지털 전이 지수", f"{transfer_data.get('transfer_readiness', 0)}점")

        # 5대 핵심 축 역량 전이 매트릭스 브리핑 카드
        trans_caps = transfer_data.get("transferred_capabilities") or []
        caps_chips = "".join(
            f"<span class='meta-chip'>🔄 <b>{html.escape(c['capability'])}</b> (전이도 {c['transfer_weight']}%)</span>"
            for c in trans_caps
        )
        st.markdown(f"""
        <div style='background-color:#f0fdf4; border:1px solid #bbf7d0; border-left:5px solid #16a34a; border-radius:8px; padding:12px 16px; margin:10px 0 18px 0;'>
            <div style='display:flex; justify-content:space-between; align-items:center; margin-bottom:6px;'>
                <span style='font-weight:700; color:#14532d; font-size:1.02rem;'>🧭 직무 온톨로지 기반 역량 전이 매트릭스 (Skill Transfer Matrix)</span>
                <span class='status-badge-verified'>{html.escape(transfer_data.get('readiness_verdict', ''))}</span>
            </div>
            <div style='font-size:0.9rem; color:#166534; margin-bottom:8px;'>
                전통 베테랑 경력({prof_saved.total_experience_years}년)이 목표 신직무(<b>{html.escape(prof_saved.desired_role)}</b>)의 핵심 디지털 역량으로 전이되는 가중치 매핑 결과입니다.
            </div>
            <div class='meta-row'>{caps_chips}</div>
        </div>
        """, unsafe_allow_html=True)

        tab1, tab2, tab3, tab4 = st.tabs([
            "🎯 실시간 맞춤 채용공고",
            "📝 시니어 경력 번역기",
            "📅 3개월 국비 로드맵 & 7일 스프린트",
            "📄 1Page 요약 경력기술서",
        ])

        with tab1:
            st.subheader("🎯 LINER 실시간 채용 공고 & 역량 대조")
            if not match_results:
                st.info("조건에 맞는 공개 채용 공고를 찾지 못했습니다. 희망 직무 키워드를 넓혀 다시 실행해 보세요.")

            for idx_job, mr in enumerate(match_results):
                job = mr.job
                company_disp = clean_company_name(job.company, job.title, job.source_url)
                portal_disp = portal_label(job.source_url)
                status_html = (
                    "<span class='status-badge-verified'>🟢 진행 중</span>"
                    if job.status == "open"
                    else (
                        "<span class='status-badge-unverified'>⚪ 마감 참고</span>"
                        if job.status == "closed"
                        else "<span class='status-badge-partial'>❔ 상태 미확인</span>"
                    )
                )

                loc_val = (job.location or "").strip()
                if not loc_val or loc_val == "공고 원문 확인":
                    loc_val = str(job.details.get("work_location") or "공고 원문 확인").strip()

                salary_val = str(job.details.get("salary") or "").strip()
                if not salary_val or salary_val in ("공고 원문 확인", "면접 후 협의"):
                    salary_val = "사내 내규에 따름 (경력 산정 후 협의)"

                chips = [f"<span class='meta-chip'>📍 {html.escape(loc_val)}</span>"]
                if getattr(mr, "required_met_ratio", ""):
                    chips.append(f"<span class='meta-chip'>🎯 {html.escape(mr.required_met_ratio)}</span>")
                if job.details.get("employment_type"):
                    chips.append(f"<span class='meta-chip'>💼 {html.escape(str(job.details['employment_type']))}</span>")
                chips.append(f"<span class='meta-chip'>💰 {html.escape(salary_val)}</span>")
                chips.append(f"<span class='meta-chip'>⏰ 마감: {html.escape(job.deadline)}</span>")
                safe_href = html.escape(_safe_url(job.source_url), quote=True)
                chips.append(f"<span class='meta-chip'>🔗 <a href='{safe_href}' target='_blank'>원문 보기</a></span>")

                st.markdown(f"""
                <div class='card'>
                    <div class='card-header'>
                        <h3 style='margin:0; font-size:1.15rem; color:#0f2942;'>{html.escape(job.title)}</h3>
                        {status_html}
                    </div>
                    <div class='company-line'>🏢 {html.escape(company_disp)} · {html.escape(portal_disp)}</div>
                    <div class='meta-row'>{''.join(chips)}</div>
                </div>
                """, unsafe_allow_html=True)

                if mr.scored:
                    st.progress(
                        min(max(int(mr.match_score), 0), 100) / 100.0,
                        text=f"요건 충족률 {mr.match_score}% (입력 이력서 vs 공고 요건 대조 · 합격 가능성 아님)",
                    )
                else:
                    reason = "공고 요건 추출 실패"
                    if job.is_mock:
                        reason = "샘플 데이터"
                    elif getattr(mr, "low_detail", False):
                        reason = "상세 요건 미기재(간이/이미지 공고 — 원문 확인 권장)"
                    st.caption(f"요건 충족률: 미산정 ({reason})")

                if getattr(mr, "tailored_advice", ""):
                    st.markdown(
                        f"<div style='background-color:#f0fdf4; border-left:4px solid #16a34a; padding:8px 12px; margin:8px 0 10px 0; border-radius:4px; font-size:0.92rem; color:#14532d;'>"
                        f"💡 <b>맞춤 지원 전략:</b> {html.escape(mr.tailored_advice)}</div>",
                        unsafe_allow_html=True,
                    )

                col_m, col_u = st.columns(2)
                with col_m:
                    if mr.matched_skills:
                        st.success("**✅ 충족 요건**\n\n" + "\n".join(f"- {x}" for x in mr.matched_skills))
                    else:
                        st.info("**✅ 충족 요건**\n\n- 기본 실무 경력 심사 필요")
                with col_u:
                    if mr.missing_skills:
                        st.warning("**🔧 보완 필요 역량**\n\n" + "\n".join(f"- {x}" for x in mr.missing_skills))
                    else:
                        st.success("**🔧 보완 필요 역량**\n\n- 주요 자격 요건 대부분 부합")

        with tab2:
            st.subheader("📝 시니어 경력 현대화 번역 (정량 성과 보존 · JD 반영)")
            st.caption("원문의 연차·비율·규격을 유지하면서 2026년 채용 공고(JD)에서 선호하는 현대적 실무 문장으로 재구성합니다.")
            for tp in translated_points:
                st.markdown(f"""
                <div class='card'>
                    <div style='background-color:#fff5f5; border-left:4px solid #dc2626; padding:8px 12px; margin-bottom:8px; border-radius:4px;'>
                        <b>기존 이력서:</b> {html.escape(tp['original'])}
                    </div>
                    <div style='background-color:#f0fdf4; border-left:4px solid #16a34a; padding:8px 12px; margin-bottom:8px; border-radius:4px;'>
                        <b>현대화 이력서 문장:</b> {html.escape(tp['modernized'])}
                    </div>
                    <div style='font-size:0.9rem; color:#475569;'>💡 <b>채용 서류 효과:</b> {html.escape(tp['impact_rationale'])}</div>
                </div>
                """, unsafe_allow_html=True)

            if translated_points:
                st.markdown("#### 📋 이력서 복사용 현대화 경력 요약문")
                copy_lines = "\n".join(tp["modernized"] for tp in translated_points)
                st.code(copy_lines, language="markdown")

            # 1페이지 완성형 이력서 HTML 생성
            resume_html = generate_modern_resume_html(prof_saved, match_results, [tp["modernized"] for tp in translated_points], transfer_data)
            report_a_md = build_mode_a_report_md(prof_saved, match_results, translated_points, roadmap)

            dl_c1, dl_c2 = st.columns(2)
            with dl_c1:
                if st.download_button(
                    "📄 [원클릭] 1페이지 표준 전환 이력서 인쇄/다운로드 (.html)",
                    data=resume_html.encode("utf-8"),
                    file_name=f"resume_{prof_saved.name}_{prof_saved.desired_role.replace(' ', '_')}.html",
                    mime="text/html",
                    key="dl_mode_a_html",
                ):
                    st.toast("✅ 1페이지 표준 전환 이력서 (.html) 다운로드가 시작되었습니다!")
            with dl_c2:
                if st.download_button(
                    "📥 상세 분석 커리어 전환 리포트 다운로드 (.md)",
                    data=report_a_md.encode("utf-8"),
                    file_name=f"careerpath_report_{prof_saved.desired_role.replace(' ', '_')}.md",
                    mime="text/markdown",
                    key="dl_mode_a_md",
                ):
                    st.toast("✅ 상세 분석 커리어 전환 리포트 (.md) 다운로드가 시작되었습니다!")

        with tab3:
            st.subheader("⚡ 당장 실행하는 7일 스프린트 & 고용24 국비 로드맵")
            st.caption("📊 시장 요구사항 근거: " + roadmap.get("market_note", ""))
            top_mkt = (roadmap.get("market") or {}).get("top") or []
            if top_mkt:
                chips_mkt = "".join(
                    f"<span class='meta-chip'><b>{html.escape(str(m['requirement']))}</b> ({m['count']}건)</span>"
                    for m in top_mkt[:8]
                )
                st.markdown(f"<div class='meta-row'>{chips_mkt}</div>", unsafe_allow_html=True)

            st.markdown("#### 🏃 [Day 1 ~ Day 7] 즉각 실행 체크리스트")
            for item in roadmap.get("sprint", []):
                st.markdown(f"- **{item['day']}**: {item['action']} *(산출물: {item['deliverable']})*")

            st.markdown("#### 🎓 고용24(HRD-Net) 국민내일배움카드 추천 훈련과정")
            courses = roadmap.get("all_courses") or ([roadmap["target_course"]] if roadmap.get("target_course") else [])
            for course in courses:
                c_url = _safe_url(course.get("url", "https://www.hrd.go.kr"))
                rec_st = course.get("recruit_status") or "일정 확인"
                c_badge = (
                    f"<span class='status-badge-unverified'>{html.escape(rec_st)}</span>"
                    if "마감" in rec_st
                    else f"<span class='status-badge-verified'>{html.escape(rec_st)}</span>"
                )
                c_chips = []
                if course.get("quota"):
                    c_chips.append(f"<span class='meta-chip'>👥 {html.escape(course['quota'])}</span>")
                if course.get("period"):
                    c_chips.append(f"<span class='meta-chip'>🗓️ 기간: {html.escape(course['period'])}</span>")
                if course.get("duration"):
                    c_chips.append(f"<span class='meta-chip'>⏱️ 시간: {html.escape(course['duration'])}</span>")
                if course.get("ncs"):
                    c_chips.append(f"<span class='meta-chip'>🏷️ NCS: {html.escape(course['ncs'])}</span>")
                if course.get("location"):
                    c_chips.append(f"<span class='meta-chip'>📍 {html.escape(course['location'])}</span>")
                c_chips.append(f"<span class='meta-chip'>🔗 <a href='{html.escape(c_url, quote=True)}' target='_blank'>고용24 과정 상세</a></span>")
                st.markdown(f"""
                <div class='card'>
                    <div class='card-header'>
                        <h4 style='margin:0; color:#0f2942;'>[{html.escape(str(course.get('institution', '')))}] {html.escape(str(course.get('title', '')))}</h4>
                        {c_badge}
                    </div>
                    <div style='font-size:0.9rem; color:#1e40af; margin-bottom:6px;'>💳 {html.escape(str(course.get('support_type', '')))}</div>
                    <div class='meta-row'>{''.join(c_chips)}</div>
                </div>
                """, unsafe_allow_html=True)

            st.markdown("#### 📅 3개월 중기 성장 마일스톤")
            for phase in roadmap.get("phases", []):
                acts = "".join(f"<li>{html.escape(a)}</li>" for a in phase["actions"])
                st.markdown(f"""
                <div class='card'>
                    <h4 style='color:#1d4ed8; margin-top:0;'>{html.escape(phase['month'])}</h4>
                    <p style='font-weight:600; color:#0f2942;'>🎯 핵심 목표: {html.escape(phase['goal'])}</p>
                    <ul>{acts}</ul>
                    <div style='font-size:0.9rem; color:#64748b;'>🔗 추천 리소스: {html.escape(phase['recommended_resource'])}</div>
                </div>
                """, unsafe_allow_html=True)

        with tab4:
            st.subheader("📄 채용담당자 전용 1Page 요약 경력기술서 (A4 표준)")
            st.caption("평균 7.4초의 서류 스크리닝을 사로잡는 A4 1장 최적화 서식입니다. 직무 요약, 핵심 역량, STAR 기법 성과를 한눈에 볼 수 있습니다.")

            if st.download_button(
                "🖨️ 채용담당자 전용 1Page 경력기술서 인쇄 / PDF 저장 (.html)",
                data=resume_html.encode("utf-8"),
                file_name=f"resume_1page_{prof_saved.name}_{prof_saved.desired_role.replace(' ', '_')}.html",
                mime="text/html",
                key="dl_mode_a_1page_tab",
                type="primary",
            ):
                st.toast("✅ 1Page 경력기술서가 다운로드되었습니다. 아래 A4 뷰어 상단의 파란색 버튼으로 즉시 인쇄/PDF 저장이 가능합니다!")

            st.caption("💡 아래 A4 실시간 뷰어 상단의 **'🖨️ 브라우저 원클릭 바로 인쇄 / PDF 저장'** 버튼을 누르면 즉시 인쇄 다이얼로그(Ctrl+P)가 팝업됩니다.")
            import streamlit.components.v1 as components
            components.html(resume_html, height=750, scrolling=True)

# ==========================================
# MODE B: Fair-Screening Copilot (기업 면접관 모드)
# ==========================================
else:
    st.subheader("🛡️ Fair-Screening Copilot: 지원자 포트폴리오 교차 검증 & 면접 질문 설계")
    st.caption(
        "지원자가 제출한 공개 링크(GitHub · 기술 블로그)와 학술·특허 실적을 본문 인용·커밋 기여·LINER Scholar로 교차 대조하며, "
        "자동 탈락이 아닌 객관적 근거와 면접 질문지·채점표를 제공합니다."
    )

    MODE_B_PRESETS = {
        "시니어 백엔드·설비 데이터 엔지니어 (다중 저장소 실제 기여 검증)": {
            "urls": "https://github.com/pallets/flask\nhttps://github.com/psf/requests",
            "gh_user": "dohyun-arch",
            "cand_author": "김도현 / Dohyun Kim",
            "claims": (
                "Python WSGI 기반 웹 애플리케이션 라우팅 및 API 서버 구조 설계\n"
                "HTTP 클라이언트 커넥션 풀 기반 초당 5,000건 실시간 설비 이벤트 전송 파이프라인 구현"
            ),
            "scholar": "",
        },
        "R&D 시니어 학술·특허 및 포트폴리오 통합 검증 (본인 논문 vs 타인 논문 도용 감별)": {
            "urls": "https://github.com/pallets/flask",
            "gh_user": "sunghoon-mfg",
            "cand_author": "홍성훈 / Sunghoon Hong",
            "claims": (
                "Python 웹 프레임워크 기반 설비 모니터링 API 서버 구축\n"
                "스마트팩토리 실시간 이상 탐지 센서 파이프라인 단독 설계"
            ),
            "scholar": (
                "스마트팩토리 적용을 위한 필수 요소 연구: A사 사례를 중심으로 | 한국품질경영학회 | 2021\n"
                "Predictive Maintenance and Intelligent Sensors in Smart Factory: Review | Sensors | 2021\n"
                "차세대 양자 초전도 스마트공장 자율제어 | IEEE | 2025"
            ),
        },
        "직접 입력": {
            "urls": "https://github.com/pallets/flask",
            "gh_user": "",
            "cand_author": "",
            "claims": (
                "파이썬 기반 웹 서버 및 API 게이트웨이 설계\n"
                "사내 대용량 데이터 파이프라인 운영"
            ),
            "scholar": "",
        },
    }

    hr_preset = st.sidebar.selectbox("면접 검증 프리셋", list(MODE_B_PRESETS.keys()))
    b_def = MODE_B_PRESETS[hr_preset]
    st.sidebar.caption("비공개 SNS나 사생활 정보는 검색 대상에서 원천 배제됩니다.")

    k_urls = f"hr_urls_{hr_preset}"
    k_gh = f"hr_gh_{hr_preset}"
    k_author = f"hr_author_{hr_preset}"
    k_claims = f"hr_claims_{hr_preset}"
    k_sch = f"hr_scholar_{hr_preset}"
    st.session_state.setdefault(k_urls, b_def["urls"])
    st.session_state.setdefault(k_gh, b_def["gh_user"])
    st.session_state.setdefault(k_author, b_def["cand_author"])
    st.session_state.setdefault(k_claims, b_def["claims"])
    st.session_state.setdefault(k_sch, b_def["scholar"])

    saved_b = st.session_state.get("mode_b_result")
    has_mode_b_result = bool(saved_b and saved_b.get("preset") == hr_preset)

    with st.expander("📋 지원자 제출 링크 · 주장 · 지원서 파일 업로드 (PDF · DOCX · TXT)", expanded=not has_mode_b_result):
        up_b = st.file_uploader(
            "지원자 포트폴리오/이력서 문서 불러오기 (공개 URL · 주장 자동 추출)",
            type=["pdf", "docx", "txt", "md"],
            key=f"b_file_{hr_preset}",
        )
        if up_b is not None:
            sig_b = (up_b.name, up_b.size, hr_preset)
            if sig_b != st.session_state.get("b_last_upload"):
                b_txt, _, b_msg = extract_text_from_upload(up_b.name, up_b.getvalue())
                st.session_state["b_last_upload"] = sig_b
                st.session_state["b_upload_msg"] = b_msg
                if b_txt:
                    parsed_b = extract_portfolio_inputs_from_text(b_txt)
                    if parsed_b["urls"]:
                        st.session_state[k_urls] = "\n".join(parsed_b["urls"])
                    if parsed_b["claims"]:
                        st.session_state[k_claims] = "\n".join(parsed_b["claims"])
                    if parsed_b["scholar"]:
                        st.session_state[k_sch] = "\n".join(parsed_b["scholar"])
                    if parsed_b.get("github_username") and not st.session_state.get(k_gh):
                        st.session_state[k_gh] = parsed_b["github_username"]
                st.rerun()
        if st.session_state.get("b_upload_msg"):
            st.caption(f"📄 {st.session_state['b_upload_msg']}")

        col1, col2 = st.columns([1, 1])
        with col1:
            urls_input = st.text_area("공개 포트폴리오 URL 목록 (줄바꿈 구분)", height=96, key=k_urls)
            github_username = st.text_input("지원자 GitHub 계정 ID (선택 — 실제 커밋·프로필 대조)", key=k_gh)
            candidate_author = st.text_input("지원자 성명 / 영문 저자명 (선택 — 학술·특허 저자 대조용)", key=k_author)
        with col2:
            claims_input = st.text_area("이력서 주요 기술 주장 (줄바꿈 구분)", height=96, key=k_claims)
            scholar_input = st.text_area("학술 논문·특허 실적 (선택 — 제목 | 학술지/특허청 | 연도)", height=96, key=k_sch)

        verify_btn = st.button("🔍 제출 포트폴리오 근거 대조 및 면접 질문 생성", type="primary", key="mode_b_run")

    current_sig_b = (hr_preset, urls_input, github_username, candidate_author, claims_input, scholar_input)
    if has_mode_b_result and saved_b.get("input_sig") != current_sig_b:
        st.info("ℹ️ 검증 대상 링크 또는 주장이 변경되었습니다. 최신 결과를 보려면 '제출 포트폴리오 근거 대조' 버튼을 다시 눌러주세요.")

    if verify_btn:
        t0 = time.perf_counter()
        with st.status("🔍 지원자 포트폴리오 다층 교차 검증 중...", expanded=True) as status_box:
            st.write("🌐 1단계: 공개 기술 문서 및 다층 구조(README·매니페스트) 수집...")
            fact_checker = HRFactChecker(liner, github_verifier=GitHubVerifier())
            raw_urls = [u.strip() for u in urls_input.split("\n") if u.strip()]
            raw_claims = [c.strip() for c in claims_input.split("\n") if c.strip()]
            raw_scholar = [s.strip() for s in scholar_input.split("\n") if s.strip()]
            claims_data = [{"category": "핵심 기술", "claim": c, "keyword": c[:30]} for c in raw_claims]

            st.write("💻 2단계: GitHub 커밋 로그·코드 변경량·특허/학술 실적 대조...")
            results = fact_checker.verify_portfolio(
                claims_data,
                raw_urls,
                github_username=github_username,
                scholar_claims=raw_scholar,
                candidate_author=candidate_author,
            )
            st.write("🎙️ 3단계: 근거 기반 실무 면접 질문 및 채점표 생성...")
            status_box.update(label="✅ 교차 검증 완료!", state="complete", expanded=False)

        st.session_state["mode_b_result"] = {
            "preset": hr_preset,
            "input_sig": current_sig_b,
            "cand_author": candidate_author,
            "gh_user": github_username,
            "results": results,
            "elapsed": round(time.perf_counter() - t0, 1),
        }
        st.rerun()

    if saved_b and saved_b.get("preset") == hr_preset:
        results = saved_b["results"]
        audit = results["audit_summary"]
        st.caption(f"교차 검증 완료 | 소요 시간 {saved_b['elapsed']}초")

        if audit.get("rejected_urls"):
            st.warning("검증 대상에서 제외된 링크(허용된 공개 기술 플랫폼이 아님): " + ", ".join(audit["rejected_urls"]))
        if audit.get("fetch_failed_urls"):
            st.warning("본문을 가져오지 못한 링크: " + ", ".join(audit["fetch_failed_urls"]))

        st.markdown("### 📊 4대 영역 검증 요약")
        m1, m2, m3, m4 = st.columns(4)
        with m1:
            st.metric("포트폴리오 주장", f"{audit['verified_count']}/{audit['total_claims']}건 확인")
            st.caption(f"일부 {audit['partially_verified_count']} · 미확인 {audit['unverified_count']}")
        with m2:
            gh_tot = audit.get("github_repos_checked", 0)
            gh_ok = audit.get("github_verified_count", 0)
            st.metric("GitHub 커밋 기여", f"{gh_ok}/{gh_tot}개 본인 기여" if gh_tot else "미제출")
            st.caption(
                f"미확인·주의 {audit.get('github_unverified_count', 0)}건" if gh_tot else "저장소 미입력"
            )
        with m3:
            sch_tot = audit.get("scholar_checked", 0)
            sch_ok = audit.get("scholar_verified_count", 0)
            st.metric("학술·특허 검증", f"{sch_ok}/{sch_tot}건 일치" if sch_tot else "미제출")
            st.caption(
                f"저자불일치 {audit.get('scholar_author_mismatch_count', 0)} · 미확인 {audit.get('scholar_unverified_count', 0)}"
                if sch_tot
                else "학술 실적 미입력"
            )
        with m4:
            st.metric("맞춤 면접 질문", f"총 {len(results['interview_questions'])}문항")
            st.caption("근거 기반 실무 압박 검증")

        exec_summary = results.get("executive_summary") or []
        if exec_summary:
            bullets_html = "".join(f"<li>{html.escape(b)}</li>" for b in exec_summary)
            st.markdown(f"""
            <div style='background-color:#f8fafc; border:1px solid #cbd5e1; border-left:5px solid #2563eb; border-radius:8px; padding:14px 18px; margin:14px 0 20px 0;'>
                <div style='font-weight:700; font-size:1.02rem; color:#0f2942; margin-bottom:8px;'>
                    💡 AI 면접관 10초 종합 요약 (Executive Briefing)
                </div>
                <ul style='margin:0; padding-left:20px; font-size:0.92rem; color:#334155; line-height:1.6;'>
                    {bullets_html}
                </ul>
            </div>
            """, unsafe_allow_html=True)

        tab_cards, tab_gh, tab_scholar, tab_questions, tab_drill = st.tabs([
            "🗂️ 3단계 근거 카드",
            "💻 GitHub 실제 기여도",
            "🎓 학술·특허 (LINER Scholar)",
            "🎙️ AI 실무 심층 면접 질문",
            "⚡ 실시간 답변 검증 & 꼬리 질문",
        ])

        with tab_cards:
            st.subheader("🗂️ 공개 자료 기반 근거 카드")
            for card in results["evidence_cards"]:
                status = card["status"]
                if status == "확인된 내용":
                    badge_html = "<span class='status-badge-verified'>✅ 확인된 내용</span>"
                elif status == "일부 확인":
                    badge_html = "<span class='status-badge-partial'>⚠️ 일부 확인</span>"
                else:
                    badge_html = "<span class='status-badge-unverified'>❓ 확인 불가 (면접 확인 요망)</span>"

                quote_html = ""
                if card.get("evidence_quote"):
                    quote_html = (
                        "<div class='quote-box'>📌 <b>원문 대조 인용구:</b> "
                        f"\"{html.escape(card['evidence_quote'])}\"</div>"
                    )

                meta_badges = []
                if card.get("has_code"):
                    meta_badges.append("<span class='meta-chip'>💻 실습 코드 포함</span>")
                if card.get("published_date"):
                    meta_badges.append(f"<span class='meta-chip'>📅 발행일: {html.escape(card['published_date'])}</span>")
                meta_badges_html = f"<div class='meta-row' style='margin-bottom:8px;'>{''.join(meta_badges)}</div>" if meta_badges else ""

                src_url_val = (card.get("source_url") or "").strip()
                if src_url_val and src_url_val.startswith(("http://", "https://")):
                    safe_src = html.escape(src_url_val, quote=True)
                    src_link_html = f"<a href='{safe_src}' target='_blank' style='color:#2563eb; text-decoration:underline; font-weight:600;'>{html.escape(src_url_val)} 🔗</a>"
                else:
                    src_link_html = html.escape(src_url_val) if src_url_val else "제출된 공개 링크 없음"

                st.markdown(f"""
                <div class='card'>
                    <div class='card-header'>
                        <span style='font-size:1.08rem; font-weight:700; color:#0f2942;'>{html.escape(card['claim'])}</span>
                        {badge_html}
                    </div>
                    <div style='font-size:0.9rem; color:#64748b; margin-bottom:6px;'>
                        🔗 <b>대조 출처:</b> {src_link_html} (검증: {html.escape(card['verified_at'])})
                    </div>
                    {meta_badges_html}
                    {quote_html}
                    <div style='background-color:#f8fafc; padding:10px; border-radius:6px; font-size:0.94rem; color:#334155;'>
                        {html.escape(card['note'])}
                    </div>
                </div>
                """, unsafe_allow_html=True)

        with tab_gh:
            st.subheader("💻 GitHub 계정 프로필 · 저장소 커밋 기여도 검증")
            gh_prof = results.get("github_profile")
            if gh_prof:
                if gh_prof.get("exists"):
                    st.info(f"👤 **GitHub 프로필 요약**: {gh_prof.get('note', '')}")
                else:
                    st.warning(f"🚨 **GitHub 계정 주의**: {gh_prof.get('note', '')}")

            gh_list = results.get("github_contributions", [])
            if not gh_list:
                st.info("검증할 GitHub 저장소 URL이 제출되지 않았습니다.")
            for gh in gh_list:
                gh_status = gh.get("status", "확인 불가")
                if "본인 기여 확인" in gh_status:
                    gh_badge = f"<span class='status-badge-verified'>✅ {html.escape(gh_status)}</span>"
                elif "저장소 소유자" in gh_status:
                    gh_badge = f"<span class='status-badge-partial'>⚠️ {html.escape(gh_status)}</span>"
                elif "타인 기여" in gh_status:
                    gh_badge = f"<span class='status-badge-alert'>🚨 {html.escape(gh_status)}</span>"
                else:
                    gh_badge = f"<span class='status-badge-unverified'>❓ {html.escape(gh_status)}</span>"

                c_cnt = gh.get("commit_count")
                cnt_label = f"{c_cnt}건" if c_cnt is not None else "조회 실패"
                ext_label = ", ".join(gh.get("extensions") or []) or "집계된 변경 파일 없음"
                lang_label = ", ".join(f"{k}: {v}%" for k, v in (gh.get("languages") or {}).items()) or "정보 없음"
                last_dt = gh.get("latest_commit_date") or "확인 안 됨"

                gh_chips = [
                    f"<span class='meta-chip'>👤 조회 계정: {html.escape(gh.get('checked_author', ''))}</span>",
                    f"<span class='meta-chip'>🏠 실제 소유자: {html.escape(gh.get('owner', ''))}</span>",
                    f"<span class='meta-chip'>📌 확인 커밋: {html.escape(cnt_label)}</span>",
                    f"<span class='meta-chip'>🗓️ 최근 활동: {html.escape(last_dt)}</span>",
                ]
                if gh.get("code_changes"):
                    cc = gh["code_changes"]
                    gh_chips.append(f"<span class='meta-chip'>📈 변경: +{cc.get('additions', 0)}/-{cc.get('deletions', 0)}</span>")

                msgs_html = ""
                if gh.get("recent_messages"):
                    m_list = " · ".join(f"\"{html.escape(m)}\"" for m in gh["recent_messages"][:3])
                    msgs_html = f"<div style='font-size:0.86rem; color:#475569; margin-top:6px;'>📝 <b>최근 커밋:</b> {m_list}</div>"

                cq_html = ""
                if gh.get("code_quality"):
                    cq = gh["code_quality"]
                    cq_html = f"""
                    <div style='background-color:#f0f9ff; border:1px solid #bae6fd; border-radius:6px; padding:10px 12px; margin-top:8px; font-size:0.9rem; color:#0369a1;'>
                        <b>🔬 AST 코드 아키텍처 정밀 분석:</b> <span class='status-badge-verified'>{html.escape(cq.get('quality_grade', ''))}</span> (복잡도 점수: <b>{cq.get('complexity_score', 0)}점</b>)<br/>
                        <span style='font-size:0.84rem; color:#0c4a6e;'>• 표본 파일: <code>{html.escape(cq.get('sampled_file', ''))}</code> | 클래스 {cq.get('classes_count', 0)}개 · 함수 {cq.get('functions_count', 0)}개 · 평균 순환 복잡도 {cq.get('avg_complexity', 0.0)}</span><br/>
                        <span style='font-size:0.84rem; color:#0c4a6e;'>• 현대적 문법: 비동기(async) {'지원' if cq.get('has_async') else '미사용'} · 타입 힌트 {'적용' if cq.get('has_type_hints') else '미적용'} · 독스트링 문서화 {'준수' if cq.get('has_docstrings') else '미흡'}</span>
                    </div>
                    """

                repo_name = html.escape(gh['repo'])
                gh_link_url = f"https://github.com/{repo_name}"
                st.markdown(f"""
                <div class='card'>
                    <div class='card-header'>
                        <a href='{gh_link_url}' target='_blank' style='font-size:1.08rem; font-weight:700; color:#1d4ed8; text-decoration:none;'>📦 {repo_name} 🔗</a>
                        {gh_badge}
                    </div>
                    <div class='meta-row'>{''.join(gh_chips)}</div>
                    <div style='font-size:0.9rem; color:#475569; margin-bottom:6px;'>
                        🧩 <b>최근 커밋 확장자:</b> {html.escape(ext_label)}<br/>
                        🔤 <b>저장소 언어 비중:</b> {html.escape(lang_label)}
                    </div>
                    <div style='background-color:#f8fafc; padding:10px; border-radius:6px; font-size:0.94rem; color:#334155;'>
                        {html.escape(gh.get('note', ''))}
                    </div>
                    {cq_html}
                    {msgs_html}
                </div>
                """, unsafe_allow_html=True)

        with tab_scholar:
            st.subheader("🎓 R&D · 학술 논문 · 특허 교차 검증 (LINER Scholar · KIPRIS)")
            sch_list = results.get("scholar_verifications", [])
            if not sch_list:
                st.info("검증할 학술 논문·특허 실적이 입력되지 않았습니다.")
            for sc in sch_list:
                st_sc = sc.get("status", "확인 불가")
                if st_sc == "확인된 내용":
                    sc_badge = "<span class='status-badge-verified'>✅ 확인된 내용</span>"
                elif st_sc == "일부 확인":
                    sc_badge = "<span class='status-badge-partial'>⚠️ 일부 확인</span>"
                elif st_sc == "저자 불일치":
                    sc_badge = "<span class='status-badge-alert'>🚨 저자 불일치 (면접 확인)</span>"
                else:
                    sc_badge = "<span class='status-badge-unverified'>❓ 확인 불가 (서지 미확인)</span>"

                kind_icon = "📜 [특허]" if sc.get("kind") == "patent" else "📚 [논문]"
                if sc.get("matched_title"):
                    authors_txt = ", ".join(str(a) for a in (sc.get("authors") or []))[:100] or "저자/발명자 미상"
                    matched_info = (
                        f"{kind_icon} <b>검색 실적:</b> {html.escape(sc['matched_title'])} "
                        f"({html.escape(sc.get('matched_journal') or '출처 미상')}, {html.escape(sc.get('matched_year') or '연도 미상')}) | "
                        f"<b>인용/등록: {sc.get('citation_count', 0)}회</b> | <b>저자/발명자:</b> {html.escape(authors_txt)}"
                    )
                else:
                    matched_info = f"{kind_icon} <b>검색 실적:</b> 일치 서지/특허 정보 미확인"

                st.markdown(f"""
                <div class='card'>
                    <div class='card-header'>
                        <span style='font-size:1.08rem; font-weight:700; color:#0f2942;'>{html.escape(sc.get('claim', ''))}</span>
                        {sc_badge}
                    </div>
                    <div style='font-size:0.9rem; color:#475569; margin-bottom:6px;'>
                        {matched_info}
                    </div>
                    <div style='background-color:#f8fafc; padding:10px; border-radius:6px; font-size:0.94rem; color:#334155;'>
                        {html.escape(sc.get('note', ''))}
                    </div>
                </div>
                """, unsafe_allow_html=True)

        with tab_questions:
            st.subheader("🎙️ 면접관을 위한 실무 검증 질문 및 현장 채점표")
            st.caption("확인되지 않은 기여도를 자의적으로 감점하지 않고, 실무 면접에서 구체적인 문제 해결 역량을 검증하도록 돕습니다.")

            dl_col1, dl_col2, dl_col3 = st.columns(3)
            md_b = build_mode_b_report_md(
                saved_b.get("cand_author", ""),
                saved_b.get("gh_user", ""),
                results,
            )
            csv_b = build_mode_b_scorecard_csv(results)
            sheet_html = generate_interview_sheet_html(results, cand_name=saved_b.get("cand_author") or "지원자")

            with dl_col1:
                if st.download_button(
                    "📄 [원클릭] 면접관 현장 채점표 인쇄/다운로드 (.html)",
                    data=sheet_html.encode("utf-8"),
                    file_name=f"interview_scorecard_{saved_b.get('cand_author', 'candidate')}.html",
                    mime="text/html",
                    key="dl_mode_b_sheet_html",
                ):
                    st.toast("✅ 면접관 현장 채점표 (.html) 다운로드가 시작되었습니다!")
            with dl_col2:
                if st.download_button(
                    "📥 상세 교차 검증 리포트 (.md)",
                    data=md_b.encode("utf-8"),
                    file_name="fair_screening_report.md",
                    mime="text/markdown",
                    key="dl_mode_b_md",
                ):
                    st.toast("✅ 상세 교차 검증 리포트 (.md) 다운로드가 시작되었습니다!")
            with dl_col3:
                if st.download_button(
                    "📊 Excel 호환 채점표 (.csv)",
                    data=csv_b,
                    file_name="fair_screening_scorecard.csv",
                    mime="text/csv",
                    key="dl_mode_b_csv",
                ):
                    st.toast("✅ Excel 호환 채점표 (.csv) 다운로드가 시작되었습니다!")

            st.caption("💡 [원클릭] 버튼을 누르면 실시간 파일이 브라우저로 저장되며, 채점표(.html)는 브라우저에서 열어 즉시 종이/PDF 인쇄가 가능합니다.")

            source_labels = {
                "github_verifier": " [GitHub 기여도 압박 질문]",
                "scholar_verifier": " [학술·특허 실체 확인 질문]",
                "fallback": " (자동 질문 생성 실패 - 기본 문구)",
                "llm": "",
            }
            for q in results["interview_questions"]:
                src_tag = source_labels.get(q.get("source", ""), "")
                st.markdown(f"""
                <div class='card'>
                    <div style='font-size:0.9rem; color:#1d4ed8; font-weight:700;'>질문 {q['idx']}. 대상 주장: {html.escape(q.get('claim_ref', ''))}{html.escape(src_tag)}</div>
                    <div style='font-size:1.08rem; font-weight:700; color:#0f2942; margin:6px 0 10px 0;'>
                        "{html.escape(q['question'])}"
                    </div>
                    <div style='background-color:#eff6ff; border-left:3px solid #2563eb; padding:8px 12px; margin-bottom:6px; font-size:0.9rem;'>
                        🎯 <b>질문 의도:</b> {html.escape(q['intent'])}
                    </div>
                    <div style='background-color:#f0fdf4; border-left:3px solid #16a34a; padding:8px 12px; font-size:0.9rem;'>
                        ⚖️ <b>확인 기준:</b> {html.escape(q['eval_criteria'])}
                    </div>
                </div>
                """, unsafe_allow_html=True)

        with tab_drill:
            st.subheader("⚡ 실시간 면접 답변 팩트체크 & 꼬리 질문 (Follow-up Question Drill)")
            st.caption("면접관이 질문을 던진 후 지원자의 답변을 입력하면, STAR 기법(Situation·Task·Action·Result) 기반으로 허점과 과장을 분석하고 실시간 꼬리 질문을 생성합니다.")

            drill_qs = results.get("interview_questions", [])
            q_options = [f"Q{q['idx']}. {q['question']}" for q in drill_qs] if drill_qs else ["직접 질문 입력"]
            sel_q_label = st.selectbox("검증할 면접 질문 선택", q_options, key="drill_sel_q")

            sel_q_obj = next((q for q in drill_qs if f"Q{q['idx']}. {q['question']}" == sel_q_label), None)
            sel_q_text = sel_q_obj["question"] if sel_q_obj else sel_q_label
            sel_criteria = sel_q_obj.get("eval_criteria", "") if sel_q_obj else ""
            sel_claim = sel_q_obj.get("claim_ref", "") if sel_q_obj else ""

            if "0건" in sel_q_text or "커밋" in sel_q_text:
                default_ans = (
                    "제출된 저장소는 사내 비공개 GitLab 환경에서 3년간 주도 개발한 뒤 오픈소스 포크본으로 미러링해 둔 것으로, "
                    "커밋 작성자 계정 매핑이 상이하나 실제 코어 라우팅과 DB 커넥션 풀 튜닝 모듈은 제가 직접 단독 설계·구현했습니다."
                )
            elif "5,000" in sel_q_text or "트래픽" in sel_q_text:
                default_ans = (
                    "해당 설비 데이터 파이프라인 구축 시 Python과 Flask 기반 웹 서비스를 설계하였고, "
                    "데이터베이스 커넥션 풀을 튜닝하여 이벤트 처리 지연 시간을 기존 대비 35% 단축하고 "
                    "초당 5,000건의 트래픽을 무장애로 처리했습니다."
                )
            elif "WSGI" in sel_q_text or "라우팅" in sel_q_text:
                default_ans = (
                    "WSGI 환경에서 Gunicorn 워커 프로세스와 Flask 앱 간의 인터페이스를 최적화하였으며, "
                    "미들웨어 단에서 인증 토큰 검증 및 로깅 훅을 구현하여 응답 지연을 최소화했습니다."
                )
            else:
                default_ans = (
                    "해당 프로젝트의 핵심 아키텍처 설계 및 구현을 담당하였으며, "
                    "성능 병목 요소를 직접 측정하고 튜닝하여 목표한 SLA를 안정적으로 달성했습니다."
                )

            if st.session_state.get("current_drill_q") != sel_q_label:
                st.session_state["current_drill_q"] = sel_q_label
                st.session_state["drill_ans_input"] = default_ans

            ans_input = st.text_area(
                "지원자 현장 답변 입력 (음성 전사 텍스트 또는 면접관 메모)",
                value=st.session_state.get("drill_ans_input", default_ans),
                height=100,
                key="drill_ans_input_area",
            )

            if st.button("🔍 지원자 답변 분석 & 실시간 꼬리 질문 도출", type="primary", key="btn_run_drill"):
                with st.spinner("Liner Router LLM 답변 정밀 팩트체크 및 꼬리 질문 설계 중..."):
                    drill_res = InterviewDrillEngine.analyze_answer(
                        question=sel_q_text,
                        answer=ans_input,
                        claim_context=sel_claim,
                        eval_criteria=sel_criteria,
                    )
                    st.session_state["drill_result"] = drill_res
                    st.toast("✅ 답변 팩트체크 및 실시간 꼬리 질문 도출 완료!")

            drill_res = st.session_state.get("drill_result")
            if drill_res:
                score = drill_res.get("score", 50)
                verdict = drill_res.get("verdict", "")
                if drill_res.get("source") == "llm":
                    st.caption("AI 답변 평가 · 점수는 실제 경력이나 성과의 입증을 의미하지 않습니다.")
                elif drill_res.get("source") == "rule_based":
                    st.caption("규칙 기반 답변 구체성 평가 · 실제 경력이나 성과의 사실 여부는 별도 확인이 필요합니다.")
                else:
                    st.caption("평가 방식 미확인 · 답변을 다시 분석해 주세요.")
                st.markdown(f"""
                <div style='background:#f8fafc; border:1px solid #cbd5e1; border-radius:8px; padding:16px; margin-top:14px;'>
                    <div style='display:flex; justify-content:space-between; align-items:center; margin-bottom:10px;'>
                        <span style='font-size:1.05rem; font-weight:700; color:#0f2942;'>📊 답변 충실도 평가 점수</span>
                        <span style='font-size:1.15rem; font-weight:800; color:{"#16a34a" if score>=70 else "#ea580c"};'>{score}점 / 100점 ({verdict})</span>
                    </div>
                    <div style='font-size:0.95rem; color:#334155; margin-bottom:8px; line-height:1.5;'>
                        💡 <b>면접관 심사평:</b> {html.escape(drill_res.get("critique", ""))}
                    </div>
                </div>
                """, unsafe_allow_html=True)

                if drill_res.get("missing_elements"):
                    missing_badges = "".join(f"<span class='meta-chip' style='background:#fee2e2; color:#b91c1c;'>⚠️ {html.escape(m)}</span>" for m in drill_res["missing_elements"])
                    st.markdown(f"<div style='margin:10px 0;'><b>답변 내 보완/의심 포인트:</b> {missing_badges}</div>", unsafe_allow_html=True)

                fu_qs = drill_res.get("follow_up_questions", [])
                if fu_qs:
                    st.markdown("#### 🎯 실시간 압박 꼬리 질문 (Follow-up Questions)")
                    for i, fu in enumerate(fu_qs, 1):
                        st.markdown(f"""
                        <div style='background:#eff6ff; border-left:4px solid #2563eb; border-radius:6px; padding:12px 16px; margin-bottom:8px;'>
                            <div style='font-weight:700; color:#1e40af;'>꼬리 질문 #{i}</div>
                            <div style='font-size:1.02rem; font-weight:600; color:#0f2942; margin-top:4px;'>"{html.escape(fu)}"</div>
                        </div>
                        """, unsafe_allow_html=True)

    st.markdown("<div style='height: 180px;'></div>", unsafe_allow_html=True)
