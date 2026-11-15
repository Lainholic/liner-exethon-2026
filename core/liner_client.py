import os
import json
import logging
import requests
from dotenv import load_dotenv

logger = logging.getLogger("LinerClient")

_ENV_PATH = os.path.join(os.path.dirname(os.path.dirname(os.path.abspath(__file__))), ".env")
load_dotenv(_ENV_PATH)

_WORK24_CACHE: dict[str, dict] = {}

class LinerClient:
    """
    LINER Platform Search & Model API Client
    With seamless Mock fallback for offline development.
    """
    def __init__(self, api_key: str = None):
        self.api_key = api_key or os.getenv("LINER_API_KEY", "").strip()
        self.search_url = "https://platform.liner.com/api/v1/tools/search/web"
        self.scholar_url = "https://platform.liner.com/api/v1/tools/search/scholar"
        self.stats = {
            "search_calls": 0,
            "search_success": 0,
            "scholar_calls": 0,
            "scholar_success": 0,
        }

    @property
    def is_live(self) -> bool:
        return bool(self.api_key and not self.api_key.startswith("your_"))

    def search_web(self, query: str, num_results: int = 3) -> list[dict]:
        """
        일반 웹 검색 (HR 포트폴리오 팩트체크 및 최신 정보 탐색 공통)
        """
        if self.is_live:
            self.stats["search_calls"] += 1
            try:
                headers = {
                    "Authorization": f"Bearer {self.api_key}",
                    "Content-Type": "application/json"
                }
                resp = requests.post(
                    self.search_url,
                    headers=headers,
                    json={
                        "query": query,
                        "max_results": num_results,
                        "include_knowledge": False
                    },
                    timeout=10
                )
                if resp.status_code == 200:
                    self.stats["search_success"] += 1
                    data = resp.json()
                    results = data.get("results", [])
                    return [
                        {
                            "title": r.get("title", ""),
                            "snippet": r.get("description", ""),
                            "url": r.get("url", ""),
                            "hostname": r.get("hostname", "")
                        }
                        for r in results
                    ]
            except Exception as e:
                logger.warning(f"search_web error: {e}")
        return []

    def search_scholar(self, query: str, num_results: int = 5) -> list[dict]:
        """
        학술 논문·특허 교차 검증용 LINER Scholar 검색 (/api/v1/tools/search/scholar)
        """
        q = (query or "").strip()
        if self.is_live and q:
            self.stats["scholar_calls"] += 1
            try:
                headers = {
                    "Authorization": f"Bearer {self.api_key}",
                    "Content-Type": "application/json",
                }
                resp = requests.post(
                    self.scholar_url,
                    headers=headers,
                    json={"query": q, "max_results": num_results},
                    timeout=10,
                )
                if resp.status_code == 200:
                    self.stats["scholar_success"] += 1
                    data = resp.json()
                    results = data.get("results", []) if isinstance(data, dict) else []
                    return [
                        {
                            "title": r.get("title", ""),
                            "url": r.get("url", ""),
                            "hostname": r.get("hostname", ""),
                            "snippet": r.get("description", ""),
                            "date": r.get("date", ""),
                            "year": (r.get("date") or "")[:4],
                            "citation_count": int(r.get("citationCount") or 0),
                            "authors": r.get("authors") or [],
                            "journal": r.get("journal") or "",
                        }
                        for r in results
                    ]
            except Exception as e:
                logger.warning(f"search_scholar error: {e}")
        return []

    def search_job_postings(self, job_title: str, num_results: int = 3) -> list[dict]:
        """원티드·잡코리아 채용 공고를 병렬 웹 검색해 정규화된 URL 목록을 반환한다."""
        if self.is_live:
            import re
            from concurrent.futures import ThreadPoolExecutor

            pat = re.compile(r"(wanted\.co\.kr/wd/\d+|jobkorea\.co\.kr/Recruit/GI_Read/\d+)")
            queries = [
                f"{job_title} 경력 채용 site:wanted.co.kr/wd",
                f"{job_title} 경력 채용 site:jobkorea.co.kr/Recruit/GI_Read",
            ]

            def _fetch_jk_live() -> list[dict]:
                try:
                    r = requests.get(
                        "https://www.jobkorea.co.kr/Search/",
                        params={"stext": f"{job_title} 경력"},
                        headers={"User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36"},
                        timeout=4,
                    )
                    if r.status_code != 200 or not r.text:
                        return []
                    gnos = list(dict.fromkeys(re.findall(r"/Recruit/GI_Read/(\d+)", r.text)))
                    return [
                        {
                            "url": f"https://www.jobkorea.co.kr/Recruit/GI_Read/{g}",
                            "hostname": "jobkorea.co.kr",
                            "title": job_title,
                            "snippet": "",
                        }
                        for g in gnos[:3]
                    ]
                except Exception:
                    return []

            with ThreadPoolExecutor(max_workers=3) as pool:
                f_web = [pool.submit(self.search_web, q, 5) for q in queries]
                f_jk = pool.submit(_fetch_jk_live)
                batches = [f_jk.result()] + [fw.result() for fw in f_web]

            seen, out = set(), []
            max_len = max((len(b) for b in batches), default=0)
            for idx in range(max_len):
                for results in batches:
                    if idx >= len(results):
                        continue
                    r = results[idx]
                    m = pat.search(r.get("url", ""))
                    if not m or m.group(1) in seen:
                        continue
                    seen.add(m.group(1))
                    out.append({
                        "id": f"LIVE-{len(out)+1}",
                        "company": r.get("hostname", ""),
                        "title": r.get("title", job_title),
                        "url": "https://www." + m.group(1),
                        "summary": r.get("snippet", ""),
                        "is_mock": False,
                    })
            if out:
                return out[:num_results]
        return self.search_jobs(job_title, senior_friendly=True)[:num_results]

    def search_training_courses(
        self, job_title: str, num_results: int = 2, missing_skills: list[str] | None = None
    ) -> list[dict]:
        """고용노동부 국민내일배움카드 훈련과정 검색 별칭 메서드."""
        return self.search_government_courses(job_title, missing_skills or [])[:num_results]

    def search_jobs(self, job_title: str, senior_friendly: bool = True) -> list[dict]:
        """
        Search 2026 current job openings matching job title and qualifications.
        """
        if self.is_live:
            try:
                headers = {
                    "Authorization": f"Bearer {self.api_key}",
                    "Content-Type": "application/json"
                }
                query = f"2026년 {job_title} 채용 공고 자격요건 우대사항 채용"
                if senior_friendly:
                    query += " 경력직 시니어 40대 중장년 환영"
                
                resp = requests.post(
                    self.search_url,
                    headers=headers,
                    json={
                        "query": query,
                        "max_results": 5,
                        "include_knowledge": False
                    },
                    timeout=10
                )
                if resp.status_code == 200:
                    data = resp.json()
                    results = data.get("results", [])
                    if results:
                        return self._parse_liner_job_results(results, job_title)
                else:
                    logger.warning(f"Live API HTTP {resp.status_code}: {resp.text[:100]}")
            except Exception as e:
                logger.warning(f"Live API error fallback to mock: {e}")

        # High-fidelity realistic Mock fallback
        return self._get_mock_jobs(job_title)

    def search_government_courses(self, job_title: str, missing_skills: list[str]) -> list[dict]:
        """
        Search MOEL (Ministry of Employment and Labor) HRD-Net free government courses.
        """
        if self.is_live:
            try:
                headers = {
                    "Authorization": f"Bearer {self.api_key}",
                    "Content-Type": "application/json"
                }
                skills_q = " ".join(missing_skills[:3]) if missing_skills else ""
                query = f"{job_title} {skills_q} 국민내일배움카드 훈련과정 site:work24.go.kr"
                
                resp = requests.post(
                    self.search_url,
                    headers=headers,
                    json={
                        "query": query,
                        "max_results": 5,
                        "include_knowledge": False
                    },
                    timeout=10
                )
                if resp.status_code == 200:
                    data = resp.json()
                    results = data.get("results", [])
                    if results:
                        parsed = self._parse_liner_course_results(results, job_title)
                        if parsed:          # 공식 도메인(work24/hrd) 결과가 있을 때만 사용
                            return self._enrich_courses_parallel(parsed)
                else:
                    logger.warning(f"Live Course HTTP {resp.status_code}: {resp.text[:100]}")
            except Exception as e:
                logger.warning(f"Live Course Search error fallback: {e}")

        return self._get_mock_courses(job_title, missing_skills)

    def _fetch_work24_cohort(self, detail_url: str, base_course: dict, timeout: float = 5) -> dict | None:
        """단일 고용24 회차 상세 페이지를 파싱한다. 미존재 회차면 None을 반환한다."""
        import re

        try:
            from bs4 import BeautifulSoup
            ua = {
                "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36",
                "Accept-Language": "ko-KR,ko;q=0.9",
            }
            getter = getattr(self, "_http_get", requests.get)
            r = getter(detail_url, headers=ua, timeout=timeout)
            if r is None or r.status_code != 200 or not r.text:
                return None
            soup = BeautifulSoup(r.text, "html.parser")

            real_title = ""
            t_el = soup.select_one(".tit_area strong.title")
            if t_el and " ".join(t_el.get_text().split()):
                real_title = " ".join(t_el.get_text().split())
            if not real_title:
                for h3 in soup.select("h3.tit1"):
                    m_t = re.search(r'귀하는\s*"([^"]+)"\s*훈련과정에', " ".join(h3.get_text().split()))
                    if m_t:
                        real_title = m_t.group(1).strip()
                        break
            if not real_title:
                return None

            enriched = dict(base_course)
            enriched["url"] = detail_url
            enriched["title"] = real_title

            top_box = None
            for el in soup.select(".tit_area, .box_border_type, .info_area, .top_area"):
                txt = " ".join(el.get_text(" ").split())
                if not txt:
                    continue
                if (real_title and real_title in txt) or "모집인원" in txt or "모집마감" in txt or "모집중" in txt:
                    top_box = el
                    break
            top_txt = " ".join(top_box.get_text(" ").split()) if top_box else ""
            if top_txt:
                org_el = top_box.select_one("strong.mr08, span.org, p.org") if top_box else None
                org_txt = " ".join(org_el.get_text().split()) if org_el else ""
                if 2 <= len(org_txt) <= 40:
                    enriched["institution"] = org_txt
                elif real_title and real_title in top_txt:
                    inst_raw = top_txt.split(real_title, 1)[0]
                    inst_raw = re.sub(r"(?:\d+년\s*인증|우수훈련기관|인증유예).*$", "", inst_raw).strip()
                    if 2 <= len(inst_raw) <= 40:
                        enriched["institution"] = inst_raw
                if "모집마감" in top_txt:
                    enriched["recruit_status"] = "모집마감"
                elif "모집중" in top_txt:
                    enriched["recruit_status"] = "모집중"
                elif "훈련중" in top_txt:
                    enriched["recruit_status"] = "훈련진행중"
                elif "모집인원" in top_txt:
                    enriched["recruit_status"] = "모집·수강신청 확인"
                else:
                    enriched["recruit_status"] = "상세 일정 확인"

                m_q = re.search(r"수강신청인원\s*(\d+명)\s*/\s*모집인원\s*(\d+명)", top_txt)
                if m_q:
                    enriched["quota"] = f"신청 {m_q.group(1)} / 정원 {m_q.group(2)}"

            kv: dict[str, str] = {}
            for em in soup.select("em.tit"):
                k = " ".join(em.get_text().split())
                par = em.parent
                if not k or par is None:
                    continue
                val = " ".join(par.get_text(" ").split())
                if val.startswith(k):
                    val = val[len(k):].strip()
                kv[k] = val

            if kv.get("훈련기간"):
                enriched["period"] = re.sub(r"\s*\(\d+회차\).*$", "", kv["훈련기간"]).strip()
            dur = kv.get("훈련시간", "")
            if dur:
                dur = re.sub(r"시간표\s*보기.*$", "", dur).strip()
                day_night = kv.get("주야구분", "").strip()
                wk = kv.get("주말여부", "").strip()
                extra = " · ".join(x for x in (day_night, wk) if x)
                enriched["duration"] = f"{dur} ({extra})" if extra else dur
            if kv.get("NCS직무분류"):
                enriched["ncs"] = kv["NCS직무분류"].strip()
            if kv.get("주소"):
                enriched["location"] = re.sub(r"지도\s*보기.*$", "", kv["주소"]).strip()
            if kv.get("훈련비"):
                won = re.findall(r"[\d,]+\s*원", kv["훈련비"])
                if won:
                    enriched["support_type"] = f"총 훈련비 {won[0]} · 국민내일배움카드(유형별 자부담 상이)"
            return enriched
        except Exception:
            return None

    def _enrich_work24_course(self, course: dict, timeout: int = 5) -> dict:
        """고용24(work24.go.kr) 상세 메타데이터를 파싱하고 마감 시 상위 모집중 회차를 자동 추적한다.
        PC 및 모바일 브라우저 모두에서 호환되는 표준 URL로 정규화한다."""
        from urllib.parse import parse_qs, urlparse

        u = (course.get("url") or "").strip()
        if "work24.go.kr" not in u:
            return course
        p = urlparse(u)
        qs = parse_qs(p.query)
        tracse_id = (qs.get("tracseId") or [""])[0]
        tme = (qs.get("tracseTme") or ["1"])[0]
        if tracse_id:
            if not tme or tme == "undefined":
                tme = "1"
            detail_url = (
                f"https://m.work24.go.kr/hr/a/a/3100/selectTracseDetl.do"
                f"?tracseId={tracse_id}&tracseTme={tme}"
            )
        elif "selectTracseDetl.do" in u:
            detail_url = u
        else:
            return course

        # 캐시 확인 (반복 조회 시 공공망 지연 방지)
        if detail_url in _WORK24_CACHE:
            return dict(_WORK24_CACHE[detail_url])

        parsed = self._fetch_work24_cohort(detail_url, course, timeout=timeout)
        if parsed is None:
            return course

        if tracse_id and tme.isdigit() and parsed.get("recruit_status") in ("모집마감", "훈련진행중"):
            for cand_tme in range(int(tme) + 1, int(tme) + 3):
                next_url = (
                    f"https://m.work24.go.kr/hr/a/a/3100/selectTracseDetl.do"
                    f"?tracseId={tracse_id}&tracseTme={cand_tme}"
                )
                if next_url in _WORK24_CACHE:
                    nxt = dict(_WORK24_CACHE[next_url])
                else:
                    nxt = self._fetch_work24_cohort(next_url, course, timeout=1.5)
                if nxt is None:
                    break
                parsed = nxt
                if parsed.get("recruit_status") == "모집중":
                    break

        # 표준 데스크톱/모바일 호환 URL 정규화
        cur_u = parsed.get("url") or detail_url
        if "tracseId=" in cur_u:
            # 고용24 상세 조회는 m.work24.go.kr 혹은 www.work24.go.kr 모두 selectTracseDetl.do 파라미터를 유지
            parsed["url"] = cur_u.strip()
        _WORK24_CACHE[detail_url] = dict(parsed)
        return parsed

    def _enrich_courses_parallel(self, courses: list[dict]) -> list[dict]:
        import re
        from concurrent.futures import ThreadPoolExecutor

        target_courses = courses[:2]
        if len(target_courses) <= 1:
            out = [self._enrich_work24_course(c, timeout=2.0) for c in target_courses]
        else:
            with ThreadPoolExecutor(max_workers=2) as pool:
                out = list(pool.map(lambda c: self._enrich_work24_course(c, timeout=2.0), target_courses))

        def _end_year(c: dict) -> int:
            yrs = re.findall(r"(20\d{2})", c.get("period") or "")
            return int(yrs[-1]) if yrs else 2026

        def _status_rank(c: dict) -> int:
            st = c.get("recruit_status") or ""
            if "모집중" in st:
                return 0
            if "마감" in st:
                return 2
            return 1

        recent = [c for c in out if _end_year(c) >= 2025]
        filtered = recent if recent else out
        filtered.sort(key=lambda c: (_status_rank(c), -_end_year(c)))
        return filtered

    def _parse_liner_job_results(self, results: list, job_title: str) -> list[dict]:
        parsed = []
        for i, r in enumerate(results[:3], 1):
            title = r.get("title", f"{job_title} 전문 인력 채용")
            desc = r.get("description", "")
            url = r.get("url", "#")
            hostname = r.get("hostname", "주요 채용 포털")
            parsed.append({
                "id": f"LIVE-JOB-{i}",
                "company": f"[{hostname}] {job_title} 채용",
                "title": title,
                "location": "서울/수도권 및 전국 (공고 참조)",
                "salary": "면접 후 협의 (경력 기반 우대)",
                "required_experience": "경력직 (중장년/시니어 우대)",
                "requirements": [
                    "해당 직무 실무 프로젝트 유경험자",
                    "조직 관리 및 유관 부서와의 능숙한 커뮤니케이션 역량"
                ],
                "preferred": [
                    "관련 기사/산업기사 자격증 또는 최신 도구 활용 가능자",
                    "디지털 전환(DX) 및 AI 생산성 도구 경험자 우대"
                ],
                "source_url": url,
                "url": url,
                "summary": desc,
                "is_mock": False
            })
        return parsed

    def _parse_liner_course_results(self, results: list, job_title: str) -> list[dict]:
        parsed = []
        official = [r for r in results if any(h in (r.get("url") or "") for h in ("work24.go.kr", "hrd.go.kr"))]
        for i, r in enumerate(official[:3], 1):
            title = r.get("title") or f"{job_title} 훈련과정"
            desc = r.get("description", "")
            if title.startswith(("국민내일배움카드", "직업능력개발", "훈련")) and desc:
                title = desc[:70]  # 제목이 일반 문구일 때는 검색 요약문을 과정 설명으로 사용
            if any(k in title for k in ("서브메뉴", "메뉴 열기", "훈련 찾기", "바로가기")):
                title = f"{job_title} 관련 훈련과정 (고용24 상세 페이지에서 과정명 확인)"  # 메뉴 문구는 과정명이 아님
            url = r.get("url", "https://www.hrd.go.kr")
            hostname = r.get("hostname", "HRD-Net")
            parsed.append({
                "id": f"LIVE-CRS-{i}",
                "institution": "고용24(work24.go.kr) 등록 훈련과정" if "work24.go.kr" in url else hostname,
                "title": title,
                "support_type": "국민내일배움카드 훈련과정 (자부담·지원 한도는 상세 페이지에서 확인)",
                "duration": "",
                "target_skills": [],
                "url": url,
                "summary": desc,
                "is_mock": False
            })
        return parsed

    def _get_mock_jobs(self, job_title: str) -> list[dict]:
        return [
            {
                "id": "MOCK-JOB-01",
                "company": "(주)스마트퓨처테크",
                "title": f"2026 {job_title} 총괄 및 시니어 프로젝트 매니저(PM)",
                "location": "서울 강남구 (하이브리드 주2일 재택)",
                "salary": "연 5,500만 ~ 7,500만 원 (경력별 협의)",
                "required_experience": "유관 경력 7년 이상 (만 40세 이상 경력자 적극 우대)",
                "requirements": [
                    f"{job_title} 관련 프로젝트 실무 리딩 경험 5년 이상",
                    "팀원 멘토링 및 일정/품질 관리 프로세스 수립 역량",
                    "비즈니스 요구사항을 기술 스펙으로 전환 가능한 커뮤니케이션"
                ],
                "preferred": [
                    "PMP 자격증 또는 유관 국가공인 자격증 보유자",
                    "AI 협업 툴(Liner 등)을 실무에 적극 도입한 경험",
                    "중장년 디지털 일자리 지원사업 참여 이력 우대"
                ],
                "source_url": "https://www.saramin.co.kr",
                "url": "https://www.saramin.co.kr",
                "summary": "전통 제조·서비스 프로세스에 AI/디지털 전환을 결합하는 총괄 매니저 포지션입니다.",
                "is_mock": True
            },
            {
                "id": "MOCK-JOB-02",
                "company": "한국데이터시스템",
                "title": f"[경력] {job_title} 운영 및 데이터 파이프라인 관리자",
                "location": "경기 판교 / 재택 가능",
                "salary": "연 4,800만 ~ 6,500만 원",
                "required_experience": "경력 4년 이상 (나이 무관/경력단절 환영)",
                "requirements": [
                    "현업 프로세스 분석 및 표준 운영 절차(SOP) 작성 능력",
                    "실무 데이터 정리 및 리포트 작성 숙련자 (Excel 고급, SQL 기초)"
                ],
                "preferred": [
                    "SQLD, 정보처리기사 또는 ADsP 자격증 보유자",
                    "클라우드/ERP 시스템 운영 경험자"
                ],
                "source_url": "https://www.wanted.co.kr",
                "url": "https://www.wanted.co.kr",
                "summary": "기존 시니어 베테랑의 업무 노하우를 바탕으로 시스템 고도화를 주도할 담당자를 채용합니다.",
                "is_mock": True
            },
            {
                "id": "MOCK-JOB-03",
                "company": "(유)글로벌네트워크솔루션",
                "title": f"{job_title} 시니어 전문 컨설턴트 및 고객사 기술지원",
                "location": "서울 영등포구 / 경기",
                "salary": "연 5,000만 ~ 6,800만 원 (성과 인센티브 별도)",
                "required_experience": "동종업계 경력 8년 이상",
                "requirements": [
                    "고객사 현장 이슈 진단 및 실행 가능한 솔루션 제시 능력",
                    "체계적인 문서화 및 보고서 발표 경험"
                ],
                "preferred": [
                    "직무 관련 전문 자격증 및 실무 포트폴리오 보유자",
                    "공공기관/대기업 프로젝트 납품 실적 유경험자"
                ],
                "source_url": "https://www.jobkorea.co.kr",
                "url": "https://www.jobkorea.co.kr",
                "summary": "풍부한 현장 경험과 신뢰도를 기반으로 고객사 파트너십을 이끌 시니어 전문가를 모십니다.",
                "is_mock": True
            }
        ]

    def _get_mock_courses(self, job_title: str, missing_skills: list[str]) -> list[dict]:
        skills_str = ", ".join(missing_skills[:2]) if missing_skills else "최신 디지털 직무 역량"
        return [
            {
                "id": "MOCK-CRS-01",
                "institution": "한국인공지능진흥원 & 폴리텍대학",
                "title": f"2026 중장년 디지털 리스킬링: {job_title} 실무 & {skills_str} 완성",
                "support_type": "샘플 데이터 - 실제 과정이 아닙니다",
                "duration": "12주 (총 180시간, 온·오프라인 블렌디드 러닝)",
                "target_skills": ["실무 프로젝트 실습", "AI 업무자동화", "포트폴리오 1:1 코칭"],
                "url": "https://www.hrd.go.kr",
                "is_mock": True
            },
            {
                "id": "MOCK-CRS-02",
                "institution": "서울디지털평생교육원",
                "title": f"시니어 베테랑을 위한 {job_title} 국가공인 자격증 및 핵심 데이터 실무",
                "support_type": "샘플 데이터 - 실제 과정이 아닙니다",
                "duration": "8주 (주말 집중반 / 100% 온라인)",
                "target_skills": ["국가공인 자격증 필기/실기", "최신 툴 활용", "현업 적용 사례"],
                "url": "https://www.hrd.go.kr",
                "is_mock": True
            }
        ]
