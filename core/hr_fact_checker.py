"""
Fair-Screening 팩트체커 (v0.3).
- 지원자가 제출한 공개 URL의 본문을 직접 수집한다 (허용 도메인만).
- LLM이 주장별로 판정하되, 반드시 본문에서 '그대로 인용'한 근거를 내야 한다.
  인용문이 실제 본문에 없으면 코드가 '확인 불가'로 강등한다.
- 선택적으로 GitHub 실제 커밋 기여도(GitHubVerifier) 및 LINER Scholar 학술·특허 교차 검증을 병행한다.
- 합격/불합격, 진위 판정은 하지 않는다. 결과는 근거 카드 + 주장별 면접 질문.
"""
import concurrent.futures
import re
from datetime import datetime
from typing import Any, Callable, Dict, List, Optional, Tuple
from urllib.parse import urlparse

from .fetcher import fetch_public_text, fetch_public_resource
from .github_verifier import GitHubVerifier, infer_username_from_urls
from .legal_sanitizer import LegalSanitizer
from .llm import llm_json, llm_available

ALLOWED = [
    "github.com", "github.io", "gitlab.com", "velog.io", "tistory.com", "medium.com",
    "notion.site", "pypi.org", "npmjs.com", "arxiv.org", "kaggle.com",
    "patents.google.com", "kipris.or.kr", "scienceon.kisti.re.kr",
]
_PATENT_DOMAINS = ("patents.google.com", "kipris.or.kr", "scienceon.kisti.re.kr")
_PATENT_PAT = re.compile(r"(?:특허|출원|등록번호|실용신안|\bKR\s*10[- ]?\d|\b10-\d{4}-\d{4,}|\bUS\s*\d{7,})", re.I)

SYSTEM = (
    "너는 채용 면접관 보조자다. 지원자 주장이 '제공된 공개 자료 본문'에 근거가 있는지만 대조한다. "
    "추측 금지. 본문에 없으면 status는 unverified. "
    'JSON: {"results":[{"idx":int,"status":"verified|partial|unverified","quote":"본문에서 그대로 복사한 근거 문장(없으면 빈 문자열)"}]} '
    "verified=주장의 핵심이 본문에 명시, partial=관련은 있으나 핵심(수치/역할)은 없음."
)
QSYS = (
    "너는 시니어 채용 면접 질문 설계자다. 각 주장과 판정 상태, 확인된 원문 인용구(또는 결손 구간), "
    "GitHub 커밋 기여 요약을 종합해 미확인 수치·실제 설계 의사결정·트러블슈팅을 검증하는 구체적 실무 질문을 만든다. "
    "나이/가족/사생활 질문 금지. "
    'JSON: {"questions":[{"idx":int,"question":"","intent":"","eval_criteria":""}]}'
)


def _is_patent_claim(raw_claim: str, journal: str = "") -> bool:
    return bool(_PATENT_PAT.search(f"{raw_claim or ''} {journal or ''}"))


def _norm(s: str) -> str:
    return re.sub(r"\s+", "", s).lower()


def _tokens(s: str) -> set[str]:
    return set(re.findall(r"[a-z0-9가-힣]+", (s or "").lower()))


def _title_similarity(a: str, b: str) -> float:
    na, nb = _norm(a), _norm(b)
    if not na or not nb:
        return 0.0
    if na == nb:
        return 1.0
    ta, tb = _tokens(a), _tokens(b)
    if not ta or not tb:
        return 0.0
    return 2.0 * len(ta & tb) / (len(ta) + len(tb))


def _journals_conflict(claimed: str, hit: str) -> bool:
    c = (claimed or "").strip()
    h = (hit or "").strip()
    if not c or not h:
        return False
    nc, nh = _norm(c), _norm(h)
    if nc in nh or nh in nc:
        return False
    tc, th = _tokens(c), _tokens(h)
    return len(tc & th) == 0


