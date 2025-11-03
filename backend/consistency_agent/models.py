"""
데이터 모델 정의
A3 노드(Content Analysis)의 분석 결과 구조
"""

from dataclasses import dataclass, field
from datetime import datetime
from typing import List, Dict, Any, Optional


@dataclass
class ArticleAnalysis:
    """단일 조항 분석 결과"""

    # 사용자 조항 정보
    user_article_no: int
    user_article_title: str

    # 매칭 정보
    matched: bool
    similarity: float  # 첫 번째 매칭 조의 유사도 (UI 표시용)
    std_article_id: Optional[str] = None  # 첫 번째 매칭 조 ID (UI 표시용, 예: "제5조")
    std_article_title: Optional[str] = None  # 첫 번째 매칭 조 제목 (UI 표시용)
    is_special: bool = False

    # 매칭된 모든 조 (정렬됨: 하위항목 개수 → 유사도 → 조 번호 순)
    matched_articles: List[Dict[str, Any]] = field(default_factory=list)

    # A1 노드의 상세 매칭 정보 (하위항목별 점수 포함)
    matched_articles_details: List[Dict[str, Any]] = field(default_factory=list)

    # 하위항목별 검색 결과
    sub_item_results: List[Dict[str, Any]] = field(default_factory=list)

    # 제안
    suggestions: List[Dict[str, Any]] = field(default_factory=list)

    # 메타데이터
    reasoning: str = ""
    analysis_timestamp: Optional[datetime] = None

    def to_dict(self) -> Dict[str, Any]:
        """딕셔너리로 변환"""
        return {
            "user_article_no": self.user_article_no,
            "user_article_title": self.user_article_title,
            "matched": self.matched,
            "similarity": self.similarity,
            "std_article_id": self.std_article_id,
            "std_article_title": self.std_article_title,
            "is_special": self.is_special,
            "matched_articles": self.matched_articles,
            "matched_articles_details": self.matched_articles_details,
            "sub_item_results": self.sub_item_results,
            "suggestions": self.suggestions,
            "reasoning": self.reasoning,
            "analysis_timestamp": self.analysis_timestamp.isoformat() if self.analysis_timestamp else None
        }


@dataclass
class ContentAnalysisResult:
    """전체 계약서 분석 결과"""
    
    contract_id: str
    contract_type: str
    
    # 조항별 분석
    article_analysis: List[ArticleAnalysis] = field(default_factory=list)
    
    # 통계
    total_articles: int = 0
    analyzed_articles: int = 0
    special_articles: int = 0
    
    # 메타데이터
    analysis_timestamp: Optional[datetime] = None
    processing_time: float = 0.0
    
    def to_dict(self) -> Dict[str, Any]:
        """딕셔너리로 변환"""
        return {
            "contract_id": self.contract_id,
            "contract_type": self.contract_type,
            "article_analysis": [a.to_dict() for a in self.article_analysis],
            "total_articles": self.total_articles,
            "analyzed_articles": self.analyzed_articles,
            "special_articles": self.special_articles,
            "analysis_timestamp": self.analysis_timestamp.isoformat() if self.analysis_timestamp else None,
            "processing_time": self.processing_time
        }
