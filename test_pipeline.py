"""정답이 있는 테스트 (외부 호출은 스텁). 실행: python test_pipeline.py"""
import sys, os
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))

from core.legal_sanitizer import LegalSanitizer
from core.hr_fact_checker import HRFactChecker
from core.analyzer import ProfileAnalyzer, JobSeekerProfile
from core.store import PostingStore

README = "This project is a FastAPI gateway. We use Kafka for event streaming and Redis cache."
CLAIMS = [
    {"claim": "FastAPI 기반 게이트웨이 설계", "category": "기술"},
    {"claim": "비공개 사내 ERP DB 마이그레이션", "category": "내부"},
    {"claim": "Kafka로 초당 3000건 처리", "category": "성능"},
]


def fake_fetch(url):
    return README if "github.com" in url else ""


def test_pii():
    raw = "010-1234-5678 720101-1234567 a@b.com 서울특별시 강남구 테헤란로 123"
    out, st = LegalSanitizer.sanitize_text(raw)
    for leak in ["010-1234-5678", "720101-1234567", "a@b.com"]:
        assert leak not in out, leak
    assert st["rrn_masked"] == 1 and st["phone_masked"] == 1 and st["email_masked"] == 1


def test_unsupported_claim_is_unverified():
    # 본문에 없는 인용문은 '확인 불가'로 강등되어야 한다
    def llm(system, user):
        if "results" in system:
            return {"results": [
                {"idx": 0, "status": "verified", "quote": "This project is a FastAPI gateway."},
                {"idx": 1, "status": "verified", "quote": "ERP migration completed in 2019"},  # 조작 인용
                {"idx": 2, "status": "partial", "quote": "We use Kafka for event streaming"},
            ]}
        return {"questions": [{"idx": 1, "question": "ERP 마이그레이션에서 본인 역할은?", "intent": "x", "eval_criteria": "y"}]}
    r = HRFactChecker(fetch=fake_fetch, llm=llm).verify_portfolio(CLAIMS, ["https://github.com/a/b"])
    s = [c["status"] for c in r["evidence_cards"]]
    assert s == ["확인된 내용", "확인 불가", "일부 확인"], s
    assert r["evidence_cards"][0]["evidence_quote"]
    assert r["interview_questions"][0]["claim_ref"] == CLAIMS[1]["claim"]  # 확인 불가 항목 우선


def test_disallowed_url_and_no_llm():
    r = HRFactChecker(fetch=fake_fetch, llm=lambda s, u: None).verify_portfolio(
        CLAIMS, ["https://facebook.com/someone", "https://evil.com/github.com"])
    assert all(c["status"] == "확인 불가" for c in r["evidence_cards"])
    assert len(r["audit_summary"]["rejected_urls"]) == 2
    assert r["interview_questions"] and r["interview_questions"][0]["source"] == "fallback"


class FakeLiner:
    def __init__(self, jobs): self.jobs = jobs
    def search_job_postings(self, role, num_results=3): return self.jobs


def test_mock_and_failed_extraction_not_scored():
    jobs = [{"id": "M", "company": "c", "title": "t", "is_mock": True},
            {"id": "L", "company": "c", "title": "t", "url": "https://x.com/job", "is_mock": False}]
    a = ProfileAnalyzer(FakeLiner(jobs), fetch=lambda u: "", llm=lambda s, u: None, store=PostingStore(":memory:"))
    res = a.analyze_profile(JobSeekerProfile(desired_role="x", skills=["a"], resume_text="r"))
    assert all(not r.scored for r in res)


def test_scoring_from_extracted_requirements():
    jobs = [{"id": "L", "company": "c", "title": "t", "url": "https://x.com/job", "is_mock": False}]
    def llm(system, user):
        if "자격요건과 우대사항" in system:
            return {"is_job_posting": True, "requirements": ["품질관리 5년", "SQL"], "preferred": [], "deadline": "2026-12-01"}
        return {"items": [{"req": "품질관리 5년", "met": True, "reason": "24년"}, {"req": "SQL", "met": False, "reason": "없음"}]}
    a = ProfileAnalyzer(FakeLiner(jobs), fetch=lambda u: "공고 본문 " * 20, llm=llm, store=PostingStore(":memory:"))
    r = a.analyze_profile(JobSeekerProfile(desired_role="x", resume_text="품질관리 24년"))[0]
    assert r.scored and r.match_score == 50 and r.job.deadline == "2026-12-01"


def test_curate_relevance_and_dup():
    from core.curate import mark_duplicates, judge_relevance
    s = PostingStore(":memory:")
    s.put("u1", "안전관리", "[A사] 안전관리자 채용 공고", "w", "open", "", ["a"], [], ["안전", "산업안전", "3년이상"])
    s.put("u2", "안전관리", "A사 채용 - 안전관리자", "j", "closed", "", ["a"], [], ["안전", "산업안전", "3년이상"])  # 중복
    s.put("u3", "안전관리", "[B사] 영업관리 시니어", "w", "open", "", ["a"], [], ["영업", "관리", "3년이상"])
    assert mark_duplicates(s) == 1
    def llm(sys_, user):
        return {"items": [{"idx": 0, "relevant": True, "reason": "동일"}, {"idx": 1, "relevant": True, "reason": "동일"},
                          {"idx": 2, "relevant": False, "reason": "영업"}]}
    st = judge_relevance(s, llm)
    assert st["judged"] == 3 and st["failed"] == 0
    cur = s.curated("안전관리")
    assert [p["url"] for p in cur] == ["u1"]            # u2=중복, u3=무관 제외
    assert s.market_requirements("안전관리")[0]["sample_size"] == 1
    # LLM 실패 시 relevant는 NULL로 남아 재시도 가능
    s.put("u4", "안전관리", "[C사] 안전", "w", "open", "", ["a"], [], ["x", "y", "z"])
    assert judge_relevance(s, lambda a, b: None)["failed"] == 1

def test_roadmap_uses_market_only_when_reliable():
    from core.roadmap import RoadmapGenerator
    class L:
        def search_training_courses(self, role, num_results=2): return []
    g = RoadmapGenerator(L())
    p = JobSeekerProfile(desired_role="x")
    weak = g.generate_roadmap(p, None, market=[{"requirement": "SQL", "count": 2, "sample_size": 3, "reliable": False}])
    assert weak["market"]["reliable"] is False and weak["market"]["top"] == [] and "부족" in weak["market_note"]
    assert "SQL" not in weak["phases"][0]["goal"]
    strong = g.generate_roadmap(p, None, market=[{"requirement": "SQL", "count": 7, "sample_size": 10, "reliable": True}])
    assert "SQL" in strong["phases"][0]["goal"] and "10건" in strong["market_note"]
    assert g.generate_roadmap(p, None)["market"]["sample_size"] == 0


