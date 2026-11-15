"""실전 문서 입출력(PDF · DOCX · TXT/MD) 파싱, 로컬 PII 마스킹 및 결과 리포트 내보내기."""
import csv
import io
import re
import xml.etree.ElementTree as ET
import zipfile
from typing import Any, Dict, List, Tuple, Optional

from .github_verifier import RESERVED_GH_PATHS, infer_username_from_urls
from .hr_fact_checker import ALLOWED as ALLOWED_DOMAINS
from .legal_sanitizer import LegalSanitizer

_KNOWN_CERTS = (
    "품질경영기사", "정보처리기사", "산업안전기사", "산업안전산업기사", "물류관리사",
    "ERP정보관리사", "빅데이터분석기사", "SQLD", "SQLP", "ADsP", "PMP", "CPIM",
    "지게차운전기능사", "전기기사", "전기기능사", "위험물산업기사", "ISO9001", "ISO14001", "ISO45001",
)
_SKILL_HINTS = (
    "스마트팩토리", "품질관리", "공정개선", "설비보전", "예지보전", "생산관리", "안전관리",
    "MES", "ERP", "SAP", "WMS", "SCM", "ISO9001", "ISO14001", "ISO45001", "6시그마", "SPC",
    "Python", "SQL", "Power BI", "Tableau", "Excel", "엑셀", "VBA", "PLC", "HMI", "CAD", "AutoCAD",
    "B2B 영업", "CRM", "SaaS", "데이터 분석", "구매", "자재", "원가절감", "ESG", "KPI",
)
_CERT_GEN_PAT = re.compile(r"([가-힣A-Za-z0-9]{2,10}(?:기사|산업기사|기능장|기술사|관리사))")
_ISO_PAT = re.compile(r"(ISO\s*(?:9001|14001|45001|27001)(?:\s*내부심사원)?)", re.I)
_PAT_LINE_PAT = re.compile(r"(?:특허|출원|등록번호|실용신안|\b10-\d{4}-\d{4,}|\bKR\s*10[- ]?\d|\bUS\s*\d{7,})", re.I)


def _extract_pdf_bytes(raw_bytes: bytes) -> str:
    try:
        import fitz  # PyMuPDF

        doc = fitz.open(stream=raw_bytes, filetype="pdf")
        try:
            return "\n".join(page.get_text() for page in doc)
        finally:
            doc.close()
    except Exception:
        pass

    try:
        from pypdf import PdfReader

        reader = PdfReader(io.BytesIO(raw_bytes))
        return "\n".join((p.extract_text() or "") for p in reader.pages)
    except Exception:
        return ""


def _extract_docx_bytes(raw_bytes: bytes) -> str:
    try:
        with zipfile.ZipFile(io.BytesIO(raw_bytes)) as zf:
            xml_bytes = zf.read("word/document.xml")
        root = ET.fromstring(xml_bytes)
        ns = "{http://schemas.openxmlformats.org/wordprocessingml/2006/main}"
        paras: List[str] = []
        for p in root.iter(f"{ns}p"):
            txt = "".join((t.text or "") for t in p.iter(f"{ns}t")).strip()
            if txt:
                paras.append(txt)
        return "\n".join(paras)
    except Exception:
        return ""


def _decode_text_bytes(raw_bytes: bytes) -> str:
    for enc in ("utf-8-sig", "utf-8", "cp949", "euc-kr"):
        try:
            return raw_bytes.decode(enc)
        except UnicodeDecodeError:
            continue
    return raw_bytes.decode("utf-8", errors="ignore")


