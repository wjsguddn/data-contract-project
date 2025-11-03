"""
ArticleMatcher - 대응 조항 검색 (멀티벡터 방식)
사용자 계약서 조항과 표준계약서 조항 매칭
"""

import logging
import re
import math
from typing import Dict, Any, List, Optional
from collections import defaultdict, Counter
from openai import AzureOpenAI
from backend.shared.services.embedding_loader import EmbeddingLoader

logger = logging.getLogger(__name__)


class ArticleMatcher:
    """
    대응 조항 검색기
    
    멀티벡터 검색 방식:
    1. 사용자 조항의 각 하위항목으로 개별 검색
    2. Top-K 청크 검색 (FAISS + Whoosh 하이브리드)
    3. 청크를 조 단위로 취합 (정규화된 평균 점수)
    4. 최고 점수 조 선택
    """
    
    def __init__(
        self,
        knowledge_base_loader,
        azure_client: AzureOpenAI,
        embedding_model: str = "text-embedding-3-large",
        similarity_threshold: float = 0.7,
        special_threshold: float = 0.3
    ):
        """
        Args:
            knowledge_base_loader: KnowledgeBaseLoader 인스턴스
            azure_client: Azure OpenAI 클라이언트
            embedding_model: 임베딩 모델명
            similarity_threshold: 매칭 성공 임계값 (기본 0.7)
            special_threshold: 특수 조항 임계값 (기본 0.3, 이 값 미만이면 특수 조항)
        """
        self.kb_loader = knowledge_base_loader
        self.azure_client = azure_client
        self.embedding_model = embedding_model
        self.threshold = similarity_threshold
        self.special_threshold = special_threshold
        
        # 조별 청크 개수 캐싱 (정규화 계산용)
        self.article_chunk_counts = {}
        
        # HybridSearcher 인스턴스 (계약 유형별)
        self.searchers = {}
        self.embedding_loader = EmbeddingLoader()
        
        logger.info(f"ArticleMatcher 초기화 완료 (match_threshold={similarity_threshold}, special_threshold={special_threshold})")
    
    def find_matching_article(
        self,
        user_article: Dict[str, Any],
        contract_type: str,
        top_k: int = 5,
        contract_id: str = None,
        text_weight: float = 0.7,
        title_weight: float = 0.3,
        dense_weight: float = 0.85
    ) -> Dict[str, Any]:
        """
        대응 조항 검색 (멀티벡터 방식)

        각 하위항목별로:
        1. top_k 청크 검색
        2. 조별 평균 점수 계산
        3. 최고 점수 조 선정

        최종적으로 하위항목별 결과를 조 단위로 집계

        정렬 순서:
        1. 하위항목 개수 (많은 순)
        2. 평균 유사도 (높은 순)
        3. 조 번호 (낮은 순)

        Args:
            user_article: 사용자 조항 (content 배열 포함)
            contract_type: 계약 유형
            top_k: 청크 레벨 검색 결과 개수 (기본 5)
            contract_id: 계약서 ID (토큰 로깅용)
            text_weight: 본문 가중치 (기본값: 0.7)
            title_weight: 제목 가중치 (기본값: 0.3)
            dense_weight: 시멘틱 가중치 (기본값: 0.85)

        Returns:
            {
                "matched": bool,
                "matched_articles": List[Dict],  # 매칭된 조 목록 (정렬됨, 여러 개 가능)
                "sub_item_results": List[Dict],  # 하위항목별 결과
                "is_special": bool
            }
        """
        user_article_no = user_article.get('number')
        user_article_title = user_article.get('title', '')

        logger.info(f"조항 매칭 시작: 제{user_article_no}조 ({user_article_title})")

        # 멀티벡터 검색 (가중치 전달)
        matched_articles, sub_item_results = self._search_with_sub_items(
            user_article,
            contract_type,
            top_k,
            contract_id,
            text_weight=text_weight,
            title_weight=title_weight,
            dense_weight=dense_weight
        )

        if not matched_articles:
            logger.warning(f"  매칭 실패: 검색 결과 없음")
            return {
                "matched": False,
                "matched_articles": [],
                "sub_item_results": sub_item_results,
                "is_special": False
            }

        # 매칭 결과 로깅
        logger.info(f"  매칭 완료: {len(matched_articles)}개 조")
        for i, article in enumerate(matched_articles, 1):
            logger.info(f"    {i}. {article['parent_id']}: {article['score']:.3f} (하위항목 {article['num_sub_items']}개)")

        return {
            "matched": True,
            "matched_articles": matched_articles,  # 정렬된 모든 매칭 조
            "sub_item_results": sub_item_results,  # 하위항목별 결과
            "is_special": False
        }
    
    def _search_with_sub_items(
        self,
        user_article: Dict[str, Any],
        contract_type: str,
        top_k: int = 3,
        contract_id: str = None,
        text_weight: float = 0.7,
        title_weight: float = 0.3,
        dense_weight: float = 0.85
    ) -> tuple[List[Dict], List[Dict]]:
        """
        사용자 조항의 각 하위항목으로 검색 (top-1 방식)
        
        각 하위항목별로:
        1. top-1 청크 검색 (제목/본문 분리)
        2. 최고 점수 조 1개 선정
        
        Args:
            text_weight: 본문 가중치 (기본값: 0.7)
            title_weight: 제목 가중치 (기본값: 0.3)
            dense_weight: 시멘틱 가중치 (기본값: 0.85)
        
        Returns:
            (article_scores, sub_item_results)
            - article_scores: 조 단위 최종 결과 (하위항목별 결과 집계)
            - sub_item_results: 하위항목별 매칭 결과
        """
        content_items = user_article.get('content', [])
        article_title = user_article.get('title', '')
        
        if not content_items:
            logger.warning("  하위항목이 없습니다")
            return [], []
        
        # 하위항목별 매칭 결과
        sub_item_results = []

        article_no = self._safe_int(user_article.get('number'))
        stored_article_embedding = None
        title_embedding_vector = None
        if contract_id and article_no is not None:
            stored_article_embedding = self.embedding_loader.load_article_embedding(contract_id, article_no)
            if stored_article_embedding:
                title_embedding_vector = stored_article_embedding.get('title_embedding')

        for idx, sub_item in enumerate(content_items, 1):
            # 정규화
            normalized = self._normalize_sub_item(sub_item)
            
            if not normalized:
                continue
            
            # 검색 쿼리 생성 (제목/본문 분리)
            text_query, title_query = self._build_search_queries(normalized, article_title)
            
            logger.debug(f"    하위항목 {idx} 검색: text={text_query[:50]}..., title={title_query}")
            sub_embedding_vector = None
            if stored_article_embedding:
                sub_embedding_vector = self._get_sub_item_embedding(stored_article_embedding, idx)


            # 하이브리드 검색 수행 (top-1 청크, 가중치 전달)
            chunk_results = self._hybrid_search(
                text_query=text_query,
                title_query=title_query,
                contract_type=contract_type,
                top_k=top_k,
                contract_id=contract_id,
                text_weight=text_weight,
                title_weight=title_weight,
                dense_weight=dense_weight,
                text_embedding=sub_embedding_vector,
                title_embedding=title_embedding_vector
            )
            
            if not chunk_results:
                continue
            
            # top-1 결과에서 최고 점수 조 선정
            best_article = self._select_best_article_from_chunks(chunk_results)
            
            if best_article:
                sub_item_results.append({
                    'sub_item_index': idx,
                    'sub_item_text': sub_item,
                    'normalized_text': normalized,
                    'matched_article_id': best_article['parent_id'],
                    'matched_article_title': best_article['title'],
                    'score': best_article['score'],
                    'matched_chunks': best_article['chunks']
                })
                
                logger.debug(f"      → {best_article['parent_id']}: {best_article['score']:.3f}")
        
        if not sub_item_results:
            return [], []
        
        # 하위항목별 결과를 조 단위로 집계
        article_scores = self._aggregate_sub_item_results(sub_item_results)
        
        return article_scores, sub_item_results
    
    def _normalize_sub_item(self, content: str) -> str:
        """
        사용자 계약서 하위항목 정규화
        
        - 앞뒤 공백 제거
        - ①②③ 등의 원문자 제거
        - 1. 2. 3. 등의 번호 제거
        - (가) (나) 등의 괄호 번호 제거
        """
        # 앞뒤 공백 제거
        text = content.strip()
        
        # 원문자 제거 (①②③...)
        text = re.sub(r'^[①②③④⑤⑥⑦⑧⑨⑩⑪⑫⑬⑭⑮]+\s*', '', text)
        
        # 숫자 + 점 제거 (1. 2. 3. ...)
        text = re.sub(r'^\d+\.\s*', '', text)
        
        # 괄호 번호 제거 ((가) (나) ...)
        text = re.sub(r'^\([가-힣]\)\s*', '', text)
        
        # 다시 앞뒤 공백 제거
        text = text.strip()
        
        return text
    
    def _build_search_query(
        self,
        sub_item: str,
        article_title: str
    ) -> str:
        """
        검색 쿼리 생성 (레거시 메서드 - 하위 호환성 유지)
        
        하위항목 전체 내용 + 조 제목 (제목은 뒤에 배치하여 가중치 과다 방지)
        
        Args:
            sub_item: 정규화된 하위항목 내용 (전체)
            article_title: 조 제목 (예: "데이터 제공 범위 및 방식")
            
        Returns:
            "{sub_item} {article_title}"
        """
        # 하위항목 전체 내용 사용 (제목은 뒤에 배치)
        return f"{sub_item} {article_title}"
    
    def _build_search_queries(
        self,
        sub_item: str,
        article_title: str
    ) -> tuple[str, str]:
        """
        검색 쿼리 생성 (제목/본문 분리)
        
        Args:
            sub_item: 정규화된 하위항목 내용 (본문)
            article_title: 조 제목
            
        Returns:
            (text_query, title_query) 튜플
            - text_query: 본문 쿼리 (sub_item)
            - title_query: 제목 쿼리 (article_title)
        """
        return (sub_item, article_title)
    
    def _get_sub_item_embedding(
        self,
        article_embedding: Dict[str, Any],
        sub_item_index: int
    ) -> Optional[List[float]]:
        for sub_item in article_embedding.get('sub_items', []):
            if sub_item.get('index') == sub_item_index:
                return sub_item.get('text_embedding')
        return None

    @staticmethod
    def _safe_int(value: Any) -> Optional[int]:
        try:
            return int(value)
        except (TypeError, ValueError):
            return None

    def _get_or_create_searcher(self, contract_type: str):
        """
        계약 유형별 HybridSearcher 가져오기 (없으면 생성)
        
        Args:
            contract_type: 계약 유형
            
        Returns:
            HybridSearcher 인스턴스
        """
        if contract_type in self.searchers:
            return self.searchers[contract_type]
        
        # HybridSearcher 생성
        from backend.consistency_agent.hybrid_searcher import HybridSearcher
        
        searcher = HybridSearcher(
            azure_client=self.azure_client,
            embedding_model=self.embedding_model,
            dense_weight=0.85
        )
        
        try:
            # 두 개의 FAISS 인덱스 로드
            faiss_indexes = self.kb_loader.load_faiss_indexes(contract_type)
            chunks = self.kb_loader.load_chunks(contract_type)
            whoosh_indexer = self.kb_loader.load_whoosh_index(contract_type)
            
            if not faiss_indexes:
                logger.error(f"FAISS 인덱스 로드 실패: {contract_type}")
                return None
            
            if not chunks:
                logger.error(f"청크 데이터 로드 실패: {contract_type}")
                return None
            
            if not whoosh_indexer:
                logger.error(f"Whoosh 인덱스 로드 실패: {contract_type}")
                return None
            
            # 두 개의 인덱스 언팩
            faiss_index_text, faiss_index_title = faiss_indexes
            
            # HybridSearcher에 두 개의 인덱스 전달
            searcher.load_indexes(faiss_index_text, faiss_index_title, chunks, whoosh_indexer)
            
            # 캐싱
            self.searchers[contract_type] = searcher
            
            logger.info(f"HybridSearcher 생성 완료: {contract_type}")
            return searcher
            
        except Exception as e:
            logger.error(f"HybridSearcher 생성 실패: {contract_type}, 에러: {e}")
            return None
    
    def _hybrid_search(
        self,
        text_query: str,
        title_query: str,
        contract_type: str,
        top_k: int,
        contract_id: str = None,
        text_weight: float = 0.7,
        title_weight: float = 0.3,
        dense_weight: float = 0.85,
        text_embedding: Optional[List[float]] = None,
        title_embedding: Optional[List[float]] = None
    ) -> List[Dict]:
        """
        하이브리드 검색 수행 (FAISS + Whoosh, 제목/본문 분리)
        """
        searcher = self._get_or_create_searcher(contract_type)

        if not searcher:
            logger.error(f"Searcher를 생성할 수 없습니다: {contract_type}")
            return []

        searcher.set_field_weights(text_weight)
        searcher.dense_weight = dense_weight

        use_precomputed = text_embedding is not None or title_embedding is not None

        if use_precomputed:
            results = searcher.search_with_embeddings(
                text_query=text_query,
                title_query=title_query,
                text_embedding=text_embedding,
                title_embedding=title_embedding,
                top_k=top_k,
                contract_id=contract_id
            )
        else:
            results = searcher.search(
                text_query=text_query,
                title_query=title_query,
                top_k=top_k,
                contract_id=contract_id
            )

        return results

    def _select_best_article_from_chunks(
        self,
        chunk_results: List[Dict]
    ) -> Optional[Dict]:
        """
        청크 검색 결과에서 최고 점수 조 1개 선정 (top-1 방식)
        
        각 조의 최고 점수 청크를 대표 점수로 사용
        
        Args:
            chunk_results: 하이브리드 검색 결과 (top-1 청크)
            
        Returns:
            {
                'parent_id': str,
                'title': str,
                'score': float,  # 조의 최고 점수
                'chunks': List[Dict]  # 해당 조의 청크들
            }
        """
        # parent_id로 그룹화
        article_groups = defaultdict(list)
        
        for result in chunk_results:
            parent_id = result.get('parent_id')
            if not parent_id:
                continue
            
            article_groups[parent_id].append(result)
        
        if not article_groups:
            return None
        
        # 조별 최고 점수 계산
        article_scores = []
        
        for parent_id, chunks in article_groups.items():
            # 최고 점수 (top-1 방식)
            max_score = max(c.get('score', 0.0) for c in chunks)
            
            # 제목 추출
            title = chunks[0].get('title', '') if chunks else ''
            
            article_scores.append({
                'parent_id': parent_id,
                'title': title,
                'score': max_score,
                'chunks': chunks
            })
        
        # 최고 점수 조 선택
        best_article = max(article_scores, key=lambda x: x['score'])
        
        return best_article
    
    def _aggregate_sub_item_results(
        self,
        sub_item_results: List[Dict]
    ) -> List[Dict]:
        """
        하위항목별 매칭 결과를 조 단위로 집계

        같은 조를 선택한 하위항목들의 점수를 평균내고,
        다른 조를 선택한 경우 모두 결과에 포함

        정렬 순서:
        1. 하위항목 개수 (많은 순)
        2. 평균 유사도 (높은 순)
        3. 조 번호 (낮은 순)

        Args:
            sub_item_results: 하위항목별 매칭 결과

        Returns:
            조 단위 집계 결과 (정렬됨)
        """
        # 조별로 그룹화
        article_groups = defaultdict(list)

        for result in sub_item_results:
            article_id = result['matched_article_id']
            article_groups[article_id].append(result)

        # 조별 평균 점수 계산
        article_scores = []

        for article_id, results in article_groups.items():
            # 평균 점수
            avg_score = sum(r['score'] for r in results) / len(results)

            # 제목 (첫 번째 결과에서)
            title = results[0]['matched_article_title']

            # 매칭된 하위항목 인덱스
            matched_sub_items = [r['sub_item_index'] for r in results]

            # 모든 청크 수집 (중복 제거)
            all_chunks = []
            seen_chunk_ids = set()
            for r in results:
                for chunk in r['matched_chunks']:
                    chunk_id = chunk.get('chunk', {}).get('id')
                    if chunk_id and chunk_id not in seen_chunk_ids:
                        all_chunks.append(chunk)
                        seen_chunk_ids.add(chunk_id)

            # base_global_id 추출 (첫 번째 청크에서)
            base_global_id = self._extract_base_global_id(all_chunks[0]) if all_chunks else None

            article_scores.append({
                'parent_id': article_id,
                'title': title,
                'score': avg_score,
                'matched_sub_items': matched_sub_items,
                'num_sub_items': len(results),
                'matched_chunks': all_chunks,
                'base_global_id': base_global_id  # 추가
            })

        # 정렬: 1. 하위항목 개수 (내림차순) → 2. 유사도 (내림차순) → 3. 조 번호 (오름차순)
        article_scores.sort(key=lambda x: (
            -x['num_sub_items'],  # 하위항목 개수 많은 순
            -x['score'],          # 유사도 높은 순
            self._extract_article_number(x['parent_id'])  # 조 번호 낮은 순
        ))

        logger.debug(f"    조 단위 집계 완료: {len(article_scores)}개 조")
        for i, article in enumerate(article_scores, 1):
            # Dense/Sparse 평균 점수 계산
            chunks = article['matched_chunks']
            if chunks:
                avg_dense = sum(c.get('dense_score', 0.0) for c in chunks) / len(chunks)
                avg_sparse = sum(c.get('sparse_score', 0.0) for c in chunks) / len(chunks)
                logger.info(f"      {i}. {article['parent_id']}: {article['score']:.3f} (D:{avg_dense:.3f}, S:{avg_sparse:.3f}, 하위항목:{article['num_sub_items']})")
            else:
                logger.debug(f"      {i}. {article['parent_id']}: {article['score']:.3f} (하위항목: {article['num_sub_items']}개)")

        return article_scores

    def _extract_article_number(self, parent_id: str) -> int:
        """
        조 ID에서 숫자 추출 (정렬용)

        예: "제3조" → 3, "제10조" → 10

        Args:
            parent_id: 조 ID (예: "제3조")

        Returns:
            조 번호 (숫자 추출 실패 시 999999)
        """
        import re
        match = re.search(r'\d+', parent_id)
        if match:
            return int(match.group())
        return 999999  # 숫자 추출 실패 시 뒤로 보냄
    
    def _extract_base_global_id(self, chunk_data: Dict) -> Optional[str]:
        """
        청크 데이터에서 base global_id 추출

        Args:
            chunk_data: 청크 데이터 (matched_chunks의 항목)

        Returns:
            base global_id (예: "urn:std:provide:art:001")
            찾을 수 없으면 None
        """
        try:
            # chunk_data 구조: {'chunk': {'global_id': '...', ...}, ...}
            global_id = chunk_data.get('chunk', {}).get('global_id', '')
            if global_id:
                # "urn:std:provide:art:001:att" → "urn:std:provide:art:001"
                base_global_id = ':'.join(global_id.split(':')[:5])
                return base_global_id
            return None
        except Exception as e:
            logger.warning(f"    base_global_id 추출 실패: {e}")
            return None

    def _build_article_chunk_count_map(self, contract_type: str):
        """
        각 조별 하위항목 개수를 미리 계산하여 캐싱

        구조: {contract_type: {parent_id: count}}
        예: {'provide': {'제1조': 1, '제2조': 6, '제3조': 4, ...}}
        """
        logger.info(f"  조별 청크 개수 캐싱 중: {contract_type}")
        
        try:
            # KnowledgeBaseLoader를 통해 chunks 데이터 로드
            chunks = self.kb_loader.load_chunks(contract_type)
            
            if not chunks:
                logger.warning(f"    청크 데이터를 로드할 수 없습니다")
                self.article_chunk_counts[contract_type] = {}
                return
            
            # parent_id별 개수 계산
            parent_ids = [chunk.get('parent_id') for chunk in chunks if chunk.get('parent_id')]
            count_map = dict(Counter(parent_ids))
            
            self.article_chunk_counts[contract_type] = count_map
            
            logger.info(f"    캐싱 완료: {len(count_map)}개 조")
            
        except Exception as e:
            logger.error(f"    청크 개수 캐싱 실패: {e}")
            self.article_chunk_counts[contract_type] = {}
    
    def load_full_article_chunks(
        self,
        parent_id: str,
        contract_type: str
    ) -> List[Dict]:
        """
        표준계약서 조의 모든 청크 로드
        
        해당 조에 속한 모든 하위항목 청크 반환 (조 본문 포함)
        """
        logger.debug(f"  조 청크 로드: {parent_id}")
        
        try:
            # KnowledgeBaseLoader를 통해 chunks 로드
            chunks = self.kb_loader.load_chunks(contract_type)
            
            if not chunks:
                logger.warning(f"    청크 데이터 로드 실패: {contract_type}")
                return []
            
            # 해당 parent_id의 청크만 필터링
            article_chunks = [
                chunk for chunk in chunks
                if chunk.get('parent_id') == parent_id
            ]
            
            # order_index로 정렬 (있는 경우)
            article_chunks.sort(key=lambda x: x.get('order_index', 0))
            
            logger.debug(f"    로드 완료: {len(article_chunks)}개 청크")
            return article_chunks
            
        except Exception as e:
            logger.error(f"    조 청크 로드 실패: {e}")
            return []

    def build_user_faiss_index(
        self,
        user_articles: List[Dict[str, Any]],
        contract_id: str
    ) -> tuple:
        """
        사용자 조문으로 FAISS 인덱스 생성 (역방향 검색용)
        
        Args:
            user_articles: 사용자 계약서 조문 리스트
            contract_id: 계약서 ID
        
        Returns:
            (faiss_index, embedding_map)
            - faiss_index: FAISS 인덱스
            - embedding_map: 인덱스 → (조문, 하위항목) 매핑
        """
        import numpy as np
        import faiss
        
        logger.info(f"  사용자 조문 FAISS 인덱스 생성 중...")
        logger.info(f"    contract_id: {contract_id}")
        
        # 먼저 전체 임베딩 데이터 확인
        all_embeddings = self.embedding_loader.load_embeddings(contract_id)
        if not all_embeddings:
            logger.error(f"    ❌ 임베딩 데이터 전체가 없음!")
            return None, []
        
        article_embeddings = all_embeddings.get("article_embeddings", [])
        logger.info(f"    DB에 저장된 조문 임베딩: {len(article_embeddings)}개")
        
        # 모든 하위항목 임베딩 수집
        embeddings_list = []
        embedding_map = []  # [(user_article, sub_item_index, sub_item_text), ...]
        
        for user_article in user_articles:
            user_no = user_article.get('number')
            user_content = user_article.get('content', [])
            
            # 임베딩 로드
            stored_embedding = self.embedding_loader.load_article_embedding(contract_id, user_no)
            if not stored_embedding:
                logger.warning(f"    제{user_no}조 임베딩 없음 - 건너뜀")
                continue
            
            # 각 하위항목 임베딩 추가
            for idx, sub_item in enumerate(user_content, 1):
                sub_embedding = self._get_sub_item_embedding(stored_embedding, idx)
                if sub_embedding is not None:
                    embeddings_list.append(sub_embedding)
                    embedding_map.append({
                        'user_article': user_article,
                        'sub_item_index': idx,
                        'sub_item_text': sub_item
                    })
        
        if not embeddings_list:
            logger.error(f"    임베딩을 하나도 로드하지 못함!")
            return None, []
        
        # FAISS 인덱스 생성
        embeddings_array = np.array(embeddings_list, dtype=np.float32)
        dimension = embeddings_array.shape[1]
        faiss_index = faiss.IndexFlatL2(dimension)
        faiss_index.add(embeddings_array)
        
        logger.info(f"    FAISS 인덱스 생성 완료: {len(embeddings_list)}개 하위항목 (dimension: {dimension})")
        
        return faiss_index, embedding_map
    
    def find_matching_user_articles(
        self,
        standard_article: Dict[str, Any],
        user_faiss_index,
        embedding_map: List[Dict],
        contract_type: str,
        top_k: int = 3
    ) -> List[Dict[str, Any]]:
        """
        역방향 검색: 표준 조문으로 사용자 계약서 조문 검색 (FAISS 기반)
        
        Args:
            standard_article: 표준 조문 정보
                {
                    'parent_id': str,
                    'title': str,
                    'chunks': List[Dict]
                }
            user_faiss_index: 사용자 조문 FAISS 인덱스
            embedding_map: 인덱스 → 조문 매핑
            contract_type: 계약 유형 (FAISS 인덱스 로드용)
            top_k: 반환할 최대 결과 개수 (조 단위)
        
        Returns:
            매칭된 사용자 조문 리스트 (유사도 순 정렬, 조 단위)
        """
        import numpy as np
        
        parent_id = standard_article.get('parent_id')
        title = standard_article.get('title', '')
        chunks = standard_article.get('chunks', [])
        
        logger.info(f"    역방향 검색 시작: {parent_id} ({title})")
        logger.info(f"      - 표준 청크 수: {len(chunks)}개")
        logger.info(f"      - FAISS 인덱스: {'있음' if user_faiss_index is not None else '없음'}")
        logger.info(f"      - embedding_map 크기: {len(embedding_map)}개")
        
        if not chunks:
            logger.warning(f"      청크가 없습니다")
            return []
        
        if user_faiss_index is None:
            logger.error(f"      FAISS 인덱스가 없습니다")
            return []
        
        # 표준 계약서 FAISS 인덱스 및 청크 로드
        standard_faiss_indexes = self.kb_loader.load_faiss_indexes(contract_type)
        standard_chunks = self.kb_loader.load_chunks(contract_type)
        
        if not standard_faiss_indexes or not standard_chunks:
            logger.error(f"      표준 계약서 인덱스/청크 로드 실패: {contract_type}")
            return []
        
        # text 인덱스만 사용 (본문 검색)
        standard_faiss_text, _ = standard_faiss_indexes
        
        # 청크 ID → 인덱스 매핑 생성
        chunk_id_to_index = {chunk['id']: idx for idx, chunk in enumerate(standard_chunks)}
        
        # 사용자 조문별 점수 집계
        user_article_scores = defaultdict(lambda: {
            'scores': [],
            'matched_chunks': [],
            'user_article': None
        })
        
        # 각 표준 청크로 FAISS 검색
        total_searches = 0
        total_matches = 0
        chunks_without_embedding = 0
        
        for chunk in chunks:
            chunk_id = chunk.get('id')
            
            # 청크 인덱스 찾기
            chunk_index = chunk_id_to_index.get(chunk_id)
            if chunk_index is None:
                chunks_without_embedding += 1
                logger.debug(f"      청크 인덱스 없음: {chunk_id}")
                continue
            
            # FAISS 인덱스에서 임베딩 추출
            try:
                chunk_embedding = standard_faiss_text.reconstruct(chunk_index)
            except Exception as e:
                chunks_without_embedding += 1
                logger.debug(f"      임베딩 추출 실패: {chunk_id}, {e}")
                continue
            
            total_searches += 1
            
            # FAISS 검색 (Top-10 하위항목)
            query_vector = np.array([chunk_embedding], dtype=np.float32)
            distances, indices = user_faiss_index.search(query_vector, k=10)
            
            # 검색 결과 처리
            chunk_matches = 0
            for idx, distance in zip(indices[0], distances[0]):
                if idx >= len(embedding_map):
                    continue
                
                match_info = embedding_map[idx]
                user_article = match_info['user_article']
                user_no = user_article.get('number')
                
                # L2 거리를 유사도로 변환
                similarity = 1.0 / (1.0 + float(distance))
                
                logger.debug(f"        청크 매칭: 제{user_no}조 하위{match_info['sub_item_index']} - 유사도 {similarity:.3f}")
                
                if similarity > 0.5:  # 임계값
                    chunk_matches += 1
                    user_article_scores[user_no]['scores'].append(similarity)
                    user_article_scores[user_no]['matched_chunks'].append({
                        'standard_chunk': chunk,
                        'user_sub_item': match_info['sub_item_text'],
                        'user_sub_item_index': match_info['sub_item_index'],
                        'similarity': similarity
                    })
                    user_article_scores[user_no]['user_article'] = user_article
            
            if chunk_matches > 0:
                total_matches += chunk_matches
                logger.debug(f"      청크 검색 완료: {chunk_matches}개 매칭")
        
        if chunks_without_embedding > 0:
            logger.warning(f"      임베딩 없는 청크: {chunks_without_embedding}개")
        
        logger.info(f"      총 {total_searches}개 청크 검색, {total_matches}개 매칭 발견")
        
        # 조별 평균 점수 계산 및 정렬
        results = []
        for user_no, data in user_article_scores.items():
            if not data['scores']:
                continue
            
            avg_score = sum(data['scores']) / len(data['scores'])
            max_score = max(data['scores'])
            
            results.append({
                'user_article': data['user_article'],
                'similarity': max_score,
                'avg_similarity': avg_score,
                'num_matches': len(data['scores']),
                'matched_chunks': data['matched_chunks']
            })
        
        # 유사도 순 정렬
        results.sort(key=lambda x: x['similarity'], reverse=True)
        
        # Top-K 반환
        top_results = results[:top_k]
        
        logger.debug(f"      검색 완료: {len(top_results)}개 사용자 조문")
        
        return top_results
    
    def _calculate_cosine_similarity(
        self,
        embedding1: List[float],
        embedding2: List[float]
    ) -> float:
        """
        코사인 유사도 계산
        
        Args:
            embedding1: 첫 번째 임베딩 벡터
            embedding2: 두 번째 임베딩 벡터
        
        Returns:
            코사인 유사도 (0.0 ~ 1.0)
        """
        import numpy as np
        
        try:
            vec1 = np.array(embedding1)
            vec2 = np.array(embedding2)
            
            # 코사인 유사도 계산
            dot_product = np.dot(vec1, vec2)
            norm1 = np.linalg.norm(vec1)
            norm2 = np.linalg.norm(vec2)
            
            if norm1 == 0 or norm2 == 0:
                return 0.0
            
            similarity = dot_product / (norm1 * norm2)
            
            # -1 ~ 1 범위를 0 ~ 1로 변환
            return (similarity + 1) / 2
            
        except Exception as e:
            logger.warning(f"코사인 유사도 계산 실패: {e}")
            return 0.0
    
    def _calculate_text_similarity(self, text1: str, text2: str) -> float:
        """
        텍스트 기반 유사도 계산 (fallback)
        
        공통 단어 비율 기반 간단한 유사도
        
        Args:
            text1: 첫 번째 텍스트
            text2: 두 번째 텍스트
        
        Returns:
            유사도 점수 (0.0 ~ 1.0)
        """
        # 공통 단어 비율 계산
        words1 = set(text1.split())
        words2 = set(text2.split())
        
        if not words1 or not words2:
            return 0.0
        
        intersection = words1 & words2
        union = words1 | words2
        
        return len(intersection) / len(union) if union else 0.0