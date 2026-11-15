"""
완성형 인쇄/다운로드용 1페이지 이력서 및 면접 평가표 HTML/CSS 템플릿 빌더.
- Mode A: 사람인/원티드 즉시 제출용 모던 1-Page 시니어 전환 이력서 HTML
- Mode B: 면접장 인쇄용 1-Page 실무 면접 평가표 (Scorecard Sheet) HTML
"""
import html
from typing import Any, Dict, List


def generate_modern_resume_html(
    profile: Any,
    match_results: List[Any],
    translated_points: List[str],
    transfer_data: Dict[str, Any],
) -> str:
    name = html.escape(getattr(profile, "name", "지원자"))
    age = getattr(profile, "age", 50)
    desired_role = html.escape(getattr(profile, "desired_role", "직무"))
    years = getattr(profile, "total_experience_years", 20)
    skills = [html.escape(str(s).strip()) for s in (getattr(profile, "skills", []) or []) if str(s).strip()]
    certs = [html.escape(str(c).strip()) for c in (getattr(profile, "held_certifications", []) or []) if str(c).strip()]
    readiness = transfer_data.get("transfer_readiness", 80)
    verdict = html.escape(transfer_data.get("readiness_verdict", "디지털 전환 우수"))

    top_caps = transfer_data.get("transferred_capabilities", [])[:5]
    caps_html = "".join(
        f"<span style='background:#e0f2fe; color:#0369a1; padding:3px 8px; border-radius:4px; font-size:12px; margin-right:6px;'>🔄 {html.escape(c['capability'])} ({c['transfer_weight']}%)</span>"
        for c in top_caps
    )

    trans_items_html = "".join(f"<li style='margin-bottom:8px; line-height:1.5;'>{html.escape(p)}</li>" for p in translated_points)

    top_jobs = match_results[:2]
    jobs_html = ""
    for mr in top_jobs:
        jb = mr.job
        strat = getattr(mr, "tailored_advice", "")
        jobs_html += f"""
        <div style='background:#f8fafc; border:1px solid #e2e8f0; border-radius:6px; padding:10px; margin-bottom:8px;'>
            <div style='font-weight:700; color:#0f2942; font-size:13px;'>{html.escape(jb.title)} | {html.escape(jb.company)}</div>
            <div style='font-size:12px; color:#475569; margin-top:4px;'><b>맞춤 어필 포인트:</b> {html.escape(strat)}</div>
        </div>
        """

    return f"""<!DOCTYPE html>
<html lang="ko">
<head>
<meta charset="utf-8">
<title>{name} - 1페이지 표준 전환 이력서</title>
<style>
    @page {{ size: A4 portrait; margin: 10mm; }}
    @media print {{
        body {{ margin: 0; padding: 0; font-size: 11.5px; -webkit-print-color-adjust: exact; print-color-adjust: exact; }}
        .section {{ page-break-inside: avoid; break-inside: avoid; }}
        .no-print {{ display: none !important; }}
    }}
    .print-bar {{
        background: #f8fafc;
        border: 1px solid #cbd5e1;
        padding: 10px 14px;
        border-radius: 6px;
        margin-bottom: 14px;
        display: flex;
        justify-content: space-between;
        align-items: center;
    }}
    .print-btn {{
        background: #2563eb;
        color: #ffffff;
        border: none;
        padding: 8px 16px;
        border-radius: 5px;
        font-weight: 700;
        font-size: 13px;
        cursor: pointer;
        box-shadow: 0 1px 3px rgba(0,0,0,0.1);
    }}
    .print-btn:hover {{
        background: #1d4ed8;
    }}
    body {{ font-family: 'Pretendard', -apple-system, BlinkMacSystemFont, 'Segoe UI', Roboto, sans-serif; color: #1e293b; margin: 0; padding: 15px; line-height: 1.4; word-break: keep-all; overflow-wrap: break-word; }}
    .header {{ border-bottom: 2px solid #0f2942; padding-bottom: 8px; margin-bottom: 12px; display: flex; justify-content: space-between; align-items: flex-end; }}
    .name {{ font-size: 22px; font-weight: 800; color: #0f2942; }}
    .target-role {{ font-size: 15px; font-weight: 700; color: #2563eb; margin-top: 3px; }}
    .meta {{ font-size: 12px; color: #64748b; }}
    .section {{ margin-bottom: 12px; page-break-inside: avoid; break-inside: avoid; }}
    .section-title {{ font-size: 13px; font-weight: 700; color: #0f2942; border-left: 4px solid #2563eb; padding-left: 8px; margin-bottom: 6px; }}
    .badge-box {{ background: #f0fdf4; border: 1px solid #bbf7d0; padding: 8px 10px; border-radius: 6px; margin-bottom: 8px; font-size: 12.5px; color: #166534; }}
    ul {{ margin: 0; padding-left: 18px; font-size: 12.5px; }}
</style>
</head>
<body>
    <div class="print-bar no-print">
        <span style="font-size:13px; font-weight:700; color:#334155;">📄 A4 표준 1Page 이력서 규격 (원티드·사람인 즉시 제출용)</span>
        <button class="print-btn" onclick="window.print()">🖨️ 브라우저 원클릭 바로 인쇄 / PDF 저장</button>
    </div>
    <div class="header">
        <div>
            <div class="name">{name} <span style="font-size:15px; font-weight:500; color:#64748b;">(만 {age}세 / 총 경력 {years}년)</span></div>
            <div class="target-role">목표 직무: {desired_role}</div>
        </div>
        <div class="meta" style="text-align:right;">
            <div>공개 지원용 1-Page 표준 규격</div>
            <div>개인 식별정보(PII) 로컬 마스킹 완료</div>
        </div>
    </div>

    <div class="badge-box">
        <b>💡 AI 역량 전이 인증 지수: {readiness}점 ({verdict})</b><br/>
        <div style="margin-top:6px;">{caps_html}</div>
    </div>

    <div class="section">
        <div class="section-title">핵심 보유 기술 및 자격증</div>
        <div style="font-size:13px; color:#334155; margin-bottom:4px;"><b>보유 역량:</b> {', '.join(skills)}</div>
        <div style="font-size:13px; color:#334155;"><b>공인 자격:</b> {', '.join(certs) if certs else '상세 이력 참조'}</div>
    </div>

    <div class="section">
        <div class="section-title">현대화 경력 기술서 (테크 문맥 전환)</div>
        <ul>{trans_items_html}</ul>
    </div>

    <div class="section">
        <div class="section-title">타깃 채용공고 적합성 및 맞춤 지원 전략</div>
        {jobs_html}
    </div>
</body>
</html>
"""


