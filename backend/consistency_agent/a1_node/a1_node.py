"""
A1 Node - Completeness Check (완전성 검증)

사용자 계약서 조문별로 표준계약과 매칭하여 누락된 조문을 식별
다단계 검증과 LLM 매칭 검증 수행
"""

import logging
import time
from datetime import datetime
from typing import Dict, Any, List, Set, Optional
from collections import defaultdict
from openai import AzureOpenAI

from .article_matcher import ArticleMatcher
from .matching_verifier import MatchingVerifier

logger = logging.getLogger(__name__)


class CompletenessCheckNode:
    """
    A1 노드 - 완전성 검증
    주요 기능:
    1. 사용자 조문과 표준 조문 매칭 (ArticleMatcher)
    2. LLM 기반 매칭 검증(MatchingVerifier)
    3. 누락 조문 식별 및 보고서 생성
    4. 매칭 결과 DB 저장
    """

    def __init__(
        self,
        knowledge_base_loader,
        azure_client: AzureOpenAI,
        matching_threshold: float = 0.7
    ):
        """
        Args:
            knowledge_base_loader: KnowledgeBaseLoader 서비스
            azure_client: Azure OpenAI 클라이언트
            matching_threshold: 매칭 성공 임계치(기본 0.7)
        """
        self.kb_loader = knowledge_base_loader
        self.azure_client = azure_client
        self.threshold = matching_threshold

        # 내부 컴포넌트 초기화
        self.article_matcher = ArticleMatcher(
            knowledge_base_loader,
            azure_client,
            similarity_threshold=matching_threshold
        )

        self.matching_verifier = MatchingVerifier(
            azure_client,
            model="gpt-4o",
            knowledge_base_loader=knowledge_base_loader
        )

        logger.info("A1 노드 (Completeness Check) 초기화 완료")

    def check_completeness_stage1(
        self,
        contract_id: str,
        user_contract: Dict[str, Any],
        contract_type: str,
        text_weight: float = 0.7,
        title_weight: float = 0.3,
        dense_weight: float = 0.85
    ) -> Dict[str, Any]:
        """
        계약서 완전성 검증 - Stage 1: 매칭 + LLM 검증

        A2/A3가 필요로 하는 매칭 결과를 생성합니다.
        누락 조문은 식별만 하고 재검증은 하지 않습니다 (Stage 2에서 수행).

        Args:
            contract_id: 계약서 ID
            user_contract: 사용자 계약서 파싱 결과
            contract_type: 분류된 계약 유형
            text_weight: 본문 가중치 (기본값 0.7)
            title_weight: 제목 가중치 (기본값 0.3)
            dense_weight: 임베딩가중치 (기본값 0.85)

        Returns:
            완전성 검증 결과 (누락 검증 제외)
            {
                "matching_details": [...],  # A2/A3 필수
                "missing_standard_articles": [...],  # Stage 2에서 사용
                "matched_user_articles": int,
                "total_user_articles": int,
                ...
            }
        """
        start_time = time.time()

        logger.info(f"[A1-S1] 매칭 검증 시작: {contract_id} (type={contract_type})")

        # 사용자 계약서 조항 추출
        user_articles = user_contract.get('articles', [])
        total_user_articles = len(user_articles)

        if not user_articles:
            logger.warning(f"[A1-S1] 검증할 조항이 없습니다")
            return {
                "contract_id": contract_id,
                "contract_type": contract_type,
                "total_user_articles": 0,
                "matched_user_articles": 0,
                "total_standard_articles": 0,
                "matched_standard_articles": 0,
                "missing_standard_articles": [],
                "matching_details": [],
                "processing_time": time.time() - start_time,
                "verification_date": datetime.now().isoformat()
            }

        # 표준계약서 항목 로드
        standard_chunks = self.kb_loader.load_chunks(contract_type)
        if not standard_chunks:
            logger.error(f"[A1-S1] 표준계약서 데이터를 로드 실패: {contract_type}")
            raise ValueError(f"표준계약서 데이터를 로드할 수 없습니다: {contract_type}")

        # 표준계약서의 parent_id 목록 추출
        standard_articles = self._extract_standard_articles(standard_chunks)
        total_standard_articles = len(standard_articles)

        logger.info(f"[A1-S1] 사용자 조문: {total_user_articles}개, 표준 조문: {total_standard_articles}개")

        # 1단계: 모든 사용자 조문과 표준 조문 매칭 수행 (병렬 처리)
        matched_standard_articles: Set[str] = set()  # 매칭된 표준 조문 ID
        matched_user_articles: Set[int] = set()  # 매칭된 사용자조문 번호
        matching_details: List[Dict] = []

        from concurrent.futures import ThreadPoolExecutor, as_completed
        
        logger.info(f"[A1-S1] 🚀 조항 매칭 병렬 처리 시작: {len(user_articles)}개 조항 (max_workers=5)")
        
        def process_single_article(article):
            """단일 조항 처리"""
            try:
                article_result = self._check_article(
                    article,
                    contract_type,
                    contract_id,
                    text_weight,
                    title_weight,
                    dense_weight
                )
                logger.info("----------------------------------------[A1-S1]----------------------------------------")
                return article_result
            except Exception as e:
                logger.error(f"[A1-S1] 조항 검증 실패 (제{article.get('number')}조): {e}")
                logger.info("----------------------------------------[A1-S1]----------------------------------------")
                return None
        
        # 병렬 실행
        with ThreadPoolExecutor(max_workers=5) as executor:
            future_to_article = {
                executor.submit(process_single_article, article): article
                for article in user_articles
            }
            
            for future in as_completed(future_to_article):
                article_result = future.result()
                
                if article_result:
                    matching_details.append(article_result)
                    
                    # 매칭 성공 시 추적
                    if article_result['matched'] and article_result['matched_articles']:
                        matched_user_articles.add(article_result['user_article_no'])
                        for matched_std_id in article_result['matched_articles']:
                            matched_standard_articles.add(matched_std_id)
        
        logger.info(f"[A1-S1] ✨ 조항 매칭 병렬 처리 완료")

        # 2단계: 누락된 표준 조문 식별 (재검증은 하지 않음)
        missing_articles = [
            std_article for std_article in standard_articles
            if std_article['parent_id'] not in matched_standard_articles
        ]

        logger.info(f"[A1-S1] 매칭 완료: 사용자 {len(matched_user_articles)}/{total_user_articles}, "
                   f"표준 {len(matched_standard_articles)}/{total_standard_articles}")
        logger.info(f"[A1-S1] 누락 조문 식별: {len(missing_articles)}개 (재검증은 Stage 2에서 수행)")

        # 3단계: 매칭 안된 사용자 조항 분석
        unmatched_user_articles = [
            article for article in user_articles
            if article.get('number') not in matched_user_articles
        ]

        unmatched_analysis = []
        if unmatched_user_articles:
            logger.info(f"[A1-S1] 매칭 안된 사용자 조항 분석: {len(unmatched_user_articles)}개")
            try:
                unmatched_analysis = self._analyze_unmatched_articles(
                    unmatched_user_articles,
                    contract_type,
                    contract_id
                )
            except Exception as e:
                logger.error(f"[A1-S1] 매칭 안된 조항 분석 실패: {e}")
        else:
            logger.info(f"[A1-S1] 모든 사용자 조항이 표준계약서와 매칭되었습니다")

        # 결과 생성 (missing_article_analysis 없음)
        processing_time = time.time() - start_time

        result = {
            "contract_id": contract_id,
            "contract_type": contract_type,
            "total_user_articles": total_user_articles,
            "matched_user_articles": len(matched_user_articles),
            "unmatched_user_articles_count": len(unmatched_user_articles),  # 추가: 매칭 안된 조항 개수
            "total_standard_articles": total_standard_articles,
            "matched_standard_articles": len(matched_standard_articles),
            "missing_standard_articles": missing_articles,
            "unmatched_user_articles": unmatched_analysis,  # 분석 결과
            "matching_details": matching_details,
            "processing_time": processing_time,
            "verification_date": datetime.now().isoformat()
        }

        logger.info(f"[A1-S1] 매칭 검증 완료: {processing_time:.2f}초")
        logger.info("========================================[A1-S1]========================================")

        return result

    def check_missing_articles(
        self,
        contract_id: str,
        contract_type: str,
        text_weight: float = 0.7,
        title_weight: float = 0.3,
        dense_weight: float = 0.85
    ) -> Dict[str, Any]:
        """
        계약서 완전성 검증 - Stage 2: 누락 조문 재검증

        DB에서 Stage 1 결과를 로드하여 누락 조문만 재검증합니다.
        이 메서드는 A2, A3와 병렬로 실행됩니다.

        Args:
            contract_id: 계약서 ID
            contract_type: 계약 유형
            text_weight: 본문 가중치
            title_weight: 제목 가중치
            dense_weight: 시멘틱 가중치

        Returns:
            누락 검증 결과
            {
                "missing_article_analysis": [...],
                "processing_time": float
            }
        """
        from backend.shared.database import SessionLocal, ValidationResult, ContractDocument

        start_time = time.time()
        logger.info(f"[A1-S2] 누락 조문 재검증 시작: {contract_id}")

        db = SessionLocal()
        try:
            # DB에서 Stage 1 결과 로드
            validation_result = db.query(ValidationResult).filter(
                ValidationResult.contract_id == contract_id
            ).first()

            if not validation_result or not validation_result.completeness_check:
                raise ValueError(f"A1-Stage1 결과를 찾을 수 없습니다: {contract_id}")

            completeness_check = validation_result.completeness_check
            missing_articles = completeness_check.get('missing_standard_articles', [])

            if not missing_articles:
                logger.info(f"[A1-S2] 누락 조문이 없습니다")
                return {
                    "missing_article_analysis": [],
                    "processing_time": time.time() - start_time
                }

            logger.info(f"[A1-S2] 누락 조문: {len(missing_articles)}개")

            # 사용자 계약서 로드 (역방향 검증용)
            contract = db.query(ContractDocument).filter(
                ContractDocument.contract_id == contract_id
            ).first()

            if not contract or not contract.parsed_data:
                raise ValueError(f"계약서 데이터를 찾을 수 없습니다: {contract_id}")

            user_articles = contract.parsed_data.get('articles', [])

            # 누락 조문 재검증
            missing_article_analysis = self._verify_missing_articles(
                missing_articles,
                user_articles,
                contract_type,
                contract_id,
                text_weight,
                title_weight,
                dense_weight
            )

            processing_time = time.time() - start_time

            result = {
                "missing_article_analysis": missing_article_analysis,
                "processing_time": processing_time
            }

            logger.info(f"[A1-S2] 누락 조문 재검증 완료: {len(missing_article_analysis)}개 ({processing_time:.2f}초)")
            logger.info("========================================[A1-S2]========================================")
            logger.info("========================================[A1-S2]========================================")

            return result

        finally:
            db.close()

    def check_completeness(
        self,
        contract_id: str,
        user_contract: Dict[str, Any],
        contract_type: str,
        text_weight: float = 0.7,
        title_weight: float = 0.3,
        dense_weight: float = 0.85
    ) -> Dict[str, Any]:
        """
        계약서 완전성 검증 (전체 - 하위 호환성 유지)

        Stage 1과 Stage 2를 순차적으로 실행하여 전체 검증을 수행합니다.
        병렬 처리가 아닌 기존 순차 방식에서 사용됩니다.

        Args:
            contract_id: 계약서 ID
            user_contract: 사용자 계약서 파싱 결과
            contract_type: 분류된 계약 유형
            text_weight: 본문 가중치 (기본값 0.7)
            title_weight: 제목 가중치 (기본값 0.3)
            dense_weight: 임베딩가중치 (기본값 0.85)

        Returns:
            완전성 검증 결과 (전체)
        """
        start_time = time.time()

        logger.info(f"A1 완전성 검증 시작 (순차): {contract_id} (type={contract_type})")

        # Stage 1: 매칭 + LLM 검증
        stage1_result = self.check_completeness_stage1(
            contract_id,
            user_contract,
            contract_type,
            text_weight,
            title_weight,
            dense_weight
        )

        # Stage 1 결과에서 필요한 데이터 추출
        user_articles = user_contract.get('articles', [])
        missing_articles = stage1_result.get('missing_standard_articles', [])

        # Stage 2: 누락 조문 재검증
        missing_article_analysis = []
        if missing_articles:
            logger.info(f"  누락 조문 재검증 시작: {len(missing_articles)}개")
            missing_article_analysis = self._verify_missing_articles(
                missing_articles,
                user_articles,
                contract_type,
                contract_id,
                text_weight,
                title_weight,
                dense_weight
            )
            logger.info(f"  누락 조문 재검증 완료: {len(missing_article_analysis)}개")

        # 전체 결과 생성 (Stage 1 + Stage 2 통합)
        processing_time = time.time() - start_time

        result = {
            **stage1_result,  # Stage 1 결과 복사
            "missing_article_analysis": missing_article_analysis,  # Stage 2 결과 추가
            "processing_time": processing_time  # 전체 처리 시간으로 덮어쓰기
        }

        logger.info(f"A1 완전성 검증 완료 (순차): {processing_time:.2f}초")
        logger.info("================================================================================")
        logger.info("================================================================================")

        return result

    def _check_article(
        self,
        user_article: Dict[str, Any],
        contract_type: str,
        contract_id: str,
        text_weight: float,
        title_weight: float,
        dense_weight: float
    ) -> Dict[str, Any]:
        """
        단일 조항 완전성 검증
        Args:
            user_article: 사용자 조항
            contract_type: 계약 유형
            contract_id: 계약서ID (토큰 로깅용)
            text_weight: 본문 가중치
            title_weight: 제목 가중치
            dense_weight: 임베딩가중치

        Returns:
            조항 매칭 결과
        """
        article_no = user_article.get('number')
        article_id = user_article.get('article_id')  # user_article_001 형식
        article_title = user_article.get('title', '')

        logger.info(f"[A1-S1] 완전성 검증: {article_title}")

        # 기본 결과 객체
        result = {
            "user_article_no": article_no,
            "user_article_id": article_id,  # 추가
            "user_article_title": article_title,
            "matched": False,
            "matched_articles": [],  # global_id 리스트로 저장될 예정
            "verification_details": []
        }

        try:
            # 1단계: 검색 기반 후보 취합 (ArticleMatcher)
            matching_result = self.article_matcher.find_matching_article(
                user_article,
                contract_type,
                top_k=3,  # 단계별로 top-3까지만 사용
                contract_id=contract_id,
                text_weight=text_weight,
                title_weight=title_weight,
                dense_weight=dense_weight
            )

            if not matching_result['matched'] or not matching_result['matched_articles']:
                logger.warning(f"[A1-S1] 매칭 실패: 검색결과 없음")
                return result

            candidate_articles = matching_result['matched_articles']
            sub_item_results = matching_result.get('sub_item_results', [])  # 하위항목별 매칭 결과
            logger.info(f"[A1-S1] 후보 조문: {len(candidate_articles)}개")

            # 전체 청크 로드 (MatchingVerifier의 참조 해결용)
            self.matching_verifier.set_all_chunks(contract_type)

            # 2단계: LLM 매칭 검증(MatchingVerifier)
            verification_result = self.matching_verifier.verify_matching(
                user_article,
                candidate_articles,
                contract_type,
                top_k=5  # Top-5 조문 LLM 검증
            )

            if verification_result['matched']:
                # ArticleMatcher 결과에서 상세 정보 추출
                selected_parent_ids = verification_result['selected_articles']
                selected_global_ids = []
                matched_details = []

                # 캐시 기반 변환 및 상세 정보 수집
                for parent_id in selected_parent_ids:
                    # ArticleMatcher의 matched_articles에서 찾기
                    found = False
                    for matched in candidate_articles:
                        if matched.get('parent_id') == parent_id:
                            base_global_id = matched.get('base_global_id')
                            if base_global_id:
                                selected_global_ids.append(base_global_id)

                                # 상세 점수 정보 수집
                                matched_chunks = matched.get('matched_chunks', [])

                                # 조 단위 평균 점수 계산
                                avg_dense = sum(c.get('dense_score', 0.0) for c in matched_chunks) / len(matched_chunks) if matched_chunks else 0.0
                                avg_sparse = sum(c.get('sparse_score', 0.0) for c in matched_chunks) / len(matched_chunks) if matched_chunks else 0.0
                                avg_dense_raw = sum(c.get('dense_score_raw', 0.0) for c in matched_chunks) / len(matched_chunks) if matched_chunks else 0.0
                                avg_sparse_raw = sum(c.get('sparse_score_raw', 0.0) for c in matched_chunks) / len(matched_chunks) if matched_chunks else 0.0

                                # 하위항목별 점수 정보
                                sub_items_scores = []
                                for chunk in matched_chunks:
                                    chunk_info = chunk.get('chunk', {})
                                    sub_items_scores.append({
                                        'chunk_id': chunk_info.get('id', ''),
                                        'global_id': chunk_info.get('global_id', ''),
                                        'text': chunk_info.get('text_raw', ''),
                                        'dense_score': chunk.get('dense_score', 0.0),
                                        'dense_score_raw': chunk.get('dense_score_raw', 0.0),
                                        'sparse_score': chunk.get('sparse_score', 0.0),
                                        'sparse_score_raw': chunk.get('sparse_score_raw', 0.0),
                                        'combined_score': chunk.get('score', 0.0)
                                    })

                                detail = {
                                    'parent_id': parent_id,
                                    'global_id': base_global_id,
                                    'title': matched.get('title', ''),
                                    'combined_score': matched.get('score', 0.0),  # 조 전체 종합 점수
                                    'num_sub_items': matched.get('num_sub_items', 0),
                                    'matched_sub_items': matched.get('matched_sub_items', []),
                                    'avg_dense_score': avg_dense,
                                    'avg_dense_score_raw': avg_dense_raw,
                                    'avg_sparse_score': avg_sparse,
                                    'avg_sparse_score_raw': avg_sparse_raw,
                                    'sub_items_scores': sub_items_scores  # 하위항목별 상세 점수
                                }
                                matched_details.append(detail)
                                found = True
                                break

                    if not found:
                        logger.warning(f"[A1-S1] base_global_id를 찾을 수 없음: {parent_id}")

                result['matched'] = True
                result['matched_articles'] = selected_parent_ids  # parent_id 리스트로 저장 (A3/프론트 호환)
                result['matched_articles_global_ids'] = selected_global_ids  # global_id 별도 저장
                result['matched_articles_details'] = matched_details  # 상세 점수 정보
                result['sub_item_results'] = sub_item_results  # 하위항목별 멀티매칭 결과
                result['verification_details'] = verification_result.get('verification_details', [])

                # 디버깅: sub_item_results 로그
                logger.info(f"[A1-S1] sub_item_results 포함: {len(sub_item_results)}개 하위항목")
                for sub_result in sub_item_results:
                    logger.info(f"[A1-S1]   하위항목 {sub_result.get('sub_item_index')}: {len(sub_result.get('matched_articles', []))}개 조")

                logger.info(f"[A1-S1] 매칭 성공: {len(result['matched_articles'])}개 조문")
                for i, (parent_id, global_id) in enumerate(zip(selected_parent_ids, selected_global_ids)):
                    logger.info(f"[A1-S1]   - {parent_id} → {global_id}")
            else:
                logger.warning(f"[A1-S1] 매칭 실패: LLM 검증 통과 못함")

        except Exception as e:
            logger.error(f"[A1-S1] 조항 검증 중 오류: {e}")
            result['error'] = str(e)

        return result

    def _extract_standard_articles(self, chunks: List[Dict]) -> List[Dict]:
        """
        표준계약서 항목 정보를 parent_id 기준으로 그룹화

        Args:
            chunks: 표준계약서 청크 리스트
        Returns:
            조항단위로 그룹화된 정보 리스트 (별지 제외)
        """
        article_map = defaultdict(lambda: {
            'parent_id': None,
            'title': None,
            'chunks': []
        })

        for chunk in chunks:
            parent_id = chunk.get('parent_id')
            if not parent_id:
                continue

            # 별지(exhibit) 제외: parent_id가 "별지"로 시작하는 경우
            if parent_id.startswith('별지'):
                continue

            if article_map[parent_id]['parent_id'] is None:
                article_map[parent_id]['parent_id'] = parent_id
                article_map[parent_id]['title'] = chunk.get('title', '')

            article_map[parent_id]['chunks'].append(chunk)

        # 리스트로 변환 후 정렬
        articles = list(article_map.values())
        articles.sort(key=lambda x: self._extract_article_number(x['parent_id']))

        logger.info(f"  표준 조문 추출 완료: {len(articles)}개 (별지 제외)")

        return articles

    def _extract_article_number(self, parent_id: str) -> int:
        """
        항목ID에서 숫자 추출 (정렬용)

        예: "제3조" -> 3
        """
        import re
        match = re.search(r'\d+', parent_id)
        if match:
            return int(match.group())
        return 999999

    def _extract_global_id_from_article(
        self,
        article: Dict[str, Any],
        contract_type: str
    ) -> str:
        """
        표준 조항 딕셔너리에서 base global_id 추출

        Args:
            article: 표준 조항 딕셔너리 (parent_id, title, chunks 포함)
            contract_type: 계약 유형

        Returns:
            base global_id (예: "urn:std:provide:art:001")
        """
        import re

        # 1. chunks에서 직접 추출 시도
        chunks = article.get('chunks', [])
        if chunks and len(chunks) > 0:
            first_chunk = chunks[0]
            global_id = first_chunk.get('global_id', '')
            if global_id:
                # :att, :sub, :cla 제거
                base_global_id = ':'.join(global_id.split(':')[:5])
                return base_global_id

        # 2. parent_id에서 직접 생성 시도
        parent_id = article.get('parent_id', '')
        match = re.search(r'제(\d+)조', parent_id)
        if match:
            article_num = int(match.group(1))
            return f"urn:std:{contract_type}:art:{article_num:03d}"

        # 3. 최종 fallback
        logger.warning(f"    global_id 생성 실패: {parent_id}")
        return parent_id

    def _verify_missing_articles(
        self,
        missing_articles: List[Dict],
        user_articles: List[Dict],
        contract_type: str,
        contract_id: str,
        text_weight: float,
        title_weight: float,
        dense_weight: float
    ) -> List[Dict]:
        """
        누락 조문 재검증 (역방향 검증)
        
        누락된 것으로 식별된 표준 조문들이 실제로 사용자 계약서에 없는지 재확인
        
        Args:
            missing_articles: 누락된 표준 조문 리스트
            user_articles: 사용자 계약서 조문 리스트
            contract_type: 계약 유형
            contract_id: 계약서 ID
            text_weight: 본문 가중치
            title_weight: 제목 가중치
            dense_weight: 시멘틱 가중치
        
        Returns:
            누락 조문 분석 결과 리스트
            [
                {
                    "standard_article_id": str,
                    "standard_article_title": str,
                    "is_truly_missing": bool,
                    "confidence": float,
                    "matched_user_article": Dict or None,
                    "reasoning": str,
                    "recommendation": str,
                    "evidence": str,
                    "risk_assessment": str,
                    "top_candidates": List[Dict]
                },
                ...
            ]
        """
        analysis_results = []

        # 사용자 조문 FAISS 인덱스 생성 (한 번만)
        logger.info(f"[A1-S2] 사용자 조문 FAISS 인덱스 생성 시작...")
        logger.info(f"[A1-S2]   - 사용자 조문 수: {len(user_articles)}개")
        logger.info(f"[A1-S2]   - contract_id: {contract_id}")

        user_faiss_index, embedding_map = self.article_matcher.build_user_faiss_index(
            user_articles=user_articles,
            contract_id=contract_id
        )

        if user_faiss_index is None:
            logger.error(f"[A1-S2] ❌ FAISS 인덱스 생성 실패 - 누락 검증 중단")
            logger.error(f"[A1-S2]   원인: 임베딩을 하나도 로드하지 못했습니다")
            logger.error(f"[A1-S2]   확인사항: 1) contract_id 정확한지, 2) DB에 임베딩 저장되어 있는지")
            return []

        logger.info(f"[A1-S2] ✓ FAISS 인덱스 생성 완료: {len(embedding_map)}개 하위항목")

        for i, missing_article in enumerate(missing_articles, 1):
            parent_id = missing_article['parent_id']
            title = missing_article['title']

            logger.info(f"[A1-S2] [{i}/{len(missing_articles)}] 누락 조문 재검증: {parent_id} ({title})")
            
            try:
                # 1단계: 역방향 검색 (표준 → 사용자) - FAISS 인덱스 재사용
                user_candidates = self.article_matcher.find_matching_user_articles(
                    standard_article=missing_article,
                    user_faiss_index=user_faiss_index,
                    embedding_map=embedding_map,
                    contract_type=contract_type,
                    top_k=3  # Top-3 후보
                )
                
                # 2단계: LLM 재검증
                verification_result = self.matching_verifier.verify_missing_article_forward(
                    standard_article=missing_article,
                    user_candidates=user_candidates,
                    contract_type=contract_type
                )

                # missing_article의 chunks에서 global_id 추출 (캐시 기반)
                global_id = self._extract_global_id_from_article(missing_article, contract_type)

                # 결과 저장
                analysis_results.append({
                    "standard_article_id": global_id,  # global_id로 저장
                    "standard_article_title": title,
                    "is_truly_missing": verification_result['is_truly_missing'],
                    "confidence": verification_result['confidence'],
                    "matched_user_article": verification_result.get('matched_user_article'),
                    "reasoning": verification_result['reasoning'],
                    "recommendation": verification_result['recommendation'],
                    "evidence": verification_result['evidence'],
                    "risk_assessment": verification_result['risk_assessment'],
                    "top_candidates": user_candidates,
                    "candidates_analysis": verification_result.get('candidates_analysis', [])
                })
                
                # 로깅
                if verification_result['is_truly_missing']:
                    logger.warning(f"[A1-S2]   → 실제 누락 확인 (신뢰도: {verification_result['confidence']:.2f})")
                else:
                    matched_no = verification_result.get('matched_user_article', {}).get('number', '?')
                    logger.info(f"[A1-S2]   → 누락 아님: 제{matched_no}조에 포함 (신뢰도: {verification_result['confidence']:.2f})")

            except Exception as e:
                logger.error(f"[A1-S2]   재검증 실패: {e}")
                # missing_article의 chunks에서 global_id 추출
                global_id = self._extract_global_id_from_article(missing_article, contract_type)
                # 실패 시 기본 결과
                analysis_results.append({
                    "standard_article_id": global_id,  # global_id로 저장
                    "standard_article_title": title,
                    "is_truly_missing": True,
                    "confidence": 0.7,
                    "matched_user_article": None,
                    "reasoning": f"재검증 중 오류 발생: {str(e)}",
                    "recommendation": f"'{title}' 조항 확인 필요",
                    "evidence": "재검증 실패",
                    "risk_assessment": "오류로 인해 정확한 평가 불가",
                    "top_candidates": [],
                    "candidates_analysis": []
                })
            finally:
                # 누락 조문별 재검증 완료 구분선
                logger.info("----------------------------------------[A1-S2]----------------------------------------")

        # 실제 누락 조문 통계
        truly_missing_count = sum(1 for r in analysis_results if r['is_truly_missing'])
        false_positive_count = len(analysis_results) - truly_missing_count

        logger.info(f"[A1-S2] 재검증 요약: 실제 누락 {truly_missing_count}개, 오탐지 {false_positive_count}개")

        return analysis_results

    def _analyze_unmatched_articles(
        self,
        unmatched_articles: List[Dict[str, Any]],
        contract_type: str,
        contract_id: str
    ) -> List[Dict[str, Any]]:
        """
        매칭되지 않은 사용자 조항 분석
        
        정방향 매칭에서 0.7 이상 점수를 받지 못한 조항들을 분석하여:
        1. additional (추가 조항): 표준에 없는 새로운 조항
        2. modified (변형 조항): 표준과 유사하지만 매칭 실패
        3. irrelevant (불필요 조항): 계약과 무관한 내용
        
        Args:
            unmatched_articles: 매칭 실패한 사용자 조항 리스트
            contract_type: 계약 유형
            contract_id: 계약서 ID
        
        Returns:
            분석 결과 리스트
        """
        if not unmatched_articles:
            return []
        
        logger.info(f"[Unmatched] 매칭 안된 조항 분석 시작: {len(unmatched_articles)}개")
        
        analysis_results = []
        
        for article in unmatched_articles:
            try:
                result = self._analyze_single_unmatched_article(
                    article, contract_type, contract_id
                )
                analysis_results.append(result)
                
                logger.info(f"[Unmatched] 제{article.get('number')}조: {result['category']} "
                          f"(신뢰도: {result['confidence']:.2f}, 위험도: {result['risk_level']})")
            
            except Exception as e:
                logger.error(f"[Unmatched] 제{article.get('number')}조 분석 실패: {e}")
                # 실패 시 기본 결과
                analysis_results.append({
                    "user_article_no": article.get('number'),
                    "user_article_title": article.get('title', ''),
                    "user_article_text": article.get('text', ''),
                    "category": "unknown",
                    "confidence": 0.0,
                    "reasoning": f"분석 중 오류 발생: {str(e)}",
                    "recommendation": "수동 검토 필요",
                    "risk_level": "medium"
                })
        
        # 통계
        categories = {}
        for result in analysis_results:
            cat = result['category']
            categories[cat] = categories.get(cat, 0) + 1
        
        logger.info(f"[Unmatched] 분석 완료: {categories}")
        
        return analysis_results
    
    def _analyze_single_unmatched_article(
        self,
        article: Dict[str, Any],
        contract_type: str,
        contract_id: str
    ) -> Dict[str, Any]:
        """단일 매칭 안된 조항 분석"""
        
        article_no = article.get('number')
        article_title = article.get('title', '')
        article_text = article.get('text', '')
        
        # LLM 프롬프트
        prompt = self._build_unmatched_analysis_prompt(
            article_no, article_title, article_text, contract_type
        )
        
        # LLM 호출
        response = self.azure_client.chat.completions.create(
            model="gpt-4o",
            messages=[
                {"role": "system", "content": "당신은 데이터 계약서 분석 전문가입니다."},
                {"role": "user", "content": prompt}
            ],
            temperature=0.1
        )
        
        # 응답 파싱
        content = response.choices[0].message.content
        parsed = self._parse_unmatched_llm_response(content)
        
        return {
            "user_article_no": article_no,
            "user_article_title": article_title,
            "user_article_text": article_text,
            **parsed
        }
    
    def _build_unmatched_analysis_prompt(
        self,
        article_no: int,
        article_title: str,
        article_text: str,
        contract_type: str
    ) -> str:
        """매칭 안된 조항 분석 프롬프트 생성"""
        
        return f"""
다음은 {contract_type} 유형의 사용자 계약서에서 표준계약서와 매칭되지 않은 조항입니다.

**제{article_no}조 ({article_title})**
{article_text}

**분석 목적**: 
이 조항이 표준계약서에 없는 이유를 파악하고, 사용자에게 적절한 가이드를 제공합니다.

**분류 기준**:

1. **additional (추가 조항)**: 
   - 표준계약서에는 없지만 사용자가 의도적으로 추가한 조항
   - 특수한 요구사항이나 추가 의무사항
   - 예: "데이터 품질 보증", "정기 보고 의무", "감사 협조", "특수 보안 요구사항"
   - **판단 기준**: 내용이 계약 이행에 도움이 되는가?

2. **modified (변형 조항)**: 
   - 표준계약서의 특정 조항과 내용은 유사하지만 제목/구조가 달라서 자동 매칭 실패
   - 예: 표준 "제3조(데이터 제공 범위 및 방식)" → 사용자 "제3조(제공 데이터의 범위)"
   - **판단 기준**: 표준 조항의 일부 내용이 누락되었을 가능성이 있는가?

3. **irrelevant (불필요 조항)**: 
   - 계약 내용과 직접 관련 없는 형식적 요소
   - 예: 목차, 부록, 서식, 일반적인 법률 조항(관할법원, 준거법)
   - **판단 기준**: 계약 이행에 실질적 영향이 없는가?

**응답 형식 (JSON):**
```json
{{
  "category": "additional|modified|irrelevant",
  "confidence": 0.0-1.0,
  "reasoning": "분류 근거 (1-2문장)",
  "recommendation": "권장 조치 (1-2문장)",
  "risk_level": "low|medium|high"
}}
```

**위험도 기준:**
- **high**: 중요한 표준 조항이 변형되어 필수 내용이 누락되었을 가능성
- **medium**: 검토가 필요한 추가 조항 또는 변형 조항
- **low**: 문제없는 추가 조항 또는 불필요한 조항

**중요**: 
- "additional"은 표준에 없는 **새로운** 내용
- "modified"는 표준에 있는 조항의 **변형**
- "irrelevant"는 계약과 **무관**한 내용
"""
    
    def _parse_unmatched_llm_response(self, content: str) -> Dict[str, Any]:
        """LLM 응답 파싱"""
        import json
        import re
        
        try:
            # JSON 블록 추출
            json_match = re.search(r'```json\s*(\{.*?\})\s*```', content, re.DOTALL)
            if json_match:
                json_str = json_match.group(1)
                parsed = json.loads(json_str)
                return parsed
            
            # JSON 블록 없이 직접 JSON인 경우
            parsed = json.loads(content)
            return parsed
        
        except Exception as e:
            logger.warning(f"LLM 응답 파싱 실패: {e}")
            # 기본값 반환
            return {
                "category": "unknown",
                "confidence": 0.5,
                "reasoning": "응답 파싱 실패",
                "recommendation": "수동 검토 필요",
                "risk_level": "medium"
            }
