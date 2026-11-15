"""실시간 면접 답변 검증 및 꼬리 질문(Follow-up Question) 생성 엔진."""
import re
from typing import Any, Dict, List, Optional
from .llm import llm_json
from .legal_sanitizer import LegalSanitizer


class InterviewDrillEngine:
    """면접관과 구직자를 위한 실시간 면접 답변 분석 및 압박 꼬리질문 생성기."""

    @staticmethod
    def analyze_answer(
        question: str,
        answer: str,
        claim_context: str = "",
        eval_criteria: str = "",
        llm_fn: Optional[Any] = None,
    ) -> Dict[str, Any]:
        """면접자의 답변을 정량/구체성 차원에서 평가하고 후속 꼬리 질문을 도출한다."""
        ans = (answer or "").strip()
        if not ans or len(ans) < 10:
            return {
                "source": "rule_based",
                "score": 20,
                "verdict": "답변 분량 부족",
                "critique": "답변이 너무 짧거나 추상적입니다. 구체적인 상황(Situation), 본인의 역할(Action), 정량적 성과(Result)를 포함해 답변해 주세요.",
                "missing_elements": ["구체적 수행 역할", "수치 기반 성과", "사용 기술 도구"],
                "follow_up_questions": [
                    "해당 프로젝트에서 본인이 직접 작성한 코드나 담당한 세부 모듈은 구체적으로 무엇이었습니까?",
                    "그 작업을 통해 개선된 성능이나 불량률 감소 등 측정 가능한 수치는 무엇이었습니까?",
                ],
            }

        # 1. LLM 분석 시도 (PII 마스킹 후 프롬프트 조립)
        ans_safe, _ = LegalSanitizer.sanitize_text(ans)
        q_safe, _ = LegalSanitizer.sanitize_text(question or "")
        ctx_safe, _ = LegalSanitizer.sanitize_text(claim_context or "")
        crit_safe, _ = LegalSanitizer.sanitize_text(eval_criteria or "")

        call_fn = llm_fn if llm_fn is not None else llm_json
        sys_prompt = (
            "당신은 테크 기업의 시니어 채용 전문 기술 면접관입니다. "
            "지원자의 면접 답변을 읽고 STAR 기법(상황, 과제, 행동, 결과) 관점에서 냉정하게 분석하세요.\n"
            "반드시 아래 JSON 형식으로만 답변하며, 각 꼬리 질문은 절대 문장이 중간에 끊기지 않도록 1~2문장 이내의 완성된 문장으로 마침표를 찍어 끝맺으세요:\n"
            "{\n"
            '  "score": 75,\n'
            '  "verdict": "우수/양호/보통/미흡/의심 중 택1",\n'
            '  "critique": "답변의 강점과 구체적인 약점 평가 (2~3문장)",\n'
            '  "missing_elements": ["부족한 부분1", "부족한 부분2"],\n'
            '  "follow_up_questions": ["완결된 날카로운 꼬리 질문 1", "완결된 날카로운 꼬리 질문 2"]\n'
            "}"
        )
        user_prompt = (
            f"[면접 질문]: {q_safe}\n"
            f"[평가 기준]: {crit_safe or '실제 기여도 및 기술적 구현 역량 검증'}\n"
            f"[원문 주장]: {ctx_safe or '포트폴리오 제출 내용'}\n"
            f"[지원자 답변]: {ans_safe}\n\n"
            "지원자의 답변이 두루뭉술하거나 과장된 부분이 있다면 이를 집요하게 파고드는 실무 꼬리 질문 2개를 작성하세요."
        )

        res = call_fn(sys_prompt, user_prompt)
        if isinstance(res, dict) and "score" in res and "follow_up_questions" in res:
            try:
                score = max(0, min(100, int(res.get("score", 60))))
                res["score"] = score
                res["follow_up_questions"] = list(res.get("follow_up_questions", []))[:2]
                res["missing_elements"] = list(res.get("missing_elements", []))[:3]
                res["source"] = "llm"
                return res
            except Exception:
                pass

        # 2. 결정론적 룰베이스 폴백 (Rule-based Deterministic Engine)
        return InterviewDrillEngine._deterministic_fallback(question, ans, eval_criteria)

    @staticmethod
    def _deterministic_fallback(question: str, answer: str, criteria: str = "") -> Dict[str, Any]:
        """LLM 장애 시에도 100% 작동하는 언어학적/수치 기반 분석기."""
        score = 50
        missing = []
        critique_parts = []

        # 1. 정량적 수치 포함 여부 (건, %, 개, ms, 초, 배, 원 등)
        num_m = re.findall(r"(?<![\d,])\d+(?:,\d{3})*(?:\.\d+)?\s*(?:%|건|개|배|초|ms|원|만|억|회|명)", answer)
        if num_m:
            score += 25
            critique_parts.append(f"답변에 정량 성과 지표({', '.join(num_m[:3])})가 포함되어 있습니다. 수치의 사실 여부는 별도 근거 확인이 필요합니다.")
        else:
            missing.append("정량적 개선 지표 (% 또는 건수)")
            critique_parts.append("정량적 결과 수치가 누락되어 성과의 규모를 가늠하기 어렵습니다.")

        # 2. 주체적 행동 키워드 검증 (설계, 구현, 작성, 도입, 개선, 해결, 조치)
        action_words = ("설계", "구현", "작성", "도입", "개선", "해결", "조치", "최적화", "분석", "개발")
        found_actions = [w for w in action_words if w in answer]
        if found_actions:
            score += 15
        else:
            missing.append("본인이 직접 수행한 핵심 조치(Action)")

        # 3. 기술 도구/기술어 언급 (Python, SQL, PLC, MES, ERP, API, Docker 등)
        tech_words = ("python", "sql", "plc", "mes", "erp", "api", "git", "linux", "모니터링", "센서", "데이터", "엑셀")
        found_techs = [w for w in tech_words if w in answer.lower()]
        if found_techs:
            score += 10
        else:
            missing.append("활용한 구체적 기술 도구나 아키텍처")

        # 종합 판정
        score = min(100, max(20, score))
        if score >= 85:
            verdict = "매우 우수 (답변 구체성 기준)"
        elif score >= 70:
            verdict = "우수 (답변 구체성 기준)"
        elif score >= 50:
            verdict = "보통 (구체적 세부 증거 보완 요망)"
        else:
            verdict = "미흡 (추상적 서술 / 추가 검증 필요)"

        # 꼬리 질문 생성
        follow_ups = []
        if "정량적 개선 지표 (% 또는 건수)" in missing:
            follow_ups.append("해당 조치를 통해 개선된 수치(응답 시간 단축률, 불량률 감소폭, 비용 절감액 등)를 구체적인 숫자로 말씀해 주실 수 있나요?")
        else:
            follow_ups.append("그 성과를 측정할 때 사용한 기준 데이터셋이나 모니터링 주기는 어떻게 설정하셨습니까?")

        if "활용한 구체적 기술 도구나 아키텍처" in missing:
            follow_ups.append("그 문제를 해결할 때 가장 핵심적으로 활용했던 라이브러리나 기술 아키텍처는 무엇이었습니까?")
        else:
            follow_ups.append("그 기술을 적용하는 과정에서 겪었던 가장 까다로운 예외 상황이나 병목 현상은 무엇이었고, 어떻게 해결하셨습니까?")

        return {
            "source": "rule_based",
            "score": score,
            "verdict": verdict,
            "critique": " ".join(critique_parts),
            "missing_elements": missing or ["도입 시 발생한 트레이드오프 설명"],
            "follow_up_questions": follow_ups[:2],
        }