def extract_text_from_upload(filename: str, raw_bytes: bytes) -> Tuple[str, Dict[str, int], str]:
    """업로드된 PDF·DOCX·TXT/MD에서 텍스트를 추출하고 즉시 로컬 PII 마스킹을 수행한다."""
    empty_stats = {"rrn_masked": 0, "phone_masked": 0, "email_masked": 0, "address_masked": 0}
    if not raw_bytes:
        return "", empty_stats, "빈 파일입니다."

    name = (filename or "").lower()
    if name.endswith(".pdf"):
        raw_text = _extract_pdf_bytes(raw_bytes)
    elif name.endswith(".docx"):
        raw_text = _extract_docx_bytes(raw_bytes)
    else:
        raw_text = _decode_text_bytes(raw_bytes)

    raw_text = re.sub(r"\n{3,}", "\n\n", raw_text).strip()
    if not raw_text:
        return "", empty_stats, "문서에서 텍스트를 추출하지 못했습니다. (스캔 이미지 PDF 여부 확인)"

    sanitized, stats = LegalSanitizer.sanitize_text(raw_text[:12000])
    masked_cnt = sum(stats.values())
    msg = f"문서 추출 완료 ({len(sanitized)}자" + (f", 민감정보 {masked_cnt}건 자동 마스킹" if masked_cnt else "") + ")"
    return sanitized, stats, msg


def _clean_eui_name(tok: str, raw: str = "", match_span: Optional[Tuple[int, int]] = None) -> str:
    """이력서 제목 토큰에서 소유격 조사('의')를 분리하되, 모호한 3글자 성명(김준의, 김정의 등)은 본문 증거 없이 임의 훼손하지 않는다."""
    if not tok:
        return ""
    # 4글자 이상이고 '의'로 끝나면(김영호의, 김정의의, 김준의의 등) 3자 이상 성명에 조사 '의'가 결합된 것이 확실하므로 분리
    if len(tok) >= 4 and tok.endswith("의"):
        return tok[:-1]
    # 3글자이고 '의'로 끝나는 경우(김준의, 김정의, 공유의, 허준의)
    if len(tok) == 3 and tok.endswith("의"):
        base2 = tok[:2]
        # 제목이 문서 어디에 위치하든, 매칭된 제목 구문 자체를 제외한 나머지 본문에서 성명 증거 탐색
        if match_span and raw:
            body = raw[:match_span[0]] + " " + raw[match_span[1]:]
        else:
            lines = (raw or "").splitlines()
            body = "\n".join(lines[1:]) if len(lines) > 1 else ""

        # 제목 외 본문에 2글자 성명이 주격조사·호칭과 함께 단독 출현하고 3글자 성명은 출현하지 않는 명확한 증거가 확인될 때만 분리
        if body and re.search(rf"(?:^|[\s\n]){re.escape(base2)}(?:[은는이가]|님|과장|대리|팀장|부장|씨|[\s\(,]|$)", body):
            if not re.search(rf"(?:^|[\s\n]){re.escape(tok)}(?:[은는이가]|님|과장|대리|팀장|부장|씨|[\s\(,]|$)", body):
                return base2
        # 본문에 명시적 추가 증거가 없거나 모호한 경우 지원자 성명 임의 훼손을 방지하기 위해 3글자 원형 보존
        return tok
    return tok


