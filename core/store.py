"""공고 데이터 저장소 (SQLite). 마감 공고도 보관한다.
- 저장: URL, 제목, 상태(open/closed), 마감일, 추출된 자격요건/우대사항, 수집시각.
- 원문 전체는 저장하지 않는다 (저작권/용량). 추출 결과와 출처 URL만 보관.
- 용도: (1) 재수집 없이 재사용 (2) 직무별 '시장 요구사항' 집계 (3) 마감 공고를 참고 데이터로 제공.
"""
import json
import os
import re
import sqlite3
import time
from collections import Counter
from datetime import date
from typing import Dict, List, Optional, Sequence, Tuple
from urllib.parse import urlparse

DEFAULT_PATH = os.path.join(os.path.dirname(os.path.dirname(os.path.abspath(__file__))), "data", "postings.db")

PORTAL_DOMAINS = {
    "wanted.co.kr", "www.wanted.co.kr",
    "jobkorea.co.kr", "www.jobkorea.co.kr", "m.jobkorea.co.kr",
    "saramin.co.kr", "www.saramin.co.kr",
}
_GENERIC_BRACKET_WORDS = {
    "급구", "경력", "경력직", "신입", "채용", "공고", "정규직", "계약직",
    "프리랜서", "공정엔지니어", "시니어", "중견그룹자회사", "중견기업",
}
_NICHE_DOMAIN_TERMS = (
    "반도체", "웨이퍼", "mems", "식각", "증착", "gdl", "연료전지",
    "약국", "게임", "웹툰", "제약", "바이오", "병원", "간호",
)
_ROLE_STOP_TOKENS = {"관리자", "담당자", "매니저", "엔지니어", "채용", "공고", "직원", "전문가", "팀장", "경력"}

_DEADLINE_RE = re.compile(r"(20\d{2})\s*[.\-/년]\s*(\d{1,2})\s*[.\-/월]\s*(\d{1,2})")
_GENERIC_ONLY_RE = re.compile(
    r"^(?:학력|경력|고졸|초대졸|대졸|전문대졸|신입|경력무관|학력무관|경력\s*\(?\d+\s*년\s*(?:이상|이하)?\)?|\d+\s*년\s*(?:이상|이하)?)"
    r"(?:\s*\([^)]*\))?(?:\s*(?:이상|이하|무관|가능))?$"
)
_LOGI_PAT = re.compile(r"(?:인근\s*거주|차량\s*소지|자차\s*보유|운전\s*가능|통근\s*버스|기숙사|즉시\s*출근|야간\s*근무)")


def is_generic_requirement(req: str) -> bool:
    """학력·연차 등 일반 형식 조건 여부를 판정한다."""
    s = (req or "").strip()
    if not s or len(s) <= 2:
        return True
    if s in ("성별무관", "나이무관", "연령무관"):
        return True
    return bool(_GENERIC_ONLY_RE.match(s))


def is_logistics_requirement(req: str) -> bool:
    """거주지·운전·통근 등 비핵심 부수 조건 여부를 판정한다."""
    return bool(_LOGI_PAT.search((req or "").strip()))


def portal_label(url: str) -> str:
    host = urlparse((url or "").strip()).netloc.lower()
    if "wanted.co.kr" in host:
        return "원티드"
    if "jobkorea.co.kr" in host:
        return "잡코리아"
    if "work24.go.kr" in host or "hrd.go.kr" in host:
        return "고용24"
    if "saramin.co.kr" in host:
        return "사람인"
    return host.replace("www.", "") or "채용 포털"


def clean_company_name(company: str, title: str = "", url: str = "") -> str:
    """도메인 문자열('wanted.co.kr' 등)을 배제하고 공고 제목·메타에서 실제 기업명을 정제한다."""
    c = (company or "").strip()
    if c and c.lower() not in PORTAL_DOMAINS and not re.search(r"\.(?:co\.kr|com|net|kr)$", c.lower()):
        return c
    t = (title or "").strip()
    m_b = re.match(r"^\s*\[([^\]]{2,25})\]", t)
    if m_b:
        cand = m_b.group(1).strip()
        if cand not in _GENERIC_BRACKET_WORDS and not any(g == cand for g in _GENERIC_BRACKET_WORDS):
            return cand
    m_c = re.match(r"^\s*((?:\(주\)|㈜)?[가-힣A-Za-z0-9·&]{2,25}(?:\(주\)|㈜)?)\s+채용\s*[-–]", t)
    if m_c:
        return m_c.group(1).strip()
    m_head = re.match(r"^\s*((?:\(주\)|㈜)[가-힣A-Za-z0-9]{2,20}|[가-힣A-Za-z0-9]{2,20}(?:\(주\)|㈜))(?:\s|$)", t)
    if m_head:
        return m_head.group(1).strip()
    lbl = portal_label(url)
    return f"{lbl} 등록 기업" if lbl in ("원티드", "잡코리아", "사람인") else "채용 기업"


