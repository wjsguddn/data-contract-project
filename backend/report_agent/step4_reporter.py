"""
Step4Reporter

통계 및 포맷팅을 포함한 최종 보고서를 생성합니다.
"""

import logging
from datetime import datetime
from typing import Dict, List, Any

logger = logging.getLogger(__name__)


class Step4Reporter:
    """
    Step 4: 최종 보고서 생성
    
    - 요약 통계 계산
    - overall_missing_clauses 포맷팅
    - user_articles 포맷팅
    - 메타데이터 추가
    """
    
    def __init__(self, kb_loader: 'KnowledgeBaseLoader' = None):
        """
        Step4Reporter 초기화
        
        Args:
            kb_loader: KnowledgeBaseLoader 인스턴스 (표준계약서 로드용)
        """
        from backend.shared.services.knowledge_base_loader import KnowledgeBaseLoader
        from openai import AzureOpenAI
        import os
        
        self.kb_loader = kb_loader or KnowledgeBaseLoader()
        self.std_chunks_cache = {}  # 표준계약서 청크 캐시
        
        # Azure OpenAI 클라이언트 초기화
        self.client = None
        try:
            self.client = AzureOpenAI(
                api_key=os.getenv("AZURE_OPENAI_API_KEY"),
                api_version="2024-08-01-preview",
                azure_endpoint=os.getenv("AZURE_OPENAI_ENDPOINT")
            )
            logger.info("Step4Reporter: Azure OpenAI 클라이언트 초기화 성공")
        except Exception as e:
            logger.warning(f"Step4Reporter: Azure OpenAI 클라이언트 초기화 실패: {e}. 서술형 보고서 생성 불가")
    
    def generate_final_report(self, step3_result: Dict[str, Any], 
                             contract_id: str, contract_type: str,
                             user_contract_data: Dict[str, Any],
                             a1_result: Dict[str, Any] = None) -> Dict[str, Any]:
        """
        최종 보고서 생성
        
        Args:
            step3_result: Step 3 결과
            contract_id: 계약서 ID
            contract_type: 계약 유형
            user_contract_data: 사용자 계약서 원본 데이터
            a1_result: A1 완전성 검증 결과 (재검증 정보 포함)
            
        Returns:
            최종 보고서 JSON
        """
        import time
        
        logger.info(f"📝 Step 4 최종 보고서 생성 시작 (contract_id: {contract_id})")
        step4_start_time = time.time()
        
        # contract_type을 인스턴스 변수로 저장 (다른 메서드에서 사용)
        self.contract_type = contract_type
        
        # 모든 조항 내용 수집 (사용자 + 표준계약서)
        substep_start = time.time()
        all_contents = self._collect_all_clause_contents(step3_result, user_contract_data, contract_type)
        logger.info(f"  ⏱️ 조항 내용 수집 완료 ({time.time() - substep_start:.1f}초)")
        
        # 누락된 조항 상세 정보 생성 (A1 재검증 결과 활용)
        substep_start = time.time()
        enriched_missing = self._enrich_missing_clauses(
            step3_result.get("overall_missing_clauses", []),
            a1_result,
            user_contract_data,
            contract_type
        )
        logger.info(f"  ⏱️ 누락 조항 상세 정보 생성 완료 ({time.time() - substep_start:.1f}초)")
        
        report = {
            "contract_id": contract_id,
            "contract_type": contract_type,
            "generated_at": datetime.now().isoformat(),
            "summary": self._calculate_statistics(step3_result, contract_type),
            "overall_missing_clauses": self._format_overall_missing(step3_result),
            "overall_missing_clauses_detailed": enriched_missing,  # 🔥 새로 추가
            "user_articles": self._format_user_articles(step3_result, user_contract_data),
            "all_clause_contents": all_contents
        }
        
        step4_elapsed = time.time() - step4_start_time
        logger.info(f"✅ Step 4 최종 보고서 생성 완료 ({step4_elapsed:.1f}초): "
                   f"전역 누락 {len(report['overall_missing_clauses'])}개, "
                   f"상세 누락 {len(enriched_missing)}개 조, "
                   f"사용자 조항 {len(report['user_articles'])}개")
        
        return report
    
    def _calculate_statistics(self, step3_result: Dict[str, Any], 
                             contract_type: str) -> Dict[str, int]:
        """
        요약 통계 계산
        
        Args:
            step3_result: Step 3 결과
            contract_type: 계약 유형
            
        Returns:
            {total, sufficient, insufficient, missing}
        """
        # 문제 있는 것 카운트
        insufficient_count = 0
        missing_count = 0
        matched_count = 0
        
        # overall_missing_clauses
        missing_count += len(step3_result.get("overall_missing_clauses", []))
        
        # user_articles
        for article_data in step3_result.get("user_articles", {}).values():
            matched_count += len(article_data.get("matched", []))
            insufficient_count += len(article_data.get("insufficient", []))
            missing_count += len(article_data.get("missing", []))
        
        # total = matched + insufficient + missing
        total = matched_count + insufficient_count + missing_count
        
        stats = {
            "total": total,
            "sufficient": matched_count,
            "insufficient": insufficient_count,
            "missing": missing_count
        }
        
        logger.info(f"통계 계산 완료: 전체 {total}개, 충족 {matched_count}개, "
                   f"불충분 {insufficient_count}개, 누락 {missing_count}개")
        
        return stats
    
    def _format_overall_missing(self, step3_result: Dict[str, Any]) -> List[Dict]:
        """
        overall_missing_clauses 포맷팅 (제목 추가)
        
        Args:
            step3_result: Step 3 결과
            
        Returns:
            포맷팅된 overall_missing_clauses
        """
        formatted = []
        
        for item in step3_result.get("overall_missing_clauses", []):
            std_clause_id = item["std_clause_id"]
            
            # 표준 조항 제목 가져오기
            title = self._get_clause_title(std_clause_id)
            
            formatted.append({
                "std_clause_id": std_clause_id,
                "std_clause_title": title,
                "analysis": item["analysis"]
            })
        
        return formatted
    
    def _format_user_articles(self, step3_result: Dict[str, Any],
                             user_contract_data: Dict[str, Any]) -> List[Dict]:
        """
        user_articles 포맷팅 (제목 추가)
        
        Args:
            step3_result: Step 3 결과
            user_contract_data: 사용자 계약서 원본 데이터
            
        Returns:
            포맷팅된 user_articles 리스트
        """
        formatted = []
        
        for user_article_no, data in step3_result.get("user_articles", {}).items():
            # 사용자 조항 번호 추출
            article_no = int(user_article_no.replace("user_article_", ""))
            
            # 사용자 조항 제목 가져오기
            user_title = self._get_user_article_title(article_no, user_contract_data)
            
            article_report = {
                "user_article_no": article_no,
                "user_article_title": user_title,
                "matched": self._format_clause_list(data.get("matched", [])),
                "insufficient": self._format_clause_list_with_analysis(
                    data.get("insufficient", [])
                ),
                "missing": self._format_clause_list_with_analysis(
                    data.get("missing", [])
                )
            }
            
            formatted.append(article_report)
        
        # 조항 번호 순으로 정렬
        formatted.sort(key=lambda x: x["user_article_no"])
        
        return formatted
    
    def _format_clause_list(self, clause_ids: List[str]) -> List[Dict]:
        """
        조항 ID 목록을 제목 포함 형식으로 변환 (matched용)
        
        Args:
            clause_ids: 표준 조항 ID 목록 또는 [{std_clause_id, analysis}] 목록
            
        Returns:
            [{std_clause_id, std_clause_title, analysis}]
        """
        formatted = []
        
        for item in clause_ids:
            # dict 형식 (새 형식)
            if isinstance(item, dict):
                std_clause_id = item.get("std_clause_id")
                analysis = item.get("analysis", "")
                title = self._get_clause_title(std_clause_id)
                formatted.append({
                    "std_clause_id": std_clause_id,
                    "std_clause_title": title,
                    "analysis": analysis
                })
            # 문자열 형식 (하위 호환성)
            else:
                std_clause_id = item
                title = self._get_clause_title(std_clause_id)
                formatted.append({
                    "std_clause_id": std_clause_id,
                    "std_clause_title": title,
                    "analysis": "표준 조항과 매칭됨"
                })
        
        return formatted
    
    def _format_clause_list_with_analysis(self, items: List[Dict]) -> List[Dict]:
        """
        조항 목록을 제목 포함 형식으로 변환 (insufficient/missing용)
        
        Args:
            items: [{std_clause_id, analysis}]
            
        Returns:
            [{std_clause_id, std_clause_title, analysis}]
        """
        formatted = []
        
        for item in items:
            std_clause_id = item["std_clause_id"]
            title = self._get_clause_title(std_clause_id)
            
            formatted.append({
                "std_clause_id": std_clause_id,
                "std_clause_title": title,
                "analysis": item["analysis"]
            })
        
        return formatted
    
    def _get_clause_title(self, std_clause_id: str) -> str:
        """
        표준 조항 제목 가져오기 (global_id를 읽기 쉬운 형식으로 변환)
        
        Args:
            std_clause_id: 표준 조항 ID (global_id)
            예: "urn:std:provide:art:005"
            
        Returns:
            읽기 쉬운 조항 제목
            예: "제5조"
        """
        try:
            # global_id 파싱
            # 예: urn:std:provide:art:005 -> 제5조
            # 예: urn:std:provide:art:005:sub:002 -> 제5조 제2항
            # 예: urn:std:provide:art:002:att -> 제2조 별지
            parts = std_clause_id.split(':')
            
            if len(parts) >= 5:
                item_type = parts[3]  # "art" 또는 "ex"
                item_num = parts[4]   # "005"
                
                # 기본 조항 번호
                if item_type == 'art':
                    title = f"제{int(item_num)}조"
                elif item_type == 'ex':
                    title = f"별지{int(item_num)}"
                else:
                    return std_clause_id
                
                # 하위 항목 확인
                if len(parts) >= 7:
                    sub_type = parts[5]  # "cla", "sub", "att", etc.
                    sub_num = parts[6]   # "001", "002", etc.
                    
                    if sub_type == 'cla':
                        # 항 (clause)
                        title += f" 제{int(sub_num)}항"
                    elif sub_type == 'sub':
                        # 호 (sub-item)
                        title += f" 제{int(sub_num)}호"
                    elif sub_type == 'att':
                        # 조본문 (article text)
                        title += " 조본문"
                    elif sub_type == 'item':
                        # 호 (구버전 호환성)
                        title += f" 제{int(sub_num)}호"
                
                return title
                
        except (ValueError, IndexError):
            pass
        
        # 파싱 실패 시 원본 반환
        return std_clause_id
    
    def _get_user_article_title(self, article_no: int, 
                               user_contract_data: Dict[str, Any]) -> str:
        """
        사용자 조항 제목 가져오기
        
        Args:
            article_no: 사용자 조항 번호 (0-based index)
            user_contract_data: 사용자 계약서 원본 데이터
            
        Returns:
            조항 제목
        """
        # user_contract_data에서 해당 조항 찾기 (article_no는 인덱스)
        articles = user_contract_data.get("articles", [])
        
        if 0 <= article_no < len(articles):
            article = articles[article_no]
            title = article.get("title", "")
            
            # 제목이 있으면 "제n조 (제목)" 형식으로 반환
            if title and title != "서문":
                return f"제{article_no}조 ({title})"
            elif title == "서문":
                return "서문"
            else:
                return f"제{article_no}조"
        
        return f"제{article_no}조"

    def _load_standard_clause_content(self, std_clause_id: str, contract_type: str) -> Dict[str, Any]:
        """
        표준계약서 조항 내용 로드
        
        Args:
            std_clause_id: 표준 조항 global_id 
                - 항 단위: "urn:std:provide:art:011:cla:004"
                - 조 단위: "urn:std:provide:art:011" (모든 항 합쳐서 반환)
            contract_type: 계약 유형
            
        Returns:
            {
                "global_id": str,
                "text_raw": str,
                "text_norm": str,
                "commentary_summary": str
            }
        """
        # 캐시 확인
        cache_key = f"{contract_type}:{std_clause_id}"
        if cache_key in self.std_chunks_cache:
            return self.std_chunks_cache[cache_key]
        
        # 표준계약서 청크 로드
        if contract_type not in self.std_chunks_cache:
            chunks = self.kb_loader.load_chunks(contract_type)
            if not chunks:
                logger.warning(f"표준계약서 청크 로드 실패: {contract_type}")
                return {}
            
            # 전체 청크를 캐시에 저장
            for chunk in chunks:
                chunk_id = chunk.get('global_id')
                if chunk_id:
                    self.std_chunks_cache[f"{contract_type}:{chunk_id}"] = chunk
        
        # 캐시에서 조회
        chunk = self.std_chunks_cache.get(cache_key, {})
        
        if not chunk:
            # 🔥 조 단위 ID인 경우: 해당 조의 모든 항을 찾아서 합치기
            if ':cla:' not in std_clause_id and ':att' not in std_clause_id:
                logger.info(f"조 단위 ID 감지, 모든 항 검색: {std_clause_id}")
                matching_chunks = []
                for key, cached_chunk in self.std_chunks_cache.items():
                    if key.startswith(f"{contract_type}:{std_clause_id}:"):
                        matching_chunks.append(cached_chunk)
                
                if matching_chunks:
                    # 모든 항을 합쳐서 하나의 청크로 반환
                    combined_chunk = {
                        "global_id": std_clause_id,
                        "text_raw": "\n".join([c.get('text_raw', '') for c in matching_chunks if c.get('text_raw')]),
                        "text_norm": "\n".join([c.get('text_norm', '') for c in matching_chunks if c.get('text_norm')]),
                        "commentary_summary": "\n".join([c.get('commentary_summary', '') for c in matching_chunks if c.get('commentary_summary')])
                    }
                    logger.info(f"  → {len(matching_chunks)}개 항 합침")
                    # 캐시에 저장
                    self.std_chunks_cache[cache_key] = combined_chunk
                    return combined_chunk
                else:
                    logger.warning(f"표준 조항을 찾을 수 없음: {std_clause_id}")
            else:
                logger.warning(f"표준 조항을 찾을 수 없음: {std_clause_id}")
        
        return chunk
    
    def _load_user_article_content(self, article_no: int, user_contract_data: Dict[str, Any]) -> Dict[str, Any]:
        """
        사용자 조항 내용 로드
        
        Args:
            article_no: 사용자 조항 번호 (0-based index)
            user_contract_data: 사용자 계약서 원본 데이터
            
        Returns:
            {
                "number": int,
                "title": str,
                "text": str,
                "content": List[str]
            }
        """
        articles = user_contract_data.get("articles", [])
        
        if 0 <= article_no < len(articles):
            return articles[article_no]
        
        logger.warning(f"사용자 조항을 찾을 수 없음: {article_no}")
        return {}
    
    def _collect_all_clause_contents(self, step3_result: Dict[str, Any], 
                                     user_contract_data: Dict[str, Any],
                                     contract_type: str) -> Dict[str, Any]:
        """
        모든 관련 조항의 내용을 수집
        
        Args:
            step3_result: Step 3 결과
            user_contract_data: 사용자 계약서 원본 데이터
            contract_type: 계약 유형
            
        Returns:
            {
                "user_articles": {
                    "user_article_0": {
                        "content": {...},
                        "matched_std_clauses": [...],
                        "insufficient_std_clauses": [...],
                        "missing_std_clauses": [...]
                    }
                },
                "overall_missing_std_clauses": [...]
            }
        """
        logger.info("모든 조항 내용 수집 시작")
        
        collected = {
            "user_articles": {},
            "overall_missing_std_clauses": []
        }
        
        # 사용자 조항별 수집
        for article_key, article_data in step3_result.get("user_articles", {}).items():
            # 사용자 조항 번호 추출 (user_article_5 -> 5)
            article_no = int(article_key.split('_')[-1])
            
            # 사용자 조항 내용
            user_content = self._load_user_article_content(article_no, user_contract_data)
            
            # 매칭된 표준 조항들
            matched_std = []
            for item in article_data.get("matched", []):
                std_id = item.get("std_clause_id") if isinstance(item, dict) else item
                std_content = self._load_standard_clause_content(std_id, contract_type)
                if std_content:
                    matched_std.append({
                        "global_id": std_id,
                        "text_raw": std_content.get("text_raw", ""),
                        "text_norm": std_content.get("text_norm", ""),
                        "commentary_summary": std_content.get("commentary_summary", ""),
                        "analysis": item.get("analysis", "") if isinstance(item, dict) else ""
                    })
            
            # 불충분한 표준 조항들
            insufficient_std = []
            for item in article_data.get("insufficient", []):
                std_id = item.get("std_clause_id") if isinstance(item, dict) else item
                std_content = self._load_standard_clause_content(std_id, contract_type)
                if std_content:
                    insufficient_std.append({
                        "global_id": std_id,
                        "text_raw": std_content.get("text_raw", ""),
                        "text_norm": std_content.get("text_norm", ""),
                        "commentary_summary": std_content.get("commentary_summary", ""),
                        "analysis": item.get("analysis", "") if isinstance(item, dict) else ""
                    })
            
            # 누락된 표준 조항들
            missing_std = []
            for item in article_data.get("missing", []):
                std_id = item.get("std_clause_id") if isinstance(item, dict) else item
                std_content = self._load_standard_clause_content(std_id, contract_type)
                if std_content:
                    missing_std.append({
                        "global_id": std_id,
                        "text_raw": std_content.get("text_raw", ""),
                        "text_norm": std_content.get("text_norm", ""),
                        "commentary_summary": std_content.get("commentary_summary", ""),
                        "analysis": item.get("analysis", "") if isinstance(item, dict) else ""
                    })
            
            collected["user_articles"][article_key] = {
                "content": user_content,
                "matched_std_clauses": matched_std,
                "insufficient_std_clauses": insufficient_std,
                "missing_std_clauses": missing_std
            }
        
        # 전역 누락 조항들
        for item in step3_result.get("overall_missing_clauses", []):
            std_id = item.get("std_clause_id") if isinstance(item, dict) else item
            std_content = self._load_standard_clause_content(std_id, contract_type)
            if std_content:
                collected["overall_missing_std_clauses"].append({
                    "global_id": std_id,
                    "text_raw": std_content.get("text_raw", ""),
                    "text_norm": std_content.get("text_norm", ""),
                    "commentary_summary": std_content.get("commentary_summary", ""),
                    "analysis": item.get("analysis", "") if isinstance(item, dict) else ""
                })
        
        logger.info(f"조항 내용 수집 완료: 사용자 조항 {len(collected['user_articles'])}개, "
                   f"전역 누락 {len(collected['overall_missing_std_clauses'])}개")
        
        return collected

    def _enrich_missing_clauses(self, overall_missing: List[Dict], 
                                a1_result: Dict[str, Any],
                                user_contract_data: Dict[str, Any],
                                contract_type: str) -> List[Dict]:
        """
        누락된 조항을 조 단위로 그룹핑하고 상세 정보 추가
        
        Args:
            overall_missing: Step3의 overall_missing_clauses
            a1_result: A1 완전성 검증 결과
            user_contract_data: 사용자 계약서 원본 데이터
            contract_type: 계약 유형
            
        Returns:
            [
                {
                    "std_article_id": "제13조",
                    "std_article_title": "이용현황 보고 등",
                    "std_article_content": {...},
                    "missing_clause_ids": ["urn:std:provide:art:013:cla:001", ...],
                    "best_candidate": {
                        "user_article_no": 9,
                        "user_article_title": "제9조 (위약 및 손해배상)",
                        "user_article_content": {...},
                        "confidence": 0.40,
                        "match_type": "부분 일치(표현 차이)",
                        "reasoning": "..."
                    },
                    "risk_assessment": "...",
                    "recommendation": "..."
                }
            ]
        """
        import re
        
        logger.info(f"🔥 누락된 조항 상세 정보 생성 시작 (overall_missing: {len(overall_missing)}개)")
        
        if not a1_result:
            logger.warning("🔥 A1 결과가 없어 상세 정보 생성 불가")
            return []
        
        # 1. 조 단위로 그룹핑
        grouped = self._group_missing_by_article(overall_missing)
        logger.info(f"🔥 조 단위 그룹핑 완료: {len(grouped)}개 조 - {list(grouped.keys())}")
        
        # 2. A1 재검증 결과 파싱
        missing_analysis = a1_result.get("missing_article_analysis", [])
        matching_details = a1_result.get("matching_details", [])
        logger.info(f"🔥 A1 재검증 결과: missing_analysis={len(missing_analysis)}개, matching_details={len(matching_details)}개")
        
        from concurrent.futures import ThreadPoolExecutor, as_completed
        from openai import RateLimitError
        import time
        
        # 병렬 처리 함수
        def process_missing_article(article_id, clause_ids):
            """단일 누락 조항 처리 (재시도 로직 포함)"""
            max_retries = 3
            
            logger.info(f"🔥 처리 중: {article_id} (clause_ids: {len(clause_ids)}개)")
            
            # A1 재검증 결과에서 해당 조 찾기 (missing_article_analysis 우선)
            a1_info = self._find_a1_reverification(missing_analysis, article_id)
            logger.info(f"🔥   missing_analysis에서 찾기: {'발견' if a1_info else '없음'}")
            
            # missing_article_analysis에 없으면 matching_details에서 찾기
            if not a1_info:
                a1_info = self._find_a1_from_matching_details(matching_details, article_id)
                logger.info(f"🔥   matching_details에서 찾기: {'발견' if a1_info else '없음'}")
            
            if not a1_info:
                logger.warning(f"🔥 {article_id}: A1 재검증 정보 없음 - SKIP")
                return None
            
            # 표준계약서 조 내용 로드
            std_content = self._load_standard_article_content(article_id, contract_type)
            
            # 가장 유사도 높은 후보 찾기
            best_candidate = self._get_best_candidate_from_a1(a1_info, user_contract_data)
            
            # 서술형 보고서 생성 (재시도 로직)
            narrative_report = None
            for attempt in range(max_retries):
                try:
                    logger.info(f"  {article_id}: 서술형 보고서 생성 시작... (시도 {attempt + 1}/{max_retries})")
                    narrative_report = self._generate_missing_clause_narrative(
                        article_id=article_id,
                        std_content=std_content,
                        best_candidate=best_candidate,
                        risk_assessment=a1_info.get("risk_assessment", ""),
                        recommendation=a1_info.get("recommendation", ""),
                        evidence=a1_info.get("evidence", "")
                    )
                    logger.info(f"✅ {article_id}: 서술형 보고서 생성 완료 (길이: {len(narrative_report)}자)")
                    break
                    
                except RateLimitError as e:
                    if attempt < max_retries - 1:
                        wait_time = (attempt + 1) * 5
                        logger.warning(f"⚠️ {article_id}: Rate Limit 도달. {wait_time}초 대기 후 재시도...")
                        time.sleep(wait_time)
                    else:
                        logger.error(f"❌ {article_id}: Rate Limit 초과로 폴백 보고서 생성")
                        narrative_report = self._generate_missing_clause_fallback(
                            article_id, std_content, best_candidate,
                            a1_info.get("risk_assessment", ""),
                            a1_info.get("recommendation", "")
                        )
                        
                except Exception as e:
                    logger.error(f"❌ {article_id}: 서술형 보고서 생성 실패: {e}")
                    narrative_report = self._generate_missing_clause_fallback(
                        article_id, std_content, best_candidate,
                        a1_info.get("risk_assessment", ""),
                        a1_info.get("recommendation", "")
                    )
                    break
            
            result = {
                "std_article_id": article_id,
                "std_article_title": std_content.get("title", ""),
                "std_article_content": std_content,
                "missing_clause_ids": clause_ids,
                "best_candidate": best_candidate,
                "risk_assessment": a1_info.get("risk_assessment", ""),
                "recommendation": a1_info.get("recommendation", ""),
                "evidence": a1_info.get("evidence", ""),
                "narrative_report": narrative_report
            }
            
            logger.info(f"  {article_id}: 상세 정보 생성 완료 (후보: {best_candidate.get('user_article_no') if best_candidate else 'N/A'})")
            return result
        
        # 병렬 실행 (최대 3개 동시 - 누락 조항은 보통 적음)
        enriched = []
        logger.info(f"🚀 누락 조항 서술형 보고서 병렬 생성 시작: {len(grouped)}개 조 (max_workers=3)")
        start_time = time.time()
        
        with ThreadPoolExecutor(max_workers=3) as executor:
            # 모든 누락 조항을 병렬로 제출
            future_to_article = {
                executor.submit(process_missing_article, article_id, clause_ids): article_id
                for article_id, clause_ids in grouped.items()
            }
            
            # 완료된 순서대로 결과 수집
            completed_count = 0
            for future in as_completed(future_to_article):
                result = future.result()
                if result:
                    enriched.append(result)
                    completed_count += 1
                    logger.info(f"📊 진행률: {completed_count}/{len(grouped)}")
        
        elapsed_time = time.time() - start_time
        logger.info(f"✨ 누락 조항 서술형 보고서 병렬 생성 완료: {len(enriched)}개 조, 총 소요 시간: {elapsed_time:.1f}초")
        
        logger.info(f"누락된 조항 상세 정보 생성 완료: {len(enriched)}개 조")
        return enriched
    
    def _group_missing_by_article(self, overall_missing: List[Dict]) -> Dict[str, List[str]]:
        """
        누락된 조항을 조 단위로 그룹핑
        
        Args:
            overall_missing: [{std_clause_id, std_clause_title, analysis}]
            
        Returns:
            {"제13조": ["urn:std:provide:art:013:cla:001", ...], ...}
        """
        import re
        
        grouped = {}
        
        for item in overall_missing:
            std_clause_id = item.get("std_clause_id", "")
            
            # art:013 추출
            match = re.search(r':art:(\d+)', std_clause_id)
            if match:
                article_no = int(match.group(1))
                article_key = f"제{article_no}조"
                
                if article_key not in grouped:
                    grouped[article_key] = []
                grouped[article_key].append(std_clause_id)
        
        return grouped
    
    def _find_a1_reverification(self, missing_analysis: List[Dict], 
                               article_id: str) -> Dict[str, Any]:
        """
        A1 재검증 결과에서 해당 조 찾기
        
        missing_article_analysis와 matching_details 모두 확인하여
        해당 조의 재검증 정보를 찾습니다.
        
        Args:
            missing_analysis: A1 전체 결과 (missing_article_analysis 포함)
            article_id: "제13조" 형식
            
        Returns:
            A1 재검증 정보 또는 None
        """
        import re
        
        # "제13조" → 13 추출
        match = re.search(r'제(\d+)조', article_id)
        if not match:
            return None
        
        article_no = int(match.group(1))
        
        # 1. missing_article_analysis에서 찾기
        for item in missing_analysis:
            std_article_id = item.get("standard_article_id", "")
            
            # global_id 형식 매칭: urn:std:provide:art:013
            if f":art:{article_no:03d}" in std_article_id:
                logger.info(f"  {article_id}: missing_article_analysis에서 발견")
                return item
        
        logger.warning(f"  {article_id}: missing_article_analysis에 없음")
        return None
    
    def _find_a1_from_matching_details(self, matching_details: List[Dict],
                                      article_id: str) -> Dict[str, Any]:
        """
        A1 matching_details에서 해당 조의 재검증 정보 찾기
        
        매칭되었지만 신뢰도가 낮아 누락으로 처리된 경우,
        matching_details의 verification_details에 정보가 있습니다.
        
        Args:
            matching_details: A1의 matching_details
            article_id: "제13조" 형식
            
        Returns:
            재구성된 A1 재검증 정보 또는 None
        """
        import re
        
        # "제13조" → 13 추출
        match = re.search(r'제(\d+)조', article_id)
        if not match:
            return None
        
        article_no = int(match.group(1))
        
        # matching_details에서 해당 조 찾기
        for detail in matching_details:
            matched_articles = detail.get("matched_articles_global_ids", [])
            verification_details = detail.get("verification_details", [])
            
            # 매칭된 조항 중에 해당 조가 있는지 확인
            for matched_id in matched_articles:
                if f":art:{article_no:03d}" in matched_id:
                    logger.info(f"  {article_id}: matching_details에서 발견 (사용자 조항 {detail.get('user_article_no')})")
                    
                    # verification_details에서 해당 조의 정보 추출
                    candidates_analysis = []
                    
                    for verification in verification_details:
                        candidate_id = verification.get("candidate_id", "")
                        
                        # 해당 조의 verification 정보만 수집
                        if f"제{article_no}조" in candidate_id or f":art:{article_no:03d}" in candidate_id:
                            candidates_analysis.append({
                                "candidate_id": candidate_id,
                                "confidence": verification.get("confidence", 0.0),
                                "match_type": verification.get("match_type", ""),
                                "reasoning": verification.get("reasoning", ""),
                                "risk": verification.get("risk", ""),
                                "recommendation": verification.get("recommendation", "")
                            })
                    
                    if candidates_analysis:
                        # missing_article_analysis 형식으로 재구성
                        return {
                            "standard_article_id": matched_id,
                            "candidates_analysis": candidates_analysis,
                            "risk_assessment": candidates_analysis[0].get("risk", "") if candidates_analysis else "",
                            "recommendation": candidates_analysis[0].get("recommendation", "") if candidates_analysis else "",
                            "evidence": f"사용자 조항 제{detail.get('user_article_no')}조와 매칭되었으나 신뢰도가 낮아 누락으로 처리됨"
                        }
        
        return None
    
    def _get_best_candidate_from_a1(self, a1_info: Dict[str, Any],
                                   user_contract_data: Dict[str, Any]) -> Dict[str, Any]:
        """
        A1 재검증 결과에서 가장 유사도 높은 후보 추출
        
        Args:
            a1_info: A1 재검증 정보
            user_contract_data: 사용자 계약서 원본 데이터
            
        Returns:
            {
                "user_article_no": 9,
                "user_article_title": "제9조 (위약 및 손해배상)",
                "user_article_content": {...},
                "confidence": 0.40,
                "match_type": "부분 일치(표현 차이)",
                "reasoning": "..."
            }
        """
        import re
        
        candidates_analysis = a1_info.get("candidates_analysis", [])
        top_candidates = a1_info.get("top_candidates", [])
        
        if not candidates_analysis:
            logger.warning("candidates_analysis가 비어있음")
            return None
        
        # confidence 기준으로 정렬
        sorted_candidates = sorted(
            candidates_analysis,
            key=lambda x: x.get('confidence', 0.0),
            reverse=True
        )
        
        best = sorted_candidates[0]
        
        # candidate_id에서 조 번호 추출 시도 1: "제9조" 형식
        candidate_id = best.get('candidate_id', '')
        match = re.search(r'제(\d+)조', candidate_id)
        user_article_no = int(match.group(1)) if match else None
        
        # 추출 실패 시 top_candidates에서 찾기 (candidate_id가 "후보 1" 형식인 경우)
        if not user_article_no and top_candidates:
            # "후보 1" → 0번 인덱스
            candidate_match = re.search(r'후보\s*(\d+)', candidate_id)
            if candidate_match:
                candidate_idx = int(candidate_match.group(1)) - 1  # 1-based → 0-based
                if 0 <= candidate_idx < len(top_candidates):
                    top_candidate = top_candidates[candidate_idx]
                    user_article = top_candidate.get('user_article', {})
                    user_article_no = user_article.get('number')
                    logger.info(f"  top_candidates에서 후보 {candidate_idx + 1} 추출: 사용자 조항 {user_article_no}")
        
        if not user_article_no:
            logger.warning(f"candidate_id에서 조 번호 추출 실패: {candidate_id}")
            return None
        
        # 사용자 조항 제목 가져오기
        user_title = self._get_user_article_title(user_article_no, user_contract_data)
        
        # 사용자 조항 내용 로드
        user_content = self._load_user_article_content(user_article_no, user_contract_data)
        
        return {
            "user_article_no": user_article_no,
            "user_article_title": user_title,
            "user_article_content": user_content,
            "confidence": best.get('confidence', 0.0),
            "match_type": best.get('match_type', ''),
            "reasoning": best.get('reasoning', ''),
            "risk": best.get('risk', ''),
            "recommendation": best.get('recommendation', '')
        }
    
    def _load_standard_article_content(self, article_id: str, 
                                      contract_type: str) -> Dict[str, Any]:
        """
        표준계약서 조 전체 내용 로드
        
        Args:
            article_id: "제13조" 형식
            contract_type: 계약 유형
            
        Returns:
            {
                "title": "이용현황 보고 등",
                "clauses": [
                    {"clause_no": 1, "text": "...", "commentary": "..."},
                    {"clause_no": 2, "text": "...", "commentary": "..."}
                ]
            }
        """
        import re
        
        # "제13조" → 13 추출
        match = re.search(r'제(\d+)조', article_id)
        if not match:
            return {"title": "", "clauses": []}
        
        article_no = int(match.group(1))
        
        # 표준계약서 청크 로드
        if contract_type not in self.std_chunks_cache:
            self.std_chunks_cache[contract_type] = self.kb_loader.load_chunks(contract_type)
        
        chunks = self.std_chunks_cache[contract_type]
        
        # 해당 조의 모든 청크 찾기
        article_chunks = []
        title = ""
        
        for chunk in chunks:
            global_id = chunk.get("global_id", "")
            
            # art:013 매칭
            if f":art:{article_no:03d}" in global_id:
                article_chunks.append(chunk)
                
                # 제목 추출 (첫 번째 청크에서)
                if not title:
                    chunk_title = chunk.get("title", "")
                    if chunk_title:
                        title = chunk_title
        
        # 항별로 정리
        clauses = []
        for chunk in article_chunks:
            clause_info = {
                "global_id": chunk.get("global_id", ""),
                "text_raw": chunk.get("text_raw", ""),
                "text_norm": chunk.get("text_norm", ""),
                "commentary_summary": chunk.get("commentary_summary", "")
            }
            clauses.append(clause_info)
        
        return {
            "title": title,
            "clauses": clauses
        }

    def _generate_missing_clause_narrative(self, article_id: str, 
                                          std_content: Dict[str, Any],
                                          best_candidate: Dict[str, Any],
                                          risk_assessment: str,
                                          recommendation: str,
                                          evidence: str) -> str:
        """
        누락된 조항에 대한 서술형 보고서 생성 (LLM 활용)
        
        Args:
            article_id: 표준 조항 ID (예: "제13조")
            std_content: 표준계약서 조 내용
            best_candidate: 가장 유사한 사용자 조항 정보
            risk_assessment: 위험성 평가
            recommendation: 권고사항
            evidence: 근거
            
        Returns:
            서술형 보고서 텍스트
        """
        logger.info(f"🔥 _generate_missing_clause_narrative 호출됨: {article_id}")
        
        if not self.client:
            logger.warning(f"🔥 Azure OpenAI 클라이언트 없음. 폴백 보고서 생성: {article_id}")
            return self._generate_missing_clause_fallback(
                article_id, std_content, best_candidate, risk_assessment, recommendation
            )
        
        # 표준계약서 내용 요약
        std_title = std_content.get("title", "")
        clauses = std_content.get("clauses", [])
        std_text = "\n".join([
            f"- {clause.get('text_norm', clause.get('text_raw', ''))}"
            for clause in clauses[:5]  # 최대 5개 항
        ])
        
        # 후보 정보
        candidate_info = ""
        if best_candidate:
            candidate_info = f"""
## 가장 유사한 사용자 조항
- **조항**: {best_candidate.get('user_article_title', 'N/A')}
- **유사도**: {best_candidate.get('confidence', 0):.0%}
- **매칭 유형**: {best_candidate.get('match_type', 'N/A')}
- **분석**: {best_candidate.get('reasoning', 'N/A')}
"""
        
        prompt = f"""당신은 데이터 계약서 검증 전문가입니다. 사용자 계약서에 누락된 표준 조항에 대한 서술형 보고서를 작성해주세요.

## 누락된 표준 조항
**{article_id} ({std_title})**

## 표준계약서 내용
{std_text}

{candidate_info}

## 위험성 평가
{risk_assessment if risk_assessment else "N/A"}

## 권고사항
{recommendation if recommendation else "N/A"}

## 근거
{evidence if evidence else "N/A"}

아래 기준에 따라 사용자가 이해하기 쉬운 서술형 보고서를 작성하세요:

### 보고서 구성
1. 누락 사실 설명: 귀하의 계약서에 {article_id}의 내용이 포함되어 있지 않다는 점을 자연스럽게 전달합니다.
2. 내용 요약: {article_id}가 일반적으로 어떤 역할을 하는 조항인지 2~3문장으로 간결하게 설명합니다.
3. 위험성 설명: 이 내용이 없을 경우 발생할 수 있는 실무적·운영상 문제를 현실적인 수준에서 설명합니다.
4. 유사 조항 분석(후보가 있는 경우): 위에 제공된 "가장 유사한 사용자 조항" 정보를 바탕으로, 해당 조항이 왜 관련된 조항으로 판단되는지 자연스럽게 설명합니다. 유사도 수치는 언급하지 않습니다.
5. 실질적 권고: 조항을 어디에, 어떤 방식으로 보완하면 좋은지 실무 중심으로 조언합니다. 조문 초안은 작성하지 않습니다.

### 작성 규칙
- 법무팀이 작성한 정식 검토 보고서 문체를 사용합니다.
- "표준계약서", "매칭", "유사도", "글로벌ID", "AI" 등 기술적 용어를 사용하지 않습니다.
- 자연스럽고 읽기 쉬운 단락 중심으로 작성하며, 단락은 3~5문장으로 유지합니다.
- 입력된 텍스트를 그대로 복붙하지 말고 의미를 재구성해 서술합니다.

### 출력 형식
- 제목 없이 본문만 작성합니다.
- 자연스러운 단락 구성으로 작성하며, 필요한 경우에만 최소한의 목록을 사용할 수 있습니다.

"""
        
        try:
            logger.info(f"누락 조항 서술형 보고서 생성 시작: {article_id}")
            
            response = self.client.chat.completions.create(
                model="gpt-4o",
                messages=[
                    {"role": "system", "content": "당신은 데이터 계약서 검증 전문가입니다. 구조화된 데이터를 사용자 친화적인 서술형 보고서로 변환하는 것이 당신의 역할입니다."},
                    {"role": "user", "content": prompt}
                ],
                temperature=0.3,
                max_tokens=1500
            )
            
            result = response.choices[0].message.content.strip()
            logger.info(f"누락 조항 서술형 보고서 생성 완료: {article_id} (토큰: {response.usage.total_tokens})")
            
            return result
        
        except Exception as e:
            logger.error(f"누락 조항 서술형 보고서 생성 실패: {article_id} - {e}")
            return self._generate_missing_clause_fallback(
                article_id, std_content, best_candidate, risk_assessment, recommendation
            )
    
    def _generate_missing_clause_fallback(self, article_id: str,
                                         std_content: Dict[str, Any],
                                         best_candidate: Dict[str, Any],
                                         risk_assessment: str,
                                         recommendation: str) -> str:
        """
        LLM 호출 실패 시 폴백 보고서 생성
        
        Args:
            article_id: 표준 조항 ID
            std_content: 표준계약서 내용
            best_candidate: 가장 유사한 사용자 조항
            risk_assessment: 위험성 평가
            recommendation: 권고사항
            
        Returns:
            기본 서술형 보고서
        """
        std_title = std_content.get("title", "")
        
        report = f"귀하의 계약서에는 표준계약서 {article_id} ({std_title})의 내용이 포함되지 않았습니다.\n\n"
        
        if risk_assessment:
            report += f"**위험성**: {risk_assessment}\n\n"
        
        if best_candidate:
            report += f"**유사 조항**: {best_candidate.get('user_article_title', 'N/A')} (유사도: {best_candidate.get('confidence', 0):.0%})\n\n"
        
        if recommendation:
            report += f"**권고사항**: {recommendation}"
        
        return report