def extract_resume_profile_from_text(text: str) -> Dict[str, Any]:
    """이력서·경력기술서 본문에서 경력 연수·연령·자격증·핵심 역량 키워드를 구조화 추출한다."""
    raw = text or ""
    exp_years = None
    for pat in (
        r"총\s*경력\s*[:：]?\s*(\d{1,2})\s*년",
        r"(\d{1,2})\s*년간",
        r"(\d{1,2})\s*년(?:\s*간|\s*이상)?\s*(?:근무|경력|재직|총괄|수행|담당|운영)",
    ):
        m_y = re.search(pat, raw)
        if m_y:
            yv = int(m_y.group(1))
            if 1 <= yv <= 50:
                exp_years = yv
                break

    age = None
    m_age = re.search(r"만\s*(\d{2})\s*세", raw)
    if m_age:
        av = int(m_age.group(1))
        if 40 <= av <= 75:
            age = av

    certs: List[str] = []
    seen_c: set[str] = set()

    def _add_cert(val: str) -> None:
        v = re.sub(r"\s+", " ", val).strip()
        if not v:
            return
        k = v.replace(" ", "").lower()
        if k not in seen_c and len(certs) < 8:
            seen_c.add(k)
            certs.append(v)

    for m_iso in _ISO_PAT.findall(raw):
        _add_cert(m_iso)
    for kc in _KNOWN_CERTS:
        if kc.lower() in raw.lower():
            _add_cert(kc)
    for m_g in _CERT_GEN_PAT.findall(raw):
        if m_g not in ("자격기사", "전문관리사"):
            _add_cert(m_g)

    skills: List[str] = []
    raw_low = raw.lower()
    for sk in _SKILL_HINTS:
        if sk.lower() in raw_low and sk not in skills:
            skills.append(sk)
            if len(skills) >= 10:
                break

    name = ""
    m_name = re.search(r"(?:이름|성명|지원자)\s*[:：]\s*([가-힣A-Za-z]{2,8})", raw)
    if m_name:
        name = m_name.group(1).strip()
    else:
        # 1. 공백이 있는 제목: <이름> <이력서> 또는 <이름의> <이력서>
        m_sp = re.search(r"^\s*([가-힣]{2,6})\s+(?:이력서|경력기술서)", raw, re.MULTILINE)
        if m_sp:
            name = _clean_eui_name(m_sp.group(1).strip(), raw, m_sp.span())
        else:
            # 2. 공백 없이 붙은 제목: <이름>이력서 또는 <이름의>이력서
            m_direct = re.search(r"^\s*([가-힣]{2,5})(?:이력서|경력기술서)", raw, re.MULTILINE)
            if m_direct:
                name = _clean_eui_name(m_direct.group(1).strip(), raw, m_direct.span())

    return {
        "name": name,
        "experience_years": exp_years,
        "age": age,
        "certifications": certs,
        "skills": skills,
    }


def extract_portfolio_inputs_from_text(text: str) -> Dict[str, Any]:
    """문서 본문에서 허용 공개 URL, GitHub 계정 ID, 주요 기술 주장 문장, 학술·특허 실적을 추출한다."""
    raw = text or ""
    urls_raw = re.findall(r"https?://[^\s\)\]>\"']+", raw)
    urls: List[str] = []
    seen_u: set[str] = set()
    for u in urls_raw:
        u_clean = u.rstrip(".,;:")
        host_m = re.match(r"https?://([^/]+)", u_clean.lower())
        host = host_m.group(1) if host_m else ""
        if any(host == d or host.endswith("." + d) for d in ALLOWED_DOMAINS):
            if u_clean not in seen_u:
                seen_u.add(u_clean)
                urls.append(u_clean)

    gh_user = infer_username_from_urls(urls)
    if not gh_user:
        for m_gh in re.findall(r"github\.com/([A-Za-z0-9-]+)", raw):
            if m_gh.lower() not in RESERVED_GH_PATHS:
                gh_user = m_gh
                break

    lines = [ln.strip("•-* \t") for ln in raw.splitlines()]
    claims: List[str] = []
    scholar: List[str] = []
    for ln in lines:
        if len(ln) < 12 or ln.startswith("http"):
            continue
        if ("|" in ln and re.search(r"(?:19|20)\d{2}", ln)) or _PAT_LINE_PAT.search(ln):
            if ln not in scholar and len(scholar) < 5:
                scholar.append(ln[:180])
            continue
        if len(claims) < 6 and ln not in claims:
            claims.append(ln[:160])

    return {"urls": urls[:8], "claims": claims, "scholar": scholar, "github_username": gh_user}