def test_market_excludes_generic_tags():
    s = PostingStore(":memory:")
    for i in range(8):
        s.put(f"u{i}", "r", f"t{i}", "c", "open", "", ["a"], [], ["SQL", "학력무관", "5년이상"])
        s.db.execute("update postings set relevant=1 where url=?", (f"u{i}",))
    m = s.market_requirements("r")
    assert [x["requirement"] for x in m] == ["SQL"] and m[0]["reliable"] is True

def test_family_exclusion_changes_market():
    from core.curate import judge_family
    s = PostingStore(":memory:")
    for i in range(10):
        dev = i < 5
        s.put(f"u{i}", "r", f"t{i}", "c", "open", "", ["a"], [], ["Java", "x", "y"] if dev else ["품질관리", "x", "y"])
        s.db.execute("update postings set relevant=1 where url=?", (f"u{i}",))
    def llm(sys_, user):
        n = user.count("\n") + 1
        return {"items": [{"idx": j, "family": "software_dev" if "Java" in line else "management_ops"}
                          for j, line in enumerate(user.split("\n"))]}
    assert judge_family(s, llm) == {"judged": 10, "failed": 0}
    all_m = {m["requirement"] for m in s.market_requirements("r")}
    ops_m = s.market_requirements("r", exclude_families=["software_dev"])
    assert "Java" in all_m and all(m["requirement"] != "Java" for m in ops_m)
    assert ops_m[0]["sample_size"] == 5 and ops_m[0]["reliable"] is False   # 표본 감소를 정직하게 반영
    assert judge_family(s, lambda a, b: None) == {"judged": 0, "failed": 0}  # 이미 분류됨 -> 대상 없음

def test_exclude_families_for_profile():
    ops = JobSeekerProfile(desired_role="x", skills=["품질관리"], resume_text="24년 품질관리, 최근 파이썬 기초 수강")
    dev = JobSeekerProfile(desired_role="x", skills=[], resume_text="10년 백엔드 개발 경험")
    assert ProfileAnalyzer.exclude_families_for(ops) == ["software_dev"]
    assert ProfileAnalyzer.exclude_families_for(dev) == []

def test_each_question_targets_one_claim_and_group_lookup():
    claims = [{"claim": "A 주장"}, {"claim": "B 주장"}]
    calls = []
    def llm(sys_, user):
        if "results" in sys_:
            return {"results": []}
        calls.append(user)
        return {"questions": [{"question": f"Q:{user}", "intent": "i", "eval_criteria": "e"}]}
    r = HRFactChecker(fetch=lambda u: "본문 " * 40, llm=llm).verify_portfolio(claims, ["https://github.com/a/b"])
    qs = r["interview_questions"]
    assert len(qs) == 2 and all(q["claim_ref"] for q in qs)          # 주장 수보다 많은 질문/빈 대상 없음
    assert {q["claim_ref"] for q in qs} == {"A 주장", "B 주장"}
    s = PostingStore(":memory:")
    s.put("u", "스마트팩토리 데이터 관리자", "t", "c", "open", "", ["a"], [], ["x", "y", "z"])
    s.db.execute("update postings set relevant=1 where url=?", ("u",))
    # 정확히 같은 이름이지만 정제 공고가 없는 그룹은 후보에서 제외되어야 한다
    s.put("e", "스마트팩토리 데이터 품질관리자", "t2", "c", "open", "", ["a"], [], ["x", "y", "z"])
    assert s.resolve_group("스마트팩토리 데이터 품질관리자") == "스마트팩토리 데이터 관리자"
    assert s.resolve_group("ESG 컨설턴트") is None

def test_course_only_official_domains_and_no_free_claim():
    from core.liner_client import LinerClient
    c = LinerClient(api_key="")
    res = [{"title": "국민내일배움카드 훈련과정", "description": "스마트팩토리 데이터 분석 과정 설명", "url": "https://m.work24.go.kr/x?id=1", "hostname": "m.work24.go.kr"},
           {"title": "블로그 글", "description": "d", "url": "https://m.blog.naver.com/a/1", "hostname": "m.blog.naver.com"}]
    out = c._parse_liner_course_results(res, "x")
    assert len(out) == 1 and "work24" in out[0]["url"] and "블로그" not in out[0]["title"]
    assert "100%" not in out[0]["support_type"] and "전액" not in out[0]["support_type"]
    assert c._parse_liner_course_results([res[1]], "x") == []        # 비공식 도메인만 있으면 빈 결과
    assert all("100%" not in m["support_type"] for m in c._get_mock_courses("x", []))

def test_menu_text_is_not_course_title_and_no_free_claims_in_ui():
    from core.liner_client import LinerClient
    c = LinerClient(api_key="")
    res = [{"title": "국민내일배움카드 훈련과정", "description": "훈련과정 정보 서브메뉴 열기 · 훈련유형",
            "url": "https://m.work24.go.kr/x", "hostname": "m.work24.go.kr"}]
    out = c._parse_liner_course_results(res, "스마트팩토리")
    assert "서브메뉴" not in out[0]["title"] and "스마트팩토리" in out[0]["title"]
    for f in ("app.py", "core/roadmap.py"):
        src = open(os.path.join(os.path.dirname(os.path.abspath(__file__)), f), encoding="utf8").read()
        assert "100%" not in src and "무료" not in src, f

def test_liner_router_llm_and_fallback():
    import requests
    from core.llm import LINER_CHAT_URL, call_llm, llm_json

    class _Resp:
        def __init__(self, code, data):
            self.status_code = code
            self._data = data
        def json(self):
            return self._data

    old_key = os.environ.get("LINER_API_KEY")
    os.environ["LINER_API_KEY"] = "test_key_only"
    try:
        calls = []
        def ok_post(url, headers=None, json=None, timeout=None):
            calls.append((url, headers, json))
            return _Resp(200, {"choices": [{"message": {"content": "pong"}}]})

        assert call_llm("ping", post=ok_post) == "pong"
        assert calls[0][0] == LINER_CHAT_URL
        assert calls[0][1]["Authorization"] == "Bearer test_key_only"
        assert "response_format" not in calls[0][2]

        def fenced_post(url, headers=None, json=None, timeout=None):
            return _Resp(200, {"choices": [{"message": {"content": "설명:\n```json\n{\"ok\": true}\n```"}}]})

        assert llm_json("sys", "user", post=fenced_post) == {"ok": True}

        models_tried = []
        def fallback_post(url, headers=None, json=None, timeout=None):
            models_tried.append(json["model"])
            if len(models_tried) == 1:
                return _Resp(500, {"error": "server"})
            return _Resp(200, {"choices": [{"message": {"content": "{\"ok\": \"fallback\"}"}}]})

        assert llm_json("sys", "user", post=fallback_post) == {"ok": "fallback"}
        assert models_tried == ["liner-gpt-router", "liner-claude-router"]

        timeout_calls = []
        def timeout_post(url, headers=None, json=None, timeout=None):
            timeout_calls.append(1)
            raise requests.Timeout("timed out")

        assert call_llm("ping", post=timeout_post) is None
        assert len(timeout_calls) == 1
    finally:
        if old_key is None:
            os.environ.pop("LINER_API_KEY", None)
        else:
            os.environ["LINER_API_KEY"] = old_key


