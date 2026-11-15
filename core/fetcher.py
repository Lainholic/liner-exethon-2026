"""공개 URL 본문 및 채용 포털(원티드/잡코리아), GitHub·블로그·ArXiv 본문 수집."""
import concurrent.futures
import html
import os
import re
from typing import Dict
from urllib.parse import urlparse
import requests

MAX_CHARS = 12000
UA = {
    "User-Agent": (
        "Mozilla/5.0 (Windows NT 10.0; Win64; x64) "
        "AppleWebKit/537.36 (KHTML, like Gecko) Chrome/131.0.0.0 Safari/537.36"
    ),
    "Accept-Language": "ko-KR,ko;q=0.9,en-US;q=0.8",
}

_WANTED_RE = re.compile(r"wanted\.co\.kr/wd/(\d+)")
_JOBKOREA_RE = re.compile(r"jobkorea\.co\.kr/Recruit/GI_Read/(\d+)", re.I)
_MANIFEST_NAMES = ("pyproject.toml", "requirements.txt", "package.json", "go.mod", "Cargo.toml", "pom.xml")
_RESERVED_GH = {
    "orgs", "users", "topics", "trending", "collections", "events",
    "explore", "marketplace", "pricing", "sponsors", "settings",
    "login", "join", "features", "security", "about",
}


def _strip_html(html_text: str) -> str:
    cleaned = re.sub(r"(?is)<(script|style|noscript|svg|header|footer|nav).*?</\1>", " ", html_text or "")
    text = re.sub(r"(?s)<[^>]+>", " ", cleaned)
    text = re.sub(r"&nbsp;|&amp;|&lt;|&gt;|&quot;", " ", text)
    return re.sub(r"\s+", " ", text).strip()


def _extract_article_html(html_text: str) -> tuple[str, dict]:
    """기술 블로그·논문 초록 등 일반 HTML 페이지에서 본문 컨테이너 및 메타데이터(코드 포함 여부, 발행일)를 추출한다."""
    has_code = False
    published_date = ""
    try:
        from bs4 import BeautifulSoup
        soup = BeautifulSoup(html_text or "", "html.parser")

        # 실습 코드 블록 감지
        if soup.find(["pre", "code"]) or "```" in (html_text or ""):
            has_code = True

        # 메타 태그 발행일 감지
        for meta in soup.find_all("meta"):
            p = (meta.get("property") or meta.get("name") or "").lower()
            if any(k in p for k in ("article:published_time", "date", "publishdate", "time", "created")):
                val = (meta.get("content") or "").strip()
                m_yr = re.search(r"(20\d{2}[-./]\d{1,2}[-./]\d{1,2})", val)
                if m_yr:
                    published_date = m_yr.group(1).replace("/", "-").replace(".", "-")
                    break

        for tag in soup(["script", "style", "noscript", "svg", "nav", "header", "footer"]):
            tag.decompose()
        for sel in (
            "blockquote.abstract",
            ".tt_article_useless_p_margin",
            ".contents_style",
            "article",
            "main",
        ):
            el = soup.select_one(sel)
            if el:
                txt = re.sub(r"\s+", " ", el.get_text(" ")).strip()
                if len(txt) > 120:
                    return txt[:MAX_CHARS], {"has_code": has_code, "published_date": published_date}
    except Exception:
        pass
    raw_txt = _strip_html(html_text)
    if not has_code and ("```" in (html_text or "") or "def " in raw_txt or "import " in raw_txt or "function " in raw_txt):
        has_code = True
    return raw_txt, {"has_code": has_code, "published_date": published_date}


