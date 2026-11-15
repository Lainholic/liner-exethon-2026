"""수집 공고 정제: (1) 검색 직무와의 관련성 판정 (2) 중복 표시. 원본 행은 삭제하지 않고 표시만 한다."""
import re
from typing import Any, Callable, Dict

from .llm import llm_json
from .store import PostingStore

REL_SYS = (
    "각 채용 공고가 '검색 직무'와 같은 직무군인지 판정한다. 제목과 태그만 근거로 한다. "
    "같은 직무이거나 업무 내용이 직접 겹치면 relevant=true. 다른 직무(예: 안전관리 검색에 영업관리, 공정개선 검색에 SW QA)는 false. "
    'JSON: {"items":[{"idx":int,"relevant":true|false,"reason":"10자 내외"}]}'
)


def _key(title: str) -> str:
    t = re.sub(r"[\[\]\(\)㈜\(주\)\-–·,./]", "", title.lower())
    t = re.sub(r"채용공고|채용|공고|모집|경력직|경력|신입", "", t)
    return re.sub(r"\s+", "", t)


def mark_duplicates(store: PostingStore) -> int:
    rows = store.db.execute("SELECT url,title,status FROM postings ORDER BY (status='open') DESC, fetched_at").fetchall()
    seen: Dict[str, str] = {}
    n = 0
    for url, title, _ in rows:
        k = _key(title)
        if k in seen and seen[k] != url:
            store.db.execute("UPDATE postings SET dup_of=? WHERE url=?", (seen[k], url)); n += 1
        else:
            seen.setdefault(k, url)
            store.db.execute("UPDATE postings SET dup_of=NULL WHERE url=?", (url,))
    store.db.commit()
    return n


def judge_relevance(store: PostingStore, llm: Callable[[str, str], Any] = llm_json, batch: int = 10) -> Dict[str, int]:
    rows = store.db.execute("SELECT url,role_query,title,tags FROM postings WHERE relevant IS NULL").fetchall()
    stat = {"judged": 0, "failed": 0}
    by_role: Dict[str, list] = {}
    for r in rows:
        by_role.setdefault(r[1], []).append(r)
    for role, items in by_role.items():
        for i in range(0, len(items), batch):
            chunk = items[i:i + batch]
            listing = "\n".join(f"{j}. {c[2]} | {c[3][:80]}" for j, c in enumerate(chunk))
            out = llm(REL_SYS, f"검색 직무: {role}\n{listing}")
            res = {int(x["idx"]): x for x in (out or {}).get("items", []) if str(x.get("idx", "")).lstrip("-").isdigit()}
            for j, c in enumerate(chunk):
                x = res.get(j)
                if x is None:
                    stat["failed"] += 1
                    continue  # relevant는 NULL로 남겨 재시도 가능
                store.db.execute("UPDATE postings SET relevant=?, relevance_reason=? WHERE url=?",
                                 (1 if x.get("relevant") else 0, str(x.get("reason", ""))[:40], c[0]))
                stat["judged"] += 1
            store.db.commit()
    return stat


FAMILIES = ("management_ops", "software_dev", "data_analytics", "sales_biz", "other")
FAM_SYS = (
    "각 채용 공고의 직무 계열을 하나로 분류한다. 제목, 태그, 요건만 근거로 한다. "
    "management_ops=생산/품질/설비/물류/구매/안전/PM/운영 등 현장·관리·운영 직무, "
    "software_dev=소프트웨어·시스템 개발(Java/Python/Scala 등 코딩이 핵심, 데이터엔지니어·백엔드·펌웨어 포함), "
    "data_analytics=데이터 분석/BI/통계, sales_biz=영업/마케팅/CS/기획/컨설팅, other=그 외. "
    'JSON: {"items":[{"idx":int,"family":"management_ops|software_dev|data_analytics|sales_biz|other"}]}'
)


def judge_family(store: PostingStore, llm: Callable[[str, str], Any] = llm_json, batch: int = 12) -> Dict[str, int]:
    rows = store.db.execute("SELECT url,title,tags,requirements FROM postings WHERE family IS NULL").fetchall()
    stat = {"judged": 0, "failed": 0}
    for i in range(0, len(rows), batch):
        chunk = rows[i:i + batch]
        listing = "\n".join(f"{j}. {c[1]} | {c[2][:90]} | {c[3][:110]}" for j, c in enumerate(chunk))
        out = llm(FAM_SYS, listing)
        res = {int(x["idx"]): x.get("family") for x in (out or {}).get("items", []) if str(x.get("idx", "")).isdigit()}
        for j, c in enumerate(chunk):
            f = res.get(j)
            if f in FAMILIES:
                store.db.execute("UPDATE postings SET family=? WHERE url=?", (f, c[0])); stat["judged"] += 1
            else:
                stat["failed"] += 1  # NULL로 남겨 재시도 가능
        store.db.commit()
    return stat