def test_github_verifier_plagiarism_and_real_contributor():
    from core.github_verifier import GitHubVerifier

    class _Resp:
        def __init__(self, code, data):
            self.status_code = code
            self._data = data
        def json(self):
            return self._data

    def stub_get(url, headers=None, params=None, timeout=None):
        if url.endswith("/repos/torvalds/linux"):
            return _Resp(200, {"owner": {"login": "torvalds"}, "fork": False})
        if url.endswith("/repos/torvalds/linux/commits"):
            return _Resp(200, [])
        if url.endswith("/repos/senior-dev/smart-factory"):
            return _Resp(200, {"owner": {"login": "senior-dev"}, "fork": False})
        if url.endswith("/repos/senior-dev/smart-factory/commits"):
            return _Resp(200, [
                {"sha": "sha1", "commit": {"author": {"date": "2026-10-15T09:00:00Z"}}},
                {"sha": "sha2", "commit": {"author": {"date": "2026-10-10T09:00:00Z"}}},
            ])
        if url.endswith("/repos/senior-dev/smart-factory/languages"):
            return _Resp(200, {"Python": 800, "PLpgSQL": 200})
        if url.endswith("/repos/senior-dev/smart-factory/commits/sha1"):
            return _Resp(200, {"files": [{"filename": "app/main.py"}, {"filename": "db/query.sql"}]})
        if url.endswith("/repos/senior-dev/smart-factory/commits/sha2"):
            return _Resp(200, {"files": [{"filename": "core/worker.py"}]})
        return _Resp(404, {})

    gv = GitHubVerifier(http_get=stub_get)
    r_fake = gv.verify_repo("https://github.com/torvalds/linux", "fake-user")
    assert r_fake["status"] == "타인 기여 프로젝트 / 본인 커밋 내역 미확인"
    assert r_fake["commit_count"] == 0 and r_fake["pressure_question"] is not None

    fc = HRFactChecker(fetch=fake_fetch, llm=lambda s, u: None, github_verifier=gv)
    port = fc.verify_portfolio(CLAIMS[:1], ["https://github.com/torvalds/linux"], github_username="fake-user")
    assert port["audit_summary"]["github_unverified_count"] == 1
    assert any(q.get("source") == "github_verifier" for q in port["interview_questions"])

    r_real = gv.verify_repo("https://github.com/senior-dev/smart-factory", "senior-dev")
    assert r_real["status"] == "본인 기여 확인"
    assert r_real["commit_count"] == 2 and r_real["latest_commit_date"] == "2026-10-15"
    assert "Python" in r_real["languages"]
    assert any("Python" in e for e in r_real["extensions"]) and any("SQL" in e for e in r_real["extensions"])
    assert r_real["pressure_question"] is None


def test_liner_scholar_verification_gate():
    class FakeScholarLiner:
        is_live = True
        def search_scholar(self, query, num_results=5):
            if "Predictive Maintenance" in query:
                return [{
                    "title": "Predictive Maintenance and Intelligent Sensors in Smart Factory: Review",
                    "journal": "Sensors",
                    "year": "2021",
                    "date": "2021-02-01",
                    "citation_count": 460,
                    "authors": ["Martin Pech"],
                    "url": "https://www.mdpi.com/1424-8220/21/4/1470",
                }]
            if "Attention Is All You Need" in query:
                return [{
                    "title": "Attention Is All You Need Reproducibility Project",
                    "journal": "Open Science Framework",
                    "year": "2020",
                    "date": "2020-01-01",
                    "citation_count": 0,
                    "authors": ["Satchel Grant"],
                    "url": "https://osf.io/example",
                }]
            return []

    fc = HRFactChecker(FakeScholarLiner(), fetch=lambda u: "", llm=lambda s, u: None)
    items = [
        "Predictive Maintenance and Intelligent Sensors in Smart Factory: Review | Sensors | 2021",
        "Attention Is All You Need | NeurIPS | 2017",
        "Quantum Teleportation ERP | IEEE | 2025",
    ]
    res = fc.verify_scholar_claims(items)
    assert [x["status"] for x in res] == ["확인된 내용", "일부 확인", "확인 불가"], res
    assert res[0]["citation_count"] == 460

    port = fc.verify_portfolio([], [], scholar_claims=[items[0], items[2]])
    assert port["audit_summary"]["scholar_checked"] == 2 and port["audit_summary"]["scholar_verified_count"] == 1
    assert any(q.get("source") == "scholar_verifier" for q in port["interview_questions"])


def test_db_synonyms_and_deadline_expiry():
    import time
    from datetime import date
    from core.store import is_deadline_expired

    s = PostingStore(":memory:")
    assert s.resolve_group("B2B SaaS 어카운트 매니저") is None
    s.put("u_b2b", "B2B 영업 관리", "B2B 매니저", "wanted", "open", "상시채용", ["B2B 영업 4년"], [], ["B2B영업", "CRM", "세일즈"])
    s.db.execute("UPDATE postings SET relevant=1 WHERE url=?", ("u_b2b",))
    s.db.commit()
    assert s.resolve_group("B2B SaaS 어카운트 매니저") == "B2B 영업 관리"

    # 30일 전 수집 데이터도 90일 캐시 기본값으로 유지되어야 한다
    s.db.execute("UPDATE postings SET fetched_at=? WHERE url=?", (time.time() - 30 * 86400, "u_b2b"))
    s.db.commit()
    assert s.get("u_b2b") is not None

    ref = date(2026, 11, 14)
    assert is_deadline_expired("2026.11.13(금)", today=ref) is True
    assert is_deadline_expired("2026.12.01", today=ref) is False
    assert is_deadline_expired("상시채용", today=ref) is False


