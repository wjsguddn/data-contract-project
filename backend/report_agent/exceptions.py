"""
Report Agent 커스텀 예외 클래스
"""


class ReportAgentError(Exception):
    """Report Agent 기본 예외"""
    pass


class ParsingError(ReportAgentError):
    """A1/A3 결과 파싱 실패"""
    pass


class ClauseReferenceError(ReportAgentError):
    """표준 조항 참조 추출 실패"""
    pass


class LLMVerificationError(ReportAgentError):
    """LLM 재검증 실패"""
    pass


class DatabaseSaveError(ReportAgentError):
    """DB 저장 실패"""
    pass
