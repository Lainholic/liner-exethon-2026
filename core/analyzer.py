from pydantic import BaseModel, Field
from collections import Counter
from concurrent.futures import ThreadPoolExecutor
from typing import Any, Callable, List, Optional

from .fetcher import fetch_job_posting_meta, fetch_public_text
from .legal_sanitizer import LegalSanitizer
from .liner_client import LinerClient
from .llm import llm_json
from .store import (
    PostingStore,
    clean_company_name,
    is_deadline_expired,
    is_generic_requirement,
    is_logistics_requirement,
    role_domain_penalty,
)

CLOSED_MARKERS = ("마감된 공고", "채용 마감", "접수마감", "마감되었습니다", "모집이 마감", "채용이 종료")

EXTRACT_SYS = (
    "채용 공고 본문에서 자격요건과 우대사항만 추출한다. 본문에 없는 내용은 만들지 않는다. "
    "details에는 본문에 명시된 요강만 넣는다(없으면 빈 문자열/빈 배열, 추측 금지). tags에는 요건을 짧은 기술/자격/경험 키워드(예: SQL, 품질관리, 정보처리기사, 5년이상)로 정규화해 넣는다. "
    'JSON: {"requirements":["..."],"preferred":["..."],"tags":["..."],"deadline":"본문에 명시된 마감일 또는 빈 문자열","is_job_posting":true|false,'
    '"details":{"salary":"","work_location":"","employment_type":"","work_hours":"","experience":"","education":"","duties":["주요업무"],"benefits":["복리후생"]}}'
)
MATCH_SYS = (
    "지원자 프로필이 각 공고 요건을 충족하는지 프로필 텍스트 근거로만 판단한다. 근거 없으면 unmet. "
    "'경력무관'·'학력무관' 등 제한 없는 요건은 met=true로 판정한다. "
    "지원자의 도메인 실무·리더십 경험이 공고 요건 역량과 실질적으로 대응되면 프로필 내 근거를 적어 met=true로 판정하되, "
    "프로필에 근거가 없는 특정 기술·자격증·타 업종 경력은 추측하지 말고 met=false로 판정한다. "
    'JSON: {"items":[{"req":"요건 원문","met":true|false,"reason":"프로필의 근거 또는 부족한 점"}],'
    '"strategy":"이 공고 지원 시 전면에 내세울 강점과 보완 어필 전략 1문장"}'
)


class JobSeekerProfile(BaseModel):
    name: str = "지원자"
    age: int = 45
    desired_role: str = "스마트팩토리 데이터 관리자"
    preferred_region: str = "전국 (무관)"
    total_experience_years: int = 12
    skills: List[str] = Field(default_factory=list)
    held_certifications: List[str] = Field(default_factory=list)
    resume_text: str = ""


class JobPosting(BaseModel):
    id: str
    company: str
    title: str
    location: str = "공고 원문 확인"
    deadline: str = "공고 원문 확인"
    requirements: List[str] = Field(default_factory=list)
    preferred: List[str] = Field(default_factory=list)
    tags: List[str] = Field(default_factory=list)
    details: dict = Field(default_factory=dict)
    source_url: str = ""
    status: str = "unknown"          # open | closed | unknown
    is_mock: bool = False
    requirements_extracted: bool = False


class MatchResult(BaseModel):
    job: JobPosting
    scored: bool
    match_score: int = 0
    matched_skills: List[str] = Field(default_factory=list)
    missing_skills: List[str] = Field(default_factory=list)
    screening_pass_prob: str = ""
    risk_factors: List[str] = Field(default_factory=list)
    tailored_advice: str = ""
    low_detail: bool = False
    required_met_ratio: str = ""