def test_analyzer_uses_curated_open_db_candidates():
    s = PostingStore(":memory:")
    s.put("https://wanted.co.kr/wd/1", "스마트팩토리 데이터 관리자", "오픈 스마트팩토리", "wanted", "open", "상시채용",
          ["품질관리 5년 이상", "스마트팩토리 운영"], [], ["스마트팩토리", "품질관리", "MES"])
    s.put("https://wanted.co.kr/wd/2", "스마트팩토리 데이터 관리자", "만료된 공고", "wanted", "open", "2020.01.01",
          ["품질관리"], [], ["스마트팩토리", "품질관리", "MES"])
    s.db.execute("UPDATE postings SET relevant=1")
    s.db.commit()

    def llm(sys_, user):
        return {"items": [{"req": "품질관리 5년 이상", "met": True, "reason": "24년"}, {"req": "스마트팩토리 운영", "met": False, "reason": "미보유"}]}

    a = ProfileAnalyzer(FakeLiner([]), fetch=lambda u: "", llm=llm, store=s)
    res = a.analyze_profile(JobSeekerProfile(desired_role="스마트팩토리 데이터 품질관리자", skills=["품질관리"], resume_text="24년 품질관리"))
    assert len(res) == 1 and res[0].job.source_url == "https://wanted.co.kr/wd/1"
    assert res[0].job.status == "open" and res[0].scored and res[0].match_score == 50


def test_translator_llm_grounding_and_no_duplicate_fallback():
    from core.translator import CareerTranslator

    resume = "24년간 중소 제조업체 부서장으로 현장 품질관리 및 공정 개선 총괄. 불량률 감소와 팀원 관리 수행."

    def stub_llm(sys_, user):
        return {"items": [
            {"original": "24년간 중소 제조업체 부서장으로 현장 품질관리 및 공정 개선 총괄", "modernized": "스마트팩토리 품질 거버넌스 총괄", "impact_rationale": "r1"},
            {"original": "10년간 삼성전자 반도체 자율제어 총괄", "modernized": "반도체 AI 총괄", "impact_rationale": "날조"},
        ]}

    t_llm = CareerTranslator(llm=stub_llm).translate(resume, "스마트팩토리 데이터 관리자")
    assert len(t_llm) == 1 and t_llm[0]["modernized"].startswith("•")
    assert "삼성전자" not in t_llm[0]["original"]

    t_fb = CareerTranslator(llm=None).translate(resume, "스마트팩토리 데이터 관리자")
    assert len(t_fb) >= 1
    origs = [x["original"] for x in t_fb]
    assert len(origs) == len(set(origs))


def test_scholar_author_matching_and_mismatch_gate():
    from core.hr_fact_checker import _author_matches

    assert _author_matches("홍성훈 / Sunghoon Hong", ["홍성훈", "권혁무"]) is True
    assert _author_matches("홍성훈 / Sunghoon Hong", ["S. Hong"]) is True
    assert _author_matches("홍성훈 / Sunghoon Hong", ["Hong, Sunghoon"]) is True
    assert _author_matches("홍성훈 / Sunghoon Hong", ["Martin Pech"]) is False

    class StubScholar:
        is_live = True
        def search_scholar(self, query, num_results=5):
            if "필수 요소" in query:
                return [{"title": "스마트팩토리 적용을 위한 필수 요소 연구", "journal": "한국품질경영학회", "year": "2021",
                         "citation_count": 3, "authors": ["홍성훈", "권혁무"], "url": "https://example.com/1"}]
            return [{"title": "Predictive Maintenance and Intelligent Sensors in Smart Factory: Review",
                     "journal": "Sensors", "year": "2021", "citation_count": 460,
                     "authors": ["Martin Pech", "Jaroslav Vrchota"], "url": "https://example.com/2"}]

    fc = HRFactChecker(StubScholar(), fetch=lambda u: "", llm=lambda s, u: None)
    items = [
        "스마트팩토리 적용을 위한 필수 요소 연구 | 한국품질경영학회 | 2021",
        "Predictive Maintenance and Intelligent Sensors in Smart Factory: Review | Sensors | 2021",
    ]
    res = fc.verify_portfolio([], [], scholar_claims=items, candidate_author="홍성훈 / Sunghoon Hong")
    assert [c["status"] for c in res["scholar_verifications"]] == ["확인된 내용", "저자 불일치"]
    assert res["audit_summary"]["scholar_author_mismatch_count"] == 1
    assert any("저자 불일치" in q["claim_ref"] for q in res["interview_questions"])


def test_compliance_docs_no_free_claims_or_strikethrough():
    base = os.path.dirname(os.path.abspath(__file__))
    files = [
        "app.py",
        "core/roadmap.py",
        "core/legal_sanitizer.py",
        "core/doc_io.py",
        "README.md",
        ".kiro/specs/careerpath-agent/requirements.md",
        "_reports/proposals/official_proposal.md",
        "docs/DEMO_VIDEO_SCRIPT.md",
    ]
    for rel in files:
        txt = open(os.path.join(base, rel), encoding="utf8").read()
        for bad in ("100% 무료", "전액 무료", "~~", "<strike>", "<s>", "<del>"):
            assert bad not in txt, f"{bad!r} found in {rel}"


def test_clean_company_and_domain_penalty():
    from core.store import clean_company_name, portal_label, role_domain_penalty

    assert clean_company_name("wanted.co.kr", "[인터엑스] 제조 산업 시니어 전문가 채용", "https://www.wanted.co.kr/wd/1") == "인터엑스"
    assert clean_company_name("m.jobkorea.co.kr", "아이제라 채용 - 스마트팩토리 PL", "https://m.jobkorea.co.kr/Recruit/GI_Read/2") == "아이제라"
    assert portal_label("https://www.wanted.co.kr/wd/1") == "원티드"
    assert portal_label("https://m.jobkorea.co.kr/Recruit/GI_Read/2") == "잡코리아"
    assert role_domain_penalty("스마트팩토리 데이터 품질관리자", "프레스 금형 품질관리", "[에이머슬리] 반도체 공정 엔지니어", ["반도체"]) == 1
    assert role_domain_penalty("스마트팩토리 데이터 품질관리자", "프레스 금형 품질관리", "[인터엑스] 제조 산업 시니어 전문가", ["제조", "품질"]) == 0

    s = PostingStore(":memory:")
    s.put("https://wanted.co.kr/wd/semi", "공정개선 엔지니어", "[A사] 반도체 식각 공정 엔지니어", "wanted.co.kr", "open", "상시채용",
          ["반도체 공정 5년", "웨이퍼 분석", "수율 개선"], [], ["반도체", "공정", "수율"])
    s.put("https://wanted.co.kr/wd/mfg", "스마트팩토리 데이터 관리자", "[B사] 제조 스마트팩토리 품질관리자", "wanted.co.kr", "open", "상시채용",
          ["제조 품질관리 5년", "MES 운영"], [], ["스마트팩토리", "품질관리", "MES"])
    s.db.execute("UPDATE postings SET relevant=1")
    s.db.commit()
    cands = s.open_candidates_for_role("스마트팩토리 데이터 품질관리자", resume_text="프레스 금형 품질관리")
    assert cands[0]["source_url"] if "source_url" in cands[0] else cands[0]["url"] == "https://wanted.co.kr/wd/mfg"


