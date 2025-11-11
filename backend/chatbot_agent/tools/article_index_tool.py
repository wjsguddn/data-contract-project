"""
ArticleIndexTool - 조 인덱스 기반 접근 도구

사용자가 조 번호나 별지 번호를 명시한 경우 사용합니다.
"""

import logging
from typing import Dict, Any, List, Optional
from backend.chatbot_agent.tools.base import BaseTool
from backend.chatbot_agent.models import ToolResult
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
    ) -> ToolResult:
        """
        조 인덱스로 DB 직접 조회
        
        Args:
            contract_id: 계약서 ID
            article_numbers: 조 번호 목록
            exhibit_numbers: 별지 번호 목록
            
        Returns:
            ToolResult: 조회 결과
        """
        try:
            if not article_numbers and not exhibit_numbers:
                return ToolResult(
                    success=False,
                    tool_name=self.name,
                    data=None,
                    error="조 번호 또는 별지 번호가 필요합니다"
                )
            
            logger.info(f"조 인덱스 조회: {contract_id}, 조={article_numbers}, 별지={exhibit_numbers}")
            
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
            results = {
                "matched_articles": [],
                "failed_articles": [],
                "matched_exhibits": [],
                "failed_exhibits": []
            }
            
            # 조 번호 조회
            if article_numbers:
                articles = parsed_data.get("articles", [])
                
                for article_no in article_numbers:
                    found = False
                    
                    for article in articles:
                        if article.get("number") == article_no:
                            results["matched_articles"].append({
                                "article_no": article_no,
                                "article_id": article.get("article_id"),
                                "title": article.get("title", ""),
                                "text": article.get("text", ""),
                                "content": article.get("content", [])
                            })
                            found = True
                            break
                    
                    if not found:
                        results["failed_articles"].append({
                            "article_no": article_no,
                            "reason": "조항을 찾을 수 없습니다"
                        })
            
            # 별지 번호 조회
            if exhibit_numbers:
                exhibits = parsed_data.get("exhibits", [])
                
                for exhibit_no in exhibit_numbers:
                    found = False
                    
                    for exhibit in exhibits:
                        if exhibit.get("number") == exhibit_no:
                            results["matched_exhibits"].append({
                                "exhibit_no": exhibit_no,
                                "exhibit_id": exhibit.get("exhibit_id"),
                                "title": exhibit.get("title", ""),
                                "content": exhibit.get("content", [])
                            })
                            found = True
                            break
                    
                    if not found:
                        results["failed_exhibits"].append({
                            "exhibit_no": exhibit_no,
                            "reason": "별지를 찾을 수 없습니다"
                        })
            
            logger.info(f"조 인덱스 조회 완료: 조={len(results['matched_articles'])}개, 별지={len(results['matched_exhibits'])}개")
            
            return ToolResult(
                success=True,
                tool_name=self.name,
                data=results,
                metadata={
                    "total_matched": len(results["matched_articles"]) + len(results["matched_exhibits"]),
                    "total_failed": len(results["failed_articles"]) + len(results["failed_exhibits"])
                }
            )
        
        except Exception as e:
            logger.error(f"조 인덱스 조회 실패: {e}")
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