def _split_latin_name(name: str) -> Optional[Tuple[str, str]]:
    """영문 저자명을 (given_compact, last_name) 소문자 튜플로 정규화한다."""
    if not re.search(r"[a-zA-Z]", name):
        return None
    if "," in name:
        left, right = name.split(",", 1)
        last_toks = re.findall(r"[a-zA-Z]+", left.lower())
        given_toks = re.findall(r"[a-zA-Z]+", right.lower())
        if last_toks and given_toks:
            return "".join(given_toks), last_toks[-1]
    toks = re.findall(r"[a-zA-Z]+", name.lower())
    if len(toks) < 2:
        return None
    return "".join(toks[:-1]), toks[-1]


def _author_matches(candidate_author: str, hit_authors: List[Any]) -> bool:
    """지원자 성명(한글·영문 별칭 포함)이 검색된 논문 저자 목록과 일치하는지 판정한다."""
    raw = (candidate_author or "").strip()
    if not raw or not hit_authors:
        return False

    aliases = [a.strip() for a in re.split(r"[/|()\n]+", raw) if a.strip()]
    expanded: List[str] = []
    for a in aliases:
        if re.search(r"[가-힣]", a) and "," in a:
            expanded.extend(seg.strip() for seg in a.split(",") if seg.strip())
        else:
            expanded.append(a)

    hits = [str(h or "").strip() for h in hit_authors if str(h or "").strip()]
    for alias in expanded:
        if re.search(r"[가-힣]", alias):
            ac = re.sub(r"\s+", "", alias.lower())
            if len(ac) >= 2 and any(ac in re.sub(r"\s+", "", h.lower()) for h in hits):
                return True
        latin_cand = _split_latin_name(alias)
        if latin_cand:
            cg, cl = latin_cand
            for h in hits:
                latin_hit = _split_latin_name(h)
                if not latin_hit:
                    continue
                hg, hl = latin_hit
                if cl == hl and cg and hg and (cg == hg or (len(cg) == 1 and hg.startswith(cg)) or (len(hg) == 1 and cg.startswith(hg))):
                    return True
    return False


def _parse_scholar_item(item: Any) -> Tuple[str, str, str, str]:
    """(raw_claim, title, claimed_journal, claimed_year) 튜플로 정규화."""
    if isinstance(item, dict):
        title = str(item.get("title") or "").strip()
        journal = str(item.get("journal") or "").strip()
        year_m = re.search(r"(19|20)\d{2}", str(item.get("year") or ""))
        year = year_m.group(0) if year_m else ""
        parts = [p for p in (title, journal, year) if p]
        return " | ".join(parts), title, journal, year

    raw = str(item or "").strip()
    if not raw:
        return "", "", "", ""

    if "|" in raw:
        segs = [s.strip() for s in raw.split("|")]
        title = segs[0]
        journal = ""
        year = ""
        for seg in segs[1:]:
            ym = re.fullmatch(r"(?:19|20)\d{2}", seg)
            if ym and not year:
                year = ym.group(0)
            elif seg and not journal:
                journal = seg
        if not year and len(segs) >= 3:
            ym = re.search(r"(19|20)\d{2}", segs[2])
            year = ym.group(0) if ym else ""
        return raw, title, journal, year

    m = re.match(r"^(.*?)\(([^()]+)\)\s*$", raw)
    if m:
        title = m.group(1).strip()
        inside = m.group(2).strip()
        ym = re.search(r"(19|20)\d{2}", inside)
        year = ym.group(0) if ym else ""
        journal = re.sub(r"(19|20)\d{2}", "", inside).strip(" ,·-/")
        return raw, title, journal, year

    return raw, raw, "", ""