def test_translator_number_preservation_and_hallucination_gate():
    from core.translator import CareerTranslator

    resume = "24년간 중소 제조업체에서 프레스 품질관리 총괄. 불량률 1.2% 감축 및 ISO9001 인증 유지."

    def hallu_llm(sys_, user):
        return {"items": [
            {"original": "24년간 중소 제조업체에서 프레스 품질관리 총괄", "modernized": "24년간 축적한 프레스 제조 도메인 기반 데이터 품질관리 프로세스 구축", "impact_rationale": "ok"},
            {"original": "불량률 1.2% 감축 및 ISO9001 인증 유지", "modernized": "불량률 50% 감축 및 매출 300억 달성 주도", "impact_rationale": "허위 수치"},
        ]}

    out = CareerTranslator(llm=hallu_llm).translate(resume, "스마트팩토리 데이터 관리자", exp_years=24)
    assert len(out) == 1
    assert "24년" in out[0]["modernized"]
    assert "300억" not in out[0]["modernized"]

    fb = CareerTranslator(llm=None).translate(resume, "스마트팩토리 데이터 관리자")
    assert any("24년" in x["modernized"] or "1.2%" in x["modernized"] for x in fb)


def test_doc_io_upload_and_report_exports():
    import io, zipfile
    from core.doc_io import (
        build_mode_a_report_md,
        build_mode_b_report_md,
        build_mode_b_scorecard_csv,
        extract_portfolio_inputs_from_text,
        extract_text_from_upload,
    )

    txt_bytes = "연락처 010-1234-5678 / test@example.com\n20년 제조 품질관리 경력".encode("utf-8")
    clean_t, stats_t, _ = extract_text_from_upload("resume.txt", txt_bytes)
    assert stats_t["phone_masked"] == 1 and stats_t["email_masked"] == 1
    assert "010-1234-5678" not in clean_t

    buf = io.BytesIO()
    with zipfile.ZipFile(buf, "w") as zf:
        zf.writestr(
            "word/document.xml",
            '<w:document xmlns:w="http://schemas.openxmlformats.org/wordprocessingml/2006/main">'
            '<w:body><w:p><w:r><w:t>https://github.com/torvalds/linux</w:t></w:r></w:p>'
            '<w:p><w:r><w:t>Python 기반 설비 API 서버 10년 설계</w:t></w:r></w:p>'
            '<w:p><w:r><w:t>스마트팩토리 연구 | 한국품질경영학회 | 2021</w:t></w:r></w:p></w:body></w:document>',
        )
    doc_txt, _, _ = extract_text_from_upload("portfolio.docx", buf.getvalue())
    parsed = extract_portfolio_inputs_from_text(doc_txt)
    assert parsed["urls"] == ["https://github.com/torvalds/linux"]
    assert any("Python" in c for c in parsed["claims"])
    assert len(parsed["scholar"]) == 1

    prof = JobSeekerProfile(age=52, total_experience_years=24, desired_role="스마트팩토리", skills=["품질관리"])
    md_a = build_mode_a_report_md(prof, [], [{"original": "o", "modernized": "• m", "impact_rationale": "r"}], {"phases": [], "sprint": []})
    assert "100%" not in md_a and "무료" not in md_a and "~~" not in md_a

    port_res = {
        "evidence_cards": [{"claim": "API 설계", "status": "확인 불가", "evidence_quote": "", "note": "n"}],
        "github_contributions": [],
        "scholar_verifications": [],
        "interview_questions": [{"idx": 1, "claim_ref": "API 설계", "question": "Q?", "intent": "i", "eval_criteria": "c"}],
        "audit_summary": {"total_claims": 1, "verified_count": 0, "partially_verified_count": 0, "unverified_count": 1},
    }
    md_b = build_mode_b_report_md("홍성훈", "sunghoon", port_res)
    csv_b = build_mode_b_scorecard_csv(port_res)
    assert "Q?" in md_b
    assert csv_b.startswith(b"\xef\xbb\xbf") and "검증영역" in csv_b.decode("utf-8-sig")


def test_github_profile_scan_and_autoselect():
    from core.github_verifier import GitHubVerifier

    class _R:
        def __init__(self, code, data):
            self.status_code = code
            self._data = data
        def json(self):
            return self._data

    def stub_get(url, headers=None, params=None, timeout=None):
        if url.endswith("/users/dev-kim"):
            return _R(200, {"login": "dev-kim", "public_repos": 5, "created_at": "2019-03-01T00:00:00Z"})
        if url.endswith("/users/dev-kim/repos"):
            return _R(200, [
                {"full_name": "dev-kim/forked-lib", "fork": True},
                {"full_name": "dev-kim/factory-api", "fork": False},
            ])
        if url.endswith("/repos/dev-kim/factory-api"):
            return _R(200, {"owner": {"login": "dev-kim"}, "fork": False})
        if url.endswith("/repos/dev-kim/factory-api/commits"):
            return _R(200, [{"sha": "abc1", "commit": {"author": {"date": "2026-10-01T00:00:00Z"}}}])
        if url.endswith("/repos/dev-kim/factory-api/languages"):
            return _R(200, {"Python": 100})
        if url.endswith("/repos/dev-kim/factory-api/commits/abc1"):
            return _R(200, {"files": [{"filename": "server.py"}]})
        return _R(404, {})

    gv = GitHubVerifier(http_get=stub_get)
    prof = gv.verify_user_profile("dev-kim")
    assert prof["exists"] is True and prof["owned_repos"] == 1 and prof["fork_repos"] == 1
    repos = gv.verify_urls(["https://github.com/dev-kim"])
    assert len(repos) == 1 and repos[0]["repo"] == "dev-kim/factory-api" and repos[0]["commit_count"] == 1


