"""
챗봇 에이전트 데이터 모델

타입 안전한 툴 응답 스키마 정의
"""

from pydantic import BaseModel, Field
from typing import Optional, Dict, List, Any, Union
from datetime import datetime


# ============================================
# 기본 ToolResult (제네릭)
# ============================================
class ToolResult(BaseModel):
    """툴 실행 결과 (제네릭)"""
    success: bool
    tool_name: str
    data: Optional[BaseModel] = None  # BaseModel로 제한
    error: Optional[str] = None
    metadata: Optional[Dict[str, Any]] = None
    
    # 추가 메타데이터
    execution_time: Optional[float] = None  # 실행 시간 (초)
    token_usage: Optional[Dict[str, int]] = None  # 토큰 사용량
    relevance_score: Optional[float] = None  # 관련성 점수 (LLM 평가)
    
    class Config:
        arbitrary_types_allowed = True


# ============================================
# 1. HybridSearchTool 응답 스키마
# ============================================
class ArticleContent(BaseModel):
    """조 내용"""
    article_no: int = Field(description="조 번호")
    title: str = Field(description="조 제목")
    text: str = Field(description="조 전체 텍스트 (제N조(제목) 형식)")
    content: List[str] = Field(description="조 내용 (항 단위 리스트)")


class HybridSearchData(BaseModel):
    """하이브리드 검색 결과"""
    results: Dict[str, List[ArticleContent]] = Field(
        description="주제별 검색 결과 {topic_name: [articles]}"
    )
    total_topics: int = Field(description="검색한 주제 개수")
    total_articles: int = Field(description="찾은 총 조 개수")


class HybridSearchToolResult(ToolResult):
    """HybridSearchTool 실행 결과"""
    tool_name: str = "hybrid_search"
    data: Optional[HybridSearchData] = None


# ============================================
# 2. ArticleIndexTool 응답 스키마
# ============================================
class ArticleIndexData(BaseModel):
    """조 번호 조회 결과"""
    matched_articles: List[ArticleContent] = Field(description="매칭된 조 목록")
    total_matched: int = Field(description="매칭된 조 개수")


class ArticleIndexToolResult(ToolResult):
    """ArticleIndexTool 실행 결과"""
    tool_name: str = "get_article_by_index"
    data: Optional[ArticleIndexData] = None


# ============================================
# 3. ArticleTitleTool 응답 스키마
# ============================================
class ArticleTitleData(BaseModel):
    """조 제목 조회 결과"""
    matched_articles: List[ArticleContent] = Field(description="매칭된 조 목록")
    total_matched: int = Field(description="매칭된 조 개수")
    search_title: str = Field(description="검색한 제목")


class ArticleTitleToolResult(ToolResult):
    """ArticleTitleTool 실행 결과"""
    tool_name: str = "get_article_by_title"
    data: Optional[ArticleTitleData] = None


# ============================================
# 5. StandardContractTool 응답 스키마
# ============================================
class StandardArticle(BaseModel):
    """표준계약서 조"""
    parent_id: str = Field(description="조 ID (예: '제5조', '별지1')")
    title: str = Field(description="조 제목")
    chunks: List[str] = Field(description="조 내용 (text_raw 리스트, 순서대로)")


class StandardContractData(BaseModel):
    """표준계약서 조회 결과"""
    method: str = Field(description="조회 방식 (matching_based | topic_based)")
    standard_articles: List[StandardArticle] = Field(description="표준계약서 조 목록")
    total_found: int = Field(description="찾은 조 개수")
    usage_note: str = Field(
        default="표준계약서는 참고용 모범 템플릿입니다. 계약 당사자의 목적과 상황에 따라 조정이 필요할 수 있습니다.",
        description="사용 시 주의사항"
    )
    # 조회 방식별 추가 정보
    topic: Optional[str] = Field(None, description="검색 주제 (topic_based인 경우)")
    user_article_numbers: Optional[List[int]] = Field(None, description="사용자 조 번호 (matching_based인 경우)")


class StandardContractToolResult(ToolResult):
    """StandardContractTool 실행 결과"""
    tool_name: str = "lookup_standard_contract"
    data: Optional[StandardContractData] = None


# ============================================
# 툴 결과 타입 유니온
# ============================================
ToolResultType = Union[
    HybridSearchToolResult,
    ArticleIndexToolResult,
    ArticleTitleToolResult,
    StandardContractToolResult,
    ToolResult  # 폴백용
]