class HRFactChecker:
    def __init__(
        self,
        liner_client=None,
        fetch: Callable[[str], str] = fetch_public_text,
        llm: Callable[[str, str], Any] = llm_json,
        github_verifier: Optional[GitHubVerifier] = None,
    ):
        self.liner = liner_client
        self.fetch = fetch
        self.llm = llm
        self.github_verifier = github_verifier

    def is_safe_public_url(self, url: str) -> bool:
        if not url or not url.startswith(("http://", "https://")):
            return False
        host = urlparse(url).netloc.lower()
        return any(host == d or host.endswith("." + d) for d in ALLOWED)

    def verify_scholar_claims(
        self, scholar_items: List[Any], candidate_author: str = ""
    ) -> List[Dict[str, Any]]:
        """LINER Scholar API로 지원자의 학술 논문·특허 실적을 교차 검증한다 (원문 서지 대조 및 저자명 일치 게이트 적용)."""
        now = datetime.now().strftime("%Y-%m-%d %H:%M")
        cand_author = (candidate_author or "").strip()
        parsed_items = [it for it in (scholar_items or []) if _parse_scholar_item(it)[1]]
        if not parsed_items:
            return []

        def _verify_one(item: Any) -> Dict[str, Any]:
            raw_claim, title, claimed_journal, claimed_year = _parse_scholar_item(item)
            is_pat = _is_patent_claim(raw_claim, claimed_journal)
            kind = "patent" if is_pat else "paper"
            safe_title, _ = LegalSanitizer.sanitize_text(title)
            query = f"{safe_title} {claimed_year}".strip() if claimed_year else safe_title
            hits = (
                self.liner.search_scholar(query, num_results=5)
                if (self.liner is not None and hasattr(self.liner, "search_scholar"))
                else []
            )

            max_sim_sch = max((_title_similarity(title, h.get("title", "")) for h in hits), default=0.0)
            if is_pat and (not hits or max_sim_sch < 0.55) and self.liner is not None and hasattr(self.liner, "search_web"):
                pat_nums = re.findall(r"(?:KR\s*)?10[- ]?\d{4}[- ]?\d{4,}|US\s*\d{7,}", raw_claim, re.I)
                pat_norm_nums = [re.sub(r"[\s-]+", "", n).upper() for n in pat_nums]
                web_hits = self.liner.search_web(f"{safe_title} 특허 (site:patents.google.com OR site:kipris.or.kr)", 5) or []
                pat_converted = []
                for w in web_hits:
                    w_url = (w.get("url") or "").strip()
                    w_host = urlparse(w_url).netloc.lower()
                    if not any(w_host == d or w_host.endswith("." + d) for d in _PATENT_DOMAINS):
                        continue
                    w_title = (w.get("title") or "").strip()
                    w_snip = (w.get("snippet") or w.get("description") or "").strip()
                    hay_comp = re.sub(r"[\s-]+", "", f"{w_title} {w_snip} {w_url}").upper()
                    pat_num_match = any(pn and pn in hay_comp for pn in pat_norm_nums)
                    sim = _title_similarity(title, w_title)
                    if not pat_num_match and sim < 0.50:
                        continue
                    ym = re.search(r"(?:19|20)\d{2}", f"{w_snip} {w_title} {w.get('date', '')}")
                    inv_m = re.search(r"(?:발명자|출원인|Inventors?)\s*[:：]\s*([^\n|]+)", w_snip, re.I)
                    inventors = (
                        [a.strip() for a in re.split(r"[,;/]", inv_m.group(1)) if a.strip()]
                        if inv_m else []
                    )
                    pat_converted.append({
                        "title": w_title or title,
                        "journal": "Google Patents / KIPRIS",
                        "year": ym.group(0) if ym else claimed_year,
                        "date": "",
                        "citation_count": 0,
                        "authors": inventors,
                        "url": w_url,
                        "_pat_num_match": pat_num_match,
                    })
                if pat_converted:
                    hits = pat_converted + list(hits or [])

            if not hits:
                return {
                    "claim": raw_claim,
                    "kind": kind,
                    "title": title,
                    "claimed_journal": claimed_journal,
                    "claimed_year": claimed_year,
                    "status": "확인 불가",
                    "author_matched": None,
                    "matched_title": "",
                    "matched_journal": "",
                    "matched_year": "",
                    "citation_count": 0,
                    "authors": [],
                    "source_url": "",
                    "verified_at": now,
                    "note": (
                        "LINER Scholar 및 특허 공개 DB(Google Patents·KIPRIS)에서 일치 서지를 찾지 못했습니다."
                        if is_pat
                        else "LINER Scholar 검색에서 일치하는 논문·특허 서지 정보를 찾지 못했습니다."
                    ),
                }

            def _rank(h: Dict[str, Any]) -> Tuple[int, float, int, int]:
                sim = _title_similarity(title, h.get("title", ""))
                hy = (h.get("year") or h.get("date") or "")[:4]
                no_conflict = int(
                    not (claimed_year and hy and claimed_year != hy)
                    and (bool(h.get("_pat_num_match")) or not _journals_conflict(claimed_journal, h.get("journal", "")))
                )
                return (1 if h.get("_pat_num_match") else 0, round(sim, 4), no_conflict, int(h.get("citation_count") or 0))

            best = max(hits, key=_rank)
            best_sim = _title_similarity(title, best.get("title", ""))
            pat_num_ok = bool(best.get("_pat_num_match"))
            hit_year = (best.get("year") or best.get("date") or "")[:4]
            hit_journal = best.get("journal") or ""
            citations = int(best.get("citation_count") or 0)
            best_authors = best.get("authors") or []
            year_conflict = bool(claimed_year and hit_year and claimed_year != hit_year)
            journal_conflict = False if pat_num_ok else _journals_conflict(claimed_journal, hit_journal)

            author_matched: Optional[bool] = None
            if cand_author and (best_sim >= 0.55 or pat_num_ok) and best_authors:
                author_matched = _author_matches(cand_author, best_authors)

            if author_matched is False and (best_sim >= 0.55 or pat_num_ok):
                status = "저자 불일치"
                authors_preview = ", ".join(str(a) for a in best_authors[:4])
                note = (
                    f"검색된 문헌의 저자·발명자 목록({authors_preview})에서 "
                    f"지원자 성명('{cand_author}')이 확인되지 않습니다. "
                    "타인 실적 기재 또는 영문 표기 차이 여부를 면접에서 확인하세요."
                )
            elif (pat_num_ok or best_sim >= 0.75) and not year_conflict and not journal_conflict:
                status = "확인된 내용"
                match_txt = " 및 저자·발명자 일치" if author_matched is True else ""
                src_name = "공개 특허 DB(Google Patents/KIPRIS)" if pat_num_ok else "LINER Scholar 학술 DB"
                note = (
                    f"{src_name} 일치{match_txt} 확인 "
                    f"(게재/등록: {hit_journal or '출처 미상'}, {hit_year or '연도 미상'}, 피인용 {citations}회)."
                )
            elif best_sim >= 0.70 or (best_sim >= 0.55 and not year_conflict and not journal_conflict):
                status = "일부 확인"
                diffs = []
                if year_conflict:
                    diffs.append(f"연도 상이(제출 {claimed_year} vs 검색 {hit_year})")
                if journal_conflict:
                    diffs.append(f"학술지 상이(제출 {claimed_journal} vs 검색 {hit_journal})")
                diff_txt = f" [{', '.join(diffs)}]" if diffs else " [제목 부분 일치]"
                note = (
                    f"유사 문헌 '{best.get('title', '')}'이 검색되었으나 추가 대조가 필요합니다{diff_txt} "
                    f"(피인용 {citations}회)."
                )
            else:
                status = "확인 불가"
                note = "유사 문헌은 검색되었으나 제출된 논문·특허 제목과 일치도가 낮습니다. 원문 DOI 또는 특허번호 확인이 필요합니다."

            matched = status != "확인 불가"
            return {
                "claim": raw_claim,
                "kind": kind,
                "title": title,
                "claimed_journal": claimed_journal,
                "claimed_year": claimed_year,
                "status": status,
                "author_matched": author_matched,
                "matched_title": best.get("title", "") if matched else "",
                "matched_journal": hit_journal if matched else "",
                "matched_year": hit_year if matched else "",
                "citation_count": citations if matched else 0,
                "authors": best_authors if matched else [],
                "source_url": best.get("url", "") if matched else "",
                "verified_at": now,
                "note": note,
            }

        if len(parsed_items) >= 2:
            with concurrent.futures.ThreadPoolExecutor(max_workers=min(4, len(parsed_items))) as pool:
                return list(pool.map(_verify_one, parsed_items))
        return [_verify_one(it) for it in parsed_items]

    def verify_portfolio(
        self,
        claims: List[Dict[str, str]],
        urls: List[str],
        github_username: str = "",
        scholar_claims: Optional[List[Any]] = None,
        candidate_author: str = "",
    ) -> Dict[str, Any]:
        now = datetime.now().strftime("%Y-%m-%d %H:%M")
        valid = [u for u in urls if self.is_safe_public_url(u)]
        rejected = [u for u in urls if u not in valid]

        sources = []  # (url, text, meta_dict)
        for u in valid:
            if self.fetch is not fetch_public_text:
                res = self.fetch(u)
                if isinstance(res, tuple) and len(res) == 2:
                    t, m_info = res
                else:
                    t, m_info = res, {}
            else:
                t, m_info = fetch_public_resource(u)
            if t:
                sources.append((u, t, m_info))
        fetch_failed = [u for u in valid if u not in [s[0] for s in sources]]

        cards = [{
            "claim": c.get("claim", ""),
            "category": c.get("category", "주요 역량"),
            "status": "확인 불가",
            "source_url": "",
            "evidence_quote": "",
            "has_code": False,
            "published_date": "",
            "verified_at": now,
            "note": "",
        } for c in claims]

        judged = False
        if sources and claims:
            corpus = "\n\n".join(f"[SOURCE {i}] {u}\n{t}" for i, (u, t, _) in enumerate(sources))
            listing = "\n".join(f"{i}. {c.get('claim','')}" for i, c in enumerate(claims))
            out = self.llm(SYSTEM, f"## 지원자 주장\n{listing}\n\n## 제출 공개 자료\n{corpus}")
            if out and isinstance(out.get("results"), list):
                judged = True
                for r in out["results"]:
                    try:
                        i = int(r.get("idx"))
                    except (TypeError, ValueError):
                        continue
                    if not 0 <= i < len(cards):
                        continue
                    quote = (r.get("quote") or "").strip()
                    st = r.get("status")
                    hit = next(((u, t, m) for u, t, m in sources if quote and _norm(quote) in _norm(t)), None)
                    if st in ("verified", "partial") and hit:
                        cards[i]["status"] = "확인된 내용" if st == "verified" else "일부 확인"
                        cards[i]["source_url"] = hit[0]
                        cards[i]["evidence_quote"] = quote
                        cards[i]["has_code"] = bool((hit[2] or {}).get("has_code"))
                        cards[i]["published_date"] = str((hit[2] or {}).get("published_date") or "")
        for c in cards:
            if c["status"] == "확인 불가":
                if rejected and not valid:
                    c["note"] = "허용된 공개 기술 플랫폼 URL이 없어 대조하지 못했습니다."
                elif not sources:
                    c["note"] = "제출 링크 본문을 가져오지 못했습니다. (비공개/접근 제한 가능)"
                elif not judged:
                    c["note"] = "자동 대조에 실패했습니다. 면접에서 직접 확인이 필요합니다."
                else:
                    c["note"] = "제출 자료에서 근거 문장을 찾지 못했습니다. 허위라는 뜻이 아닙니다."
                c["source_url"] = c["source_url"] or (sources[0][0] if sources else "")
            elif c["status"] == "일부 확인":
                c["note"] = "관련 기술 언급은 있으나 구체 기여·수치는 면접 확인이 필요합니다."
            else:
                c["note"] = "제출 자료 본문에서 근거 문장이 확인되었습니다."

        gh_results: List[Dict[str, Any]] = []
        gh_profile: Optional[Dict[str, Any]] = None
        if self.github_verifier is not None or (github_username or "").strip():
            gv = self.github_verifier if self.github_verifier is not None else GitHubVerifier()
            gh_results = gv.verify_urls(valid, github_username)
            eff_gh_user = (github_username or "").strip() or infer_username_from_urls(valid)
            if eff_gh_user and hasattr(gv, "verify_user_profile"):
                gh_profile = gv.verify_user_profile(eff_gh_user)

        corpus_preview = "\n".join(f"[{u}] {t[:320]}" for u, t, _ in sources[:2]) if sources else ""
        questions = self._questions(cards, corpus_preview=corpus_preview, gh_results=gh_results)
        gh_questions = [gh["pressure_question"] for gh in gh_results if gh.get("pressure_question")]
        if gh_questions:
            questions = gh_questions + questions

        scholar_results: List[Dict[str, Any]] = []
        if scholar_claims:
            scholar_results = self.verify_scholar_claims(
                scholar_claims, candidate_author=candidate_author
            )
            mismatch_scholar = [s for s in scholar_results if s["status"] == "저자 불일치"]
            unverified_scholar = [s for s in scholar_results if s["status"] == "확인 불가"]
            scholar_qs: List[Dict[str, Any]] = []
            for s in mismatch_scholar:
                authors_txt = ", ".join(str(a) for a in (s.get("authors") or [])[:4]) or "타 저자"
                scholar_qs.append({
                    "claim_ref": f"[학술·특허 저자 불일치] {s['title']}",
                    "question": (
                        f"제출하신 실적 '{s['title']}'의 LINER Scholar 저자 목록({authors_txt})에서 "
                        f"지원자 성명('{candidate_author.strip()}')이 확인되지 않습니다. "
                        "타인 논문 기재 경위 또는 공동저자·영문명 표기 근거를 구체적으로 설명해 주십시오."
                    ),
                    "intent": "타인 학술 실적 도용 여부 및 실제 저자 기여 범위 검증",
                    "eval_criteria": "학회 공문·DOI 원문 저자 표기 또는 공동연구 증빙 제시 가능 여부",
                    "source": "scholar_verifier",
                })
            for s in unverified_scholar:
                scholar_qs.append({
                    "claim_ref": f"[학술·특허] {s['title']}",
                    "question": (
                        f"제출하신 실적 '{s['title']}'의 공식 학술 DB(LINER Scholar) 서지 정보가 확인되지 않았습니다. "
                        "정확한 게재 학술지·출원번호 및 본인의 제1저자/핵심 기여 내용을 설명해 주십시오."
                    ),
                    "intent": "R&D·논문·특허 실적의 실제 게재 여부 및 본인 핵심 기여 검증",
                    "eval_criteria": "서지 정보·DOI·특허번호 제시 가능 여부 및 연구 설계 상세 설명의 일관성",
                    "source": "scholar_verifier",
                })
            questions.extend(scholar_qs[:3])

        for idx_num, q in enumerate(questions, 1):
            q["idx"] = idx_num

        # 바쁜 면접관을 위한 10초 종합 요약 (Executive Briefing)
        tot_c = len(cards)
        ok_c = sum(c["status"] == "확인된 내용" for c in cards)
        part_c = sum(c["status"] == "일부 확인" for c in cards)
        unv_c = sum(c["status"] == "확인 불가" for c in cards)
        gh_alerts = [g for g in gh_results if g.get("pressure_question")]
        sch_mismatch = [s for s in scholar_results if s.get("status") == "저자 불일치"]
        sch_unverified = [s for s in scholar_results if s.get("status") == "확인 불가"]
        sch_matched = [s for s in scholar_results if s.get("status") == "일치"]

        exec_bullets = [
            f"주요 이력 주장 {tot_c}건 중 {ok_c}건 원문 일치 대조 완료 (일부 확인 {part_c}건, 원문 결손 {unv_c}건)"
        ]
        if gh_results:
            if gh_alerts:
                exec_bullets.append(f"GitHub 기여 분석: {len(gh_alerts)}개 저장소에서 본인 커밋 증거 부족 또는 단순 문서 수정 감지")
            else:
                exec_bullets.append(f"GitHub 기여 분석: {len(gh_results)}개 저장소 전건에서 지원자 본인 코드 구현 커밋 확인")
        else:
            exec_bullets.append("GitHub 기여 분석: 저장소 미제출로 실무 코드 기여도 검증 생략")

        if scholar_results:
            sch_details = []
            if sch_matched:
                sch_details.append(f"{len(sch_matched)}건 서지 정보 일치")
            if sch_mismatch:
                sch_details.append(f"{len(sch_mismatch)}건 저자 불일치(소명 필수)")
            if sch_unverified:
                sch_details.append(f"{len(sch_unverified)}건 서지 미확인")
            desc = ", ".join(sch_details) if sch_details else f"{len(scholar_results)}건 확인"
            exec_bullets.append(f"학술·특허 검증: 총 {len(scholar_results)}건 ({desc})")
        else:
            exec_bullets.append("학술·특허 검증: 학술 실적 미제출")

        exec_bullets.append(f"추천 면접 전략: 미확인 역량 및 실질 기여도를 집중 판정하는 맞춤형 {len(questions)}문항 활용")

        return {
            "evidence_cards": cards,
            "github_contributions": gh_results,
            "github_profile": gh_profile,
            "scholar_verifications": scholar_results,
            "interview_questions": questions,
            "executive_summary": exec_bullets,
            "audit_summary": {
                "total_claims": len(cards),
                "verified_count": sum(c["status"] == "확인된 내용" for c in cards),
                "partially_verified_count": sum(c["status"] == "일부 확인" for c in cards),
                "unverified_count": sum(c["status"] == "확인 불가" for c in cards),
                "rejected_urls": rejected,
                "fetch_failed_urls": fetch_failed,
                "llm_judged": judged,
                "github_repos_checked": len(gh_results),
                "github_verified_count": sum(
                    1 for g in gh_results if "본인 기여 확인" in (g.get("status") or "")
                ),
                "github_unverified_count": sum(1 for g in gh_results if g.get("pressure_question")),
                "scholar_checked": len(scholar_results),
                "scholar_verified_count": sum(s["status"] == "확인된 내용" for s in scholar_results),
                "scholar_author_mismatch_count": sum(
                    s["status"] == "저자 불일치" for s in scholar_results
                ),
                "scholar_unverified_count": sum(
                    s["status"] == "확인 불가" for s in scholar_results
                ),
            },
        }

    def _questions(
        self,
        cards: List[Dict[str, Any]],
        corpus_preview: str = "",
        gh_results: Optional[List[Dict[str, Any]]] = None,
    ) -> List[Dict[str, Any]]:
        # 확인 불가 > 일부 확인 > 확인된 순으로 최대 5개. 주장마다 따로 호출해 질문-주장 불일치를 원천 차단한다.
        order = {"확인 불가": 0, "일부 확인": 1, "확인된 내용": 2}
        idxs = sorted(range(len(cards)), key=lambda i: order[cards[i]["status"]])[:5]
        if not idxs:
            return []

        gh_summary = ""
        if gh_results:
            gh_summary = "; ".join(
                f"{g.get('repo', '')}: {g.get('status', '')}(커밋 {g.get('commit_count')}건)"
                for g in gh_results[:2]
            )

        def _gen_one(i: int) -> Dict[str, Any]:
            c = cards[i]
            parts = [f"[판정 상태] {c['status']}", f"[지원자 주장] {c['claim']}"]
            if c.get("evidence_quote"):
                parts.append(f"[확인된 원문 인용구] {c['evidence_quote']}")
            elif corpus_preview:
                parts.append(f"[제출 자료 발췌 요약] {corpus_preview[:300]}")
            if gh_summary:
                parts.append(f"[GitHub 기여 요약] {gh_summary}")
            out = self.llm(QSYS, "\n".join(parts))
            q = next((x for x in (out or {}).get("questions", []) if x.get("question")), None) if out else None
            if q:
                return {"claim_ref": c["claim"], "question": q["question"],
                        "intent": q.get("intent", ""), "eval_criteria": q.get("eval_criteria", ""), "source": "llm"}
            return {"claim_ref": c["claim"],
                    "question": f"'{c['claim']}'에서 본인이 직접 맡은 역할과 결과를 구체적으로 설명해 주십시오.",
                    "intent": "주장의 개인 기여 범위 확인", "eval_criteria": "역할·의사결정·결과의 구체성",
                    "source": "fallback"}

        if len(idxs) >= 2:
            with concurrent.futures.ThreadPoolExecutor(max_workers=min(4, len(idxs))) as pool:
                qs = list(pool.map(_gen_one, idxs))
        else:
            qs = [_gen_one(idxs[0])]

        for k, q_item in enumerate(qs, 1):
            q_item["idx"] = k
        return qs
