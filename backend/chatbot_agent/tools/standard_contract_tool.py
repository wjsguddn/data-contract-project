"""
StandardContractTool - 표준계약서 조회 툴

사용자 조 번호 또는 주제를 기반으로 표준계약서 조문을 조회합니다.
"""

import logging
import json
from typing import List, Optional, Dict, Any
from pathlib import Path
from openai import OpenAI

from backend.chatbot_agent.tools.base import BaseTool
from backend.shared.database import SessionLocal, ContractDocument, ClassificationResult, ValidationResult
from backend.chatbot_agent.models import (
    StandardContractToolResult,
    StandardContractData,
    StandardArticle
)

logger = logging.getLogger(__name__)


class StandardContractTool(BaseTool):
    """
    표준계약서 조회 툴
    
    두 가지 조회 방식:
    1. 매칭 기반: A1 검증 결과를 활용하여 사용자 조에 대응하는 표준 조 조회
    2. 주제 기반: LLM으로 주제 관련 표준 조 선별 후 조회
    """
    
    def __init__(self, openai_client: OpenAI):
        self.openai_client = openai_client
    
    @property
    def name(self) -> str:
        return "lookup_standard_contract"
    
    @property
    def description(self) -> str:
        return """
        표준계약서 조문을 조회합니다.
        
        두 가지 조회 방식:
        1. 매칭 기반 조회 (user_article_numbers 제공 시):
           - A1 검증 결과를 활용하여 사용자 조에 대응하는 표준 조 조회
           - 예: user_article_numbers=[3, 5] → 제3조, 제5조에 매칭된 표준 조 반환
        
        2. 주제 기반 조회 (topic 제공 시):
           - LLM으로 주제 관련 표준 조 선별 후 조회
           - 예: topic="데이터 보안" → 보안 관련 표준 조 반환
        
        반환 정보:
        - 표준계약서 조문 전체 텍스트
        - 조 ID, 제목, 청크 정보
        - 사용 시 주의사항
        
        사용 시기:
        - 사용자 계약서와 표준계약서를 비교해야 할 때
        - 표준계약서의 권장 사항을 확인해야 할 때
        """
    
    def get_schema(self) -> Dict[str, Any]:
        return {
            "name": self.name,
            "description": self.description,
            "parameters": {
                "type": "object",
                "properties": {
                    "user_article_numbers": {
                        "type": "array",
                        "description": "사용자 조 번호 리스트 (매칭 기반 조회 시 사용)",
                        "items": {"type": "integer"}
                    },
                    "topic": {
                        "type": "string",
                        "description": "검색 주제 (주제 기반 조회 시 사용)"
                    }
                }
            }
        }
    
    def execute(
        self,
        contract_id: str,
        user_article_numbers: Optional[List[int]] = None,
        topic: Optional[str] = None
    ) -> StandardContractToolResult:
        """
        표준계약서 조회
        
        Args:
            contract_id: 계약서 ID
            user_article_numbers: 사용자 조 번호 리스트 (매칭 기반)
            topic: 검색 주제 (주제 기반)
            
        Returns:
            StandardContractToolResult
        """
        try:
            logger.info(
                f"[StandardContractTool] 조회 시작: contract_id={contract_id}, "
                f"user_articles={user_article_numbers}, topic={topic}"
            )
            
            # 계약 유형 조회
            contract_type = self._get_contract_type(contract_id)
            if not contract_type:
                return StandardContractToolResult(
                    success=False,
                    tool_name=self.name,
                    error="계약 유형을 찾을 수 없습니다"
                )
            
            # 조회 방식 결정
            if user_article_numbers:
                # 매칭 기반 조회
                return self._lookup_by_matching(contract_id, user_article_numbers, contract_type)
            elif topic:
                # 주제 기반 조회
                return self._lookup_by_topic(topic, contract_type)
            else:
                return StandardContractToolResult(
                    success=False,
                    tool_name=self.name,
                    error="user_article_numbers 또는 topic 중 하나를 제공해야 합니다"
                )
                
        except Exception as e:
            logger.error(f"[StandardContractTool] 오류 발생: {e}")
            import traceback
            logger.error(traceback.format_exc())
            
            return StandardContractToolResult(
                success=False,
                tool_name=self.name,
                error=f"표준계약서 조회 실패: {str(e)}"
            )
    
    def _get_contract_type(self, contract_id: str) -> Optional[str]:
        """계약 유형 조회"""
        db = SessionLocal()
        try:
            classification = db.query(ClassificationResult).filter(
                ClassificationResult.contract_id == contract_id
            ).first()
            
            if not classification:
                return None
            
            return classification.confirmed_type or classification.predicted_type
            
        finally:
            db.close()
    
    def _lookup_by_matching(
        self,
        contract_id: str,
        user_article_numbers: List[int],
        contract_type: str
    ) -> StandardContractToolResult:
        """
        매칭 기반 조회
        
        A1 검증 결과에서 사용자 조에 매칭된 표준 조를 찾아 반환
        """
        logger.info(f"[StandardContractTool] 매칭 기반 조회: {user_article_numbers}")
        
        # A1 매칭 결과 로드
        db = SessionLocal()
        try:
            validation = db.query(ValidationResult).filter(
                ValidationResult.contract_id == contract_id
            ).first()
            
            if not validation or not validation.completeness_check:
                return StandardContractToolResult(
                    success=False,
                    tool_name=self.name,
                    error="A1 검증 결과를 찾을 수 없습니다"
                )
            
            matching_details = validation.completeness_check.get('matching_details', [])
            
            # 사용자 조 번호로 표준 조 parent_id 추출
            standard_parent_ids = set()
            
            for detail in matching_details:
                user_no = detail.get('user_article_no')
                if user_no in user_article_numbers:
                    matched_articles = detail.get('matched_articles', [])
                    standard_parent_ids.update(matched_articles)
            
            if not standard_parent_ids:
                return StandardContractToolResult(
                    success=True,
                    tool_name=self.name,
                    data=StandardContractData(
                        method="matching_based",
                        standard_articles=[],
                        total_found=0,
                        user_article_numbers=user_article_numbers
                    )
                )
            
            # 표준 조문 로드
            standard_articles = self._load_std_articles(
                list(standard_parent_ids),
                contract_type
            )
            
            return StandardContractToolResult(
                success=True,
                tool_name=self.name,
                data=StandardContractData(
                    method="matching_based",
                    standard_articles=standard_articles,
                    total_found=len(standard_articles),
                    user_article_numbers=user_article_numbers
                )
            )
            
        finally:
            db.close()
    
    def _lookup_by_topic(
        self,
        topic: str,
        contract_type: str
    ) -> StandardContractToolResult:
        """
        주제 기반 조회
        
        LLM으로 주제 관련 표준 조를 선별한 후 조회
        """
        logger.info(f"[StandardContractTool] 주제 기반 조회: {topic}")
        
        # 표준계약서 구조 로드
        structured_path = Path(f"data/extracted_documents/{contract_type}_std_contract_structured.json")
        
        if not structured_path.exists():
            return StandardContractToolResult(
                success=False,
                tool_name=self.name,
                error=f"표준계약서 구조 파일을 찾을 수 없습니다: {structured_path}"
            )
        
        with open(structured_path, 'r', encoding='utf-8') as f:
            structured_data = json.load(f)
        
        # 조와 별지 목록 생성
        articles_list = []
        for article in structured_data.get('articles', []):
            parent_id = article.get('parent_id', '')
            title = article.get('title', '')
            articles_list.append(f"{parent_id} ({title})")
        
        for exhibit in structured_data.get('exhibits', []):
            parent_id = exhibit.get('parent_id', '')
            title = exhibit.get('title', '')
            articles_list.append(f"{parent_id} ({title})")
        
        # LLM으로 관련 조 선별
        selected_parent_ids = self._select_relevant_articles(topic, articles_list)
        
        if not selected_parent_ids:
            return StandardContractToolResult(
                success=True,
                tool_name=self.name,
                data=StandardContractData(
                    method="topic_based",
                    standard_articles=[],
                    total_found=0,
                    topic=topic
                )
            )
        
        # 표준 조문 로드
        standard_articles = self._load_std_articles(selected_parent_ids, contract_type)
        
        return StandardContractToolResult(
            success=True,
            tool_name=self.name,
            data=StandardContractData(
                method="topic_based",
                standard_articles=standard_articles,
                total_found=len(standard_articles),
                topic=topic
            )
        )
    
    def _select_relevant_articles(
        self,
        topic: str,
        articles_list: List[str]
    ) -> List[str]:
        """
        LLM으로 주제 관련 조 선별
        
        Args:
            topic: 검색 주제
            articles_list: 조 목록 (예: ["제1조 (목적)", "제2조 (정의)"])
            
        Returns:
            선별된 parent_id 리스트 (예: ["제1조", "제2조"])
        """
        articles_text = "\n".join([f"- {article}" for article in articles_list])
        
        system_msg = "당신은 계약서 조항 분석 전문가입니다. JSON 형식으로만 응답하세요."
        
        user_prompt = f"""다음은 표준계약서의 조 목록입니다:

{articles_text}

주제: "{topic}"

위 주제와 관련된 조를 모두 선택하세요.
관련성이 높은 조부터 낮은 조 순으로 최대 5개까지 선택합니다.

응답 형식 (JSON):
{{
    "selected_articles": ["제1조", "제3조", ...]
}}

JSON만 응답하세요."""
        
        # 프롬프트 로깅
        logger.info("=" * 80)
        logger.info("[StandardContractTool] 표준계약서 조항 선별 LLM 호출")
        logger.info("=" * 80)
        logger.info(f"[SYSTEM]\n{system_msg}")
        logger.info("-" * 80)
        logger.info(f"[USER]\n{user_prompt}")
        logger.info("=" * 80)
        
        try:
            response = self.openai_client.chat.completions.create(
                model="gpt-4o",
                messages=[
                    {
                        "role": "system",
                        "content": system_msg
                    },
                    {
                        "role": "user",
                        "content": user_prompt
                    }
                ],
                temperature=0.2,
                max_tokens=500,
                response_format={"type": "json_object"}
            )
            
            response_text = response.choices[0].message.content.strip()
            
            # 응답 로깅
            logger.info("=" * 80)
            logger.info("[StandardContractTool] LLM 응답")
            logger.info("=" * 80)
            logger.info(response_text)
            logger.info("=" * 80)
            
            data = json.loads(response_text)
            
            selected = data.get('selected_articles', [])
            logger.info(f"[StandardContractTool] 선별된 조항: {selected} ({len(selected)}개)")
            
            return selected
            
        except Exception as e:
            logger.error(f"[StandardContractTool] LLM 선별 실패: {e}")
            import traceback
            logger.error(traceback.format_exc())
            return []
    
    def _load_std_articles(
        self,
        parent_ids: List[str],
        contract_type: str
    ) -> List[StandardArticle]:
        """
        표준 조문 로드
        
        Args:
            parent_ids: 조 ID 리스트 (예: ["제1조", "제2조"])
            contract_type: 계약 유형
            
        Returns:
            StandardArticle 리스트
        """
        chunks_path = Path(f"data/chunked_documents/{contract_type}_std_contract_chunks.json")
        
        if not chunks_path.exists():
            logger.error(f"청크 파일을 찾을 수 없습니다: {chunks_path}")
            return []
        
        with open(chunks_path, 'r', encoding='utf-8') as f:
            all_chunks = json.load(f)
        
        # parent_id별로 청크 그룹화
        articles_dict: Dict[str, Dict[str, Any]] = {}
        
        for chunk in all_chunks:
            parent_id = chunk.get('parent_id')
            if parent_id not in parent_ids:
                continue
            
            if parent_id not in articles_dict:
                articles_dict[parent_id] = {
                    'parent_id': parent_id,
                    'title': chunk.get('title', ''),
                    'chunks': []
                }
            
            articles_dict[parent_id]['chunks'].append(chunk)
        
        # StandardArticle 객체 생성
        standard_articles = []
        
        for parent_id in parent_ids:
            if parent_id not in articles_dict:
                continue
            
            article_data = articles_dict[parent_id]
            chunks = article_data['chunks']
            
            # 청크를 order_index로 정렬
            chunks.sort(key=lambda c: c.get('order_index', 0))
            
            # text_raw 리스트 생성 (순서대로)
            text_raw_list = []
            for chunk in chunks:
                text_raw = chunk.get('text_raw', '').strip()
                if text_raw:
                    text_raw_list.append(text_raw)
            
            standard_articles.append(
                StandardArticle(
                    parent_id=parent_id,
                    title=article_data['title'],
                    chunks=text_raw_list
                )
            )
        
        logger.info(f"[StandardContractTool] 표준 조문 로드 완료: {len(standard_articles)}개")
        
        return standard_articles
