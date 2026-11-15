"""공개 GitHub API 기반 지원자 실제 커밋·기여도 및 확장자 검증 모듈."""
import concurrent.futures
import os
from collections import Counter
from typing import Any, Dict, List, Optional, Tuple
from urllib.parse import urlparse
import requests

from .code_analyzer import CodeQualityAnalyzer

RESERVED_GH_PATHS = {
    "orgs", "users", "topics", "trending", "collections", "events",
    "explore", "marketplace", "pricing", "sponsors", "settings",
    "login", "join", "features", "security", "about",
}

EXT_LANG_MAP = {
    ".py": "Python",
    ".c": "C",
    ".h": "C/C++",
    ".cpp": "C++",
    ".cc": "C++",
    ".sql": "SQL",
    ".js": "JavaScript",
    ".ts": "TypeScript",
    ".tsx": "TypeScript",
    ".jsx": "JavaScript",
    ".java": "Java",
    ".go": "Go",
    ".rs": "Rust",
    ".cs": "C#",
    ".rb": "Ruby",
    ".php": "PHP",
    ".kt": "Kotlin",
    ".swift": "Swift",
    ".ipynb": "Jupyter",
    ".sh": "Shell",
}


def parse_github_repo(url: str) -> Optional[Tuple[str, str]]:
    """github.com/{owner}/{repo} 형태의 공개 저장소 URL에서 (owner, repo)를 추출한다."""
    if not url:
        return None
    p = urlparse(url.strip())
    if p.scheme not in ("http", "https") or p.netloc.lower() not in ("github.com", "www.github.com"):
        return None
    parts = [x for x in p.path.split("/") if x]
    if len(parts) < 2:
        return None
    owner, repo = parts[0], parts[1]
    if owner.lower() in RESERVED_GH_PATHS:
        return None
    if repo.endswith(".git"):
        repo = repo[:-4]
    if not owner or not repo:
        return None
    return owner, repo


def infer_username_from_urls(urls: List[str]) -> str:
    """제출된 URL 목록 중 github.com/{username} 프로필 URL이 있으면 계정 ID를 추론한다."""
    for u in urls or []:
        if not u:
            continue
        p = urlparse(u.strip())
        if p.scheme not in ("http", "https") or p.netloc.lower() not in ("github.com", "www.github.com"):
            continue
        parts = [x for x in p.path.split("/") if x]
        if len(parts) == 1 and parts[0].lower() not in RESERVED_GH_PATHS:
            return parts[0]
    return ""