def generate_interview_sheet_html(results: Dict[str, Any], cand_name: str = "지원자") -> str:
    audit = results.get("audit_summary", {})
    exec_summary = results.get("executive_summary", [])
    exec_html = "".join(f"<li style='margin-bottom:4px;'>{html.escape(b)}</li>" for b in exec_summary)

    qs = results.get("interview_questions", [])
    q_rows = ""
    for q in qs:
        q_rows += f"""
        <tr style='border-bottom:1px solid #e2e8f0;'>
            <td style='padding:8px; font-weight:700; color:#0f2942; vertical-align:top; width:6%; text-align:center;'>Q{q.get('idx')}</td>
            <td style='padding:8px; vertical-align:top; width:22%; font-size:12px; color:#475569;'><b>{html.escape(q.get('claim_ref', ''))}</b></td>
            <td style='padding:8px; vertical-align:top; width:44%; font-size:12px; color:#0f2942;'>
                <div style='font-weight:700;'>{html.escape(q.get('question', ''))}</div>
                <div style='color:#64748b; font-size:11px; margin-top:4px;'><b>평가 기준:</b> {html.escape(q.get('eval_criteria', ''))}</div>
            </td>
            <td style='padding:8px; vertical-align:top; width:13%; text-align:center; font-size:12px;'>
                [ ] 상 &nbsp; [ ] 중 &nbsp; [ ] 하
            </td>
            <td style='padding:8px; vertical-align:top; width:15%;'></td>
        </tr>
        """

    return f"""<!DOCTYPE html>
<html lang="ko">
<head>
<meta charset="utf-8">
<title>면접관 채점 시트 - {html.escape(cand_name)}</title>
<style>
    @page {{ size: A4 portrait; margin: 10mm; }}
    @media print {{
        body {{ margin: 0; padding: 0; font-size: 11px; -webkit-print-color-adjust: exact; print-color-adjust: exact; }}
        thead {{ display: table-header-group; }}
        tr {{ page-break-inside: avoid; break-inside: avoid; }}
        table {{ page-break-inside: auto; }}
        .header, .meta-box {{ page-break-inside: avoid; break-inside: avoid; }}
        .no-print {{ display: none !important; }}
    }}
    .print-bar {{
        background: #f8fafc;
        border: 1px solid #cbd5e1;
        padding: 10px 14px;
        border-radius: 6px;
        margin-bottom: 14px;
        display: flex;
        justify-content: space-between;
        align-items: center;
    }}
    .print-btn {{
        background: #2563eb;
        color: #ffffff;
        border: none;
        padding: 8px 16px;
        border-radius: 5px;
        font-weight: 700;
        font-size: 13px;
        cursor: pointer;
        box-shadow: 0 1px 3px rgba(0,0,0,0.1);
    }}
    .print-btn:hover {{
        background: #1d4ed8;
    }}
    body {{ font-family: 'Pretendard', -apple-system, BlinkMacSystemFont, 'Segoe UI', Roboto, sans-serif; color: #1e293b; margin: 0; padding: 15px; font-size: 12px; }}
    .header {{ border-bottom: 2px solid #0f2942; padding-bottom: 8px; margin-bottom: 12px; display: flex; justify-content: space-between; align-items: flex-end; page-break-inside: avoid; break-inside: avoid; }}
    .title {{ font-size: 18px; font-weight: 800; color: #0f2942; }}
    .meta-box {{ background: #f8fafc; border: 1px solid #cbd5e1; border-radius: 6px; padding: 8px 12px; margin-bottom: 12px; page-break-inside: avoid; break-inside: avoid; }}
    table {{ width: 100%; border-collapse: collapse; margin-top: 8px; table-layout: fixed; page-break-inside: auto; }}
    thead {{ display: table-header-group; }}
    tr {{ page-break-inside: avoid; break-inside: avoid; }}
    th {{ background: #f1f5f9; color: #0f2942; font-weight: 700; padding: 6px 8px; text-align: left; border-bottom: 2px solid #cbd5e1; font-size: 12px; }}
    td {{ word-break: break-word; overflow-wrap: break-word; }}
</style>
</head>
<body>
    <div class="print-bar no-print">
        <span style="font-size:13px; font-weight:700; color:#334155;">📄 A4 표준 1Page 이력서 규격 (원티드·사람인 즉시 제출용)</span>
        <button class="print-btn" onclick="window.print()">🖨️ 브라우저 원클릭 바로 인쇄 / PDF 저장</button>
    </div>
    <div class="header">
        <div>
            <div class="title">AI 심층 면접관 현장 채점표 (Scorecard)</div>
            <div style="font-size:13px; color:#2563eb; font-weight:700; margin-top:2px;">지원자: {html.escape(cand_name)} (포트폴리오 팩트체크 기반)</div>
        </div>
        <div style="text-align:right; font-size:11px; color:#64748b;">
            면접일자: 2026. &nbsp; . &nbsp; .<br/>면접관 서명: _______________
        </div>
    </div>

    <div class="meta-box">
        <div style="font-weight:700; color:#0f2942; margin-bottom:4px;">💡 10초 종합 요약 (Executive Briefing)</div>
        <ul style="margin:0; padding-left:16px; font-size:11.5px; color:#334155;">{exec_html}</ul>
        <div style="margin-top:6px; font-size:11px; color:#64748b;">
            대조 결과: 주장 검증 {audit.get('verified_count', 0)}/{audit.get('total_claims', 0)}건 · 
            GitHub {audit.get('github_verified_count', 0)}개 기여 · 
            Scholar/특허 {audit.get('scholar_verified_count', 0)}건 일치
        </div>
    </div>

    <div style="font-weight:700; font-size:13px; color:#0f2942; margin-top:10px;">📋 근거 기반 실무 압박 면접 문항 (총 {len(qs)}문항)</div>
    <table>
        <thead>
            <tr>
                <th style="text-align:center;">No</th>
                <th>검증 대상 주장</th>
                <th>심층 질문 및 확인 기준</th>
                <th style="text-align:center;">채점</th>
                <th>면접관 메모</th>
            </tr>
        </thead>
        <tbody>
            {q_rows}
        </tbody>
    </table>
</body>
</html>
"""
