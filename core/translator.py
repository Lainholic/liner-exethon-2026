import re
from typing import Any, Callable, Dict, List, Optional
from .legal_sanitizer import LegalSanitizer
from .liner_client import LinerClient
from .llm import llm_json

TRANS_SYS = (
    "너는 40+ 시니어 경력 전환 전문 이력서 에디터다. 지원자 이력서 원문에서 서로 다른 핵심 경력 문장·성과를 "
    "2~4개 발췌해 실제 이력서에 바로 붙여 넣을 수 있는 완성형 경력 기술 문장(35~95자, '~총괄·개선', '~구축·운영' 종결)으로 재구성한다. "
    "원문에 있는 연차·비율·금액·규격(예: 24년, 1.2%, 80억, ISO9001)을 modernized 문장 안에 반드시 그대로 보존하라. "
    "이력서 원문에 없는 수치·자격증·회사명을 절대 지어내지 마라. original은 원문 문장을 그대로 발췌한다. "
    'JSON: {"items":[{"original":"원문 발췌","modernized":"정량 성과와 JD 역량을 결합한 1줄 이력서 문장(35~95자)","impact_rationale":"서류 통과에 유리한 이유"}]}'
)


def _norm_tokens(text: str) -> set[str]:
    return set(re.findall(r"[a-z0-9가-힣]{2,}", (text or "").lower()))


def _extract_numbers(text: str) -> set[str]:
    return set(re.findall(r"\d+(?:\.\d+)?", text or ""))


def _is_grounded(original: str, resume_text: str) -> bool:
    orig_toks = _norm_tokens(original)
    if not orig_toks:
        return False
    res_toks = _norm_tokens(resume_text)
    if orig_toks & res_toks and (len(orig_toks & res_toks) / len(orig_toks)) >= 0.5:
        return True
    # 한국어 띄어쓰기 차이 보정
    res_compact = re.sub(r"\s+", "", (resume_text or "").lower())
    hits = sum(1 for t in orig_toks if t in res_compact)
    return (hits / len(orig_toks)) >= 0.5


def _is_valid_translation(
    original: str, modernized: str, resume_text: str, exp_years: Optional[int] = None
) -> bool:
    if not _is_grounded(original, resume_text):
        return False
    clean_mod = modernized.lstrip("• ").strip()
    if len(clean_mod) < 12:
        return False
    allowed_nums = _extract_numbers(resume_text) | {"2026"}
    if exp_years:
        allowed_nums.add(str(exp_years))
    mod_nums = _extract_numbers(clean_mod)
    if not mod_nums.issubset(allowed_nums):
        return False
    return True