class GitHubVerifier:
    """공개 GitHub REST API로 지원자 실제 커밋 수, 최근 활동일, 언어/확장자 기여도를 대조한다."""

    BASE_URL = "https://api.github.com"

    def __init__(self, http_get=None, token: Optional[str] = None, timeout: int = 8):
        self.http_get = http_get or requests.get
        self.timeout = timeout
        tok = (token if token is not None else os.getenv("GITHUB_TOKEN", "")).strip()
        self.headers = {
            "Accept": "application/vnd.github+json",
            "User-Agent": "CareerPathAgent/0.2",
        }
        if tok:
            self.headers["Authorization"] = f"Bearer {tok}"

    def _get(self, url: str, params: Optional[Dict[str, Any]] = None):
        return self.http_get(url, headers=self.headers, params=params, timeout=self.timeout)

    @staticmethod
    def _error_card(
        repo_full: str,
        repo_url: str,
        owner: str,
        target_author: str,
        author_explicit: bool,
        status: str,
        note: str,
        commit_count: Optional[int] = None,
        pressure_question: Optional[Dict[str, str]] = None,
    ) -> Dict[str, Any]:
        return {
            "repo": repo_full,
            "url": repo_url,
            "owner": owner,
            "checked_author": target_author,
            "author_explicit": author_explicit,
            "is_fork": False,
            "parent_repo": "",
            "commit_count": commit_count,
            "latest_commit_date": "",
            "extensions": [],
            "languages": {},
            "recent_messages": [],
            "code_changes": {"additions": 0, "deletions": 0},
            "code_quality": None,
            "status": status,
            "note": note,
            "pressure_question": pressure_question,
        }

    def verify_repo(self, url: str, username: str = "") -> Optional[Dict[str, Any]]:
        """단일 GitHub 저장소의 실제 커밋 기여도를 검증한다."""
        parsed = parse_github_repo(url)
        if not parsed:
            return None
        owner, repo = parsed
        repo_full = f"{owner}/{repo}"
        repo_url = f"https://github.com/{repo_full}"
        author_explicit = bool((username or "").strip())
        target_author = (username or "").strip() or owner

        try:
            r_meta = self._get(f"{self.BASE_URL}/repos/{owner}/{repo}")
        except Exception:
            return self._error_card(
                repo_full, repo_url, owner, target_author, author_explicit,
                "확인 불가",
                "GitHub API 호출 제한 또는 네트워크 오류로 커밋 내역을 조회하지 못했습니다.",
            )

        if r_meta is None:
            return self._error_card(
                repo_full, repo_url, owner, target_author, author_explicit,
                "확인 불가",
                "GitHub API 호출 제한 또는 네트워크 오류로 커밋 내역을 조회하지 못했습니다.",
            )

        if r_meta.status_code == 404:
            pq = {
                "claim_ref": f"[GitHub 기여도] {repo_full}",
                "question": (
                    f"제출하신 '{repo_full}' 저장소가 비공개이거나 접근할 수 없습니다. "
                    "본인이 직접 작성한 핵심 코드 구조와 실행 과정을 화면 공유 또는 코드 설명으로 검증할 수 있습니까?"
                ),
                "intent": "비공개/존재하지 않는 저장소 진위 및 본인 직접 구현 여부 확인",
                "eval_criteria": "코드 아키텍처 설명의 일관성 및 핵심 로직 구현 근거 제시 여부",
                "source": "github_verifier",
            }
            return self._error_card(
                repo_full, repo_url, owner, target_author, author_explicit,
                "확인 불가",
                "저장소가 비공개이거나 존재하지 않습니다.",
                commit_count=0,
                pressure_question=pq,
            )

        if r_meta.status_code != 200:
            return self._error_card(
                repo_full, repo_url, owner, target_author, author_explicit,
                "확인 불가",
                "GitHub API 호출 제한 또는 네트워크 오류로 커밋 내역을 조회하지 못했습니다.",
            )

        try:
            meta = r_meta.json()
            if not isinstance(meta, dict):
                meta = {}
        except Exception:
            meta = {}

        is_fork = bool(meta.get("fork"))
        actual_owner = (meta.get("owner") or {}).get("login") or owner
        parent_repo = (meta.get("parent") or {}).get("full_name", "")
        target_author = (username or "").strip() or actual_owner

        commits = None
        commit_timed_out_or_5xx = False
        try:
            r_commits = self._get(
                f"{self.BASE_URL}/repos/{owner}/{repo}/commits",
                params={"author": target_author, "per_page": 30},
            )
            if r_commits is None:
                return self._error_card(
                    repo_full, repo_url, actual_owner, target_author, author_explicit,
                    "확인 불가",
                    "GitHub API 호출 제한 또는 네트워크 오류로 커밋 내역을 조회하지 못했습니다.",
                )
            if r_commits.status_code >= 500:
                commit_timed_out_or_5xx = True
            elif r_commits.status_code != 200:
                return self._error_card(
                    repo_full, repo_url, actual_owner, target_author, author_explicit,
                    "확인 불가",
                    "GitHub API 호출 제한 또는 네트워크 오류로 커밋 내역을 조회하지 못했습니다.",
                )
            else:
                raw_commits = r_commits.json()
                commits = raw_commits if isinstance(raw_commits, list) else []
        except requests.Timeout:
            commit_timed_out_or_5xx = True
        except Exception:
            return self._error_card(
                repo_full, repo_url, actual_owner, target_author, author_explicit,
                "확인 불가",
                "GitHub API 호출 제한 또는 네트워크 오류로 커밋 내역을 조회하지 못했습니다.",
            )

        if commit_timed_out_or_5xx:
            if author_explicit:
                try:
                    r_user = self._get(f"{self.BASE_URL}/users/{target_author}")
                except Exception:
                    r_user = None
                if r_user is not None and r_user.status_code == 404:
                    commits = []
                elif r_user is not None and r_user.status_code == 200 and actual_owner.lower() != target_author.lower():
                    pq = {
                        "claim_ref": f"[GitHub 기여도] {repo_full}",
                        "question": (
                            f"제출하신 '{repo_full}'(실제 소유자: {actual_owner})은 초대형 저장소로 전체 커밋 조회가 제한되었습니다. "
                            f"계정 '{target_author}'이 직접 기여한 커밋 SHA 또는 병합된 PR URL을 제시하고 구현 내용을 설명해 주십시오."
                        ),
                        "intent": "초대형 오픈소스 저장소 제출 시 실제 본인 기여 커밋·PR 진위 확인",
                        "eval_criteria": "직접 작성한 커밋 SHA/PR 링크 제시 여부 및 해당 변경 코드 설명의 일관성",
                        "source": "github_verifier",
                    }
                    return self._error_card(
                        repo_full, repo_url, actual_owner, target_author, author_explicit,
                        "타인 기여 프로젝트 / 본인 커밋 내역 미확인",
                        f"'{repo_full}'(실제 소유자: {actual_owner})은 초대형 저장소로 GitHub 전체 커밋 필터 조회가 제한되었습니다. 본인 기여 커밋 SHA 또는 PR 링크 확인이 필요합니다.",
                        commit_count=None,
                        pressure_question=pq,
                    )
            if commits is None:
                return self._error_card(
                    repo_full, repo_url, actual_owner, target_author, author_explicit,
                    "확인 불가",
                    "GitHub API 호출 제한 또는 네트워크 오류로 커밋 내역을 조회하지 못했습니다.",
                )

        commit_count = len(commits)
        latest_commit_date = ""
        if commits:
            latest_commit_date = (
                ((commits[0].get("commit") or {}).get("author") or {}).get("date", "")
            )[:10]

        if commit_count == 0:
            if author_explicit and not is_fork and actual_owner.lower() == target_author.lower():
                try:
                    r_all = self._get(
                        f"{self.BASE_URL}/repos/{owner}/{repo}/commits",
                        params={"per_page": 5},
                    )
                    raw_all = r_all.json() if (r_all is not None and r_all.status_code == 200) else []
                except Exception:
                    raw_all = []
                if isinstance(raw_all, list) and len(raw_all) > 0:
                    git_names_list = []
                    for c in raw_all[:5]:
                        gn = (((c.get("commit") or {}).get("author") or {}).get("name") or "").strip()
                        if gn and gn not in git_names_list:
                            git_names_list.append(gn)
                    git_names = ", ".join(git_names_list[:3]) or "미상"
                    unlinked_cnt = len(raw_all)
                    unlinked_msgs = [
                        ((c.get("commit") or {}).get("message") or "").splitlines()[0].strip()[:90]
                        for c in raw_all[:3]
                        if ((c.get("commit") or {}).get("message") or "").strip()
                    ]
                    pq = {
                        "claim_ref": f"[GitHub 기여도] {repo_full}",
                        "question": (
                            f"제출하신 '{repo_full}' 저장소는 지원자 계정 소유이나 '{target_author}' 계정으로 매칭된 커밋은 0건이고, "
                            f"로컬 Git 작성자({git_names}) 명의 커밋만 {unlinked_cnt}건 확인됩니다. "
                            "로컬 Git 이메일 설정과 실제 핵심 구현 코드를 면접에서 직접 설명해 주시겠습니까?"
                        ),
                        "intent": "계정 이메일 미연동 또는 타인 커밋 복사·업로드 여부 확인",
                        "eval_criteria": "로컬 Git 작성자 일치 경위 및 저장소 핵심 모듈 설계 설명의 구체성",
                        "source": "github_verifier",
                    }
                    return {
                        "repo": repo_full,
                        "url": repo_url,
                        "owner": actual_owner,
                        "checked_author": target_author,
                        "author_explicit": author_explicit,
                        "is_fork": is_fork,
                        "parent_repo": parent_repo,
                        "commit_count": 0,
                        "latest_commit_date": "",
                        "extensions": [],
                        "languages": {},
                        "recent_messages": unlinked_msgs,
                        "code_changes": {"additions": 0, "deletions": 0},
                        "status": "저장소 소유자 커밋 확인 (Git 이메일 미연동 가능성)",
                        "note": (
                            f"비포크(Non-fork) 본인 소유 저장소({repo_full})이나 '{target_author}' 이메일 연동 커밋은 0건이며 "
                            f"로컬 작성자({git_names}) 커밋 {unlinked_cnt}건이 확인됩니다."
                        ),
                        "pressure_question": pq,
                    }

            fork_info = (
                f" (원본 포크: {parent_repo})"
                if is_fork and parent_repo
                else (" (포크 저장소)" if is_fork else "")
            )
            note = (
                f"'{repo_full}' 저장소(실제 소유자: {actual_owner}{fork_info})에서 "
                f"계정 '{target_author}'의 커밋 이력이 0건입니다. "
                "타인 기여 프로젝트 제출 또는 커밋 이메일 미연동 여부를 확인하세요."
            )
            pq = {
                "claim_ref": f"[GitHub 기여도] {repo_full}",
                "question": (
                    f"제출하신 '{repo_full}' 저장소(실제 소유자: {actual_owner})에서 "
                    f"'{target_author}' 계정의 커밋 내역이 0건으로 확인됩니다. "
                    "본인이 직접 작성한 파일·함수와 커밋 계정이 다른 사유를 구체적으로 설명해 주십시오."
                ),
                "intent": "타인 프로젝트 도용·단순 포크 여부 및 본인 직접 구현 범위 검증",
                "eval_criteria": "직접 작성한 파일·함수 구조, 커밋 계정 불일치 사유 및 설계 의사결정의 구체성",
                "source": "github_verifier",
            }
            return {
                "repo": repo_full,
                "url": repo_url,
                "owner": actual_owner,
                "checked_author": target_author,
                "author_explicit": author_explicit,
                "is_fork": is_fork,
                "parent_repo": parent_repo,
                "commit_count": 0,
                "latest_commit_date": "",
                "extensions": [],
                "languages": {},
                "recent_messages": [],
                "code_changes": {"additions": 0, "deletions": 0},
                "status": "타인 기여 프로젝트 / 본인 커밋 내역 미확인",
                "note": note,
                "pressure_question": pq,
            }

        recent_messages = [
            ((c.get("commit") or {}).get("message") or "").splitlines()[0].strip()[:90]
            for c in commits[:3]
            if ((c.get("commit") or {}).get("message") or "").strip()
        ]

        languages: Dict[str, float] = {}
        try:
            r_lang = self._get(f"{self.BASE_URL}/repos/{owner}/{repo}/languages")
            if r_lang is not None and r_lang.status_code == 200:
                raw_lang = r_lang.json()
                if isinstance(raw_lang, dict):
                    total = sum(v for v in raw_lang.values() if isinstance(v, (int, float)) and v > 0)
                    if total > 0:
                        languages = {
                            k: round(100.0 * v / total, 1)
                            for k, v in raw_lang.items()
                            if isinstance(v, (int, float)) and v > 0
                        }
        except Exception:
            pass

        ext_counts: Counter = Counter()
        add_sum = 0
        del_sum = 0
        for c in commits[:2]:
            sha = (c.get("sha") or "").strip()
            if not sha:
                continue
            try:
                r_detail = self._get(f"{self.BASE_URL}/repos/{owner}/{repo}/commits/{sha}")
                if r_detail is not None and r_detail.status_code == 200:
                    detail = r_detail.json()
                    if isinstance(detail, dict):
                        st_obj = detail.get("stats") or {}
                        files = detail.get("files") or []
                        if st_obj:
                            add_sum += int(st_obj.get("additions") or 0)
                            del_sum += int(st_obj.get("deletions") or 0)
                        else:
                            for f in files:
                                add_sum += int(f.get("additions") or 0)
                                del_sum += int(f.get("deletions") or 0)
                        for f in files:
                            fname = f.get("filename") or ""
                            _, ext = os.path.splitext(fname)
                            ext = ext.lower()
                            if ext:
                                ext_counts[ext] += 1
            except Exception:
                continue

        extensions = [
            f"{EXT_LANG_MAP.get(ext, ext.lstrip('.').upper())}({ext}, {cnt}건)"
            for ext, cnt in ext_counts.most_common(6)
        ]

        pressure_q = None
        if (
            author_explicit
            and commit_count == 1
            and ext_counts
            and all(ext in (".md", ".txt", ".rst") for ext in ext_counts)
        ):
            status = "경미한 문서 기여 (핵심 코드 구현 확인 필요)"
            pressure_q = {
                "claim_ref": f"[GitHub 기여도] {repo_full}",
                "question": (
                    f"제출하신 '{repo_full}' 저장소에서 '{target_author}' 계정의 커밋은 문서 파일({', '.join(ext_counts.keys())}) 1건만 확인됩니다. "
                    "문서 수정 외에 본인이 직접 작성한 핵심 소스코드 파일과 기능 구현 내역을 설명해 주십시오."
                ),
                "intent": "단순 README·문서 1건 수정만으로 대형 프로젝트 기여를 주장하는지 검증",
                "eval_criteria": "직접 구현한 소스코드 모듈·알고리즘 구조와 커밋·PR 증빙 제시 가능 여부",
                "source": "github_verifier",
            }
        else:
            status = (
                "본인 기여 확인"
                if author_explicit
                else "저장소 소유자 커밋 확인 (지원자 ID 대조 권장)"
            )

        ext_txt = f" 주요 변경 확장자: {', '.join(extensions)}." if extensions else ""
        chg_txt = f" (변경량 +{add_sum}/-{del_sum})" if (add_sum or del_sum) else ""
        note = (
            f"계정 '{target_author}' 기준 커밋 {commit_count}건 확인"
            f" (최근 활동일: {latest_commit_date or '미상'}){chg_txt}.{ext_txt}"
        )

        # 코드 품질 및 아키텍처 AST 정적 분석
        code_quality = None
        if ext_counts.get(".py"):
            try:
                r_tree = self._get(f"{self.BASE_URL}/repos/{owner}/{repo}/git/trees/HEAD?recursive=1")
                if r_tree is not None and r_tree.status_code == 200:
                    tree_data = r_tree.json().get("tree", [])
                    py_files = [f["path"] for f in tree_data if f.get("path", "").endswith(".py") and not f.get("path", "").startswith("test")]
                    if py_files:
                        sample_path = py_files[0]
                        raw_url = f"https://raw.githubusercontent.com/{owner}/{repo}/HEAD/{sample_path}"
                        r_code = self._get(raw_url)
                        if r_code is not None and r_code.status_code == 200:
                            code_quality = CodeQualityAnalyzer.analyze_python_source(r_code.text)
                            code_quality["sampled_file"] = sample_path
            except Exception:
                pass

        return {
            "repo": repo_full,
            "url": repo_url,
            "owner": actual_owner,
            "checked_author": target_author,
            "author_explicit": author_explicit,
            "is_fork": is_fork,
            "parent_repo": parent_repo,
            "commit_count": commit_count,
            "latest_commit_date": latest_commit_date,
            "extensions": extensions,
            "languages": languages,
            "recent_messages": recent_messages,
            "code_changes": {"additions": add_sum, "deletions": del_sum},
            "code_quality": code_quality,
            "status": status,
            "note": note,
            "pressure_question": pressure_q,
        }

    def verify_user_profile(self, username: str) -> Optional[Dict[str, Any]]:
        """GitHub 계정 실존 여부, 공개/오리지널/포크 저장소 비율 및 최근 대표 저장소를 조회한다."""
        user = (username or "").strip()
        if not user:
            return None
        try:
            r_u = self._get(f"{self.BASE_URL}/users/{user}")
        except Exception:
            return None
        if r_u is None:
            return None
        if r_u.status_code == 404:
            return {
                "username": user,
                "exists": False,
                "public_repos": 0,
                "owned_repos": 0,
                "fork_repos": 0,
                "top_repos": [],
                "account_created": "",
                "note": f"공개 GitHub에서 계정 '{user}'을(를) 찾을 수 없습니다.",
            }
        if r_u.status_code != 200:
            return None
        try:
            u_data = r_u.json() if isinstance(r_u.json(), dict) else {}
        except Exception:
            u_data = {}

        repos: List[Dict[str, Any]] = []
        try:
            r_repos = self._get(
                f"{self.BASE_URL}/users/{user}/repos",
                params={"sort": "updated", "per_page": 10},
            )
            if r_repos is not None and r_repos.status_code == 200:
                raw_r = r_repos.json()
                if isinstance(raw_r, list):
                    repos = [x for x in raw_r if isinstance(x, dict)]
        except Exception:
            repos = []

        owned = [x for x in repos if not x.get("fork")]
        forks = [x for x in repos if x.get("fork")]
        top_repos = [
            f"https://github.com/{x['full_name']}"
            for x in owned[:2]
            if x.get("full_name")
        ]
        created = str(u_data.get("created_at") or "")[:10]
        pub_cnt = int(u_data.get("public_repos") or len(repos))
        return {
            "username": user,
            "exists": True,
            "public_repos": pub_cnt,
            "owned_repos": len(owned),
            "fork_repos": len(forks),
            "top_repos": top_repos,
            "account_created": created,
            "note": (
                f"GitHub 계정 '{user}' 확인 (가입일 {created or '미상'}, 공개 저장소 {pub_cnt}개 중 "
                f"최근 {len(repos)}개 기준 오리지널 {len(owned)} · 포크 {len(forks)})"
            ),
        }

    def verify_urls(self, urls: List[str], username: str = "") -> List[Dict[str, Any]]:
        """URL 목록에서 GitHub 저장소를 중복 없이 추출해 검증한다. 프로필 URL만 있으면 상위 공개 저장소를 자동 조회한다."""
        effective_user = (username or "").strip() or infer_username_from_urls(urls)
        seen = set()
        target_urls: List[str] = []
        for u in urls or []:
            parsed = parse_github_repo(u)
            if not parsed:
                continue
            key = (parsed[0].lower(), parsed[1].lower())
            if key in seen:
                continue
            seen.add(key)
            target_urls.append(u)

        if not target_urls and effective_user:
            prof = self.verify_user_profile(effective_user)
            target_urls = list((prof or {}).get("top_repos") or [])

        if not target_urls:
            return []
        if len(target_urls) >= 2:
            with concurrent.futures.ThreadPoolExecutor(max_workers=min(3, len(target_urls))) as pool:
                res_list = list(pool.map(lambda u: self.verify_repo(u, effective_user), target_urls))
            return [r for r in res_list if r is not None]
        one = self.verify_repo(target_urls[0], effective_user)
        return [one] if one is not None else []
