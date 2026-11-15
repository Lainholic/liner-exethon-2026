from typing import Any, Callable, Dict, List, Optional
from .liner_client import LinerClient
from .analyzer import JobSeekerProfile, MatchResult
from .legal_sanitizer import LegalSanitizer
from .llm import llm_json

_UNSET = object()

ROADMAP_SYS = (
    "너는 40+ 시니어 경력전환 커리어 전략가다. 지원자의 경력·보유역량·부족역량·시장요구·실제 추천공고·고용24 국비과정을 반영해 "
    "실행 가능한 7일 즉각 스프린트(6개 항목)와 3개월 로드맵(3개 항목)을 작성한다. "
    "지원자 경력과 목표 직무, 부족 역량, 제공된 실제 공고명·국비과정명을 직접 인용하라. "
    "추천 국비과정이 '모집마감' 상태이면 해당 기수에 바로 수강신청하라고 쓰지 말고, "
    "해당 기관 차기 회차 개설 일정 확인 및 동일 NCS 직무분류의 현재 모집 중 과정 대체 신청으로 안내하라. "
    "지원 금액·자부담률은 '과정 상세에서 확인'으로 안내하며 과장된 비용 보장을 쓰지 마라. "
    'JSON: {"sprint":[{"day":"Day 1 (오늘)","action":"...","deliverable":"..."}],'
    '"phases":[{"month":"1개월차: ...","goal":"...","actions":["...","...","..."],"recommended_resource":"..."}]}'
)