def test_low_detail_guard_and_weighted_scoring():
    from core.analyzer import ProfileAnalyzer, JobSeekerProfile
    from core.store import PostingStore

    s = PostingStore(":memory:")
    role = "스마트팩토리 데이터 관리자"
    tags = ["스마트팩토리", "데이터", "품질"]
    s.put("u_low", role, "저상세 공고", "c1", "open", "", ["성실하고 책임감 있는 분"], [], tags)
    s.put("u_rich", role, "상세 공고", "c2", "open", "", ["센서 데이터 분석 3년", "Python"], ["도메인 이해"], tags)
    s.db.execute("UPDATE postings SET relevant=1")
    s.db.commit()

    stub_llm = lambda sys, u: {
        "items": [
            {"req": "센서 데이터 분석 3년", "met": False, "reason": ""},
            {"req": "Python", "met": True, "reason": ""},
            {"req": "도메인 이해", "met": True, "reason": ""},
        ],
        "strategy": "제조 도메인과 Python 역량을 부각하세요.",
    }
    a = ProfileAnalyzer(None, llm=stub_llm, store=s)
    res = a.analyze_profile(JobSeekerProfile(desired_role=role, resume_text="Python 개발 3년, 제조업 근무"))
    assert len(res) == 2
    r_rich = next(r for r in res if r.job.source_url == "u_rich")
    r_low = next(r for r in res if r.job.source_url == "u_low")

    assert r_rich.scored is True and r_rich.low_detail is False
    assert r_rich.match_score == 59
    assert r_rich.required_met_ratio == "필수 1/2 · 우대 1/1"
    assert "제조 도메인" in r_rich.tailored_advice

    assert r_low.scored is False and r_low.low_detail is True
    assert r_low.match_score == 0
    assert "상세 요건" in r_low.tailored_advice or "상세 직무 요강" in r_low.tailored_advice


def test_work24_cohort_advance_and_closed_course_roadmap():
    from core.liner_client import LinerClient
    from core.roadmap import RoadmapGenerator
    from core.analyzer import JobSeekerProfile, MatchResult, JobPosting

    class _Resp:
        def __init__(self, text):
            self.status_code = 200
            self.text = text

    def stub_get(url, headers=None, timeout=None):
        if "tracseTme=1" in url:
            return _Resp('<div class="tit_area"><strong class="title">스마트팩토리 실무</strong> 모집마감 수강신청인원 20명 / 모집인원 20명</div>')
        elif "tracseTme=2" in url:
            return _Resp('<div class="tit_area"><strong class="title">스마트팩토리 실무</strong> 모집중 수강신청인원 5명 / 모집인원 30명</div>'
                         '<div><em class="tit">NCS직무분류</em><span>20010101 기계가공</span></div>')
        return None

    lc = LinerClient()
    lc._http_get = stub_get
    r1 = lc._fetch_work24_cohort("https://m.work24.go.kr/wk/a/b/1200/retriveDtlTrprInfo.do?trprId=A1&tracseTme=1", {"title": "t"})
    assert r1 is not None and r1["recruit_status"] == "모집마감"
    assert r1.get("quota") == "신청 20명 / 정원 20명"

    r2 = lc._fetch_work24_cohort("https://m.work24.go.kr/wk/a/b/1200/retriveDtlTrprInfo.do?trprId=A1&tracseTme=2", {"title": "t"})
    assert r2 is not None and r2["recruit_status"] == "모집중"
    assert r2.get("quota") == "신청 5명 / 정원 30명"
    assert r2.get("ncs") == "20010101 기계가공"

    lc.search_government_courses = lambda r, m=None: [{"title": "스마트과정", "institution": "기관", "recruit_status": "모집마감", "ncs": "20010101"}]
    rg = RoadmapGenerator(lc, llm=lambda s, u: None)
    p = JobSeekerProfile(age=50, total_experience_years=20, desired_role="스마트팩토리", skills=["품질"])
    rm = rg.generate_roadmap(p, MatchResult(scored=True, job=JobPosting(id="j1", company="c", title="t", status="open", deadline="", requirements=["a"], preferred=[], tags=[], details={})), [])
    assert any("차수" in a or "동일 NCS" in a or "일정" in a for a in rm["phases"][0]["actions"])
    assert "Day 2" in rm["sprint"][1]["day"]


def test_github_multilayer_context_and_trivial_doc_commit():
    from core.github_verifier import GitHubVerifier
    from core.fetcher import _fetch_github_repo_context

    class _Resp:
        def __init__(self, code, data=None, text=""):
            self.status_code = code
            self._data = data or {}
            self.text = text
        def json(self):
            return self._data

    def stub_get(url, headers=None, params=None, timeout=None):
        if url.endswith("/README.md") or url.endswith("/readme.md"):
            return _Resp(200, text="# Test Service\nWe use FastAPI and Redis.")
        if url.endswith("/contents"):
            return _Resp(200, data=[
                {"name": "README.md", "path": "README.md", "type": "file"},
                {"name": "requirements.txt", "path": "requirements.txt", "type": "file"},
            ])
        if url.endswith("/requirements.txt"):
            return _Resp(200, text="fastapi>=0.100\nredis>=5.0\npydantic>=2.0")
        if url.endswith("/users/doc-author"):
            return _Resp(200, data={"login": "doc-author", "public_repos": 1, "created_at": "2020-01-01T00:00:00Z"})
        if url.endswith("/users/doc-author/repos"):
            return _Resp(200, data=[{"full_name": "org/doc-repo", "fork": False}])
        if url.endswith("/repos/org/doc-repo"):
            return _Resp(200, data={"owner": {"login": "org"}, "fork": False})
        if url.endswith("/repos/org/doc-repo/commits"):
            return _Resp(200, data=[
                {"sha": "c1", "commit": {"author": {"name": "doc-author", "email": "other@email.com", "date": "2026-10-01T00:00:00Z"}, "message": "docs: update README.md"}},
            ])
        if url.endswith("/repos/org/doc-repo/commits/c1"):
            return _Resp(200, data={"files": [{"filename": "README.md", "additions": 3, "deletions": 1}]})
        return _Resp(404, {})

    import core.fetcher
    orig_get = core.fetcher.requests.get
    try:
        core.fetcher.requests.get = stub_get
        ctx = _fetch_github_repo_context("org", "doc-repo")
        assert "FastAPI" in ctx
        assert "requirements.txt" in ctx
        assert "fastapi" in ctx
    finally:
        core.fetcher.requests.get = orig_get

    gv = GitHubVerifier(http_get=stub_get)
    res = gv.verify_urls(["https://github.com/org/doc-repo"], username="doc-author")
    assert len(res) == 1
    r0 = res[0]
    assert "경미한 문서 기여" in r0["status"]
    assert r0.get("code_changes") == {"additions": 3, "deletions": 1}
    assert r0.get("recent_messages") == ["docs: update README.md"]