def _fetch_github_repo_context(owner: str, repo: str, timeout: int = 6) -> str:
    """GitHub 저장소의 README + 최상위 파일 구조 + 의존성 매니페스트를 다층 수집한다."""
    repo = repo[:-4] if repo.endswith(".git") else repo
    api_headers = {"Accept": "application/vnd.github+json", "User-Agent": "CareerPathAgent/0.3"}
    tok = os.getenv("GITHUB_TOKEN", "").strip()
    if tok:
        api_headers["Authorization"] = f"Bearer {tok}"

    def _get_readme() -> str:
        for fname in ("README.md", "readme.md"):
            try:
                r = requests.get(
                    f"https://raw.githubusercontent.com/{owner}/{repo}/HEAD/{fname}",
                    headers=UA,
                    timeout=timeout,
                )
                if r.status_code == 200 and r.text.strip():
                    return r.text.strip()
            except Exception:
                continue
        return ""

    def _get_contents() -> list[str]:
        try:
            r = requests.get(
                f"https://api.github.com/repos/{owner}/{repo}/contents",
                headers=api_headers,
                timeout=min(timeout, 4),
            )
            if r.status_code == 200:
                data = r.json()
                if isinstance(data, list):
                    return [str(x.get("name")) for x in data if isinstance(x, dict) and x.get("name")]
        except Exception:
            pass
        return []

    with concurrent.futures.ThreadPoolExecutor(max_workers=2) as pool:
        f_rm = pool.submit(_get_readme)
        f_ls = pool.submit(_get_contents)
        readme = f_rm.result()
        names = f_ls.result()

    sections: list[str] = []
    if readme:
        sections.append(f"[README 원문]\n{readme[:7500]}")
    if names:
        sections.append(f"[저장소 최상위 파일 구조]\n{', '.join(names[:30])}")
        manifests = [m for m in _MANIFEST_NAMES if m in names][:2]
        if manifests:
            def _get_mf(fn: str):
                try:
                    r = requests.get(
                        f"https://raw.githubusercontent.com/{owner}/{repo}/HEAD/{fn}",
                        headers=UA,
                        timeout=min(timeout, 4),
                    )
                    if r.status_code == 200 and r.text.strip():
                        return fn, r.text.strip()[:1800]
                except Exception:
                    pass
                return fn, ""

            with concurrent.futures.ThreadPoolExecutor(max_workers=2) as mpool:
                for fn, txt in mpool.map(_get_mf, manifests):
                    if txt:
                        sections.append(f"[의존성 매니페스트: {fn}]\n{txt}")

    return "\n\n".join(sections)[:MAX_CHARS]


def _github_raw_candidates(url: str) -> list[str]:
    """github.com/owner/repo 이면 README 원문 후보를 우선 시도 (렌더링 HTML보다 정확)."""
    p = urlparse(url)
    parts = [x for x in p.path.split("/") if x]
    if p.netloc.lower() == "github.com" and len(parts) >= 2:
        o, r = parts[0], parts[1]
        return [
            f"https://raw.githubusercontent.com/{o}/{r}/HEAD/README.md",
            f"https://raw.githubusercontent.com/{o}/{r}/HEAD/readme.md",
        ]
    return []


def _fetch_wanted_meta(jid: str, timeout: int = 8) -> Dict[str, str]:
    api_url = f"https://www.wanted.co.kr/api/v4/jobs/{jid}"
    try:
        r = requests.get(api_url, headers={**UA, "Accept": "application/json"}, timeout=timeout)
        if r.status_code != 200:
            return {}
        data = r.json()
        job = data.get("job") if isinstance(data, dict) else None
        if not isinstance(job, dict):
            return {}
        company = str((job.get("company") or {}).get("name") or "").strip()
        title = str(job.get("position") or "").strip()
        status = "open" if job.get("status") == "active" else "closed"
        deadline = str(job.get("due_time") or "상시채용").strip()
        addr = job.get("address") or {}
        location = str(addr.get("full_location") or addr.get("location") or "").strip()
        det = job.get("detail") or {}
        parts = [f"포지션: {title}", f"회사명: {company}", f"근무지: {location}", f"마감일: {deadline}"]
        for label, key in (
            ("회사·팀 소개", "intro"),
            ("주요업무", "main_tasks"),
            ("자격요건", "requirements"),
            ("우대사항", "preferred_points"),
            ("혜택 및 복지", "benefits"),
        ):
            val = str(det.get(key) or "").strip()
            if val:
                parts.append(f"[{label}]\n{val}")
        body = "\n\n".join(parts)[:MAX_CHARS]
        return {
            "company": company,
            "title": title,
            "status": status,
            "deadline": deadline,
            "location": location,
            "body": body,
            "portal": "wanted",
        }
    except Exception:
        return {}