# ============================================
# 툴 결과 검증 헬퍼
# ============================================
class ToolResultValidator:
    """툴 결과 검증 헬퍼"""
    
    @staticmethod
    def validate_and_cast(
        result: ToolResult,
        expected_type: type
    ) -> Optional[ToolResult]:
        """타입 검증 및 캐스팅"""
        if not isinstance(result, expected_type):
            import logging
            logger = logging.getLogger(__name__)
            logger.warning(
                f"예상 타입 불일치: {type(result)} != {expected_type}"
            )
            return None
        
        if not result.success or not result.data:
            return None
        
        return result
    
    @staticmethod
    def safe_get_articles(
        result: ToolResultType
    ) -> List[ArticleContent]:
        """안전하게 조 목록 추출"""
        if isinstance(result, HybridSearchToolResult):
            articles = []
            if result.data:
                for topic_articles in result.data.results.values():
                    articles.extend(topic_articles)
            return articles
        
        elif isinstance(result, (ArticleIndexToolResult, ArticleTitleToolResult)):
            if result.data:
                return result.data.matched_articles
            return []
        
        else:
            return []


# ============================================
# ChatbotResponse (API 응답)
# ============================================
class ChatbotResponse(BaseModel):
    """챗봇 응답"""
    success: bool = Field(description="성공 여부")
    message: str = Field(description="응답 메시지")
    sources: List[Dict[str, Any]] = Field(default_factory=list, description="출처 목록")
    session_id: Optional[str] = Field(None, description="세션 ID")
    error: Optional[str] = Field(None, description="에러 메시지")
    metadata: Optional[Dict[str, Any]] = Field(None, description="추가 메타데이터")


# ============================================
# ValidationResult (검증 결과)
# ============================================
class ValidationResult(BaseModel):
    """검증 결과"""
    is_valid: bool = Field(description="검증 통과 여부")
    reason: Optional[str] = Field(None, description="검증 실패 이유")
    confidence: Optional[float] = Field(None, description="신뢰도 (0.0-1.0)")
    method: Optional[str] = Field(None, description="검증 방법 (rule_based, llm 등)")


# ============================================
# ToolPlan (도구 실행 계획)
# ============================================
class ToolPlan(BaseModel):
    """도구 실행 계획"""
    intent: str = Field(description="질문 의도 (조회, 비교, 검색 등)")
    topics: List[Dict[str, Any]] = Field(
        description="주제별 도구 실행 계획",
        default_factory=list
    )
    
    class Config:
        arbitrary_types_allowed = True


# ============================================
# AgentState 및 관련 모델
# ============================================
from typing import TypedDict


class DecisionLog(BaseModel):
    """의사결정 로그"""
    step: str = Field(description="단계 (tool_needed_check, planning, evaluation 등)")
    reasoning: str = Field(description="판단 근거")
    action: str = Field(description="수행한 행동")
    confidence: Optional[float] = Field(None, description="신뢰도 (0.0-1.0)")
    timestamp: str = Field(description="ISO 형식 타임스탬프")
    method: Optional[str] = Field(None, description="사용한 방법 (rule_based, llm 등)")


class CollectedInfo(BaseModel):
    """수집된 정보"""
    source: str = Field(description="툴 이름")
    content: Any = Field(description="실제 내용")
    relevance: float = Field(description="관련성 점수 (0.0-1.0)")
    timestamp: str = Field(description="수집 시각 (ISO 형식)")
    article_refs: List[str] = Field(default_factory=list, description="참조된 조 목록")


class AgentState(TypedDict, total=False):
    """에이전트 상태 (LangGraph State)"""
    # 입력
    contract_id: str
    user_message: str
    session_id: str
    
    # 대화 히스토리 (plain dict 사용)
    messages: List[Dict[str, str]]  # [{"role": "user"|"assistant", "content": str}]
    
    # 이전 대화 컨텍스트 필요 여부
    need_previous_context: bool  # 이전 대화가 현재 질문 답변에 필요한지
    
    # 계약서 구조 정보
    contract_structure: Optional[Dict[str, Any]]  # {articles: [...], exhibits: [...]}
    
    # 툴 실행 이력
    tool_history: List[Dict[str, Any]]  # [{tool: str, args: dict, result: Any, timestamp: str}]
    
    # 수집된 정보
    collected_info: List[Dict[str, Any]]  # CollectedInfo의 dict 형태
    
    # 탐색 상태
    explored_articles: List[str]  # 이미 탐색한 조 목록
    unexplored_articles: List[str]  # 미탐색 조 목록
    
    # 반복 제어
    iteration_count: int
    max_iterations: int
    
    # 의사결정 로그
    decision_log: List[Dict[str, Any]]  # DecisionLog의 dict 형태
    
    # 다음 실행할 툴 정보 (여러 개 가능)
    next_tools: List[Dict[str, Any]]  # [{tool: str, args: dict, reasoning: str, tool_call_id: str}, ...]
    
    # 평가 결과
    missing_info: Optional[str]  # 부족한 정보 (evaluate_sufficiency에서 설정)
    
    # 최종 출력
    final_response: Optional[str]
    sources: List[Dict[str, Any]]