def test_patent_verification_and_contextual_questions():
    from core.hr_fact_checker import HRFactChecker

    claims = [{"category": "기술", "claim": "반도체 패키징 결함 실시간 검사 장치 및 방법", "keyword": "반도체"}]
    scholar_lines = ["반도체 패키징 결함 실시간 검사 장치 및 방법 | 특허청 10-2023-0012345 | 2023"]

    def stub_search(q, max_results=3):
        return [{"title": "반도체 패키징 결함 실시간 검사 장치 및 방법", "snippet": "등록특허 10-2023-0012345 발명자: 김철수, 이동현 출원일: 2023", "url": "https://patents.google.com/patent/KR1020230012345B1/ko"}]

    def stub_llm(sys_prompt, user_prompt):
        if "results" in sys_prompt:
            return {"results": [{"idx": 0, "status": "verified", "quote": "반도체 패키징 결함 실시간 검사 장치"}]}
        if "interview" in sys_prompt:
            assert "GitHub 저장소 기여 요약" in user_prompt or "문헌" in user_prompt or "반도체" in user_prompt
            return {"questions": [{"idx": 1, "question": "특허 등록된 반도체 결함 검사 알고리즘의 감지 원리는 무엇인가요?", "intent": "원천 기술 이해도 검증", "eval_criteria": "특허 청구항 1항 설명 가능 여부"}]}
        return None

    class _FakeLiner:
        def search_web(self, q, max_results=3):
            return stub_search(q, max_results=max_results)

    checker = HRFactChecker(liner_client=_FakeLiner(), fetch=lambda u: "반도체 패키징 결함 실시간 검사 장치 본문", llm=stub_llm)
    res = checker.verify_portfolio(claims, ["https://github.com/org/packaging-vision"], candidate_author="이동현", scholar_claims=scholar_lines)
    assert len(res["scholar_verifications"]) == 1
    sc = res["scholar_verifications"][0]
    assert sc["kind"] == "patent"
    assert sc["status"] == "확인된 내용"
    assert "이동현" in str(sc.get("authors"))
    assert len(res["interview_questions"]) >= 1


def test_resume_structured_profile_extraction():
    from core.doc_io import extract_resume_profile_from_text

    text = (
        "성명: 이현수 / 만 52세\n"
        "총 경력: 24년 (24년간 제조 현장에서 품질관리 총괄)\n"
        "보유 자격증: 품질경영기사, ISO9001 심사원, 산업안전기사\n"
        "보유 역량: Python 기초, PLC 제어, 공정개선, 엑셀 데이터 가공"
    )
    p = extract_resume_profile_from_text(text)
    assert p["name"] == "이현수"
    assert p["age"] == 52
    assert p["experience_years"] == 24
    assert set(p["certifications"]) >= {"품질경영기사", "ISO9001", "산업안전기사"}
    assert set(p["skills"]) >= {"품질관리", "공정개선", "Python", "엑셀", "PLC"}

    # 소유격 조사 '의' 분리 및 끝음절 '의' 성명 보존 회귀 검증
    assert extract_resume_profile_from_text("성명: 김정의\n경력 10년")["name"] == "김정의"
    assert extract_resume_profile_from_text("김정의 이력서\n경력 10년")["name"] == "김정의"
    assert extract_resume_profile_from_text("김정의의 이력서\n경력 10년")["name"] == "김정의"
    assert extract_resume_profile_from_text("김준의 이력서\n총 경력: 10년")["name"] == "김준의"
    assert extract_resume_profile_from_text("김준의경력기술서\n총 경력: 10년")["name"] == "김준의"
    assert extract_resume_profile_from_text("김준의의 이력서\n총 경력: 10년")["name"] == "김준의"
    assert extract_resume_profile_from_text("김영호의 이력서\n총 경력: 20년")["name"] == "김영호"
    assert extract_resume_profile_from_text("박민수 이력서\n총 경력: 15년")["name"] == "박민수"
    assert extract_resume_profile_from_text("이정의의 경력기술서\n총 경력: 12년")["name"] == "이정의"
    assert extract_resume_profile_from_text("공유의 이력서\n총 경력: 8년\n공유는 백엔드 개발자입니다.")["name"] == "공유"
    assert extract_resume_profile_from_text("경력 요약\n공유의 이력서\n총 경력: 8년\n공유는 백엔드 개발자입니다.")["name"] == "공유"
    assert extract_resume_profile_from_text("허준의이력서\n총 경력: 15년\n허준 과장은 공정 전문가입니다.")["name"] == "허준"


def test_report_printer_print_css_and_name():
    from core.analyzer import JobSeekerProfile
    from core.report_printer import generate_modern_resume_html, generate_interview_sheet_html

    prof = JobSeekerProfile(
        name="테스트지원자",
        age=48,
        total_experience_years=18,
        desired_role="스마트팩토리 데이터 관리자",
    )
    res_html = generate_modern_resume_html(prof, [], ["현대화 문장 1"], {})
    assert "테스트지원자" in res_html
    assert "page-break-inside: avoid" in res_html
    assert "@media print" in res_html

    sheet_html = generate_interview_sheet_html(
        {"audit_summary": {}, "executive_summary": ["요약"], "interview_questions": [{"idx": 1, "claim_ref": "c", "question": "q", "eval_criteria": "e"}]},
        cand_name="테스트지원자"
    )
    assert "테스트지원자" in sheet_html
    assert "display: table-header-group" in sheet_html
    assert "page-break-inside: avoid" in sheet_html


