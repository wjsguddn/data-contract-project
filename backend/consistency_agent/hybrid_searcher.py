"""
HybridSearcher for Consistency Agent
FAISS + Whoosh 하이브리드 검색 (0.85 / 0.15 가중치)
"""

import logging
import numpy as np
from typing import List, Dict, Any
from collections import defaultdict
from openai import AzureOpenAI
from backend.shared.database import SessionLocal, TokenUsage

logger = logging.getLogger("uvicorn.error")


class HybridSearcher:
    """
    하이브리드 검색기
    
    - Dense: FAISS 벡터 유사도 검색 (가중치 0.85)
    - Sparse: Whoosh BM25 키워드 검색 (가중치 0.15)
    - Fusion: 정규화 + 가중합
    """
    
    def __init__(
        self,
        azure_client: AzureOpenAI,
        embedding_model: str = "text-embedding-3-large",
        dense_weight: float = 0.85
    ):
        """
        Args:
            azure_client: Azure OpenAI 클라이언트
            embedding_model: 임베딩 모델명
            dense_weight: Dense 검색 가중치 (기본 0.85)
        """
        self.client = azure_client
        self.embedding_model = embedding_model
        self._dense_weight = dense_weight
        
        # 필드 가중치 (본문:제목 = 7:3)
        self.text_weight = 0.7
        self.title_weight = 0.3
        
        # 로드된 인덱스
        self.faiss_index = None  # Deprecated: 하위 호환성을 위해 유지
        self.faiss_index_text = None  # text_norm 인덱스
        self.faiss_index_title = None  # title 인덱스
        self.chunks = None
        self.whoosh_indexer = None
        
        logger.info(f"HybridSearcher 초기화 (Dense: {self.dense_weight:.2f}, Sparse: {self.sparse_weight:.2f})")
        logger.info(f"필드 가중치 (본문: {self.text_weight:.2f}, 제목: {self.title_weight:.2f})")
    
    def load_indexes(
        self,
        faiss_index_text,
        faiss_index_title,
        chunks: List[Dict],
        whoosh_indexer
    ):
        """
        인덱스 로드 (이중 FAISS 인덱스)
        
        Args:
            faiss_index_text: text_norm FAISS 인덱스
            faiss_index_title: title FAISS 인덱스
            chunks: 청크 메타데이터 리스트
            whoosh_indexer: Whoosh 인덱서
        """
        # 단일 인덱스 인자 감지 (하위 호환성 체크)
        if not isinstance(faiss_index_text, tuple) and faiss_index_title is None:
            raise ValueError(
                "단일 FAISS 인덱스는 더 이상 지원되지 않습니다. "
                "KnowledgeBaseLoader.load_faiss_indexes()를 사용하여 "
                "두 개의 인덱스(text, title)를 로드하세요."
            )
        
        self.faiss_index_text = faiss_index_text
        self.faiss_index_title = faiss_index_title
        self.chunks = chunks
        self.whoosh_indexer = whoosh_indexer
        
        # 하위 호환성을 위해 faiss_index도 설정 (deprecated)
        self.faiss_index = faiss_index_text
        
        logger.info(f"인덱스 로드 완료: {len(chunks)} chunks")
        logger.info(f"  - text_norm 인덱스: {faiss_index_text.ntotal if faiss_index_text else 0} vectors")
        logger.info(f"  - title 인덱스: {faiss_index_title.ntotal if faiss_index_title else 0} vectors")
    
    @property
    def dense_weight(self) -> float:
        """Dense 가중치 getter"""
        return self._dense_weight
    
    @dense_weight.setter
    def dense_weight(self, value: float):
        """Dense 가중치 setter (Sparse 가중치 자동 계산)"""
        if not (0.0 <= value <= 1.0):
            raise ValueError(f"Dense 가중치는 0~1 사이여야 합니다: {value}")
        self._dense_weight = value
        logger.debug(f"가중치 업데이트: Dense={value:.2f}, Sparse={1.0-value:.2f}")
    
    @property
    def sparse_weight(self) -> float:
        """Sparse 가중치 getter (자동 계산)"""
        return 1.0 - self._dense_weight
    
    def embed_query(self, query: str, contract_id: str = None) -> np.ndarray:
        """
        쿼리를 임베딩 벡터로 변환 (EmbeddingService 사용)

        Args:
            query: 검색 쿼리
            contract_id: 계약서 ID (토큰 로깅용)

        Returns:
            임베딩 벡터 (numpy array)
        """
        from backend.shared.services import get_embedding_service

        embedding = get_embedding_service().get_embedding(
            text=query,
            contract_id=contract_id,
            component="consistency_agent"
        )
        return np.array([embedding], dtype=np.float32)
    
    def dense_search(
        self,
        text_query: str,
        title_query: str,
        top_k: int = 50,
        contract_id: str = None
    ) -> List[Dict[str, Any]]:
        """
        Dense 검사(FAISS 벡터 유사도 - 제목/본문 분리

        Args:
            text_query: 본문 검색쿼리
            title_query: 제목 검색쿼리
            top_k: 반환할 결과 개수
            contract_id: 계약ID (토큰 로깅)

        Returns:
            검색결과 리스트(text_score, title_score 포함)
        """
        return self._dense_search_internal(
            text_query=text_query,
            title_query=title_query,
            top_k=top_k,
            contract_id=contract_id,
        )

    def _dense_search_internal(
        self,
        text_query: str,
        title_query: str,
        top_k: int,
        contract_id: str = None,
        text_embedding=None,
        title_embedding=None,
    ) -> List[Dict[str, Any]]:
        if self.faiss_index_text is None or self.faiss_index_title is None or self.chunks is None:
            logger.error("FAISS 인덱스가 로드되지 않았습니다")
            return []

        try:
            text_results = {}
            if text_embedding is not None:
                text_vector = self._ensure_vector(text_embedding)
            elif text_query and str(text_query).strip():
                text_vector = self.embed_query(text_query, contract_id)
            else:
                text_vector = None

            if text_vector is not None:
                distances, indices = self.faiss_index_text.search(
                    text_vector,
                    min(top_k, self.faiss_index_text.ntotal)
                )

                for idx, distance in zip(indices[0], distances[0]):
                    if idx < len(self.chunks):
                        chunk_id = self.chunks[idx]['id']
                        similarity = 1.0 / (1.0 + float(distance))
                        text_results[chunk_id] = {
                            'chunk': self.chunks[idx],
                            'text_score': similarity
                        }

            title_results = {}
            if title_embedding is not None:
                title_vector = self._ensure_vector(title_embedding)
            elif title_query and str(title_query).strip():
                title_vector = self.embed_query(title_query, contract_id)
            else:
                title_vector = None

            if title_vector is not None:
                distances, indices = self.faiss_index_title.search(
                    title_vector,
                    min(top_k, self.faiss_index_title.ntotal)
                )

                for idx, distance in zip(indices[0], distances[0]):
                    if idx < len(self.chunks):
                        chunk_id = self.chunks[idx]['id']
                        similarity = 1.0 / (1.0 + float(distance))
                        title_results[chunk_id] = {
                            'chunk': self.chunks[idx],
                            'title_score': similarity
                        }

            all_chunk_ids = set(text_results.keys()) | set(title_results.keys())

            if not all_chunk_ids:
                logger.warning("Dense 검색결과 없음 (제목/본문 모두)")
                return []

            results = []
            for chunk_id in all_chunk_ids:
                text_score = text_results.get(chunk_id, {}).get('text_score', 0.0)
                title_score = title_results.get(chunk_id, {}).get('title_score', 0.0)

                chunk = text_results.get(chunk_id, title_results.get(chunk_id))['chunk']
                weighted_score = self.text_weight * text_score + self.title_weight * title_score

                results.append({
                    'chunk': chunk,
                    'score': weighted_score,
                    'text_score': text_score,
                    'title_score': title_score,
                    'source': 'dense'
                })

            results.sort(key=lambda x: x['score'], reverse=True)
            top_results = results[:top_k]

            logger.info(f"✓ Faiss 검색완료: {len(results)}건(본문: {len(text_results)}, 제목: {len(title_results)})")

            if top_results:
                scores = [r['score'] for r in top_results]
                logger.info(f"Dense top-k: {len(top_results)}건 점수 범위 [{min(scores):.4f} ~ {max(scores):.4f}]")

            return top_results

        except Exception as e:
            logger.error(f"Dense 검색 실패: {e}")
            import traceback
            logger.error(traceback.format_exc())
            return []

    def sparse_search(
        self,
        text_query: str,
        title_query: str,
        top_k: int = 50
    ) -> List[Dict[str, Any]]:
        """
        Sparse 검색 (Whoosh BM25) - 제목/본문 분리

        Args:
            text_query: 본문 검색 쿼리
            title_query: 제목 검색 쿼리
            top_k: 반환할 결과 개수

        Returns:
            검색 결과 리스트 (text_score, title_score 포함)
        """
        if self.whoosh_indexer is None:
            logger.error("Whoosh 인덱스가 로드되지 않았습니다")
            return []

        try:
            # WhooshSearcher.search_with_field_weights() 호출
            whoosh_results = self.whoosh_indexer.search_with_field_weights(
                text_query=text_query,
                title_query=title_query,
                text_weight=self.text_weight,
                title_weight=self.title_weight,
                top_k=top_k
            )

            if not whoosh_results:
                logger.warning(f"Sparse 검색 결과 없음")
                return []

            scores = [hit['score'] for hit in whoosh_results]
            logger.info(f"Sparse top-k: {len(whoosh_results)}개, 점수 범위 [{min(scores):.4f} ~ {max(scores):.4f}]")

            # 결과 변환
            results = []
            for hit in whoosh_results:
                chunk = {
                    'id': hit['id'],
                    'global_id': hit['global_id'],
                    'unit_type': hit['unit_type'],
                    'parent_id': hit['parent_id'],
                    'title': hit['title'],
                    'text_raw': hit['text_raw'],
                    'text_norm': hit['text_norm'],
                    'source_file': hit['source_file'],
                    'order_index': hit['order_index'],
                    'anchors': hit.get('anchors', [])
                }

                results.append({
                    'chunk': chunk,
                    'score': hit['score'],
                    'text_score': hit.get('text_score', 0.0),
                    'title_score': hit.get('title_score', 0.0),
                    'source': 'sparse'
                })

            return results

        except Exception as e:
            logger.error(f"Sparse 검색 실패: {e}")
            import traceback
            logger.error(traceback.format_exc())
            return []
    
    def normalize_scores(self, results: List[Dict[str, Any]]) -> List[Dict[str, Any]]:
        """
        검색 결과 점수를 Min-Max 정규화 (0~1 범위)
        
        Args:
            results: 검색 결과 리스트
            
        Returns:
            정규화된 검색 결과 리스트
        """
        if not results:
            return results
        
        scores = [r['score'] for r in results]
        min_score = min(scores)
        max_score = max(scores)
        
        # 모든 점수가 같은 경우
        if max_score == min_score:
            for r in results:
                r['normalized_score'] = 1.0
            return results
        
        # Min-Max 정규화
        for r in results:
            r['normalized_score'] = (r['score'] - min_score) / (max_score - min_score)
        
        return results
    
    def fuse_scores(
        self,
        dense_results: List[Dict[str, Any]],
        sparse_results: List[Dict[str, Any]]
    ) -> List[Dict[str, Any]]:
        """
        Dense와 Sparse 검색 결과를 융합

        Adaptive Weighting:
        - Sparse 결과가 없으면 자동으로 Dense 가중치를 1.0으로 조정
        - 이를 통해 0.85 상한 문제 해결

        Args:
            dense_results: Dense 검색 결과 (text_score, title_score 포함)
            sparse_results: Sparse 검색 결과 (text_score, title_score 포함)

        Returns:
            융합된 검색 결과 리스트
        """
        # Adaptive Weighting: Sparse 결과 부재 시 가중치 조정
        if not sparse_results and dense_results:
            logger.warning(f"Sparse 검색 결과 없음 - Adaptive Weighting 적용 (Dense: 1.0)")
            effective_dense_weight = 1.0
            effective_sparse_weight = 0.0
        else:
            effective_dense_weight = self.dense_weight
            effective_sparse_weight = self.sparse_weight

        # 1. 원본 점수 맵 생성 (정규화 전)
        dense_raw_scores = {r['chunk']['id']: r['score'] for r in dense_results}
        sparse_raw_scores = {r['chunk']['id']: r['score'] for r in sparse_results}

        # 2. 점수 정규화
        dense_normalized = self.normalize_scores(dense_results)
        sparse_normalized = self.normalize_scores(sparse_results)

        # 3. 청크 ID별로 결과 수집
        chunk_scores = {}

        # Dense 결과 추가
        for result in dense_normalized:
            chunk_id = result['chunk']['id']
            chunk_scores[chunk_id] = {
                'chunk': result['chunk'],
                'dense_score': result['normalized_score'],
                'dense_score_raw': dense_raw_scores.get(chunk_id, 0.0),  # 정규화 이전 원본 점수
                'sparse_score': 0.0,
                'sparse_score_raw': 0.0,
                'text_score': result.get('text_score', 0.0),
                'title_score': result.get('title_score', 0.0)
            }

        # Sparse 결과 추가/병합
        sparse_contribution_count = 0
        for result in sparse_normalized:
            chunk_id = result['chunk']['id']
            if chunk_id in chunk_scores:
                chunk_scores[chunk_id]['sparse_score'] = result['normalized_score']
                chunk_scores[chunk_id]['sparse_score_raw'] = sparse_raw_scores.get(chunk_id, 0.0)  # 정규화 이전 원본 점수
                sparse_contribution_count += 1
            else:
                chunk_scores[chunk_id] = {
                    'chunk': result['chunk'],
                    'dense_score': 0.0,
                    'dense_score_raw': 0.0,
                    'sparse_score': result['normalized_score'],
                    'sparse_score_raw': sparse_raw_scores.get(chunk_id, 0.0),  # 정규화 이전 원본 점수
                    'text_score': result.get('text_score', 0.0),
                    'title_score': result.get('title_score', 0.0)
                }

        # 진단: Sparse 기여도
        if sparse_results:
            overlap_rate = sparse_contribution_count / len(chunk_scores) * 100
            logger.info(f"  Sparse-Dense 중복: {sparse_contribution_count}/{len(chunk_scores)} ({overlap_rate:.1f}%)")
            logger.info(f"  가중치 - Dense: {effective_dense_weight:.2f}, Sparse: {effective_sparse_weight:.2f}")

        # 3. 가중합 계산 (Adaptive Weighting 적용)
        fused_results = []
        for chunk_id, data in chunk_scores.items():
            final_score = (
                effective_dense_weight * data['dense_score'] +
                effective_sparse_weight * data['sparse_score']
            )

            fused_results.append({
                'chunk': data['chunk'],
                'score': final_score,
                'dense_score': data['dense_score'],
                'dense_score_raw': data['dense_score_raw'],  # 원본 점수 추가
                'sparse_score': data['sparse_score'],
                'sparse_score_raw': data['sparse_score_raw'],  # 원본 점수 추가
                'text_score': data['text_score'],
                'title_score': data['title_score'],
                'parent_id': data['chunk'].get('parent_id'),
                'title': data['chunk'].get('title')
            })

        # 4. 최종 점수로 정렬
        fused_results.sort(key=lambda x: x['score'], reverse=True)

        return fused_results
    
    def search(
        self,
        text_query: str,
        title_query: str,
        top_k: int = 10,
        dense_top_k: int = 30,
        sparse_top_k: int = 30,
        contract_id: str = None
    ) -> List[Dict[str, Any]]:
        """
        하이브리드 검색을 수행 (제목/본문 분리)
        """
        return self._search_internal(
            text_query=text_query,
            title_query=title_query,
            top_k=top_k,
            dense_top_k=dense_top_k,
            sparse_top_k=sparse_top_k,
            contract_id=contract_id,
        )

    def search_with_embeddings(
        self,
        text_query: str,
        title_query: str,
        text_embedding,
        title_embedding,
        top_k: int = 10,
        dense_top_k: int = 30,
        sparse_top_k: int = 30,
        contract_id: str = None
    ) -> List[Dict[str, Any]]:
        """
        하이브리드 검색 (사전 계산된 임베딩 사용)
        """
        return self._search_internal(
            text_query=text_query,
            title_query=title_query,
            top_k=top_k,
            dense_top_k=dense_top_k,
            sparse_top_k=sparse_top_k,
            contract_id=contract_id,
            text_embedding=text_embedding,
            title_embedding=title_embedding,
        )

    def _search_internal(
        self,
        text_query: str,
        title_query: str,
        top_k: int,
        dense_top_k: int,
        sparse_top_k: int,
        contract_id: str = None,
        text_embedding=None,
        title_embedding=None,
    ) -> List[Dict[str, Any]]:
        if self.faiss_index_text is None or self.faiss_index_title is None or self.whoosh_indexer is None:
            logger.error("검색 인덱스가 로드되지 않았습니다")
            return []

        try:
            logger.debug("하이브리드 검색(제목/본문 분리)")
            logger.debug(f"  본문 쿼리: {text_query[:100]}...")
            logger.debug(f"  제목 쿼리: {title_query[:100]}...")
            logger.info(f"가중치 - 본문:제목 = {self.text_weight:.2f}:{self.title_weight:.2f}, Dense:Sparse = {self.dense_weight:.2f}:{self.sparse_weight:.2f}")

            dense_results = self._dense_search_internal(
                text_query=text_query,
                title_query=title_query,
                top_k=dense_top_k,
                contract_id=contract_id,
                text_embedding=text_embedding,
                title_embedding=title_embedding,
            )
            logger.debug(f"  Dense: {len(dense_results)}건")

            sparse_results = self.sparse_search(
                text_query=text_query,
                title_query=title_query,
                top_k=sparse_top_k
            )
            logger.debug(f"  Sparse: {len(sparse_results)}건")

            fused_results = self.fuse_scores(dense_results, sparse_results)
            logger.debug(f"  Fusion: {len(fused_results)}건")

            final_results = fused_results[:top_k]
            return final_results

        except Exception as e:
            logger.error(f"하이브리드 검색 실패: {e}")
            import traceback
            traceback.print_exc()
            return []

    def set_field_weights(self, text_weight: float):
        """
        본문:제목 가중치 설정 (제목 가중치는 자동 계산)

        Args:
            text_weight: 본문 가중치 (0~1)

        Raises:
            ValueError: 가중치가 유효하지 않은 경우
        """
        # 범위 검증
        if not (0.0 <= text_weight <= 1.0):
            raise ValueError(f"본문 가중치는 0~1 사이여야 합니다: {text_weight}")
        
        self.text_weight = text_weight
        self.title_weight = 1.0 - text_weight
        
        logger.info(f"필드 가중치 변경: 본문={self.text_weight:.2f}, 제목={self.title_weight:.2f}")

    @staticmethod
    def _ensure_vector(vector) -> np.ndarray:
        """Ensure the embedding vector is a 2D numpy array."""
        if isinstance(vector, np.ndarray):
            arr = vector.astype(np.float32, copy=False)
        else:
            arr = np.array(vector, dtype=np.float32)

        if arr.ndim == 1:
            arr = arr.reshape(1, -1)
        elif arr.ndim != 2:
            raise ValueError("Embedding vector must be 1D or 2D.")

        return arr

    def _log_token_usage(
        self,
        contract_id: str,
        api_type: str,
        model: str,
        prompt_tokens: int,
        completion_tokens: int,
        total_tokens: int,
        extra_info: dict = None
    ):
        """토큰 사용량을 DB에 저장"""
        try:
            db = SessionLocal()
            token_usage = TokenUsage(
                contract_id=contract_id,
                component="consistency_agent",
                api_type=api_type,
                model=model,
                prompt_tokens=prompt_tokens,
                completion_tokens=completion_tokens,
                total_tokens=total_tokens,
                extra_info=extra_info
            )
            db.add(token_usage)
            db.commit()
            logger.info(f"토큰 사용량 로깅: {api_type} - {total_tokens} tokens")
        except Exception as e:
            logger.error(f"토큰 사용량 로깅 실패: {e}")
        finally:
            db.close()