def role_domain_penalty(role: str, resume_text: str, title: str, tags: Sequence[str] = ()) -> int:
    """목표 직무/이력서에 없는 특수 업종 키워드(반도체·연료전지·게임 등)가 공고에 있으면 패널티 1을 부여한다."""
    q_txt = f"{role or ''} {resume_text or ''}".lower()
    p_txt = f"{title or ''} {' '.join(tags or ())}".lower()
    return 1 if any(term in p_txt and term not in q_txt for term in _NICHE_DOMAIN_TERMS) else 0

ROLE_SYNONYMS: List[Tuple[Tuple[str, ...], List[str]]] = [
    (("b2b", "saas", "어카운트", "세일즈", "솔루션", "영업"), ["B2B 영업 관리", "고객성공 매니저"]),
    (("csm", "고객성공", "고객사 관리", "리텐션"), ["고객성공 매니저", "B2B 영업 관리"]),
    (("스마트팩토리", "스마트공장", "mes"), ["스마트팩토리 데이터 관리자", "공정개선 엔지니어", "생산관리"]),
    (("품질", "qa", "qc", "iso"), ["품질관리 관리자", "공정개선 엔지니어", "스마트팩토리 데이터 관리자"]),
    (("설비", "보전", "예지보전", "유지보수"), ["설비보전 엔지니어", "스마트팩토리 데이터 관리자"]),
    (("공정", "생산기술", "수율"), ["공정개선 엔지니어", "생산관리"]),
    (("생산", "제조", "공장"), ["생산관리", "공정개선 엔지니어", "스마트팩토리 데이터 관리자"]),
    (("물류", "scm", "포워딩"), ["물류 SCM 관리자", "구매 자재 관리"]),
    (("구매", "자재", "조달", "소싱"), ["구매 자재 관리", "물류 SCM 관리자"]),
    (("erp", "sap", "경영정보", "재무", "회계"), ["ERP 운영 담당자"]),
    (("pm", "프로젝트", "pl"), ["프로젝트 매니저 PM"]),
    (("데이터 분석", "데이터분석", "분석가", "bi", "애널리스트", "라벨링", "ai 데이터"), ["데이터 분석가", "스마트팩토리 데이터 관리자"]),
    (("안전", "중대재해", "산업안전", "위험성평가", "ehs"), ["안전관리 담당자"]),
    (("esg", "지속가능", "탄소", "환경경영"), ["ESG 컨설턴트"]),
]


def is_deadline_expired(deadline: str, today: Optional[date] = None) -> bool:
    """'YYYY.MM.DD' 형태 마감일이 오늘 이전이면 True, 상시·미확인·오늘 이후면 False를 반환한다."""
    m = _DEADLINE_RE.search(deadline or "")
    if not m:
        return False
    try:
        dl_date = date(int(m.group(1)), int(m.group(2)), int(m.group(3)))
    except ValueError:
        return False
    return dl_date < (today or date.today())


