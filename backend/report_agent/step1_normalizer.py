"""
Step1Normalizer

A1과 A3 결과를 파싱하여 사용자 조항 기준으로 정규화합니다.
"""

import logging
import re
from typing import Dict, List, Any

from backend.shared.services.knowledge_base_loader import KnowledgeBaseLoader
from backend.report_agent.exceptions import ParsingError, ClauseReferenceError

logger = logging.getLogger(__name__)


class Step1Normalizer:
    """
    Step 1: 1차 정규화 (사용자 조항 기준)
    
    - A1 파싱: is_truly_missing, matched articles
    - A3 파싱: matched, insufficient, missing
    - 조 단위 확장: "제23조" → 모든 하위 항목
    - 중복 제거: A3에서 언급된 항목을 overall_missing에서 제거
    """
    
    def __init__(self, kb_loader: KnowledgeBaseLoader):
        """
        Step1Normalizer 초기화
        
        Args:
            kb_loader: KnowledgeBaseLoader 인스턴스
        """
        self.kb_loader = kb_loader
        self.std_chunks = None
    
    def normalize(self, a1_result: Dict[str, Any], a3_result: Dict[str, Any], 
                  contract_type: str) -> Dict[str, Any]:
        """
        A1, A3 결과를 사용자 조항 기준으로 정규화
        
        Args:
            a1_result: A1 노드 결과
            a3_result: A3 노드 결과
            contract_type: 계약 유형
            
        Returns:
            {
                "overall_missing_clauses": List[str],
                "user_articles": Dict[str, Dict]
            }
        """
        logger.info(f"Step 1 정규화 시작 (계약 유형: {contract_type})")
        
        try:
            # 표준계약서 청크 로드
            self.std_chunks = self.kb_loader.load_chunks(contract_type)
            if not self.std_chunks:
                self.std_chunks = []
            logger.info(f"표준계약서 청크 {len(self.std_chunks)}개 로드 완료")
            
            # A1 파싱
            overall_missing = self._parse_a1_missing(a1_result)
            user_articles = self._parse_a1_matching(a1_result)
            logger.info(f"A1 파싱 완료: 전역 누락 {len(overall_missing)}개, "
                       f"매칭된 사용자 조항 {len(user_articles)}개")
            
            # A3 파싱 (기존 user_articles에 추가)
            self._parse_a3_results(a3_result, user_articles)
            logger.info(f"A3 파싱 완료: 총 사용자 조항 {len(user_articles)}개")
            
            # 중복 제거
            overall_missing = self._remove_duplicates(overall_missing, user_articles)
            logger.info(f"중복 제거 후: 전역 누락 {len(overall_missing)}개")
            
            result = {
                "overall_missing_clauses": overall_missing,
                "user_articles": user_articles
            }
            
            logger.info("Step 1 정규화 완료")
            return result
            
        except Exception as e:
            logger.error(f"Step 1 정규화 실패: {e}")
            raise ParsingError(f"A1/A3 결과 정규화 실패: {e}") from e
    
    def _parse_a1_missing(self, a1_result: Dict[str, Any]) -> List[str]:
        """
        A1 Stage 2에서 is_truly_missing: true 추출 및 하위 항목 확장
        
        Args:
            a1_result: A1 노드 결과
            
        Returns:
            overall_missing 표준 항목 ID 목록
        """
        overall_missing = []
        
        for item in a1_result.get("missing_article_analysis", []):
            if item.get("is_truly_missing"):
                std_article_id = item["standard_article_id"]
                # 조 단위 ID와 모든 하위 항목 ID 추가
                clause_ids = self._expand_article_to_clauses(std_article_id)
                overall_missing.extend(clause_ids)
                logger.debug(f"{std_article_id}에 대해 {len(clause_ids)}개 조항 추가")
        
        return overall_missing
    
    def _parse_a1_matching(self, a1_result: Dict[str, Any]) -> Dict[str, Dict]:
        """
        A1 matching_details에서 매칭된 표준 조항 추출
        
        Args:
            a1_result: A1 노드 결과
            
        Returns:
            user_articles 딕셔너리
        """
        user_articles = {}
        
        for detail in a1_result.get("matching_details", []):
            if detail.get("matched"):
                user_article_no = f"user_article_{detail['user_article_no']}"
                matched_ids = detail.get("matched_articles_global_ids", [])
                user_articles[user_article_no] = {
                    "matched": matched_ids,
                    "insufficient": [],
                    "missing": []
                }
                logger.debug(f"{user_article_no}: 매칭된 조항 {len(matched_ids)}개")
        
        return user_articles
    
    def _parse_a3_results(self, a3_result: Dict[str, Any], user_articles: Dict[str, Dict]):
        """
        A3 결과를 user_articles에 추가 (matched, insufficient, missing)
        
        Args:
            a3_result: A3 노드 결과
            user_articles: 기존 user_articles (A1에서 생성)
        """
        for article in a3_result.get("article_analysis", []):
            user_article_no = f"user_article_{article['user_article_no']}"
            
            # user_articles에 없으면 초기화
            if user_article_no not in user_articles:
                user_articles[user_article_no] = {
                    "matched": [],
                    "insufficient": [],
                    "missing": []
                }
            
            # A3 matched_articles 추가 (A1 오탐지 복구)
            if article.get("matched_articles"):
                for matched in article["matched_articles"]:
                    global_id = matched.get("global_id")
                    if global_id and global_id not in user_articles[user_article_no]["matched"]:
                        user_articles[user_article_no]["matched"].append(global_id)
            
            # insufficient/missing 파싱
            suggestions = article.get("suggestions", [])
            for suggestion in suggestions:
                # missing_items는 이미 global_id 리스트
                missing_items = suggestion.get("missing_items", [])
                if missing_items:
                    user_articles[user_article_no]["missing"].extend(missing_items)
                    logger.debug(f"{user_article_no}: missing {len(missing_items)}개 추가")
                
                # insufficient_items도 이미 global_id 리스트
                insufficient_items = suggestion.get("insufficient_items", [])
                if insufficient_items:
                    user_articles[user_article_no]["insufficient"].extend(insufficient_items)
                    logger.debug(f"{user_article_no}: insufficient {len(insufficient_items)}개 추가")
    
    def _extract_clause_references(self, text: str) -> List[str]:
        """
        정규식으로 "제N조", "제N조 제M항", "제N조 제M호" 추출 및 global_id 매핑
        
        Args:
            text: 분석 텍스트
            
        Returns:
            global_id 목록
        """
        clause_ids = []
        
        # 정규식 패턴
        patterns = [
            r'제(\d+)조\s*제(\d+)호',  # 제N조 제M호
            r'제(\d+)조\s*제(\d+)항',  # 제N조 제M항
            r'제(\d+)조'              # 제N조
        ]
        
        for pattern in patterns:
            matches = re.findall(pattern, text)
            for match in matches:
                if isinstance(match, tuple):
                    if len(match) == 2:
                        # 제N조 제M항 or 제N조 제M호
                        article_no = int(match[0])
                        sub_no = int(match[1])
                        # 조 단위 참조인 경우 확장
                        if '호' in pattern:
                            # 제N조 제M호 형식
                            clause_ref = f"제{article_no}조 제{sub_no}호"
                        else:
                            # 제N조 제M항 형식
                            clause_ref = f"제{article_no}조 제{sub_no}항"
                        ids = self._expand_article_to_clauses(clause_ref)
                        clause_ids.extend(ids)
                    else:
                        # 제N조만
                        article_no = int(match)
                        clause_ref = f"제{article_no}조"
                        ids = self._expand_article_to_clauses(clause_ref)
                        clause_ids.extend(ids)
                else:
                    # 제N조만
                    article_no = int(match)
                    clause_ref = f"제{article_no}조"
                    ids = self._expand_article_to_clauses(clause_ref)
                    clause_ids.extend(ids)
        
        return list(set(clause_ids))  # 중복 제거
    
    def _expand_article_to_clauses(self, article_ref: str) -> List[str]:
        """
        조 단위 참조를 모든 하위 항목 ID로 확장
        
        Args:
            article_ref: 조항 참조 (예: "제23조", "urn:std:provide:art:023")
            
        Returns:
            global_id 목록
        """
        if not self.std_chunks:
            logger.warning("표준계약서 청크가 로드되지 않음")
            return []
        
        # article_ref에서 조 번호 추출
        if article_ref.startswith("urn:"):
            # 이미 global_id 형식
            article_no_match = re.search(r':art:(\d+)', article_ref)
            if article_no_match:
                article_no = int(article_no_match.group(1))
            else:
                return [article_ref]
        else:
            # "제N조" 형식
            article_no_match = re.search(r'제(\d+)조', article_ref)
            if not article_no_match:
                logger.warning(f"조항 번호 추출 실패: {article_ref}")
                return []
            article_no = int(article_no_match.group(1))
        
        # 해당 조의 모든 청크 찾기
        clause_ids = []
        for chunk in self.std_chunks:
            global_id = chunk.get("global_id", "")
            if f":art:{article_no:03d}" in global_id:
                clause_ids.append(global_id)
        
        if not clause_ids:
            logger.warning(f"제{article_no}조에 대한 조항을 찾을 수 없음")
        
        return clause_ids
    
    def _remove_duplicates(self, overall_missing: List[str], 
                          user_articles: Dict[str, Dict]) -> List[str]:
        """
        A3에서 언급된 항목을 overall_missing에서 제거
        
        A1 오탐지 복구된 항목은 이미 A3에 포함되어 있으므로,
        A3에서 언급된 모든 ID를 overall_missing에서 제거한다.
        
        Args:
            overall_missing: A1 전역 누락 목록
            user_articles: 사용자 조항별 데이터
            
        Returns:
            중복 제거된 overall_missing 목록
        """
        # user_articles의 모든 insufficient/missing ID 수집
        mentioned_ids = set()
        for article_data in user_articles.values():
            mentioned_ids.update(article_data.get("insufficient", []))
            mentioned_ids.update(article_data.get("missing", []))
        
        # overall_missing에서 제거 (A3에서 언급된 것은 전역 누락 아님)
        filtered = [id for id in overall_missing if id not in mentioned_ids]
        
        removed_count = len(overall_missing) - len(filtered)
        if removed_count > 0:
            logger.info(f"overall_missing에서 {removed_count}개 항목 제거 "
                       f"(A3 사용자 조항에서 언급됨)")
        
        return filtered