class RoadmapGenerator:
    """
    고용노동부 HRD-Net 국비과정과 연계한 3개월 단계별 커리어 로드맵 및 7일 즉각 실행 스프린트 생성기.
    """
    def __init__(self, liner_client: Optional[LinerClient] = None, llm: Any = _UNSET):
        self.liner = liner_client or LinerClient()
        if llm is _UNSET:
            self.llm = llm_json if getattr(self.liner, "is_live", False) else None
        else:
            self.llm = llm

    def generate_roadmap(self, profile: JobSeekerProfile, match_result: Optional[MatchResult] = None,
                         market: Optional[List[Dict]] = None) -> Dict:
        # market: PostingStore.market_requirements() 결과. 표본(n)이 충분(reliable)할 때만 근거로 사용한다.
        market = market or []
        n = market[0]["sample_size"] if market else 0
        reliable = bool(market and market[0].get("reliable"))
        top_skills = [m["requirement"] for m in market[:3]] if reliable else []
        market_note = (
            f"수집 공고 {n}건 중 반복 등장: " + ", ".join(f"{m['requirement']}({m['count']}건)" for m in market[:5])
            if reliable else
            (f"수집 공고 표본이 {n}건으로 부족해 시장 요구사항 집계는 표시하지 않습니다." if n else "수집된 공고가 없어 시장 요구사항 집계가 없습니다.")
        )
        missing = [m.split(" — ")[0] for m in match_result.missing_skills] if match_result else ["직무 핵심 기초 및 표준 이론"]
        # Liner API 실시간 국비지원 교육과정 탐색 (부족 역량 반영)
        if hasattr(self.liner, "search_government_courses"):
            courses = self.liner.search_government_courses(profile.desired_role, missing[:3])[:2]
        else:
            courses = self.liner.search_training_courses(profile.desired_role, num_results=2)

        primary_course = courses[0] if courses else {
            "title": f"고용노동부 2026 {profile.desired_role} 양성 국비지원 과정",
            "institution": "고용노동부 지정 훈련기관",
            "support_type": "국민내일배움카드 국비지원 과정 (자부담·지원 한도는 과정 상세에서 확인)",
            "url": "https://www.hrd.go.kr"
        }

        focus_skill_1 = top_skills[0] if top_skills else (missing[0] if len(missing) > 0 else "직무 핵심 역량")
        focus_skill_2 = top_skills[1] if len(top_skills) > 1 else (missing[1] if len(missing) > 1 else "디지털 도구 및 실습")
        course_title = primary_course.get("title") or f"{profile.desired_role} 국비지원 과정"
        gap_txt = ", ".join(missing[:2]) if missing else focus_skill_1
        has_open_match = bool(
            match_result is not None
            and getattr(match_result.job, "status", "") == "open"
            and not getattr(match_result.job, "is_mock", False)
        )
        target_title = match_result.job.title if match_result is not None else f"{profile.desired_role} 목표 공고"

        course_closed = "마감" in str(primary_course.get("recruit_status") or "")
        ncs_label = primary_course.get("ncs") or profile.desired_role
        if course_closed:
            m1_action0 = f"고용24(HRD-Net)에서 '{course_title}' 차기 기수 알림 확인 및 동일 NCS({ncs_label}) 현재 모집 중 국비과정 수강 신청"
            day2_action = f"고용24(HRD-Net)에서 '{course_title}'({primary_course.get('institution', '')}) 차기 회차 개설 일정을 확인하고, 동일 NCS 분류({ncs_label})의 현재 모집 중 과정을 조회·신청"
            day2_deliv = "차기 기수 일정 확인 또는 동일 NCS 모집 중 과정 수강신청 내역 확보 (자부담 여부는 과정 상세에서 확인)"
        else:
            m1_action0 = f"고용24(HRD-Net) 접속하여 국민내일배움카드 발급 상태 및 '{course_title}' 개강·자부담 조건 확인 후 신청"
            day2_action = f"고용24(HRD-Net)에서 국민내일배움카드 발급 확인 및 '{course_title}' 과정 수강 신청"
            day2_deliv = "훈련과정 수강신청 완료증 확보 (자부담 여부는 과정 상세에서 확인)"

        fallback_months = [
            {
                "month": "1개월차: 기초 체력 & 핵심 자격 요건 보완",
                "goal": f"공고 서류 필터링을 방지하기 위한 기초 자격 요건 충족 ({focus_skill_1})",
                "actions": [
                    m1_action0,
                    f"목표 직무 핵심 보완 영역({focus_skill_1}) 중심 기초 학습 및 관련 자격 시험 일정 확인 (주 6시간 학습)",
                    "시니어 경력 기술서 초안 정리: 과거 실무 성과를 최신 직무 용어로 재정의"
                ],
                "recommended_resource": f"HRD-Net 국민내일배움카드 훈련기관: {primary_course.get('institution')}"
            },
            {
                "month": "2개월차: 실무 프로젝트 & AI 생산성 툴 습득",
                "goal": f"경력직의 실무 경쟁력을 입증할 포트폴리오 및 {focus_skill_2} 숙달",
                "actions": [
                    "국비지원 과정 내 실무 프로젝트 참여: 실제 현업 데이터를 활용한 문제 해결 과제 완수",
                    "AI 생산성 도구(Liner Search 등)를 실무 프로세스에 접목한 사례 구축",
                    "2~3페이지 분량의 직무 수행 계획서 및 프로젝트 포트폴리오 1부 완성"
                ],
                "recommended_resource": "Liner AI 플랫폼을 활용한 실시간 최신 산업 트렌드 및 기업 동향 리서치"
            },
            {
                "month": "3개월차: 맞춤형 이력서 타깃팅 & 실전 구직 지원",
                "goal": "진행 중 타깃 공고 실전 지원 및 시니어 맞춤 면접 대비",
                "actions": [
                    "공고별 요구사항에 맞춰 이력서 키워드 1:1 커스터마이징 (우선 타깃 공고 TOP 3 순차 지원)",
                    "시니어 면접의 핵심인 '유연성', '협업 조직과의 소통 역량', '디지털 도구 수용성' 답변 스크립트 준비",
                    "주 3회 정기 지원 및 서류 피드백 반영하며 면접 진행"
                ],
                "recommended_resource": "고용복지플러스센터 중장년내일센터 취업 상담·알선 프로그램 (제공 내용과 비용은 센터에 확인)"
            }
        ]

        if has_open_match:
            day1_action = f"진행 중 1순위 공고 '{target_title}' 요건 분석 및 '시니어 경력 번역기' 문구를 이력서 상단에 반영"
            day4_action = f"1순위 진행 중 공고 '{target_title}' 공식 채용 페이지로 맞춤 이력서 실전 제출"
            day5_action = f"유관 진행 중 공고 2~3곳 대상 '{focus_skill_2}' 키워드 보강 후 순차 접수"
        else:
            day1_action = f"고용24·원티드·잡코리아에 '{profile.desired_role}' 실시간 채용 알림 설정 및 참고 공고 요건({gap_txt}) 분석"
            day4_action = f"신규 오픈되는 '{profile.desired_role}' 우선 타깃 공고 1곳 선정 후 맞춤 이력서 제출"
            day5_action = f"연관 직무군 진행 중 공고 2곳 탐색 후 '{focus_skill_2}' 경험 문구 반영해 접수"

        sprint_days, months = self._llm_customize(
            profile, match_result, primary_course, top_skills, missing, target_title, has_open_match
        )
        if not sprint_days:
            sprint_days = [
                {
                    "day": "Day 1 (오늘)",
                    "action": day1_action,
                    "deliverable": "최신 채용 시장 키워드가 적용된 1페이지 이력서 개정본 완성"
                },
                {
                    "day": "Day 2",
                    "action": day2_action,
                    "deliverable": day2_deliv
                },
                {
                    "day": "Day 3",
                    "action": f"부족 역량({gap_txt}) 보완을 위한 직무 자격·실습 커리큘럼 일정 확인 및 학습 착수",
                    "deliverable": "학습·자격 준비 일정표 확정 (해당 시 이력서에 '취득 준비 중' 명시)"
                },
                {
                    "day": "Day 4",
                    "action": day4_action,
                    "deliverable": "1순위 기업 지원서 접수 및 제출 요건 체크 완료"
                },
                {
                    "day": "Day 5",
                    "action": day5_action,
                    "deliverable": "복수 타깃 기업 지원 포트폴리오 및 지원 내역 정리"
                },
                {
                    "day": "Day 6~7",
                    "action": f"'{gap_txt}' 보완 계획과 조직 협업·디지털 도구 적응력 면접 답변 스크립트 연습",
                    "deliverable": "핵심 실무·압박 면접 질문 1분 스피치 3건 숙달"
                }
            ]
        if not months:
            months = fallback_months

        return {
            "desired_role": profile.desired_role,
            "market_note": market_note,
            "market": {"sample_size": n, "reliable": reliable, "top": market[:8] if reliable else []},
            "target_course": primary_course,
            "all_courses": courses,
            "phases": months,
            "sprint": sprint_days
        }

    def _llm_customize(
        self,
        profile: JobSeekerProfile,
        match_result: Optional[MatchResult],
        course: Dict,
        top_skills: List[str],
        missing: List[str],
        target_title: str,
        has_open_match: bool,
    ):
        if self.llm is None:
            return None, None
        prompt = (
            f"만 나이: {profile.age}세 / 경력: {profile.total_experience_years}년\n"
            f"희망 직무: {profile.desired_role}\n"
            f"보유 역량: {', '.join(profile.skills[:8])}\n"
            f"시장 핵심 역량: {', '.join(top_skills) or '미집계'}\n"
            f"부족·보완 역량: {', '.join(missing[:4])}\n"
            f"1순위 {'진행 중 ' if has_open_match else '참고 '}공고: {target_title} (기업: {getattr(match_result.job, 'company', '') if match_result else ''})\n"
            f"추천 국비과정: {course.get('title', '')} / 기관: {course.get('institution', '')} / "
            f"상태: {course.get('recruit_status', '상세확인')} / NCS: {course.get('ncs', '미상')} / "
            f"기간: {course.get('period', '상세확인')} / 시간: {course.get('duration', '상세확인')}"
        )
        out = self.llm(ROADMAP_SYS, prompt)
        if not isinstance(out, dict):
            return None, None

        scrub = LegalSanitizer.scrub_policy_text
        raw_sprint = out.get("sprint")
        raw_phases = out.get("phases")

        sprint = []
        if isinstance(raw_sprint, list):
            for it in raw_sprint[:7]:
                if isinstance(it, dict) and it.get("day") and it.get("action") and it.get("deliverable"):
                    sprint.append({
                        "day": scrub(str(it["day"]).strip()),
                        "action": scrub(str(it["action"]).strip()),
                        "deliverable": scrub(str(it["deliverable"]).strip()),
                    })

        phases = []
        if isinstance(raw_phases, list):
            for ph in raw_phases[:3]:
                if isinstance(ph, dict) and ph.get("month") and ph.get("goal") and isinstance(ph.get("actions"), list):
                    acts = [scrub(str(a).strip()) for a in ph["actions"] if str(a).strip()][:4]
                    if acts:
                        phases.append({
                            "month": scrub(str(ph["month"]).strip()),
                            "goal": scrub(str(ph["goal"]).strip()),
                            "actions": acts,
                            "recommended_resource": scrub(str(ph.get("recommended_resource") or "고용24(HRD-Net) 및 중장년내일센터").strip()),
                        })

        return (sprint if len(sprint) >= 4 else None), (phases if len(phases) == 3 else None)
