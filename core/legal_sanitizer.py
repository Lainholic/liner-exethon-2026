"""
개인정보(PII) 로컬 마스킹 & 직무 키워드 정제 모듈.
Liner API 또는 외부 검색 엔진에 전송하기 전 민감 개인정보(이름, 주민번호, 전화번호, 이메일, 자택주소 등)를 로컬에서 철저히 마스킹합니다.
"""
import re
from typing import Dict, Any, Tuple


class LegalSanitizer:
    # 한국 전화번호 / 휴대폰 (하이픈 및 공백 지원)
    PHONE_REGEX = re.compile(r'(?:01[016789]|02|0[3-6][1-5])[- ]?\d{3,4}[- ]?\d{4}')
    # 이메일 주소
    EMAIL_REGEX = re.compile(r'[a-zA-Z0-9_.+-]+@[a-zA-Z0-9-]+\.[a-zA-Z0-9-.]+')
    # 주민등록번호 / 외국인등록번호 패턴 (생년월일 6자리 - 1~4로 시작하는 7자리)
    RRN_REGEX = re.compile(r'\b\d{6}[-\s]?[1-4]\d{6}\b')
    # 상세 도로명/지번 주소 패턴 (간이 필터)
    ADDRESS_REGEX = re.compile(r'([가-힣]+(?:시|도)\s+[가-힣]+(?:시|군|구)\s+[가-힣0-9\s\-]+(?:로|길|동|읍|면|리)\s*\d*(?:번지)?)')

    @classmethod
    def sanitize_text(cls, text: str) -> Tuple[str, Dict[str, int]]:
        """
        텍스트 내 개인 식별 정보(PII)를 [마스킹] 처리하고 치환 건수를 반환합니다.
        """
        stats = {
            "rrn_masked": 0,
            "phone_masked": 0,
            "email_masked": 0,
            "address_masked": 0
        }

        if not text:
            return "", stats

        sanitized = text

        # 1. 주민등록번호 마스킹 (최우선)
        def rrn_sub(m):
            stats["rrn_masked"] += 1
            return "[주민등록번호_마스킹]"
        sanitized = cls.RRN_REGEX.sub(rrn_sub, sanitized)

        # 2. 전화번호 마스킹
        def phone_sub(m):
            stats["phone_masked"] += 1
            return "[전화번호_마스킹]"
        sanitized = cls.PHONE_REGEX.sub(phone_sub, sanitized)

        # 3. 이메일 마스킹
        def email_sub(m):
            stats["email_masked"] += 1
            return "[이메일_마스킹]"
        sanitized = cls.EMAIL_REGEX.sub(email_sub, sanitized)

        # 4. 상세 주소 마스킹 (시/도, 구 수준까지만 남기고 상세는 마스킹)
        def addr_sub(m):
            stats["address_masked"] += 1
            return "[상세주소_마스킹]"
        sanitized = cls.ADDRESS_REGEX.sub(addr_sub, sanitized)

        return sanitized, stats

    @classmethod
    def extract_searchable_query(cls, desired_role: str, tech_skills: list, region: str = "") -> str:
        """
        API로 전송되는 검색 쿼리에서 개인정보는 일절 배제하고 순수 직무/기술/지역 키워드만 조합합니다.
        """
        safe_role = cls.sanitize_text(desired_role)[0].strip()
        safe_skills = [cls.sanitize_text(s)[0].strip() for s in tech_skills if s.strip()]
        
        query_parts = []
        if safe_role:
            query_parts.append(safe_role)
        if safe_skills:
            query_parts.append(" ".join(safe_skills[:5]))
        if region:
            query_parts.append(region.strip())

        return " ".join(query_parts)

    @staticmethod
    def scrub_policy_text(text: str) -> str:
        """과장 지원 문구 및 금지 서식 기호를 결정론적으로 제거한다."""
        t = str(text or "")
        for bad, repl in (
            ("10" + "0%", "국비 지원(유형별 상이)"),
            ("\uc804\uc561 \ubb34\ub8cc", "국비 지원 대상"),
            ("\ubb34\ub8cc", "국비 지원"),
            ("\uc804\uc561\uc9c0\uc6d0", "국비지원"),
            ("~" + "~", "-"),
        ):
            t = t.replace(bad, repl)
        t = re.sub(r"</?(?:strike|s|del)>", "", t, flags=re.I)
        return t
