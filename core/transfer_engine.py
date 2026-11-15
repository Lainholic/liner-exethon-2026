"""
전통 직무 경력 ➔ 디지털/신산업 직무 간 역량 전이 가중치 매트릭스 및 전이도 계산 엔진.
- 전통 제조/영업/사무 베테랑의 숨겨진 기초 역량이 디지털 신직무에 어떻게 매핑되는지 가중치 기반으로 산출한다.
- 5대 핵심 축(도메인 지식, 데이터/품질 관리, 공정/운영 최적화, 협업/리더십, 디지털 도구 활용) 방사형 지수 계산.
"""
from typing import Dict, List, Set, Tuple

# 전통 역량 키워드 ➔ 디지털 신직무 역량 전이 가중치 사전 (0.0 ~ 1.0)
TRANSFER_ONTOLOGY: Dict[str, Dict[str, float]] = {
    # 품질/제조 ➔ 스마트팩토리/데이터/공정
    "품질관리": {"데이터 이상 감지": 0.85, "공정 데이터 분석": 0.80, "품질 예측 모델링": 0.70, "표준 운영(SOP)": 0.95},
    "iso9001": {"품질 규격 감사": 0.90, "데이터 무결성 관리": 0.75, "프로세스 표준화": 0.90},
    "불량률감소": {"수율 최적화": 0.85, "원인 분석(RCA)": 0.80, "SPC 통계적 공정관리": 0.85},
    "공정개선": {"공정 자동화 설계": 0.80, "생산 병목 제거": 0.85, "ERP/MES 연계": 0.75},
    "mes": {"스마트팩토리 데이터 관리": 0.95, "실시간 설비 모니터링": 0.90, "생산 실적 트래킹": 0.90},
    "plc": {"OT 데이터 수집": 0.85, "센서/IoT 인터페이스": 0.80, "엣지 컴퓨팅": 0.70},
    "설비보전": {"예지보전(PdM)": 0.80, "설비 가동률 분석": 0.85, "센서 이상 징후 포착": 0.75},

    # 영업/유통 ➔ B2B SaaS / CSM / 테크세일즈
    "고객사관리": {"고객 성공(CSM)": 0.90, "계정 확장(Upselling)": 0.80, "이탈율(Churn) 방지": 0.85},
    "납품계약": {"엔터프라이즈 SLA 체결": 0.85, "B2B 솔루션 견적": 0.80, "계약 리스크 관리": 0.85},
    "영업관리": {"파이프라인 관리": 0.85, "매출 예측(Forecasting)": 0.80, "CRM 데이터 분석": 0.75},
    "대면영업": {"고객사 페인포인트 발굴": 0.90, "솔루션 데모 프레젠테이션": 0.80},

    # 구매/물류 ➔ SCM 데이터 / ERP 운영
    "구매발주": {"수요 예측 연계 발주": 0.80, "원가 분석": 0.85, "공급망 리스크 분석": 0.80},
    "자재관리": {"재고 최적화 알고리즘": 0.80, "안전재고 산정": 0.85, "WMS 연동": 0.80},
    "협력사소싱": {"공급망 다변화": 0.85, "글로벌 벤더 실사": 0.80},
    "erp": {"ERP 정보 시스템 운영": 0.95, "자재 수불 데이터 무결성": 0.90},

    # 공통 기초
    "엑셀": {"스프레드시트 데이터 모델링": 0.75, "피벗/수식 데이터 분석": 0.80},
    "python": {"업무 자동화 스크립트": 0.85, "데이터 전처리": 0.80},
    "sql": {"관계형 데이터베이스 쿼리": 0.90, "실무 데이터 추출": 0.90},
}

RADAR_AXES = [
    "도메인 전문성",
    "데이터/품질 분석",
    "공정/운영 최적화",
    "협업 및 리더십",
    "디지털 도구 적응력",
]


class SkillTransferEngine:
    """전통 역량과 신규 직무 요구역량 간 전이 가중치 및 방사형 역량 점수를 계산한다."""

    @staticmethod
    def calculate_transfer_profile(
        held_skills: List[str],
        experience_years: int,
        target_role: str,
        resume_text: str = ""
    ) -> Dict[str, any]:
        raw_skills = [str(s).strip().lower().replace(" ", "") for s in held_skills if str(s).strip()]
        full_text = f"{' '.join(raw_skills)} {resume_text.lower()} {target_role.lower()}"

        transferred_skills: Dict[str, float] = {}
        for skill in raw_skills:
            for onto_key, mapping in TRANSFER_ONTOLOGY.items():
                if onto_key in skill:
                    for target_cap, weight in mapping.items():
                        transferred_skills[target_cap] = max(transferred_skills.get(target_cap, 0.0), weight)

        # 5대 축 점수 계산 (0 ~ 100점)
        # 1. 도메인 전문성 (경력 연수에 비례)
        domain_score = min(95, 50 + int(experience_years * 2.2))

        # 2. 데이터/품질 분석
        data_keywords = ("데이터", "품질", "분석", "iso", "불량", "측정", "통계", "sql", "엑셀", "모니터링")
        data_hits = sum(1 for kw in data_keywords if kw in full_text)
        data_score = min(95, 45 + data_hits * 10)

        # 3. 공정/운영 최적화
        process_keywords = ("공정", "개선", "생산", "mes", "설비", "재고", "scm", "물류", "sop", "원가")
        proc_hits = sum(1 for kw in process_keywords if kw in full_text)
        proc_score = min(95, 45 + proc_hits * 10)

        # 4. 협업 및 리더십 (팀장/부서장/고객사 관리 등)
        lead_keywords = ("팀장", "부서장", "총괄", "관리", "협력사", "고객사", "계약", "협상", "소통", "멘토링")
        lead_hits = sum(1 for kw in lead_keywords if kw in full_text)
        lead_score = min(95, 50 + lead_hits * 10)

        # 5. 디지털 도구 적응력
        digital_keywords = ("python", "파이썬", "sql", "erp", "mes", "ai", "클라우드", "자동화", "crm", "iot")
        digi_hits = sum(1 for kw in digital_keywords if kw in full_text)
        digi_score = min(95, 40 + digi_hits * 12)

        radar_scores = [domain_score, data_score, proc_score, lead_score, digi_score]
        transfer_readiness = round(sum(radar_scores) / len(radar_scores), 1)

        sorted_transfers = sorted(transferred_skills.items(), key=lambda x: x[1], reverse=True)

        return {
            "radar_axes": RADAR_AXES,
            "radar_scores": radar_scores,
            "transfer_readiness": transfer_readiness,
            "transferred_capabilities": [
                {"capability": k, "transfer_weight": round(v * 100)} for k, v in sorted_transfers[:6]
            ],
            "readiness_verdict": (
                "상위 15% 디지털 전환 준비도" if transfer_readiness >= 80
                else "현장 실무 중심 디지털 전환 유망군" if transfer_readiness >= 65
                else "기초 직무 역량 기반 성장 잠재군"
            )
        }
