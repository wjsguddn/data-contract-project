"""
ArticleIndexTool - 조 인덱스 기반 접근 도구

사용자가 조 번호나 별지 번호를 명시한 경우 사용합니다.
"""

import logging
import time
from typing import Dict, Any, List, Optional
from backend.chatbot_agent.tools.base import BaseTool
from backend.chatbot_agent.models import (
    ArticleIndexToolResult,
    ArticleIndexData,
    ArticleContent
)
from backend.shared.database import SessionLocal, ContractDocument

logger = logging.getLogger("uvicorn.error")


class ArticleIndexTool(BaseTool):
    """
    조 인덱스 기반 접근 도구
    
    사용자가 조 번호나 별지 번호를 명시한 경우 사용합니다.
    """
    
    @property
    def name(self) -> str:
        return "get_article_by_index"
    
    @property
    def description(self) -> str:
        return """
        조 번호나 별지 번호로 계약서 조항을 조회합니다.
        
        사용 시기:
        - 사용자가 사용자 계약서의 내용에 있어서 "2조", "제5조", "별지2" 등 명확한 "조"나 "별지"에 대한 인덱스 정보를 명시한 경우
        
        입력:
        - article_numbers: 조 번호 목록 (예: [1, 5, 10])
        - exhibit_numbers: 별지 번호 목록 (예: [1, 2])
        
        출력:
        - 조나 별지 단위로 전체 content 배열 반환
        - 매칭 실패한 경우 실패 정보 포함
        """
    
    def get_schema(self) -> Dict[str, Any]:
        return {
            "name": self.name,
            "description": self.description,
            "parameters": {
                "type": "object",
                "properties": {
                    "article_numbers": {
                        "type": "array",
                        "description": "조 번호 목록 (예: [1, 5, 10])",
                        "items": {"type": "integer"}
                    },
                    "exhibit_numbers": {
                        "type": "array",
                        "description": "별지 번호 목록 (예: [1, 2])",
                        "items": {"type": "integer"}
                    }
                }
            }
        }
    
    def execute(
        self,
        contract_id: str,
        article_numbers: Optional[List[int]] = None,
        exhibit_numbers: Optional[List[int]] = None
    ) -> ArticleIndexToolResult:
        """
        조 인덱스로 DB 직접 조회 (타입 안전)
        
        Args:
            contract_id: 계약서 ID
            article_numbers: 조 번호 목록
            exhibit_numbers: 별지 번호 목록
            
        Returns:
            ArticleIndexToolResult: 타입 안전한 조회 결과
        """
        start_time = time.time()
        
        try:
            if not article_numbers and not exhibit_numbers:
                return ArticleIndexToolResult(
                    success=False,
                    tool_name=self.name,
                    data=None,
                    error="조 번호 또는 별지 번호가 필요합니다",
                    execution_time=time.time() - start_time
                )
            
            logger.info(f"[ArticleIndexTool] 조회 시작: {contract_id}, 조={article_numbers}, 별지={exhibit_numbers}")
            
            # DB에서 계약서 로드
            db = SessionLocal()
            contract = db.query(ContractDocument).filter(
                ContractDocument.contract_id == contract_id
            ).first()
            
            if not contract or not contract.parsed_data:
                return ArticleIndexToolResult(
                    success=False,
                    tool_name=self.name,
                    data=None,
                    error="계약서를 찾을 수 없습니다",
                    execution_time=time.time() - start_time
                )
            
            parsed_data = contract.parsed_data
            matched_articles: List[ArticleContent] = []
            failed_info = {
                "failed_articles": [],
                "failed_exhibits": []
            }
            
            # 조 번호 조회
            if article_numbers:
                articles = parsed_data.get("articles", [])
                
                for article_no in article_numbers:
                    found = False
                    
                    for article in articles:
                        if article.get("number") == article_no:
                            # ArticleContent 스키마로 변환
                            matched_articles.append(ArticleContent(
                                article_no=article_no,
                                title=article.get("title", ""),
                                text=article.get("text", ""),
                                content=article.get("content", [])
                            ))
                            found = True
                            break
                    
                    if not found:
                        failed_info["failed_articles"].append({
                            "article_no": article_no,
                            "reason": "조항을 찾을 수 없습니다"
                        })
            
            # 별지 번호 조회 (ArticleContent로 통합)
            if exhibit_numbers:
                exhibits = parsed_data.get("exhibits", [])
                
                for exhibit_no in exhibit_numbers:
                    found = False
                    
                    for exhibit in exhibits:
                        if exhibit.get("number") == exhibit_no:
                            # 별지도 ArticleContent로 표현 (article_no는 음수로)
                            matched_articles.append(ArticleContent(
                                article_no=-exhibit_no,  # 별지는 음수로 구분
                                title=f"별지{exhibit_no} {exhibit.get('title', '')}",
                                text=f"별지{exhibit_no}",
                                content=exhibit.get("content", [])
                            ))
                            found = True
                            break
                    
                    if not found:
                        failed_info["failed_exhibits"].append({
                            "exhibit_no": exhibit_no,
                            "reason": "별지를 찾을 수 없습니다"
                        })
            
            # ArticleIndexData 스키마로 래핑
            result_data = ArticleIndexData(
                matched_articles=matched_articles,
                total_matched=len(matched_articles)
            )
            
            logger.info(f"조 인덱스 조회 완료: {result_data.total_matched}개 매칭")
            
            return ArticleIndexToolResult(
                success=True,
                tool_name=self.name,
                data=result_data,
                metadata=failed_info if (failed_info["failed_articles"] or failed_info["failed_exhibits"]) else None,
                execution_time=time.time() - start_time
            )
        
        except Exception as e:
            logger.error(f"조 인덱스 조회 실패: {e}")
            import traceback
            logger.error(traceback.format_exc())
            return ArticleIndexToolResult(
                success=False,
                tool_name=self.name,
                data=None,
                error=str(e),
                execution_time=time.time() - start_time
            )
        
        finally:
            db.close()