def build_mode_a_report_md(
    profile: Any,
    match_results: List[Any],
    translated_points: List[Dict[str, str]],
    roadmap: Dict[str, Any],
) -> str:
    """Mode A 맞춤형 커리어 전환·이력서 보강 리포트 Markdown 생성."""
    scrub = LegalSanitizer.scrub_policy_text
    certs = getattr(profile, "held_certifications", None) or []
    lines = [
        f"# CareerPath 전환 리포트 — 목표 직무: {profile.desired_role}",
        "",
        f"- **경력 / 연령**: 총 {profile.total_experience_years}년 (만 {profile.age}세)",
        f"- **보유 역량 키워드**: {', '.join(profile.skills) if profile.skills else '미입력'}",
        f"- **보유 자격증**: {', '.join(certs) if certs else '미입력'}",
        "",
        "## 1. 채용 공고 매칭 및 역량 갭 요약",
    ]
    for mr in match_results:
        job = mr.job
        st_lbl = "진행 중" if job.status == "open" else ("마감 참고" if job.status == "closed" else "상태 미확인")
        if mr.scored:
            ratio = f" ({mr.required_met_ratio})" if getattr(mr, "required_met_ratio", "") else ""
            score_lbl = f"{mr.match_score}% (가중 요건 충족률{ratio})"
        elif getattr(mr, "low_detail", False):
            score_lbl = "미산정 (상세요강 이미지·요약 공고)"
        else:
            score_lbl = "미산정"
        lines.extend([
            f"### [{st_lbl}] {job.title} — {job.company}",
            f"- **매칭률**: {score_lbl} | **근무지**: {job.location} | **마감**: {job.deadline}",
            f"- **출처**: {job.source_url}",
            f"- **충족 요건**: {', '.join(mr.matched_skills[:4]) or '확인 필요'}",
            f"- **보완 필요**: {', '.join(mr.missing_skills[:4]) or '없음'}",
            f"- **지원 전략**: {mr.tailored_advice or '공고 원문 요건 확인 필요'}",
            "",
        ])

    lines.append("## 2. 이력서 현대화 번역문 (JD 반영)")
    for tp in translated_points:
        lines.extend([
            f"- **기존**: {tp.get('original', '')}",
            f"  - **개선**: {tp.get('modernized', '')}",
            f"  - **효과**: {tp.get('impact_rationale', '')}",
        ])

    lines.extend(["", "## 3. 7일 즉각 실행 체크리스트 & 국비 훈련과정"])
    for c in roadmap.get("all_courses") or ([roadmap["target_course"]] if roadmap.get("target_course") else []):
        lines.append(
            f"- **과정**: [{c.get('institution', '')}] {c.get('title', '')} "
            f"(기간: {c.get('period') or '상세확인'}, 시간: {c.get('duration') or '상세확인'}) -> {c.get('url', '')}"
        )
    lines.append("")
    for sp in roadmap.get("sprint", []):
        lines.append(f"- **{sp['day']}**: {sp['action']} *(산출물: {sp['deliverable']})*")

    lines.extend(["", "## 4. 3개월 성장 로드맵"])
    for ph in roadmap.get("phases", []):
        lines.append(f"### {ph['month']} — {ph['goal']}")
        for act in ph.get("actions", []):
            lines.append(f"- {act}")
        lines.append("")

    return scrub("\n".join(lines))