def test_product_upgrades_region_exec_summary_and_code_meta():
    import sqlite3
    from core.store import PostingStore
    from core.hr_fact_checker import HRFactChecker
    from core.fetcher import _extract_article_html
    from core.liner_client import LinerClient

    # 1. 지역 필터링 정합성 테스트
    store = PostingStore(":memory:")
    store.put(
        "https://wanted.co.kr/wd/101", "스마트팩토리 데이터 관리자", "서울 판교 공정 데이터 관리자",
        "스마트솔루션", "open", "상시", ["파이썬", "SQL", "MES"], ["통계"], ["파이썬", "MES", "데이터"],
        {"work_location": "경기 성남시 분당구 판교역로 100", "duties": ["MES 분석"]}
    )
    store.put(
        "https://wanted.co.kr/wd/102", "스마트팩토리 데이터 관리자", "포항 제철 공정 개선 엔지니어",
        "포항엔지니어링", "open", "상시", ["파이썬", "SQL", "MES"], ["통계"], ["파이썬", "MES", "데이터"],
        {"work_location": "경북 포항시 남구 동촌동 1", "duties": ["공정 개선"]}
    )
    store.db.execute("UPDATE postings SET relevant=1")
    store.db.commit()

    seoul_cands = store.open_candidates_for_role("스마트팩토리 데이터 관리자", preferred_region="서울·수도권")
    assert len(seoul_cands) >= 2
    assert "판교" in seoul_cands[0]["title"]

    prov_cands = store.open_candidates_for_role("스마트팩토리 데이터 관리자", preferred_region="지방 (영남·호남·충청·기타)")
    assert len(prov_cands) >= 2
    assert "포항" in prov_cands[0]["title"]

    # 2. Executive Briefing 및 블로그 코드 메타 검증
    sample_blog_html = """
    <html>
        <head>
            <meta name="article:published_time" content="2026-03-15T09:00:00Z" />
        </head>
        <body>
            <article>
                <h1>FastAPI 비동기 아키텍처 실습</h1>
                <p>본 포스팅에서는 초당 3000건의 트래픽을 처리하는 비동기 게이트웨이를 구현합니다.</p>
                <pre><code>def process_event(event): return True</code></pre>
            </article>
        </body>
    </html>
    """
    body, meta_info = _extract_article_html(sample_blog_html)
    assert meta_info["has_code"] is True
    assert meta_info["published_date"] == "2026-03-15"

    def stub_llm(s, u):
        if "results" in s:
            return {"results": [{"idx": 0, "status": "verified", "quote": "초당 3000건의 트래픽을 처리"}]}
        return {"questions": [{"idx": 1, "question": "비동기 게이트웨이 병목 해결 방법은?", "intent": "구조 검증", "eval_criteria": "이벤트루프"}]}

    checker = HRFactChecker(
        fetch=lambda u: (body, meta_info),
        llm=stub_llm
    )
    claims = [{"claim": "초당 3000건 트래픽 처리 게이트웨이", "category": "아키텍처"}]
    res = checker.verify_portfolio(claims, ["https://velog.io/@tech/fastapi-gateway"])
    assert len(res["executive_summary"]) >= 2
    assert "주요 이력 주장 1건 중 1건 원문 일치 대조 완료" in res["executive_summary"][0]
    assert res["evidence_cards"][0]["has_code"] is True
    assert res["evidence_cards"][0]["published_date"] == "2026-03-15"

    # 3. LINER API 통계 객체 검증
    client = LinerClient(api_key="mock_key")
    assert "search_calls" in client.stats
    assert "scholar_calls" in client.stats


def test_transfer_engine_and_code_quality_ast():
    from core.transfer_engine import SkillTransferEngine
    from core.code_analyzer import CodeQualityAnalyzer

    # 1. 역량 전이 매트릭스 엔진 검증
    res = SkillTransferEngine.calculate_transfer_profile(
        held_skills=["품질관리", "ISO9001", "불량률감소", "MES", "PLC"],
        experience_years=24,
        target_role="스마트팩토리 데이터 관리자",
        resume_text="24년간 제조 현장에서 품질관리 및 공정 개선 총괄."
    )
    assert res["transfer_readiness"] >= 75
    assert len(res["radar_scores"]) == 5
    assert len(res["transferred_capabilities"]) >= 4
    caps_names = [c["capability"] for c in res["transferred_capabilities"]]
    assert any("데이터" in c or "품질" in c or "모니터링" in c for c in caps_names)

    # 2. AST 코드 품질 정적 분석 검증
    py_sample = '''
"""비동기 이벤트 게이트웨이 모듈"""
import asyncio
from typing import Dict, Any

class EventProcessor:
    """이벤트 처리 코어 엔진"""
    def __init__(self, buffer_size: int = 1000):
        self.buffer_size = buffer_size

    async def dispatch(self, event: Dict[str, Any]) -> bool:
        if not event:
            return False
        for k, v in event.items():
            if k == "priority":
                return True
        return False
'''
    cq = CodeQualityAnalyzer.analyze_python_source(py_sample)
    assert cq["parsed"] is True
    assert cq["classes_count"] == 1
    assert cq["functions_count"] == 2
    assert cq["has_async"] is True
    assert cq["has_type_hints"] is True
    assert cq["has_docstrings"] is True
    assert cq["complexity_score"] >= 70
    assert "A+" in cq["quality_grade"] or "B+" in cq["quality_grade"]


def test_interview_drill_engine():
    from core.interview_drill import InterviewDrillEngine

    # 1. 짧은 무성의 답변
    short_res = InterviewDrillEngine.analyze_answer("Q1", "열심히 했습니다.")
    assert short_res["score"] <= 30
    assert "답변 분량 부족" in short_res["verdict"]
    assert len(short_res["follow_up_questions"]) == 2

    # 2. 결정론적 폴백 풍부한 정량 답변
    rich_ans = "Python과 Flask로 초당 5,000건의 설비 이벤트를 처리하는 파이프라인을 설계 및 구현하여 장애율을 35% 감소시켰습니다."
    drill_res = InterviewDrillEngine.analyze_answer(
        question="Q1",
        answer=rich_ans,
        eval_criteria="정량 성과 및 기술 스택",
        llm_fn=lambda sys, usr: None,  # 폴백 강제 유도
    )
    assert drill_res["score"] >= 80
    assert len(drill_res["follow_up_questions"]) >= 1
    assert "우수" in drill_res["verdict"]
    assert "5,000건" in drill_res["critique"]
    assert drill_res["source"] == "rule_based"
    assert "입증" not in drill_res["verdict"]


def test_interview_drill_uses_parsed_llm_response():
    from unittest.mock import patch
    from core.interview_drill import InterviewDrillEngine

    result = {
        "score": 73,
        "verdict": "양호",
        "critique": "AI 평가 결과",
        "missing_elements": ["검증 자료"],
        "follow_up_questions": ["측정 기준은?", "담당 범위는?"],
    }
    with patch("core.interview_drill.llm_json", return_value=result) as call:
        actual = InterviewDrillEngine.analyze_answer("담당 업무는?", "Python으로 이벤트 처리 시스템을 구현했습니다.")
    assert actual["score"] == 73
    assert actual["critique"] == "AI 평가 결과"
    assert actual["source"] == "llm"
    assert "담당 업무는?" in call.call_args.args[1]

    for invalid in (None, {"score": "invalid", "follow_up_questions": []}):
        fallback = InterviewDrillEngine.analyze_answer(
            "담당 업무는?", "Python으로 1,234,567건을 처리하고 지연을 12.5% 개선했습니다.",
            llm_fn=lambda system, user: invalid,
        )
        assert fallback["source"] == "rule_based"
        assert "1,234,567건" in fallback["critique"]
        assert "12.5%" in fallback["critique"]


if __name__ == "__main__":
    for name, fn in list(globals().items()):
        if name.startswith("test_"):
            fn(); print("PASS", name)
    print("ALL PASS (stubbed unit tests; live behavior is NOT covered here)")

