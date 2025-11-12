"""
StructureTool - 사용자 계약서 구조 파악 툴

사용자 계약서의 조 목록과 별지 목록을 반환합니다.
"""

import logging
from typing import Optional
from langchain.tools import BaseTool
from pydantic import BaseModel, Field

from backend.shared.database import SessionLocal, ContractDocument
from backend.chatbot_agent.models import (
    StructureToolResult,
    ContractStructureData
)

logger = logging.getLogger(__name__)


class StructureToolInput(BaseModel):
    """StructureTool 입력 스키마"""
    contract_id: str = Field(description="계약서 ID")


class StructureTool(BaseTool):
    """
    사용자 계약서 구조 파악 툴
    
    계약서의 조 목록과 별지 목록을 반환합니다.
    서문(제0조)은 제외하고 실제 조항만 반환합니다.
    """
    
    name: str = "get_contract_structure"
    description: str = """
    사용자 계약서의 구조를 파악합니다.
    
    반환 정보:
    - 조 목록 (예: ['제1조(목적)', '제2조(정의)'])
    - 별지 목록 (예: ['별지1 대상데이터'])
    - 총 조 개수
    - 총 별지 개수
    
    사용 시기:
    - 계약서 전체 구조를 파악해야 할 때
    - 특정 조를 찾기 전에 어떤 조들이 있는지 확인할 때
    """
    args_schema: type[BaseModel] = StructureToolInput
    
    def _run(self, contract_id: str) -> StructureToolResult:
        """
        계약서 구조 조회
        
        Args:
            contract_id: 계약서 ID
            
        Returns:
            StructureToolResult
        """
        try:
            logger.info(f"[StructureTool] 계약서 구조 조회 시작: {contract_id}")
            
            # DB에서 계약서 조회
            db = SessionLocal()
            try:
                contract = db.query(ContractDocument).filter(
                    ContractDocument.contract_id == contract_id
                ).first()
                
                if not contract:
                    return StructureToolResult(
                        success=False,
                        tool_name=self.name,
                        error=f"계약서를 찾을 수 없습니다: {contract_id}"
                    )
                
                parsed_data = contract.parsed_data
                if not parsed_data:
                    return StructureToolResult(
                        success=False,
                        tool_name=self.name,
                        error="파싱된 데이터가 없습니다"
                    )
                
                # 조 목록 추출 (서문 제외)
                articles = parsed_data.get('articles', [])
                article_texts = []
                
                for article in articles:
                    article_no = article.get('number')
                    
                    # 서문(제0조) 제외
                    if article_no == 0:
                        continue
                    
                    title = article.get('title', '')
                    text = article.get('text', '')
                    
                    # text가 있으면 사용, 없으면 "제N조(제목)" 형식으로 생성
                    if text:
                        article_texts.append(text)
                    elif title:
                        article_texts.append(f"제{article_no}조({title})")
                    else:
                        article_texts.append(f"제{article_no}조")
                
                # 별지 목록 추출
                exhibits = parsed_data.get('exhibits', [])
                exhibit_texts = []
                
                for exhibit in exhibits:
                    exhibit_no = exhibit.get('number')
                    title = exhibit.get('title', '')
                    
                    if title:
                        exhibit_texts.append(f"별지{exhibit_no} {title}")
                    else:
                        exhibit_texts.append(f"별지{exhibit_no}")
                
                # 결과 생성
                structure_data = ContractStructureData(
                    articles=article_texts,
                    exhibits=exhibit_texts,
                    total_articles=len(article_texts),
                    total_exhibits=len(exhibit_texts)
                )
                
                logger.info(
                    f"[StructureTool] 구조 조회 완료: "
                    f"{structure_data.total_articles}개 조, "
                    f"{structure_data.total_exhibits}개 별지"
                )
                
                return StructureToolResult(
                    success=True,
                    tool_name=self.name,
                    data=structure_data
                )
                
            finally:
                db.close()
                
        except Exception as e:
            logger.error(f"[StructureTool] 오류 발생: {e}")
            import traceback
            logger.error(traceback.format_exc())
            
            return StructureToolResult(
                success=False,
                tool_name=self.name,
                error=f"계약서 구조 조회 실패: {str(e)}"
            )
    
    async def _arun(self, contract_id: str) -> StructureToolResult:
        """비동기 실행 (동기 버전 호출)"""
        return self._run(contract_id)
