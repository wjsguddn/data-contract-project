"""
ArticleTitleTool - 조 제목 기반 접근 도구

사용자가 조 제목을 명시한 경우 사용합니다.
"""

import logging
import re
from typing import Dict, Any, List
from backend.chatbot_agent.tools.base import BaseTool
from backend.chatbot_agent.models import ToolResult
from backend.shared.database import SessionLocal, ContractDocument

logger = logging.getLogger("uvicorn.error")


class ArticleTitleTool(BaseTool):
    """
    조 제목 기반 접근 도구
    
    사용자가 조 제목을 명시한 경우 사용합니다.
    """
    
    @property
    def name(self) -> str:
        return "get_article_by_title"
    
    @property
    def description(self) -> str:
        return """
        조 제목으로 계약서 조항을 조회합니다.
        
        사용 시기:
        - 사용자가 "목적 조항", "대가 및 지급조건" 등 제목을 언급한 경우
        
        입력:
        - titles: 조 제목 목록 (공백 제거 후 매칭)
        
        출력:
        - 조 단위로 전체 content 배열 반환
        - 매칭 실패한 경우 실패 정보 포함
        """
    
    def get_schema(self) -> Dict[str, Any]:
        return {
            "name": self.name,
            "description": self.description,
            "parameters": {
                "type": "object",
                "properties": {
                    "titles": {
                        "type": "array",
                        "description": "조 제목 목록 (예: ['목적', '대가 및 지급조건'])",
                        "items": {"type": "string"}
                    }
                },
                "required": ["titles"]
            }
        }
    
    def execute(
        self,
        contract_id: str,
        titles: List[str]
    ) -> ToolResult:
        """
        조 제목으로 DB 직접 조회
        
        Args:
            contract_id: 계약서 ID
            titles: 조 제목 목록
            
        Returns:
            ToolResult: 조회 결과
        """
        try:
            if not titles:
                return ToolResult(
                    success=False,
                    tool_name=self.name,
                    data=None,
                    error="조 제목이 필요합니다"
                )
            
            logger.info(f"조 제목 조회: {contract_id}, 제목={titles}")
            
            # DB에서 계약서 로드
            db = SessionLocal()
            contract = db.query(ContractDocument).filter(
                ContractDocument.contract_id == contract_id
            ).first()
            
            if not contract or not contract.parsed_data:
                return ToolResult(
                    success=False,
                    tool_name=self.name,
                    data=None,
                    error="계약서를 찾을 수 없습니다"
                )
            
            parsed_data = contract.parsed_data
            articles = parsed_data.get("articles", [])
            
            results = {
                "matched_articles": [],
                "failed_titles": []
            }
            
            # 제목별 조회
            for title_query in titles:
                # 제목 정규화 (공백 제거)
                normalized_query = self._normalize_title(title_query)
                
                found = False
                
                for article in articles:
                    article_title = article.get("title", "")
                    normalized_article_title = self._normalize_title(article_title)
                    
                    # 공백 제거 후 비교
                    if normalized_query == normalized_article_title:
                        results["matched_articles"].append({
                            "article_no": article.get("number"),
                            "article_id": article.get("article_id"),
                            "title": article_title,
                            "text": article.get("text", ""),
                            "content": article.get("content", []),
                            "matched_title": title_query
                        })
                        found = True
                        break
                    
                    # 부분 매칭 (정규화된 쿼리가 정규화된 제목에 포함되는 경우)
                    if normalized_query in normalized_article_title:
                        results["matched_articles"].append({
                            "article_no": article.get("number"),
                            "article_id": article.get("article_id"),
                            "title": article_title,
                            "text": article.get("text", ""),
                            "content": article.get("content", []),
                            "matched_title": title_query,
                            "match_type": "partial"
                        })
                        found = True
                        break
                
                if not found:
                    results["failed_titles"].append({
                        "title": title_query,
                        "reason": "제목을 찾을 수 없습니다"
                    })
            
            logger.info(f"조 제목 조회 완료: {len(results['matched_articles'])}개 매칭")
            
            return ToolResult(
                success=True,
                tool_name=self.name,
                data=results,
                metadata={
                    "total_matched": len(results["matched_articles"]),
                    "total_failed": len(results["failed_titles"])
                }
            )
        
        except Exception as e:
            logger.error(f"조 제목 조회 실패: {e}")
            import traceback
            logger.error(traceback.format_exc())
            return ToolResult(
                success=False,
                tool_name=self.name,
                data=None,
                error=str(e)
            )
        
        finally:
            db.close()
    
    def _normalize_title(self, title: str) -> str:
        """
        제목 정규화 (공백 제거)
        
        Args:
            title: 원본 제목
            
        Returns:
            정규화된 제목
        """
        # 모든 공백 제거
        normalized = re.sub(r'\s+', '', title)
        
        # 소문자 변환 (영문 포함 시)
        normalized = normalized.lower()
        
        return normalized
