"""
HybridSearchTool - 하이브리드 검색 도구

사용자 계약서에서 관련 조항을 검색합니다.
- FAISS (벡터 검색) + Whoosh (키워드 검색)
- 제목/본문 분리 검색
- 주제별 독립 검색
- LLM 기반 청크 필터링
- 조 단위 반환
"""

import logging
import json
from typing import Dict, Any, List, Optional
from pathlib import Path
from backend.chatbot_agent.tools.base import BaseTool
from backend.chatbot_agent.models import (
    HybridSearchToolResult,
    HybridSearchData,
    ArticleContent
)
from backend.consistency_agent.hybrid_searcher import HybridSearcher
from backend.shared.services import get_knowledge_base_loader
from backend.shared.database import SessionLocal, ContractDocument
from openai import OpenAI
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
    
    def __init__(self, openai_client: OpenAI):
        """
        Args:
            openai_client: OpenAI 클라이언트
        """
        self.openai_client = openai_client
        self.kb_loader = get_knowledge_base_loader()
        
        # 챗봇용 가중치 설정
        self.dense_weight = 0.85  # Dense 검색 가중치 (RRF에서는 미사용)
        self.text_weight = 0.6    # 본문 가중치
        self.title_weight = 0.4   # 제목 가중치
        
        # 챗봇용 top_k 설정
        self.top_k = 5  # 최종 반환 개수
        self.dense_top_k = 20  # Dense 검색 개수
        self.sparse_top_k = 20  # Sparse 검색 개수
        
        # 인덱스 캐시 (계약서별)
        self._searcher_cache = {}
        
        logger.info(f"HybridSearchTool 초기화 (RRF 모드, 본문:제목 = {self.text_weight}:{self.title_weight})")
    
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
    ) -> HybridSearchToolResult:
        """
        주제별 하이브리드 검색 실행 (LLM 필터링 + 조 단위 반환)
        
        Args:
            contract_id: 계약서 ID
            topics: 검색할 주제 목록
            
        Returns:
            HybridSearchToolResult: 조 단위 검색 결과
        """
        try:
            logger.info(f"[HybridSearchTool] 검색 시작: {contract_id}, {len(topics)}개 주제")
            
            # 사용자 계약서 인덱스 로드 (캐시 사용)
            if contract_id in self._searcher_cache:
                searcher = self._searcher_cache[contract_id]
                logger.debug(f"인덱스 캐시 히트: {contract_id}")
            else:
                searcher = self._load_user_contract_indexes(contract_id)
                if not searcher:
                    return HybridSearchToolResult(
                        success=False,
                        tool_name=self.name,
                        error="사용자 계약서 인덱스를 로드할 수 없습니다"
                    )
                self._searcher_cache[contract_id] = searcher
                logger.info(f"인덱스 캐시 저장: {contract_id}")
            
            # 주제별 검색 수행
            results_by_topic = {}
            
            for topic in topics:
                topic_name = topic.get("topic_name", "unknown")
                queries = topic.get("queries", [])
                
                if not queries:
                    logger.warning(f"주제 '{topic_name}'에 쿼리가 없습니다")
                    continue
                
                logger.info(f"[HybridSearchTool] 주제 '{topic_name}' 검색: {len(queries)}개 쿼리")
                
                # 쿼리별 검색 결과 수집
                all_chunks = []
                
                for query_idx, query in enumerate(queries, 1):
                    logger.info(f"  쿼리 {query_idx}/{len(queries)}: '{query[:50]}...'")
                    
                    # 하이브리드 검색 (top-5 청크)
                    search_results = searcher.search(
                        text_query=query,
                        title_query=query,
                        top_k=self.top_k,
                        dense_top_k=self.dense_top_k,
                        sparse_top_k=self.sparse_top_k,
                        contract_id=contract_id
                    )
                    
                    if search_results:
                        logger.info(f"    → {len(search_results)}개 청크 매칭")
                        all_chunks.extend(search_results)
                    else:
                        logger.warning(f"    → 매칭 결과 없음")
                
                if not all_chunks:
                    logger.warning(f"주제 '{topic_name}'에 대한 검색 결과 없음")
                    results_by_topic[topic_name] = []
                    continue
                
                # LLM 필터링 (관련성 판별)
                filtered_chunks = self._filter_relevant_chunks(
                    topic_name,
                    queries,
                    all_chunks,
                    contract_id
                )
                
                # 조 단위로 변환
                articles = self._convert_to_articles(
                    filtered_chunks,
                    contract_id
                )
                
                results_by_topic[topic_name] = articles
                
                logger.info(
                    f"[HybridSearchTool] 주제 '{topic_name}' 완료: "
                    f"{len(all_chunks)}개 청크 → LLM 필터링 {len(filtered_chunks)}개 → "
                    f"조 단위 변환 {len(articles)}개"
                )
            
            # HybridSearchData 생성
            search_data = HybridSearchData(
                results=results_by_topic,
                total_topics=len(topics),
                total_articles=sum(len(articles) for articles in results_by_topic.values())
            )
            
            logger.info(
                f"[HybridSearchTool] 검색 완료: {search_data.total_topics}개 주제, "
                f"{search_data.total_articles}개 조"
            )
            
            return HybridSearchToolResult(
                success=True,
                tool_name=self.name,
                data=search_data
            )
        
        except Exception as e:
            logger.error(f"[HybridSearchTool] 검색 실패: {e}")
            import traceback
            logger.error(traceback.format_exc())
            
            return HybridSearchToolResult(
                success=False,
                tool_name=self.name,
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
            
            # mapping.json 로드
            mapping = self._load_mapping(contract_id)
            if not mapping:
                logger.warning(f"mapping.json을 로드할 수 없습니다: {contract_id}")
                # mapping 없이도 동작하도록 (하위 호환성)
            
            # HybridSearcher 초기화 (RRF 사용)
            searcher = HybridSearcher(
                azure_client=self.openai_client,
                dense_weight=self.dense_weight,  # RRF에서는 사용 안 함
                fusion_method="rrf"  # 챗봇은 RRF 사용
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
            
            # mapping 설정
            if mapping:
                searcher.set_mapping(mapping)
            
            logger.info(f"사용자 계약서 인덱스 로드 완료 (RRF 모드): {contract_id}")
            return searcher
        
        except Exception as e:
            logger.error(f"인덱스 로드 실패: {e}")
            return None
    
    def _load_mapping(self, contract_id: str) -> Optional[List[Dict[str, Any]]]:
        """
        mapping.json 로드
        
        Args:
            contract_id: 계약서 ID
            
        Returns:
            mapping 리스트 또는 None
        """
        try:
            import json
            mapping_path = Path("data/user_contract_indexes/faiss") / f"{contract_id}_mapping.json"
            
            if not mapping_path.exists():
                logger.warning(f"mapping 파일이 존재하지 않습니다: {mapping_path}")
                return None
            
            with open(mapping_path, 'r', encoding='utf-8') as f:
                mapping = json.load(f)
            
            logger.info(f"mapping 로드 완료: {len(mapping)}개 항목")
            return mapping
        
        except Exception as e:
            logger.error(f"mapping 로드 실패: {e}")
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

                # 조 본문 청크 (Whoosh 인덱스와 동일한 형식으로 변경)
                chunks.append({
                    "id": f"제{article_no}조",  # 변경: article_id_title → 제N조
                    "parent_id": f"제{article_no}조",
                    "title": title,
                    "text_norm": article.get("text", ""),
                    "unit_type": "articleTitle"  # 변경: articleText → articleTitle
                })

                # 하위항목 청크 (Whoosh 인덱스와 동일한 형식으로 변경)
                for idx, sub_item in enumerate(content, 1):
                    chunks.append({
                        "id": f"제{article_no}조 내용{idx}",  # 변경: article_id_sub_idx → 제N조 내용M
                        "parent_id": f"제{article_no}조",
                        "title": title,
                        "text_norm": sub_item,
                        "unit_type": "articleContent"  # 변경: clause → articleContent
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
    
    def _filter_relevant_chunks(
        self,
        topic_name: str,
        queries: List[str],
        chunks: List[Dict[str, Any]],
        contract_id: str
    ) -> List[Dict[str, Any]]:
        """
        LLM으로 관련 청크 필터링
        
        Args:
            topic_name: 주제 이름
            queries: 검색 쿼리 리스트
            chunks: 검색된 청크 리스트
            contract_id: 계약서 ID
            
        Returns:
            필터링된 청크 리스트
        """
        if not chunks:
            return []
        
        # 중복 제거 (chunk_id 기준)
        unique_chunks = {}
        for chunk in chunks:
            chunk_obj = chunk.get("chunk", {})
            chunk_id = chunk_obj.get("id")
            if chunk_id not in unique_chunks:
                unique_chunks[chunk_id] = chunk
            elif chunk.get("score", 0) > unique_chunks[chunk_id].get("score", 0):
                unique_chunks[chunk_id] = chunk
        
        chunks = list(unique_chunks.values())
        
        # Top-5만 LLM 필터링
        top_chunks = sorted(chunks, key=lambda x: x.get("score", 0), reverse=True)[:5]
        
        # 청크 정보 포맷팅
        chunks_info = []
        for idx, chunk_data in enumerate(top_chunks):
            chunk = chunk_data.get("chunk", {})
            parent_id = chunk.get("parent_id", "")
            
            # 부모 조항 정보 조회
            parent_info = self._get_parent_article_info(contract_id, parent_id)
            
            chunks_info.append({
                "index": idx,
                "chunk_id": chunk.get("id", ""),
                "chunk_text": chunk.get("text_norm", ""),
                "parent_id": parent_id,
                "parent_title": parent_info.get("title", ""),
                "score": chunk_data.get("score", 0.0)
            })
        
        # LLM 프롬프트
        chunks_text = "\n\n".join([
            f"[{c['index']}] {c['parent_id']} ({c['parent_title']})\n{c['chunk_text']}"
            for c in chunks_info
        ])
        
        queries_text = "\n".join([f"- {q}" for q in queries])
        
        prompt = f"""다음은 "{topic_name}" 주제로 검색된 계약서 청크들입니다.

검색 쿼리:
{queries_text}

검색 결과:
{chunks_text}

각 청크가 주제와 실제로 관련있는지 판단하세요.
관련있는 청크의 인덱스만 선택합니다.

응답 형식 (JSON):
{{
    "relevant_indices": [0, 2, 3, ...]
}}

JSON만 응답하세요."""
        
        try:
            response = self.openai_client.chat.completions.create(
                model="gpt-4o",
                messages=[
                    {
                        "role": "system",
                        "content": "당신은 계약서 내용 분석 전문가입니다. JSON 형식으로만 응답하세요."
                    },
                    {
                        "role": "user",
                        "content": prompt
                    }
                ],
                temperature=0.2,
                max_tokens=300,
                response_format={"type": "json_object"}
            )
            
            response_text = response.choices[0].message.content.strip()
            data = json.loads(response_text)
            
            relevant_indices = data.get("relevant_indices", [])
            
            # 필터링된 청크 반환
            filtered = [top_chunks[i] for i in relevant_indices if 0 <= i < len(top_chunks)]
            
            logger.info(
                f"  LLM 필터링: {len(top_chunks)}개 → {len(filtered)}개 "
                f"(선택: {relevant_indices})"
            )
            
            return filtered
            
        except Exception as e:
            logger.error(f"  LLM 필터링 실패: {e}, 전체 반환")
            return top_chunks
    
    def _convert_to_articles(
        self,
        chunks: List[Dict[str, Any]],
        contract_id: str
    ) -> List[ArticleContent]:
        """
        청크를 조 단위로 변환
        
        Args:
            chunks: 청크 리스트
            contract_id: 계약서 ID
            
        Returns:
            ArticleContent 리스트
        """
        if not chunks:
            return []
        
        # parent_id 추출 및 중복 제거
        parent_ids = list(set([
            chunk.get("chunk", {}).get("parent_id")
            for chunk in chunks
        ]))
        
        # DB에서 조 전체 content 조회
        articles = self._load_full_articles(contract_id, parent_ids)
        
        return articles
    
    def _load_full_articles(
        self,
        contract_id: str,
        parent_ids: List[str]
    ) -> List[ArticleContent]:
        """
        조 전체 content 배열 조회
        
        Args:
            contract_id: 계약서 ID
            parent_ids: 조 ID 리스트 (예: ["제3조", "제5조"])
            
        Returns:
            ArticleContent 리스트
        """
        try:
            db = SessionLocal()
            contract = db.query(ContractDocument).filter(
                ContractDocument.contract_id == contract_id
            ).first()
            
            if not contract or not contract.parsed_data:
                return []
            
            articles = contract.parsed_data.get("articles", [])
            
            # parent_id에서 조 번호 추출하여 매칭
            result = []
            
            for parent_id in parent_ids:
                # "제5조" → 5
                try:
                    article_no = int(parent_id.replace("제", "").replace("조", ""))
                except:
                    continue
                
                for article in articles:
                    if article.get("number") == article_no:
                        result.append(
                            ArticleContent(
                                article_no=article_no,
                                title=article.get("title", ""),
                                text=article.get("text", ""),
                                content=article.get("content", [])
                            )
                        )
                        break
            
            return result
            
        except Exception as e:
            logger.error(f"조 전체 조회 실패: {e}")
            return []
        
        finally:
            db.close()