class CareerTranslator:
    """
    시니어의 과거 도메인 실무 경험을 2026년 채용 공고(JD) 표준 직무 역량 키워드로 번역하는 엔진.
    Liner Router LLM을 우선 호출해 원문 근거 검증 후 변환하며, 실패 시 12종 도메인 사전으로 폴백한다.
    """
    def __init__(
        self,
        liner_client: Optional[LinerClient] = None,
        llm: Optional[Callable[[str, str], Any]] = llm_json,
    ):
        self.liner = liner_client or LinerClient()
        self.llm = llm

        # 도메인 구체 패턴을 먼저 두고 범용 관리 패턴을 후순위에 배치
        self.translation_dictionary = [
            {
                "pattern": r"(현장\s*품질\s*관리|품질\s*관리\s*총괄|품질\s*보증|ISO\s*9001|불량률\s*(?:감소|감축))",
                "modern": "스마트팩토리 데이터 파이프라인 품질 최적화 및 공정 이상 탐지 SOP 수립",
                "impact": "과거의 수기 품질 관리를 현대적 데이터 기반 불량 감지 및 품질 거버넌스로 전환",
            },
            {
                "pattern": r"(공정\s*개선|생산\s*공정|수율\s*개선|프레스|금형|작업\s*관리)",
                "modern": "린(Lean) 방법론 기반 공정 병목 제거 및 생산 수율 데이터 모니터링",
                "impact": "단순 현장 작업 감독을 체계적인 프로세스 엔지니어링 및 KPI 지표 관리로 재정의",
            },
            {
                "pattern": r"(설비\s*(?:관리|보전|점검)|기계\s*유지보수|장비\s*점검)",
                "modern": "설비 예지보전(Predictive Maintenance) 및 가동률 최적화 체계 구축",
                "impact": "사후 고장 수리를 IoT·데이터 기반 선제적 예지보전 전문성으로 포지셔닝",
            },
            {
                "pattern": r"(고객사\s*(?:응대|관리)|B2B\s*영업|영업\s*(?:관리|총괄)|거래처|납품|수주)",
                "modern": "B2B 엔터프라이즈 키 어카운트(Key Account) 관리 및 고객 성공(Customer Success) 리딩",
                "impact": "단순 영업·납품을 장기 고객사 파트너십 및 솔루션 컨설팅 역량으로 승격",
            },
            {
                "pattern": r"(구매|자재|조달|발주|소싱|협력사\s*관리)",
                "modern": "데이터 기반 공급망 소싱 최적화 및 협력사 납기·원가 리스크 관리",
                "impact": "경험 중심 구매 발주 업무를 전략적 공급망 원가 절감(Cost Reduction) 역량으로 재해석",
            },
            {
                "pattern": r"(물류|SCM|창고|재고\s*관리|배송|포워딩)",
                "modern": "WMS·ERP 연동 재고 회전율 최적화 및 엔드투엔드 SCM 운영 관리",
                "impact": "현장 입출고 관리를 데이터 기반 공급망 가시성 확보 역량으로 현대화",
            },
            {
                "pattern": r"(재무|회계|결산|원가\s*관리|세무|자금)",
                "modern": "ERP 기반 원가·손익 구조 분석 및 경영 의사결정 재무 모델링 지원",
                "impact": "기장·결산 경력을 사업부 수익성 개선을 이끄는 FP&A 비즈니스 파트너 역량으로 확장",
            },
            {
                "pattern": r"(산업\s*안전|안전\s*관리|중대재해|안전\s*보건|위험성\s*평가)",
                "modern": "중대재해처벌법 대응 ISO45001 안전보건 거버넌스 및 현장 위험성 평가 총괄",
                "impact": "현장 점검 이력을 기업 법적 컴플라이언스 및 선제적 안전 체계 구축 역량으로 부각",
            },
            {
                "pattern": r"(ERP|CRM|SAP|MES|스마트공장|센서\s*데이터|파이썬)",
                "modern": "레거시 현업 프로세스와 디지털 ERP·MES·데이터 모니터링 환경의 가교 구축",
                "impact": "도메인 현장 경험에 디지털 도구 학습 의지를 결합한 하이브리드 실무자로 포지셔닝",
            },
            {
                "pattern": r"(엑셀\s*(?:정리|장부|관리)|문서\s*작성|수기\s*관리|장부)",
                "modern": "ERP 연계 데이터 정합성 검증 및 경영진 의사결정 지원 대시보드 리포팅",
                "impact": "단순 문서 작성을 비즈니스 인텔리전스(BI) 및 데이터 시각화 역량으로 부각",
            },
            {
                "pattern": r"(팀원\s*관리|부서장|반장|조직\s*관리|인력\s*관리|팀장)",
                "modern": "크로스펑셔널(Cross-functional) 조직 협업 커뮤니케이션 및 현장 실무 코칭",
                "impact": "수직적 조직 관리를 현대적 협업 툴 친화적 실행 리더십으로 번역",
            },
            {
                "pattern": r"(프로젝트\s*진행|일정\s*관리|납기\s*준수|PM)",
                "modern": "표준 마일스톤 리스크 관리 및 납기 온타임(On-time) 딜리버리 총괄",
                "impact": "일상적 일정 관리를 프로젝트 매니지먼트(PM) 표준 프레임워크 역량으로 전환",
            },
        ]

    def translate(
        self,
        resume_text: str,
        target_job: str,
        market_keywords: Optional[List[str]] = None,
        missing_skills: Optional[List[str]] = None,
        exp_years: Optional[int] = None,
    ) -> List[Dict[str, str]]:
        """이력서 원문에서 경력 문장을 발췌해 정량 수치를 보존한 목표 JD 문장으로 현대화 번역한다."""
        text = (resume_text or "").strip()
        if not text:
            return []

        scrub = LegalSanitizer.scrub_policy_text
        if self.llm is not None:
            mkt = ", ".join((market_keywords or [])[:6]) or "시장 공고 일반 역량"
            miss = ", ".join((missing_skills or [])[:4]) or "없음"
            user_prompt = (
                f"목표 직무: {target_job}\n"
                f"시장 공고 핵심 키워드: {mkt}\n"
                f"보완 권장 영역: {miss}\n\n"
                f"이력서 원문:\n{text}"
            )
            out = self.llm(TRANS_SYS, user_prompt)
            items = (out or {}).get("items") if isinstance(out, dict) else None
            if isinstance(items, list):
                verified: List[Dict[str, str]] = []
                seen_orig: set[str] = set()
                for it in items[:4]:
                    if not isinstance(it, dict):
                        continue
                    orig = str(it.get("original") or "").strip()
                    mod = scrub(str(it.get("modernized") or "").strip())
                    rat = scrub(str(it.get("impact_rationale") or "").strip())
                    norm_orig = re.sub(r"\s+", "", orig.lower())
                    if not orig or not mod or norm_orig in seen_orig:
                        continue
                    if not _is_valid_translation(orig, mod, text, exp_years=exp_years):
                        continue
                    seen_orig.add(norm_orig)
                    if not mod.startswith("•"):
                        mod = f"• {mod}"
                    verified.append({
                        "original": orig,
                        "modernized": mod,
                        "impact_rationale": rat or f"{target_job} 채용 공고의 실무 역량 표현으로 재구성",
                        "target_context": f"[{target_job}] 2026 채용 시장 핵심 역량 반영",
                    })
                if verified:
                    return verified

        return self._fallback_translate(text, target_job)

    def _fallback_translate(self, resume_text: str, target_job: str) -> List[Dict[str, str]]:
        results: List[Dict[str, str]] = []
        sentences = [s.strip() for s in re.split(r"[\n.?!]", resume_text) if len(s.strip()) > 6]
        matched_patterns: set[str] = set()
        seen_orig: set[str] = set()

        for s in sentences:
            norm_s = re.sub(r"\s+", "", s.lower())
            if norm_s in seen_orig:
                continue
            metrics = re.findall(
                r"(?:\d+(?:\.\d+)?\s*(?:년|개월|%|억|만원|건|명|배)|ISO\s*\d+)",
                s,
                re.I,
            )
            metric_suffix = f" ({', '.join(dict.fromkeys(m.strip() for m in metrics[:3]))} 달성·적용)" if metrics else ""
            for rule in self.translation_dictionary:
                pat = rule["pattern"]
                if pat not in matched_patterns and re.search(pat, s, re.I):
                    matched_patterns.add(pat)
                    seen_orig.add(norm_s)
                    results.append({
                        "original": s,
                        "modernized": f"• {rule['modern']}{metric_suffix}",
                        "impact_rationale": rule["impact"],
                        "target_context": f"[{target_job}] 서류 심사관 우대 키워드 자동 반영",
                    })
                    break  # 동일 원문 문장의 중복 출력 방지

        if not results:
            results.append({
                "original": resume_text[:80] + ("..." if len(resume_text) > 80 else ""),
                "modernized": f"• {target_job} 현업 실무 노하우 기반의 데이터 드리븐(Data-driven) 업무 프로세스 혁신",
                "impact_rationale": "시니어의 풍부한 현장 도메인 지식을 현대 채용 시장의 핵심 역량 키워드로 연결",
                "target_context": f"[{target_job}] 핵심 직무기술서(JD) 부합",
            })

        return results