class ProfileAnalyzer:
    """공고 수집(마감 포함) → 저장소 캐시 → 요건 대조. 마감 공고는 '참고용'으로 보관·표시한다."""

    def __init__(self, liner_client: Optional[LinerClient] = None,
                 fetch: Callable[[str], str] = fetch_public_text,
                 llm: Callable[[str, str], Any] = llm_json,
                 store: Optional[PostingStore] = None, max_new: int = 6):
        self.liner = liner_client or LinerClient()
        self.fetch = fetch
        self.llm = llm
        self.store = store or PostingStore()
        self.max_new = max_new  # 1회 실행당 신규 수집(LLM 호출) 상한
        self.stats = Counter()  # 수집 결과/건너뜀 사유 집계

    def collect(
        self,
        role: str,
        num_candidates: int = 5,
        group: Optional[str] = None,
        exclude_families=(),
        resume_text: str = "",
        preferred_region: str = "",
    ) -> List[JobPosting]:
        """정제된 진행 중(open) DB 공고와 실시간 웹 검색 공고를 결합해 JobPosting 목록을 반환한다."""
        group = group or role
        out: List[JobPosting] = []
        seen_urls: set[str] = set()
        excl_set = set(exclude_families or ())

        for p in self.store.open_candidates_for_role(
            role,
            exclude_families=exclude_families,
            resume_text=resume_text,
            limit=4,
            preferred_region=preferred_region,
        ):
            u = p["url"]
            if u in seen_urls:
                continue
            seen_urls.add(u)
            details = p.get("details") or {}
            title = p.get("title", "")
            out.append(JobPosting(
                id=f"DB-{len(out) + 1}",
                company=clean_company_name(p.get("company", ""), title, u),
                title=title,
                location=details.get("work_location") or "공고 원문 확인",
                deadline=p.get("deadline") or "공고 원문 확인",
                requirements=list(p.get("requirements") or []),
                preferred=list(p.get("preferred") or []),
                tags=list(p.get("tags") or []),
                details=details,
                source_url=u,
                status="open",
                is_mock=False,
                requirements_extracted=bool(p.get("requirements")),
            ))

        rich_open = [
            j for j in out
            if sum(
                1 for r in (j.requirements + j.preferred)
                if not is_generic_requirement(r) and not is_logistics_requirement(r)
            ) >= 2
        ]
        new_cap = 0 if len(rich_open) >= 3 else self.max_new
        new = 0
        to_fetch = []
        for j in self.liner.search_job_postings(role, num_results=num_candidates):
            url = j.get("url") or j.get("source_url") or ""
            if url and url in seen_urls:
                continue
            job = JobPosting(
                id=j.get("id", "JOB"),
                company=clean_company_name(j.get("company", ""), j.get("title", ""), url),
                title=j.get("title", ""),
                location=j.get("location", "공고 원문 확인"),
                source_url=url,
                is_mock=bool(j.get("is_mock")),
            )
            if job.is_mock:
                out.append(job)
                continue
            cached = self.store.get(url)
            if cached:
                if excl_set and self.store.get_family(url) in excl_set:
                    continue
                job.company = clean_company_name(cached.get("company", "") or job.company, cached.get("title", "") or job.title, url)
                job.status, job.deadline = cached["status"], cached["deadline"] or job.deadline
                if is_deadline_expired(job.deadline):
                    job.status = "closed"
                job.requirements, job.preferred, job.tags = cached["requirements"], cached["preferred"], cached["tags"]
                job.details = cached.get("details", {})
                job.requirements_extracted = bool(job.requirements)
                seen_urls.add(url)
                out.append(job)
                continue
            if new >= new_cap or not url.startswith("http"):
                self.stats["skip_limit_or_badurl"] += 1
                continue
            new += 1
            to_fetch.append((url, job))

        if self.fetch is fetch_public_text and len(to_fetch) >= 2:
            def _grab(item):
                u, jb = item
                meta = fetch_job_posting_meta(u)
                body = meta.get("body") or self.fetch(u)
                return jb, u, meta, body

            with ThreadPoolExecutor(max_workers=min(3, len(to_fetch))) as pool:
                fetched = list(pool.map(_grab, to_fetch))
        else:
            fetched = []
            for u, jb in to_fetch:
                meta = fetch_job_posting_meta(u) if self.fetch is fetch_public_text else {}
                body = meta.get("body") or self.fetch(u)
                fetched.append((jb, u, meta, body))

        for job, url, meta, body in fetched:
            if not body:
                self.stats["skip_fetch_empty:" + url.split("/")[2]] += 1
                continue
            closed = meta.get("status") == "closed" or any(k in body[:800] for k in CLOSED_MARKERS)
            ext = self.llm(EXTRACT_SYS, body)
            if not ext or not ext.get("is_job_posting") or not ext.get("requirements"):
                self.stats["skip_extract_fail:" + url.split("/")[2]] += 1
                continue
            if meta.get("company"):
                job.company = clean_company_name(meta["company"], job.title, url)
            if meta.get("location"):
                job.location = meta["location"]
            if ext.get("deadline") or meta.get("deadline"):
                job.deadline = str(ext.get("deadline") or meta.get("deadline"))
                if is_deadline_expired(job.deadline):
                    closed = True
            job.status = "closed" if closed else "open"
            job.requirements = [str(x) for x in ext.get("requirements", [])][:8]
            job.preferred = [str(x) for x in ext.get("preferred", [])][:6]
            job.tags = [str(x) for x in ext.get("tags", [])][:12]
            job.details = ext.get("details") if isinstance(ext.get("details"), dict) else {}
            job.requirements_extracted = True
            self.stats["saved_" + job.status + ":" + url.split("/")[2]] += 1
            self.store.put(url, group, job.title, job.company, job.status, job.deadline,
                           job.requirements, job.preferred, job.tags, job.details)
            seen_urls.add(url)
            out.append(job)
        return out

    def analyze_profile(self, profile: JobSeekerProfile) -> List[MatchResult]:
        safe_resume = (profile.resume_text or "").strip()[:4000]
        safe_skills = [str(s).strip() for s in (profile.skills or []) if str(s).strip()][:15]
        safe_certs = [str(c).strip() for c in (profile.held_certifications or []) if str(c).strip()][:10]
        profile_text = (f"경력 {profile.total_experience_years}년\n보유 키워드: {', '.join(safe_skills)}\n"
                        f"자격: {', '.join(safe_certs)}\n이력: {safe_resume}")
        excl = self.exclude_families_for(profile)
        candidates = self.collect(
            profile.desired_role,
            exclude_families=excl,
            resume_text=safe_resume,
            preferred_region=getattr(profile, "preferred_region", ""),
        )

        mocks = [j for j in candidates if j.is_mock]
        real = [j for j in candidates if not j.is_mock]
        real.sort(key=lambda j: j.status == "open", reverse=True)
        jobs_to_score = real[:5]

        def _score_one(job: JobPosting) -> MatchResult:
            if job.details.get("work_location") and job.location in ("", "공고 원문 확인"):
                job.location = job.details["work_location"]
            raw_reqs = [str(x).strip() for x in job.requirements if str(x).strip()]
            raw_prefs = [str(x).strip() for x in job.preferred if str(x).strip()]
            duties = [str(d).strip() for d in ((job.details or {}).get("duties") or []) if str(d).strip()]
            substantive = [
                r for r in (raw_reqs + raw_prefs)
                if not is_generic_requirement(r) and not is_logistics_requirement(r)
            ]
            if len(substantive) < 2 and duties:
                for d in duties[:3]:
                    raw_reqs.append(f"담당업무: {d}")
                substantive = [
                    r for r in (raw_reqs + raw_prefs)
                    if not is_generic_requirement(r) and not is_logistics_requirement(r)
                ]
            if len(substantive) == 0 or (len(raw_reqs) + len(raw_prefs) < 2):
                return MatchResult(
                    job=job,
                    scored=False,
                    low_detail=True,
                    risk_factors=["상세요강이 이미지·요약 형태로 등록되어 정밀 역량 산정을 생략했습니다. 원문 공고를 직접 확인하세요."],
                    tailored_advice="상세 직무 요강이 이미지 또는 외부 양식으로 제공되는 공고입니다. 원문 링크에서 세부 자격요건을 확인하세요.",
                )

            reqs = raw_reqs + raw_prefs
            m = self.llm(MATCH_SYS, f"## 프로필\n{profile_text}\n\n## 요건\n" + "\n".join(reqs))
            items = (m or {}).get("items") or []
            if not items:
                return MatchResult(scored=False, job=job,
                                   risk_factors=["요건 대조에 실패해 점수를 산정하지 않았습니다."])

            req_set = set(raw_reqs)
            pref_only_set = set(raw_prefs) - req_set
            weighted = []
            req_tot = req_met = pref_tot = pref_met = 0
            met: List[str] = []
            unmet: List[str] = []

            for idx_it, it in enumerate(items):
                req_txt = str(it.get("req") or "").strip()
                reason = str(it.get("reason") or "").strip()
                is_met = bool(it.get("met"))
                is_pref = (req_txt in pref_only_set) or (req_txt not in req_set and idx_it >= len(raw_reqs))
                if is_pref:
                    w = 0.15 if is_logistics_requirement(req_txt) else 0.45
                    pref_tot += 1
                    pref_met += int(is_met)
                else:
                    w = (
                        0.20 if is_logistics_requirement(req_txt)
                        else (0.35 if is_generic_requirement(req_txt) else 1.0)
                    )
                    req_tot += 1
                    req_met += int(is_met)
                weighted.append((w, is_met))
                entry = f"{req_txt} — {reason}"
                if is_met:
                    met.append(entry)
                else:
                    unmet.append(entry)

            total_w = sum(w for w, _ in weighted) or 1.0
            score_val = round(100 * sum(w for w, m_flag in weighted if m_flag) / total_w)
            ratio_txt = f"필수 {req_met}/{req_tot}" + (f" · 우대 {pref_met}/{pref_tot}" if pref_tot else "")

            strategy = LegalSanitizer.scrub_policy_text(str((m or {}).get("strategy") or "").strip())
            if not strategy:
                met_head = ", ".join(x.split(" — ")[0] for x in met[:2])
                core_unmet = [x.split(" — ")[0] for x in unmet if not is_logistics_requirement(x.split(" — ")[0])]
                unmet_head = ", ".join(core_unmet[:2])
                if met_head and unmet_head:
                    strategy = f"강점 어필: {met_head} 실무 경력을 상단에 배치하고, 보완 요건({unmet_head})은 유관 프로젝트·학습 계획으로 보강하세요."
                elif met_head:
                    strategy = f"강점 어필: {met_head} 핵심 역량이 공고 요건과 직접 부합하므로 정량 성과 중심으로 강조하세요."
                else:
                    strategy = f"보완 포인트: {unmet_head or '직무 핵심 역량'} 관련 실무 접점과 전환 준비 내역을 중심으로 보강하세요."

            note = "마감된 공고입니다(시장 참고용). " if job.status == "closed" else ""
            return MatchResult(
                job=job,
                scored=True,
                match_score=score_val,
                matched_skills=met[:6],
                missing_skills=unmet[:6],
                risk_factors=[u.split(" — ")[0] for u in unmet[:2]],
                tailored_advice=note + strategy,
                required_met_ratio=ratio_txt,
            )

        if len(jobs_to_score) >= 2:
            with ThreadPoolExecutor(max_workers=5) as pool:
                results = list(pool.map(_score_one, jobs_to_score))
        else:
            results = [_score_one(j) for j in jobs_to_score]

        for job in mocks:
            results.append(MatchResult(scored=False, job=job,
                                       risk_factors=["샘플 데이터입니다. 실제 공고가 아닙니다."]))

        results.sort(
            key=lambda x: (
                x.scored,
                x.job.status == "open",
                -role_domain_penalty(profile.desired_role, profile.resume_text, x.job.title, x.job.tags),
                x.match_score,
            ),
            reverse=True,
        )
        return results

    def market_requirements(self, role: str, top: int = 10, exclude_families=()):
        group = self.store.resolve_group(role)
        if group is None:
            return []
        return self.store.market_requirements(group, top, exclude_families=exclude_families)

    @staticmethod
    def exclude_families_for(profile: "JobSeekerProfile") -> List[str]:
        """프로필에 개발 직무 경력이 보이지 않으면 소프트웨어 개발 계열 공고를 시장 집계에서 제외한다.
        (기초 수강 언급은 개발 경력으로 보지 않는다)"""
        text = f"{profile.resume_text} {' '.join(profile.skills)} {profile.desired_role}"
        dev = ("개발자", "개발 경력", "개발 경험", "소프트웨어 개발", "백엔드", "프론트엔드", "프로그래머", "SW개발", "데이터엔지니어")
        return [] if any(k in text for k in dev) else ["software_dev"]

