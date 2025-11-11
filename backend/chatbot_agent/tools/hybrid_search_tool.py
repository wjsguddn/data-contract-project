"""
HybridSearchTool - 하이브리드 검색 도구

사용자 계약서에서 관련 조항을 검색합니다.
- FAISS (벡터 검색) + Whoosh (키워드 검색)
- 제목/본문 분리 검색
- 주제별 독립 검색
"""

import logging
from typing import Dict, Any, List
from pathlib import Path
from backend.chatbot_agent.tools.base import BaseTool
from backend.chatbot_agent.models import ToolResult
from backend.consistency_agent.hybrid_searcher import HybridSearcher
from backend.shared.services import get_knowledge_base_loader
from backend.shared.database import SessionLocal, ContractDocument
from openai import AzureOpenAI
import os

logger = logging.getLogger("uvicorn.error")


class HybridSearchTool(BaseTool):
    """
    하이브리드 검색 도구
    
    사용자 계약서에서 관련 조항을 검색합니다.
    - FAISS (벡터 검색) + Whoosh (키워드 검색)
    - 제목/본문 분리 검색
    - 주제별 독립 검색
    """
    
    def __init__(self, azure_client: AzureOpenAI):
        """
        Args:
            azure_client: Azure OpenAI 클라이언트
        """
        self.azure_client = azure_client
        self.kb_loader = get_knowledge_base_loader()
        
        # 챗봇용 가중치 설정
        self.dense_weight = 0.85  # Dense 검색 가중치
        self.text_weight = 0.8    # 본문 가중치 (제목보다 높게)
        self.title_weight = 0.2   # 제목 가중치
        
        # 챗봇용 top_k 설정
        self.top_k = 5  # 최종 반환 개수
        self.dense_top_k = 20  # Dense 검색 개수
        self.sparse_top_k = 20  # Sparse 검색 개수
        
        logger.info(f"HybridSearchTool 초기화 (Dense: {self.dense_weight}, Text: {self.text_weight})")
    
    @property
    def name(self) -> str:
        return "hybrid_search"
    
    @property
    def description(self) -> str:
        return """
        사용자 계약서에서 관련 조항을 검색합니다.
        
        사용 시기:
        - 사용자가 조 번호나 제목을 명시하지 않은 경우
        - 내용 기반으로 관련 조항을 찾아야 하는 경우
        
        입력:
        - topics: 검색할 주제 목록 (각 주제는 독립적으로 검색됨)
          - topic_name: 주제 이름
          - queries: 검색 쿼리 목록 (1-3개)
            * 동일한 쿼리로 본문과 제목을 모두 검색
            * 가중합으로 랭킹 (본문 0.8, 제목 0.2)
        
        출력:
        - 주제별로 매칭된 하위항목 목록 (조 전체가 아님)
        """
    
    def get_schema(self) -> Dict[str, Any]:
        return {
            "name": self.name,
            "description": self.description,
            "parameters": {
                "type": "object",
                "properties": {
                    "topics": {
                        "type": "array",
                        "description": "검색할 주제 목록",
                        "items": {
                            "type": "object",
                            "properties": {
                                "topic_name": {
                                    "type": "string",
                                    "description": "주제 이름"
                                },
                                "queries": {
                                    "type": "array",
                                    "description": "검색 쿼리 목록 (1-3개). 동일한 쿼리로 본문과 제목을 모두 검색합니다.",
                                    "items": {"type": "string"},
                                    "minItems": 1,
                                    "maxItems": 3
                                }
                            },
                            "required": ["topic_name", "queries"]
                        }
                    }
                },
                "required": ["topics"]
            }
        }
    
    def execute(
        self,
        contract_id: str,
        topics: List[Dict[str, Any]]
    ) -> ToolResult:
        """
        주제별 하이브리드 검색 실행
        
        Args:
            contract_id: 계약서 ID
            topics: 검색할 주제 목록
            
        Returns:
            ToolResult: 검색 결과
        """
        try:
            logger.info(f"하이브리드 검색 시작: {contract_id}, {len(topics)}개 주제")
            
            # 사용자 계약서 인덱스 로드
            searcher = self._load_user_contract_indexes(contract_id)
            if not searcher:
                return ToolResult(
                    success=False,
                    tool_name=self.name,
                    data=None,
                    error="사용자 계약서 인덱스를 로드할 수 없습니다"
                )
            
            # 주제별 검색 수행
            results_by_topic = {}
            
            for topic in topics:
                topic_name = topic.get("topic_name", "unknown")
                queries = topic.get("queries", [])
                
                if not queries:
                    logger.warning(f"주제 '{topic_name}'에 쿼리가 없습니다")
                    continue
                
                logger.info(f"주제 '{topic_name}' 검색: {len(queries)}개 쿼리")
                
                # 쿼리별 검색 결과 수집
                topic_results = []
                
                for query in queries:
                    # 하이브리드 검색 (제목/본문 분리)
                    search_results = searcher.search(
                        text_query=query,
                        title_query=query,
                        top_k=self.top_k,
                        dense_top_k=self.dense_top_k,
                        sparse_top_k=self.sparse_top_k,
                        contract_id=contract_id
                    )
                    
                    # 결과 변환 (청크 정보 + 부모 조항 정보)
                    for result in search_results:
                        chunk = result.get("chunk", {})
                        
                        # DB에서 부모 조항 정보 조회
                        parent_info = self._get_parent_article_info(
                            contract_id,
                            chunk.get("parent_id")
                        )
                        
                        topic_results.append({
                            "chunk_id": chunk.get("id"),
                            "chunk_text": chunk.get("text_norm", ""),
                            "parent_id": chunk.get("parent_id"),
                            "parent_title": parent_info.get("title", ""),
                            "score": result.get("score", 0.0),
                            "dense_score": result.get("dense_score", 0.0),
                            "sparse_score": result.get("sparse_score", 0.0)
                        })
                
                # 중복 제거 및 점수 순 정렬
                unique_results = self._deduplicate_results(topic_results)
                results_by_topic[topic_name] = unique_results[:self.top_k]
            
            logger.info(f"하이브리드 검색 완료: {len(results_by_topic)}개 주제")
            
            return ToolResult(
                success=True,
                tool_name=self.name,
                data=results_by_topic,
                metadata={
                    "total_topics": len(topics),
                    "total_results": sum(len(r) for r in results_by_topic.values())
                }
            )
        
        except Exception as e:
            logger.error(f"하이브리드 검색 실패: {e}")
            import traceback
            logger.error(traceback.format_exc())
            return ToolResult(
                success=False,
                tool_name=self.name,
                data=None,
                error=str(e)
            )
    
    def _load_user_contract_indexes(self, contract_id: str) -> HybridSearcher:
        """
        사용자 계약서 인덱스 로드
        
        Args:
            contract_id: 계약서 ID
            
        Returns:
            HybridSearcher: 하이브리드 검색기 (실패 시 None)
        """
        try:
            # 인덱스 경로
            index_base = Path("data/user_contract_indexes")
            faiss_text_path = index_base / "faiss" / f"{contract_id}_text.faiss"
            faiss_title_path = index_base / "faiss" / f"{contract_id}_title.faiss"
            whoosh_dir = index_base / "whoosh" / contract_id
            
            # 인덱스 존재 확인
            if not faiss_text_path.exists() or not faiss_title_path.exists():
                logger.error(f"FAISS 인덱스가 존재하지 않습니다: {contract_id}")
                return None
            
            if not whoosh_dir.exists():
                logger.error(f"Whoosh 인덱스가 존재하지 않습니다: {contract_id}")
                return None
            
            # 청크 메타데이터 로드 (parsed_data에서)
            chunks = self._load_chunks_from_db(contract_id)
            if not chunks:
                logger.error(f"청크 메타데이터를 로드할 수 없습니다: {contract_id}")
                return None
            
            # HybridSearcher 초기화
            searcher = HybridSearcher(
                azure_client=self.azure_client,
                dense_weight=self.dense_weight
            )
            
            # 필드 가중치 설정
            searcher.set_field_weights(text_weight=self.text_weight)
            
            # 인덱스 로드
            faiss_index_text, faiss_index_title, whoosh_indexer = self.kb_loader.load_user_contract_indexes(
                contract_id
            )
            
            searcher.load_indexes(
                faiss_index_text=faiss_index_text,
                faiss_index_title=faiss_index_title,
                chunks=chunks,
                whoosh_indexer=whoosh_indexer
            )
            
            logger.info(f"사용자 계약서 인덱스 로드 완료: {contract_id}")
            return searcher
        
        except Exception as e:
            logger.error(f"인덱스 로드 실패: {e}")
            return None
    
    def _load_chunks_from_db(self, contract_id: str) -> List[Dict[str, Any]]:
        """
        DB에서 청크 메타데이터 로드
        
        Args:
            contract_id: 계약서 ID
            
        Returns:
            청크 메타데이터 리스트
        """
        try:
            db = SessionLocal()
            contract = db.query(ContractDocument).filter(
                ContractDocument.contract_id == contract_id
            ).first()
            
            if not contract or not contract.parsed_data:
                return []
            
            # parsed_data에서 청크 생성
            chunks = []
            articles = contract.parsed_data.get("articles", [])
            
            for article in articles:
                article_id = article.get("article_id")
                article_no = article.get("number")
                title = article.get("title", "")
                content = article.get("content", [])
                
                # 조 본문 청크
                chunks.append({
                    "id": f"{article_id}_title",
                    "parent_id": f"제{article_no}조",
                    "title": title,
                    "text_norm": article.get("text", ""),
                    "unit_type": "articleText"
                })
                
                # 하위항목 청크
                for idx, sub_item in enumerate(content, 1):
                    chunks.append({
                        "id": f"{article_id}_sub_{idx}",
                        "parent_id": f"제{article_no}조",
                        "title": title,
                        "text_norm": sub_item,
                        "unit_type": "clause"
                    })
            
            return chunks
        
        except Exception as e:
            logger.error(f"청크 로드 실패: {e}")
            return []
        
        finally:
            db.close()
    
    def _get_parent_article_info(
        self,
        contract_id: str,
        parent_id: str
    ) -> Dict[str, Any]:
        """
        부모 조항 정보 조회
        
        Args:
            contract_id: 계약서 ID
            parent_id: 부모 조항 ID (예: "제5조")
            
        Returns:
            조항 정보 (title 포함)
        """
        try:
            db = SessionLocal()
            contract = db.query(ContractDocument).filter(
                ContractDocument.contract_id == contract_id
            ).first()
            
            if not contract or not contract.parsed_data:
                return {}
            
            articles = contract.parsed_data.get("articles", [])
            
            # parent_id에서 조 번호 추출 (예: "제5조" → 5)
            article_no = int(parent_id.replace("제", "").replace("조", ""))
            
            for article in articles:
                if article.get("number") == article_no:
                    return {
                        "title": article.get("title", ""),
                        "text": article.get("text", "")
                    }
            
            return {}
        
        except Exception as e:
            logger.error(f"부모 조항 정보 조회 실패: {e}")
            return {}
        
        finally:
            db.close()
    
    def _deduplicate_results(
        self,
        results: List[Dict[str, Any]]
    ) -> List[Dict[str, Any]]:
        """
        중복 제거 및 점수 순 정렬
        
        Args:
            results: 검색 결과 리스트
            
        Returns:
            중복 제거된 결과 (점수 순 정렬)
        """
        # chunk_id 기준으로 중복 제거 (최고 점수 유지)
        unique_map = {}
        
        for result in results:
            chunk_id = result.get("chunk_id")
            if chunk_id not in unique_map:
                unique_map[chunk_id] = result
            else:
                # 기존 점수와 비교하여 높은 점수 유지
                if result.get("score", 0) > unique_map[chunk_id].get("score", 0):
                    unique_map[chunk_id] = result
        
        # 점수 순 정렬
        sorted_results = sorted(
            unique_map.values(),
            key=lambda x: x.get("score", 0),
            reverse=True
        )
        
        return sorted_results