def _fetch_jobkorea_meta(gno: str, timeout: int = 8) -> Dict[str, str]:
    outer_url = f"https://www.jobkorea.co.kr/Recruit/GI_Read/{gno}"
    ifrm_url = f"https://www.jobkorea.co.kr/Recruit/GI_Read_Comt_Ifrm?Gno={gno}"

    def _get(u: str) -> str:
        try:
            r = requests.get(u, headers=UA, timeout=timeout)
            return r.text if r.status_code == 200 else ""
        except Exception:
            return ""

    with concurrent.futures.ThreadPoolExecutor(max_workers=2) as pool:
        f_outer = pool.submit(_get, outer_url)
        f_ifrm = pool.submit(_get, ifrm_url)
        outer_html = f_outer.result()
        ifrm_html = f_ifrm.result()

    if not outer_html and not ifrm_html:
        return {}

    company = ""
    title = ""
    m_title = re.search(r"<title[^>]*>(.*?)</title>", outer_html, re.I | re.S)
    if m_title:
        raw_t = html.unescape(re.sub(r"\s+", " ", m_title.group(1))).strip()
        m_comp = re.match(r"^\s*(.+?)\s+채용\s*[-–|]", raw_t)
        if m_comp:
            comp_cand = m_comp.group(1).strip()
            if "대기업 계열사" in comp_cand and ":" in comp_cand:
                comp_cand = comp_cand.split(":", 1)[0].strip()
            company = comp_cand[:40]
        title = raw_t.split("|")[0].strip()

    outer_txt = _strip_html(outer_html)
    ifrm_txt = _strip_html(ifrm_html)
    closed = any(k in outer_txt[:1500] for k in ("마감된 채용공고", "접수가 마감", "채용이 마감", "공고가 마감"))

    deadline = ""
    m_dl = re.search(r"마감일\s*[:：]?\s*(20\d{2}\.\d{2}\.\d{2}(?:\([가-힣]\))?|상시채용|채용시)", outer_txt)
    if m_dl:
        deadline = m_dl.group(1).strip()

    location = ""
    m_loc = re.search(r"근무지주소\s+([^\n|]{4,60}?)(?:\s+지도보기|\s+인근지하철|\s+지원자격|$)", outer_txt)
    if m_loc:
        location = m_loc.group(1).strip()

    combined = "\n\n".join(x for x in (outer_txt[:4500], f"[상세요강 본문]\n{ifrm_txt[:7000]}" if ifrm_txt else "") if x)
    return {
        "company": company,
        "title": title,
        "status": "closed" if closed else "open",
        "deadline": deadline,
        "location": location,
        "body": combined[:MAX_CHARS],
        "portal": "jobkorea",
    }


def fetch_job_posting_meta(url: str, timeout: int = 8) -> Dict[str, str]:
    """채용 포털 URL에서 기업명·상태·마감일·근무지·상세요강 본문을 직접 추출한다."""
    u = (url or "").strip()
    m_w = _WANTED_RE.search(u)
    if m_w:
        return _fetch_wanted_meta(m_w.group(1), timeout=timeout)
    m_j = _JOBKOREA_RE.search(u)
    if m_j:
        return _fetch_jobkorea_meta(m_j.group(1), timeout=timeout)
    return {}


def fetch_public_resource(url: str, timeout: int = 10) -> tuple[str, dict]:
    """공개 URL 본문 및 추가 메타데이터(코드 포함 여부, 발행일 등)를 함께 반환한다."""
    meta_info: dict = {"has_code": False, "published_date": ""}
    if _WANTED_RE.search(url or "") or _JOBKOREA_RE.search(url or ""):
        meta = fetch_job_posting_meta(url, timeout=min(timeout, 8))
        if len(meta.get("body", "")) > 80:
            return meta["body"], meta_info

    p = urlparse((url or "").strip())
    parts = [x for x in p.path.split("/") if x]
    if p.netloc.lower() in ("github.com", "www.github.com") and len(parts) == 2 and parts[0].lower() not in _RESERVED_GH:
        gh_ctx = _fetch_github_repo_context(parts[0], parts[1], timeout=min(timeout, 6))
        if len(gh_ctx) > 80:
            return gh_ctx, {"has_code": True, "published_date": ""}

    for u in _github_raw_candidates(url) + [url]:
        try:
            r = requests.get(u, headers=UA, timeout=timeout)
            if r.status_code == 200 and r.text.strip():
                if u.endswith(".md"):
                    body = r.text
                    has_code = "```" in body or "def " in body or "import " in body
                    meta_info = {"has_code": has_code, "published_date": ""}
                else:
                    body, meta_info = _extract_article_html(r.text)
                if len(body) > 80:
                    return body[:MAX_CHARS], meta_info
        except Exception:
            continue
    return "", meta_info


def fetch_public_text(url: str, timeout: int = 10) -> str:
    body, _ = fetch_public_resource(url, timeout=timeout)
    return body
