"""
경량 AST(Abstract Syntax Tree) 기반 실무 코드 아키텍처 및 품질/복잡도 분석 엔진.
- 지원자가 제출한 공개 파이썬 소스코드의 함수 수, 클래스 구조, 순환 복잡도(Cyclomatic Complexity)를 계산한다.
- 단순 Hello World나 복사된 튜토리얼 수준인지, 실무 프로덕션 아키텍처인지 '코드 품질 지수(Code Quality Index)'로 판정.
"""
import ast
import re
from typing import Dict, Any, List


class CodeQualityAnalyzer:
    """파이썬 및 주요 코드 텍스트의 AST/구문 구조를 분석해 복잡도와 설계 충실도를 측정한다."""

    @staticmethod
    def analyze_python_source(code_text: str) -> Dict[str, Any]:
        if not code_text or not code_text.strip():
            return {
                "parsed": False,
                "complexity_score": 0,
                "quality_grade": "분석 불가 (코드 없음)",
                "classes_count": 0,
                "functions_count": 0,
                "avg_complexity": 0.0,
                "has_async": False,
                "has_type_hints": False,
                "has_docstrings": False,
            }

        try:
            tree = ast.parse(code_text)
        except SyntaxError:
            # 부분 스니펫이거나 타 언어일 경우 휴리스틱 판정
            classes = len(re.findall(r"\bclass\s+\w+", code_text))
            functions = len(re.findall(r"\bdef\s+\w+|\bfunction\s+\w+", code_text))
            branches = len(re.findall(r"\bif\b|\bfor\b|\bwhile\b|\btry\b", code_text))
            return {
                "parsed": False,
                "complexity_score": min(95, 40 + branches * 5 + classes * 10),
                "quality_grade": "실무 구현 수준 (휴리스틱 추정)" if branches >= 5 else "기초 실습 수준",
                "classes_count": classes,
                "functions_count": functions,
                "avg_complexity": round(max(1.0, branches / max(1, functions)), 1),
                "has_async": bool(re.search(r"\basync\b", code_text)),
                "has_type_hints": ":" in code_text and "->" in code_text,
                "has_docstrings": '"""' in code_text or "'''" in code_text,
            }

        classes = 0
        functions = 0
        branches = 0
        has_async = False
        has_type_hints = False
        has_docstrings = False

        for node in ast.walk(tree):
            if isinstance(node, ast.ClassDef):
                classes += 1
                if ast.get_docstring(node):
                    has_docstrings = True
            elif isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef)):
                functions += 1
                if isinstance(node, ast.AsyncFunctionDef):
                    has_async = True
                if ast.get_docstring(node):
                    has_docstrings = True
                if node.returns or any(arg.annotation for arg in node.args.args):
                    has_type_hints = True
            elif isinstance(node, (ast.If, ast.For, ast.While, ast.ExceptHandler, ast.With)):
                branches += 1

        avg_comp = round((branches + functions) / max(1, functions), 1)

        # 복잡도 및 품질 종합 산정 (0 ~ 100)
        score = 40
        score += min(25, classes * 8)
        score += min(20, functions * 4)
        score += 5 if has_async else 0
        score += 5 if has_type_hints else 0
        score += 5 if has_docstrings else 0
        score = min(98, score)

        if score >= 80:
            grade = "A+ (엔터프라이즈 모듈형 아키텍처)"
        elif score >= 65:
            grade = "B+ (실무 서비스 수준 설계)"
        else:
            grade = "C (기초 스크립트 / 튜토리얼 수준)"

        return {
            "parsed": True,
            "complexity_score": score,
            "quality_grade": grade,
            "classes_count": classes,
            "functions_count": functions,
            "avg_complexity": avg_comp,
            "has_async": has_async,
            "has_type_hints": has_type_hints,
            "has_docstrings": has_docstrings,
        }