def build_mode_b_report_md(
    candidate_author: str,
    github_username: str,
    results: Dict[str, Any],
) -> str:
    """Mode B 면접관용 Fair-Screening 교차 검증 리포트 Markdown 생성."""
    scrub = LegalSanitizer.scrub_policy_text
    audit = results.get("audit_summary", {})
    lines = [
        "# Fair-Screening 면접관 교차 검증 리포트",
        "",
        f"- **지원자 식별(선택)**: {candidate_author or '미입력'} | GitHub: `{github_username or '미입력'}`",
        f"- **포트폴리오 주장**: {audit.get('verified_count', 0)}/{audit.get('total_claims', 0)}건 확인 (일부 {audit.get('partially_verified_count', 0)}, 미확인 {audit.get('unverified_count', 0)})",
        f"- **GitHub 기여 검증**: {audit.get('github_verified_count', 0)}/{audit.get('github_repos_checked', 0)}개 본인 기여 (미확인·주의 {audit.get('github_unverified_count', 0)}건)",
        f"- **학술·특허 검증**: {audit.get('scholar_verified_count', 0)}/{audit.get('scholar_checked', 0)}건 일치 (저자불일치 {audit.get('scholar_author_mismatch_count', 0)}, 미확인 {audit.get('scholar_unverified_count', 0)})",
        "",
        "## 1. 공개 자료 기반 근거 카드",
    ]
    for c in results.get("evidence_cards", []):
        lines.append(f"- **[{c.get('status')}]** {c.get('claim')}")
        if c.get("evidence_quote"):
            lines.append(f"  - 원문 인용: \"{c['evidence_quote']}\"")
        lines.append(f"  - 비고: {c.get('note', '')}")

    if results.get("github_contributions"):
        lines.extend(["", "## 2. GitHub 커밋 기여도 검증"])
        for g in results["github_contributions"]:
            lines.append(
                f"- **[{g.get('status')}]** `{g.get('repo')}` (조회 계정 `{g.get('checked_author')}` 커밋: {g.get('commit_count')}건)"
            )
            lines.append(f"  - {g.get('note', '')}")

    if results.get("scholar_verifications"):
        lines.extend(["", "## 3. LINER Scholar 학술·특허 교차 검증"])
        for sc in results["scholar_verifications"]:
            lines.append(f"- **[{sc.get('status')}]** {sc.get('claim')}")
            lines.append(f"  - {sc.get('note', '')}")

    lines.extend(["", "## 4. AI 실무 검증 면접 질문지"])
    for q in results.get("interview_questions", []):
        lines.extend([
            f"### Q{q.get('idx')}. {q.get('claim_ref', '')}",
            f"- **질문**: {q.get('question', '')}",
            f"- **의도**: {q.get('intent', '')}",
            f"- **확인 기준**: {q.get('eval_criteria', '')}",
            "",
        ])

    return scrub("\n".join(lines))


def build_mode_b_scorecard_csv(results: Dict[str, Any]) -> bytes:
    """면접관 현장 채점용 Excel 호환 UTF-8-SIG CSV 시트를 생성한다."""
    buf = io.StringIO()
    writer = csv.writer(buf)
    writer.writerow([
        "번호", "검증영역", "대상주장_또는_실적", "사전검증상태",
        "대조근거_요약", "면접질문", "확인기준", "평점(상_중_하)", "면접관메모",
    ])

    q_by_ref = {q.get("claim_ref", ""): q for q in results.get("interview_questions", [])}
    idx = 0
    for c in results.get("evidence_cards", []):
        idx += 1
        q = q_by_ref.get(c.get("claim", ""), {})
        writer.writerow([
            idx, "포트폴리오", c.get("claim", ""), c.get("status", ""),
            c.get("evidence_quote") or c.get("note", ""),
            q.get("question", ""), q.get("eval_criteria", ""), "", "",
        ])
    for g in results.get("github_contributions", []):
        idx += 1
        pq = g.get("pressure_question") or {}
        writer.writerow([
            idx, "GitHub기여", g.get("repo", ""), g.get("status", ""),
            g.get("note", ""), pq.get("question", ""), pq.get("eval_criteria", ""), "", "",
        ])
    for sc in results.get("scholar_verifications", []):
        idx += 1
        ref = f"[학술·특허 저자 불일치] {sc.get('title', '')}" if sc.get("status") == "저자 불일치" else f"[학술·특허] {sc.get('title', '')}"
        q = q_by_ref.get(ref, {})
        writer.writerow([
            idx, "학술·특허", sc.get("claim", ""), sc.get("status", ""),
            sc.get("note", ""), q.get("question", ""), q.get("eval_criteria", ""), "", "",
        ])

    return buf.getvalue().encode("utf-8-sig")