class PostingStore:
    def __init__(self, path: str = DEFAULT_PATH):
        if path != ":memory:":
            os.makedirs(os.path.dirname(path), exist_ok=True)
        self.db = sqlite3.connect(path)
        self.db.execute("""CREATE TABLE IF NOT EXISTS postings(
            url TEXT PRIMARY KEY, role_query TEXT, title TEXT, company TEXT,
            status TEXT, deadline TEXT, requirements TEXT, preferred TEXT,
            fetched_at REAL, tags TEXT DEFAULT '[]')""")
        self._migrate()
        self.db.commit()

    def get(self, url: str, max_age_days: float = 90) -> Optional[Dict]:
        row = self.db.execute("SELECT url,role_query,title,company,status,deadline,requirements,preferred,fetched_at,tags,details "
                              "FROM postings WHERE url=?", (url,)).fetchone()
        if not row or (time.time() - row[8]) > max_age_days * 86400:
            return None
        return {"url": row[0], "role_query": row[1], "title": row[2], "company": row[3], "status": row[4],
                "deadline": row[5], "requirements": json.loads(row[6]), "preferred": json.loads(row[7]),
                "tags": json.loads(row[9]), "details": json.loads(row[10] or "{}")}

    def get_family(self, url: str) -> Optional[str]:
        row = self.db.execute("SELECT family FROM postings WHERE url=?", (url,)).fetchone()
        return row[0] if row else None

    def put(self, url: str, role_query: str, title: str, company: str, status: str, deadline: str,
            requirements: List[str], preferred: List[str], tags: List[str] = (), details: Optional[Dict] = None) -> None:
        self.db.execute("INSERT INTO postings(url,role_query,title,company,status,deadline,requirements,preferred,fetched_at,tags,details) VALUES(?,?,?,?,?,?,?,?,?,?,?) ON CONFLICT(url) DO UPDATE SET role_query=excluded.role_query,title=excluded.title,company=excluded.company,status=excluded.status,deadline=excluded.deadline,requirements=excluded.requirements,preferred=excluded.preferred,fetched_at=excluded.fetched_at,tags=excluded.tags,details=excluded.details",
                        (url, role_query, title, company, status, deadline,
                         json.dumps(requirements, ensure_ascii=False), json.dumps(preferred, ensure_ascii=False),
                         time.time(), json.dumps(list(tags), ensure_ascii=False), json.dumps(details or {}, ensure_ascii=False)))
        self.db.commit()

    def by_role(self, role_query: str) -> List[Dict]:
        rows = self.db.execute("SELECT url FROM postings WHERE role_query=? AND requirements!='[]'", (role_query,)).fetchall()
        return [self.get(r[0], max_age_days=3650) for r in rows]

    def market_requirements(self, role_query: str, top: int = 10, min_sample: int = 8, exclude_families=()) -> List[Dict]:
        """정제된 공고(마감 포함)에서 자주 등장하는 '역량' 태그. 학력/경력연차 같은 일반 조건은 제외.
        sample_size(n)와 reliable(n>=min_sample)을 항상 함께 반환한다."""
        generic = re.compile(r"(학력|졸업?|졸$|대졸|초대졸|고졸|무관|신입|경력|\d+\s*년\s*(이상|이하)?|이상$|이하$)")
        posts = self.curated(role_query, exclude_families)
        c = Counter()
        for p in posts:
            for r in set(t.strip() for t in p.get("tags", [])):
                if r and not generic.search(r):
                    c[r] += 1
        n = len(posts)
        return [{"requirement": k, "count": v, "sample_size": n, "reliable": n >= min_sample}
                for k, v in c.most_common(top)]

    def _available_groups(self) -> List[str]:
        return [g for (g,) in self.db.execute("SELECT DISTINCT role_query FROM postings WHERE relevant=1 AND dup_of IS NULL")]

    @staticmethod
    def _synonym_groups(role: str, avail_set: set[str]) -> List[str]:
        rl = (role or "").lower()
        found: List[str] = []
        for keys, targets in ROLE_SYNONYMS:
            if any(k in rl for k in keys):
                for tgt in targets:
                    if tgt in avail_set and tgt not in found:
                        found.append(tgt)
        return found

    def resolve_group(self, role: str, min_sim: float = 0.5) -> Optional[str]:
        """입력 직무와 가장 비슷한 '정제된 공고가 있는' 저장 그룹을 찾는다.
        글자 bigram Jaccard 유사도가 min_sim 미만이면 ROLE_SYNONYMS에서 실제 DB 보유 그룹을 매칭한다."""
        def bg(s: str):
            s = "".join(s.split())
            return {s[i:i + 2] for i in range(len(s) - 1)} or {s}

        available = self._available_groups()
        if not available:
            return None
        target = bg(role)
        best, best_sim = None, 0.0
        for g in available:
            b = bg(g)
            sim = len(target & b) / len(target | b)
            if sim > best_sim:
                best, best_sim = g, sim
        if best_sim >= min_sim:
            return best
        syn = self._synonym_groups(role, set(available))
        return syn[0] if syn else None

    def open_candidates_for_role(
        self,
        role: str,
        exclude_families: Sequence[str] = (),
        resume_text: str = "",
        limit: int = 5,
        preferred_region: str = "",
    ) -> List[Dict]:
        """직무 그룹과 연관 동의어 그룹에서 도메인 부합도와 요건 충실도, 지역 적합성을 반영해 진행 중 정제 공고를 정렬 반환한다."""
        available = self._available_groups()
        avail_set = set(available)
        groups: List[str] = []
        primary = self.resolve_group(role)
        if primary:
            groups.append(primary)
        for g in self._synonym_groups(role, avail_set):
            if g not in groups:
                groups.append(g)

        role_toks = {
            tok for tok in re.findall(r"[a-z0-9가-힣]{2,}", (role or "").lower())
            if tok not in _ROLE_STOP_TOKENS
        }

        # 지역 키워드 매핑
        capital_keywords = ("서울", "경기", "인천", "판교", "분당", "수원", "성남", "용인", "화성", "안양", "과천", "부천", "일산", "고양", "송도", "수도권")
        province_keywords = ("부산", "울산", "대구", "경남", "경북", "광주", "전남", "전북", "대전", "충남", "충북", "세종", "강원", "제주", "포항", "창원", "구미", "청주", "천안", "아산")

        pref_reg = (preferred_region or "").strip()

        seen_urls: set[str] = set()
        scored_rows: List[Tuple[Tuple[int, int, int, int, int, int, int, int], Dict]] = []
        for grp_idx, g in enumerate(groups):
            posts = self.curated(g, exclude_families=exclude_families)
            for post_idx, p in enumerate(posts):
                if not p or p["url"] in seen_urls:
                    continue
                if p.get("status") != "open" or is_deadline_expired(p.get("deadline", "")):
                    continue
                seen_urls.add(p["url"])
                all_reqs = list(p.get("requirements", [])) + list(p.get("preferred", []))
                specific_cnt = sum(
                    1 for r in all_reqs
                    if not is_generic_requirement(r) and not is_logistics_requirement(r)
                ) + (1 if (p.get("details") or {}).get("duties") else 0)
                title = p.get("title", "")
                tags = p.get("tags") or []
                dom_pen = role_domain_penalty(role, resume_text, title, tags)
                hay = f"{g} {title} {' '.join(tags)}".lower()
                role_hits = sum(1 for tok in role_toks if tok in hay)

                # 지역 일치 페널티 (0=선호 일치, 1=무관/미확인, 2=비선호)
                reg_pen = 0
                if pref_reg:
                    loc_text = f"{p.get('location', '')} {(p.get('details') or {}).get('work_location', '')}"
                    if "수도권" in pref_reg or "서울" in pref_reg:
                        if any(k in loc_text for k in capital_keywords):
                            reg_pen = 0
                        elif any(k in loc_text for k in province_keywords):
                            reg_pen = 2
                        else:
                            reg_pen = 1
                    elif "지방" in pref_reg or "영남" in pref_reg or "호남" in pref_reg or "충청" in pref_reg:
                        if any(k in loc_text for k in province_keywords):
                            reg_pen = 0
                        elif any(k in loc_text for k in capital_keywords):
                            reg_pen = 2
                        else:
                            reg_pen = 1

                key = (
                    dom_pen,
                    reg_pen,
                    0 if grp_idx == 0 else 1,
                    -role_hits,
                    0 if specific_cnt >= 2 else 1,
                    -min(specific_cnt, 6),
                    grp_idx,
                    post_idx,
                )
                scored_rows.append((key, p))

        scored_rows.sort(key=lambda x: x[0])
        return [x[1] for x in scored_rows[:limit]]

    def _migrate(self):
        cols = {r[1] for r in self.db.execute("PRAGMA table_info(postings)")}
        for name, ddl in (("relevant", "INTEGER"), ("relevance_reason", "TEXT"), ("dup_of", "TEXT"), ("details", "TEXT"), ("family", "TEXT")):
            if name not in cols:
                self.db.execute(f"ALTER TABLE postings ADD COLUMN {name} {ddl}")

    def curated(self, role_query: str, exclude_families=()) -> List[Dict]:
        """관련성 통과(또는 미설정 기본값) + 중복 아님 + 요건 충실(태그 2개 이상) 공고만."""
        rows = self.db.execute("SELECT url FROM postings WHERE role_query=? AND (relevant=1 OR relevant IS NULL) AND dup_of IS NULL", (role_query,)).fetchall()
        posts = [self.get(r[0], max_age_days=3650) for r in rows]
        fam = {r[0]: r[1] for r in self.db.execute("SELECT url,family FROM postings WHERE role_query=?", (role_query,))}
        return [p for p in posts if p and len(p.get("tags", [])) >= 2 and fam.get(p["url"]) not in set(exclude_families)]
