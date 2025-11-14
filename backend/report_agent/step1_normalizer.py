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
                  a3_recovered_result: Dict[str, Any] = None,
                  contract_type: str = None) -> Dict[str, Any]:
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
            
            # A3 Primary 파싱 (기존 user_articles에 추가)
            self._parse_a3_results(a3_result, user_articles, contract_type)
            logger.info(f"A3 Primary 파싱 완료: 총 사용자 조항 {len(user_articles)}개")
            
            # A3 Recovered 파싱 및 병합 (있는 경우)
            if a3_recovered_result:
                self._merge_a3_recovered_results(a3_recovered_result, user_articles, contract_type)
                logger.info(f"A3 Recovered 병합 완료")
            
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
                
                # verification_details에서 reasoning 추출
                matched_with_reasoning = []
                verification_details = detail.get("verification_details", [])
                
                for std_id in matched_ids:
                    # 해당 std_id의 reasoning 찾기
                    reasoning = ""
                    for verification in verification_details:
                        candidate_id = verification.get("candidate_id", "")
                        if candidate_id in std_id or std_id.endswith(candidate_id):
                            if verification.get("is_match"):
                                reasoning = verification.get("reasoning", "")
                                logger.debug(f"  {std_id}: reasoning 발견 - {reasoning[:50]}...")
                                break
                    
                    if not reasoning:
                        logger.warning(f"  {std_id}: reasoning 없음 (verification_details: {len(verification_details)}개)")
                    
                    matched_with_reasoning.append({
                        "std_clause_id": std_id,
                        "analysis": reasoning if reasoning else "표준 조항과 매칭됨"
                    })
                
                user_articles[user_article_no] = {
                    "matched": matched_with_reasoning,
                    "insufficient": [],
                    "missing": []
                }
                logger.debug(f"{user_article_no}: 매칭된 조항 {len(matched_ids)}개")
        
        return user_articles
    
    def _parse_a3_results(self, a3_result: Dict[str, Any], user_articles: Dict[str, Dict], contract_type: str):
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
            
            # A3 matched_articles 추가 (항 단위로 분해)
            if article.get("matched_articles"):
                logger.info(f"{user_article_no}: A3 matched_articles {len(article['matched_articles'])}개")
                for matched in article["matched_articles"]:
                    # matched_chunks에서 실제 매칭된 하위 항목의 global_id 추출
                    matched_chunks = matched.get("matched_chunks", [])
                    matched_sub_items = matched.get("matched_sub_items", [])
                    sub_items = matched.get("sub_items", [])  # A3 상세 분석 결과
                    
                    logger.info(f"  - 표준 조항: {matched.get('global_id')}, "
                               f"청크 {len(matched_chunks)}개, matched_sub_items: {matched_sub_items}, "
                               f"sub_items: {len(sub_items)}개")
                    
                    if matched_chunks:
                        # matched_sub_items가 있으면 해당 인덱스만 사용
                        if matched_sub_items:
                            logger.info(f"    matched_sub_items 사용: {matched_sub_items}")
                            for idx in matched_sub_items:
                                if idx < len(matched_chunks):
                                    chunk_global_id = matched_chunks[idx].get("global_id")
                                    logger.info(f"      [{idx}] {chunk_global_id}")
                                    
                                    # A3 sub_items에서 해당 인덱스의 summary 찾기
                                    summary = ""
                                    for sub_item in sub_items:
                                        if sub_item.get("index") == idx and sub_item.get("fidelity") == "sufficient":
                                            summary = sub_item.get("summary", "")
                                            break
                                    
                                    if chunk_global_id:
                                        # 중복 체크: matched, insufficient, missing 모두 확인
                                        existing_in_matched = [m.get("std_clause_id") if isinstance(m, dict) else m 
                                                              for m in user_articles[user_article_no]["matched"]]
                                        existing_in_insufficient = [m.get("std_clause_id") if isinstance(m, dict) else m 
                                                                   for m in user_articles[user_article_no]["insufficient"]]
                                        existing_in_missing = [m.get("std_clause_id") if isinstance(m, dict) else m 
                                                              for m in user_articles[user_article_no]["missing"]]
                                        
                                        if chunk_global_id in existing_in_insufficient or chunk_global_id in existing_in_missing:
                                            logger.info(f"        → matched 추가 스킵 (insufficient/missing에 이미 존재)")
                                        elif chunk_global_id not in existing_in_matched:
                                            logger.info(f"        → matched에 추가 (summary: {summary[:50] if summary else 'N/A'})")
                                            user_articles[user_article_no]["matched"].append({
                                                "std_clause_id": chunk_global_id,
                                                "analysis": summary if summary else "A3 상세 분석에서 매칭됨"
                                            })
                                        else:
                                            logger.info(f"        → 이미 존재 (중복 제거)")
                        else:
                            # matched_sub_items가 없으면 모든 청크 사용
                            for idx, chunk in enumerate(matched_chunks):
                                chunk_global_id = chunk.get("global_id")
                                
                                # A3 sub_items에서 해당 인덱스의 summary 찾기
                                summary = ""
                                for sub_item in sub_items:
                                    if sub_item.get("index") == idx and sub_item.get("fidelity") == "sufficient":
                                        summary = sub_item.get("summary", "")
                                        break
                                
                                if chunk_global_id:
                                    # 중복 체크 (std_clause_id 기준)
                                    existing_ids = [m.get("std_clause_id") if isinstance(m, dict) else m 
                                                   for m in user_articles[user_article_no]["matched"]]
                                    if chunk_global_id not in existing_ids:
                                        user_articles[user_article_no]["matched"].append({
                                            "std_clause_id": chunk_global_id,
                                            "analysis": summary if summary else "A3 상세 분석에서 매칭됨"
                                        })
                    else:
                        # fallback: 조 단위 global_id 사용
                        global_id = matched.get("global_id")
                        if global_id:
                            # 중복 체크 (std_clause_id 기준)
                            existing_ids = [m.get("std_clause_id") if isinstance(m, dict) else m 
                                           for m in user_articles[user_article_no]["matched"]]
                            if global_id not in existing_ids:
                                user_articles[user_article_no]["matched"].append({
                                    "std_clause_id": global_id,
                                    "analysis": "A3 상세 분석에서 매칭됨"
                                })
            
            # insufficient/missing 파싱 (JSON 구조)
            # A3 matched_articles에서 sub_items를 먼저 수집 (summary 활용)
            # 모든 fidelity 값 포함 (sufficient, insufficient, missing)
            sub_items_by_global_id = {}
            for matched in article.get("matched_articles", []):
                for sub_item in matched.get("sub_items", []):
                    # 각 sub_item의 global_id 찾기
                    idx = sub_item.get("index")
                    matched_chunks = matched.get("matched_chunks", [])
                    if idx is not None and idx < len(matched_chunks):
                        chunk_global_id = matched_chunks[idx].get("global_id")
                        if chunk_global_id:
                            sub_items_by_global_id[chunk_global_id] = sub_item
                            logger.debug(f"    sub_item 매핑: {chunk_global_id} -> {sub_item.get('fidelity')} ({sub_item.get('summary', '')[:50]})")
            
            suggestions = article.get("suggestions", [])
            for suggestion in suggestions:
                # missing_items는 이제 JSON 객체 리스트
                missing_items = suggestion.get("missing_items", [])
                for item in missing_items:
                    if isinstance(item, dict):
                        # JSON 구조: {"std_article": "제X조", "std_clause": "제Y항", "reason": "..."}
                        std_article = item.get("std_article", "")
                        std_clause = item.get("std_clause", "")
                        reason = item.get("reason", "")
                        
                        # global_id 매핑
                        global_id = self._map_to_global_id(std_article, std_clause, contract_type)
                        if global_id:
                            # A3 sub_items에서 summary 찾기
                            sub_item = sub_items_by_global_id.get(global_id)
                            if sub_item and sub_item.get("fidelity") == "missing":
                                summary = sub_item.get("summary", "")
                                analysis = summary if summary else f"{std_article} {std_clause}: {reason}"
                                logger.info(f"    missing: {global_id} -> A3 summary 사용")
                            else:
                                analysis = f"{std_article} {std_clause}: {reason}"
                                logger.info(f"    missing: {global_id} -> reason 사용 (sub_item 없음)")
                            
                            user_articles[user_article_no]["missing"].append({
                                "std_clause_id": global_id,
                                "analysis": analysis
                            })
                        else:
                            logger.warning(f"{user_article_no}: global_id 매핑 실패: {std_article} {std_clause}")
                    elif isinstance(item, str):
                        # Fallback: 텍스트 형식 (하위 호환성)
                        logger.warning(f"{user_article_no}: 텍스트 형식 감지 (JSON 권장): {item[:50]}...")
                        user_articles[user_article_no]["missing"].append({
                            "std_clause_id": item,
                            "analysis": item
                        })
                
                logger.debug(f"{user_article_no}: missing {len(missing_items)}개 추가")
                
                # insufficient_items도 동일하게 처리
                insufficient_items = suggestion.get("insufficient_items", [])
                for item in insufficient_items:
                    if isinstance(item, dict):
                        # JSON 구조
                        std_article = item.get("std_article", "")
                        std_clause = item.get("std_clause", "")
                        reason = item.get("reason", "")
                        
                        # global_id 매핑
                        global_id = self._map_to_global_id(std_article, std_clause, contract_type)
                        if global_id:
                            # A3 sub_items에서 summary 찾기
                            sub_item = sub_items_by_global_id.get(global_id)
                            if sub_item and sub_item.get("fidelity") == "insufficient":
                                summary = sub_item.get("summary", "")
                                analysis = summary if summary else f"{std_article} {std_clause}: {reason}"
                                logger.info(f"    insufficient: {global_id} -> A3 summary 사용")
                            else:
                                analysis = f"{std_article} {std_clause}: {reason}"
                                logger.info(f"    insufficient: {global_id} -> reason 사용 (sub_item 없음)")
                            
                            user_articles[user_article_no]["insufficient"].append({
                                "std_clause_id": global_id,
                                "analysis": analysis
                            })
                        else:
                            logger.warning(f"{user_article_no}: global_id 매핑 실패: {std_article} {std_clause}")
                    elif isinstance(item, str):
                        # Fallback: 텍스트 형식
                        logger.warning(f"{user_article_no}: 텍스트 형식 감지 (JSON 권장): {item[:50]}...")
                        user_articles[user_article_no]["insufficient"].append({
                            "std_clause_id": item,
                            "analysis": item
                        })
                
                logger.debug(f"{user_article_no}: insufficient {len(insufficient_items)}개 추가")
    
    def _merge_a3_recovered_results(self, a3_recovered_result: Dict[str, Any], 
                                    user_articles: Dict[str, Dict], contract_type: str):
        """
        A3 Recovered 결과를 user_articles에 병합
        
        Recovered 결과는 A1 재검증 후의 매칭 결과를 기반으로 하므로,
        Primary 결과보다 더 정확합니다. 따라서 Recovered의 insufficient/missing 항목을
        Primary 결과에 추가합니다.
        
        Args:
            a3_recovered_result: A3 Recovered 결과
            user_articles: 기존 user_articles (Primary 결과 포함)
            contract_type: 계약 유형
        """
        logger.info("A3 Recovered 결과 병합 시작")
        
        for article in a3_recovered_result.get("article_analysis", []):
            user_article_no = f"user_article_{article['user_article_no']}"
            
            # user_articles에 없으면 초기화
            if user_article_no not in user_articles:
                user_articles[user_article_no] = {
                    "matched": [],
                    "insufficient": [],
                    "missing": []
                }
            
            # A3 Recovered의 insufficient/missing 항목 추가
            # (matched는 추가하지 않음 - Primary와 중복 방지)
            
            # sub_items 수집 (summary 활용)
            sub_items_by_global_id = {}
            for matched in article.get("matched_articles", []):
                for sub_item in matched.get("sub_items", []):
                    idx = sub_item.get("index")
                    matched_chunks = matched.get("matched_chunks", [])
                    if idx is not None and idx < len(matched_chunks):
                        chunk_global_id = matched_chunks[idx].get("global_id")
                        if chunk_global_id:
                            sub_items_by_global_id[chunk_global_id] = sub_item
            
            suggestions = article.get("suggestions", [])
            recovered_insufficient_count = 0
            recovered_missing_count = 0
            
            for suggestion in suggestions:
                # missing_items 병합
                missing_items = suggestion.get("missing_items", [])
                for item in missing_items:
                    if isinstance(item, dict):
                        std_article = item.get("std_article", "")
                        std_clause = item.get("std_clause", "")
                        reason = item.get("reason", "")
                        
                        global_id = self._map_to_global_id(std_article, std_clause, contract_type)
                        if global_id:
                            # 중복 체크: Primary에 이미 있는지 확인
                            existing_ids = [m.get("std_clause_id") for m in user_articles[user_article_no]["missing"]]
                            
                            if global_id not in existing_ids:
                                # A3 sub_items에서 summary 찾기
                                sub_item = sub_items_by_global_id.get(global_id)
                                if sub_item and sub_item.get("fidelity") == "missing":
                                    summary = sub_item.get("summary", "")
                                    analysis = summary if summary else f"{std_article} {std_clause}: {reason}"
                                else:
                                    analysis = f"{std_article} {std_clause}: {reason}"
                                
                                user_articles[user_article_no]["missing"].append({
                                    "std_clause_id": global_id,
                                    "analysis": analysis
                                })
                                recovered_missing_count += 1
                                logger.info(f"  {user_article_no}: Recovered missing 추가 - {global_id}")
                
                # insufficient_items 병합
                insufficient_items = suggestion.get("insufficient_items", [])
                for item in insufficient_items:
                    if isinstance(item, dict):
                        std_article = item.get("std_article", "")
                        std_clause = item.get("std_clause", "")
                        reason = item.get("reason", "")
                        
                        global_id = self._map_to_global_id(std_article, std_clause, contract_type)
                        if global_id:
                            # 중복 체크: Primary에 이미 있는지 확인
                            existing_ids = [m.get("std_clause_id") for m in user_articles[user_article_no]["insufficient"]]
                            
                            if global_id not in existing_ids:
                                # A3 sub_items에서 summary 찾기
                                sub_item = sub_items_by_global_id.get(global_id)
                                if sub_item and sub_item.get("fidelity") == "insufficient":
                                    summary = sub_item.get("summary", "")
                                    analysis = summary if summary else f"{std_article} {std_clause}: {reason}"
                                else:
                                    analysis = f"{std_article} {std_clause}: {reason}"
                                
                                user_articles[user_article_no]["insufficient"].append({
                                    "std_clause_id": global_id,
                                    "analysis": analysis
                                })
                                recovered_insufficient_count += 1
                                logger.info(f"  {user_article_no}: Recovered insufficient 추가 - {global_id}")
            
            if recovered_insufficient_count > 0 or recovered_missing_count > 0:
                logger.info(f"{user_article_no}: Recovered 병합 완료 - "
                          f"insufficient {recovered_insufficient_count}개, missing {recovered_missing_count}개 추가")
    
    def _map_to_global_id(self, std_article: str, std_clause: str, contract_type: str) -> str:
        """
        표준계약서 조항을 global_id로 매핑
        
        Args:
            std_article: "제X조" 형식
            std_clause: "제Y항" 또는 "제Y호" 형식
            contract_type: 계약 유형
            
        Returns:
            global_id (예: "urn:std:provide:art:005:cla:001")
        """
        if not self.std_chunks:
            logger.warning("표준계약서 청크가 로드되지 않음")
            return ""
        
        # 조 번호 추출
        article_match = re.search(r'제(\d+)조', std_article)
        if not article_match:
            logger.warning(f"조 번호 추출 실패: {std_article}")
            return ""
        article_no = int(article_match.group(1))
        
        # 항/호 번호 추출
        clause_no = None
        sub_no = None
        is_article_text = False  # 조본문 여부
        
        if '조본문' in std_clause or std_clause.strip() == '':
            # 조본문 (항/호 없음)
            is_article_text = True
        elif '항' in std_clause:
            clause_match = re.search(r'제(\d+)항', std_clause)
            if clause_match:
                clause_no = int(clause_match.group(1))
        elif '호' in std_clause:
            sub_match = re.search(r'제(\d+)호', std_clause)
            if sub_match:
                sub_no = int(sub_match.group(1))
        
        # global_id 찾기
        for chunk in self.std_chunks:
            global_id = chunk.get("global_id", "")
            
            # 조 번호 매칭
            if f":art:{article_no:03d}" not in global_id:
                continue
            
            # 조본문 매칭 (:att)
            if is_article_text:
                if ":att" in global_id:
                    return global_id
            # 항 번호 매칭 (cla)
            elif clause_no is not None:
                if f":cla:{clause_no:03d}" in global_id:
                    return global_id
            # 호 번호 매칭 (sub)
            elif sub_no is not None:
                if f":sub:{sub_no:03d}" in global_id:
                    return global_id
        
        logger.warning(f"global_id를 찾을 수 없음: {std_article} {std_clause}")
        return ""
    
    def _extract_clause_references(self, text: str) -> List[str]:
        """
        정규식으로 "제N조", "제N조 제M항", "제N조 제M호" 추출 및 global_id 매핑
        
        "표준계약서 제X조 제Y항: 설명" 형식도 처리
        
        Args:
            text: 분석 텍스트
            
        Returns:
            global_id 목록
        """
        clause_ids = []
        
        # 정규식 패턴 (우선순위 순서)
        # 주의: "및" 패턴은 A3 프롬프트에서 금지했으므로 경고용으로만 유지
        patterns = [
            # "표준계약서 제N조 제M항 및 제K항" 형식 (경고: 이 형식은 사용하지 말아야 함)
            (r'표준계약서\s*제(\d+)조\s*제(\d+)항\s*및\s*제(\d+)항', 'multi_sub_warning'),
            # "표준계약서 제N조 제M항" 형식
            (r'표준계약서\s*제(\d+)조\s*제(\d+)항', 'sub'),
            # "표준계약서 제N조 제M호" 형식
            (r'표준계약서\s*제(\d+)조\s*제(\d+)호', 'item'),
            # "표준계약서 제N조 (제목)" 형식 (괄호 포함)
            (r'표준계약서\s*제(\d+)조\s*\([^)]+\)', 'article'),
            # "표준계약서 제N조" 형식
            (r'표준계약서\s*제(\d+)조', 'article'),
            # "제N조 제M항 및 제K항" 형식 (경고)
            (r'제(\d+)조\s*제(\d+)항\s*및\s*제(\d+)항', 'multi_sub_warning'),
            # "제N조 제M호" 형식
            (r'제(\d+)조\s*제(\d+)호', 'item'),
            # "제N조 제M항" 형식
            (r'제(\d+)조\s*제(\d+)항', 'sub'),
            # "제N조 (제목)" 형식 (괄호 포함)
            (r'제(\d+)조\s*\([^)]+\)', 'article'),
            # "제N조" 형식
            (r'제(\d+)조', 'article')
        ]
        
        for pattern, pattern_type in patterns:
            matches = re.findall(pattern, text)
            for match in matches:
                if pattern_type == 'multi_sub_warning':
                    # 제N조 제M항 및 제K항 (A3 프롬프트 위반)
                    logger.warning(f"A3가 '및' 형식을 사용했습니다 (프롬프트 위반): {text[:100]}")
                    # 첫 번째 항만 사용
                    article_no = int(match[0])
                    sub_no1 = int(match[1])
                    clause_ref = f"제{article_no}조 제{sub_no1}항"
                    ids = self._expand_article_to_clauses(clause_ref)
                    clause_ids.extend(ids)
                elif pattern_type == 'sub':
                    # 제N조 제M항
                    article_no = int(match[0])
                    sub_no = int(match[1])
                    clause_ref = f"제{article_no}조 제{sub_no}항"
                    ids = self._expand_article_to_clauses(clause_ref)
                    clause_ids.extend(ids)
                elif pattern_type == 'item':
                    # 제N조 제M호
                    article_no = int(match[0])
                    item_no = int(match[1])
                    clause_ref = f"제{article_no}조 제{item_no}호"
                    ids = self._expand_article_to_clauses(clause_ref)
                    clause_ids.extend(ids)
                elif pattern_type == 'article':
                    # 제N조만
                    article_no = int(match) if isinstance(match, str) else int(match[0])
                    clause_ref = f"제{article_no}조"
                    ids = self._expand_article_to_clauses(clause_ref)
                    clause_ids.extend(ids)
        
        return list(set(clause_ids))  # 중복 제거
    
    def _expand_article_to_clauses(self, article_ref: str) -> List[str]:
        """
        조항 참조를 global_id로 변환
        
        Args:
            article_ref: 조항 참조 (예: "제23조", "제23조 제2항", "제23조 제3호")
            
        Returns:
            global_id 목록
        """
        if not self.std_chunks:
            logger.warning("표준계약서 청크가 로드되지 않음")
            return []
        
        # article_ref 파싱
        article_no = None
        clause_no = None  # 항 (cla)
        sub_no = None  # 호 (sub)
        
        # "제N조 제M항" 형식
        match = re.search(r'제(\d+)조\s*제(\d+)항', article_ref)
        if match:
            article_no = int(match.group(1))
            clause_no = int(match.group(2))
        else:
            # "제N조 제M호" 형식
            match = re.search(r'제(\d+)조\s*제(\d+)호', article_ref)
            if match:
                article_no = int(match.group(1))
                sub_no = int(match.group(2))
            else:
                # "제N조" 형식
                match = re.search(r'제(\d+)조', article_ref)
                if match:
                    article_no = int(match.group(1))
        
        if not article_no:
            logger.warning(f"조항 번호 추출 실패: {article_ref}")
            return []
        
        # 해당 조항의 청크 찾기
        clause_ids = []
        for chunk in self.std_chunks:
            global_id = chunk.get("global_id", "")
            
            # 조 번호 매칭
            if f":art:{article_no:03d}" not in global_id:
                continue
            
            # 항 번호가 지정된 경우 (cla)
            if clause_no is not None:
                if f":cla:{clause_no:03d}" in global_id:
                    clause_ids.append(global_id)
            # 호 번호가 지정된 경우 (sub)
            elif sub_no is not None:
                if f":sub:{sub_no:03d}" in global_id:
                    clause_ids.append(global_id)
            # 조만 지정된 경우 (모든 하위 항목 포함)
            else:
                clause_ids.append(global_id)
        
        if not clause_ids:
            logger.warning(f"{article_ref}에 대한 조항을 찾을 수 없음")
        
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
            # 이제 insufficient/missing이 딕셔너리 리스트이므로 std_clause_id 추출
            for item in article_data.get("insufficient", []):
                if isinstance(item, dict):
                    mentioned_ids.add(item.get("std_clause_id"))
                else:
                    mentioned_ids.add(item)  # 하위 호환성
            
            for item in article_data.get("missing", []):
                if isinstance(item, dict):
                    mentioned_ids.add(item.get("std_clause_id"))
                else:
                    mentioned_ids.add(item)  # 하위 호환성
        
        # overall_missing에서 제거 (A3에서 언급된 것은 전역 누락 아님)
        filtered = [id for id in overall_missing if id not in mentioned_ids]
        
        removed_count = len(overall_missing) - len(filtered)
        if removed_count > 0:
            logger.info(f"overall_missing에서 {removed_count}개 항목 제거 "
                       f"(A3 사용자 조항에서 언급됨)")
        
        return filtered
