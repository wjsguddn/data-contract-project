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
        self.kb_loader = kb_loader or KnowledgeBaseLoader()
        self.std_chunks_cache = {}  # 표준계약서 청크 캐시
    
    def generate_final_report(self, step3_result: Dict[str, Any], 
                             contract_id: str, contract_type: str,
                             user_contract_data: Dict[str, Any]) -> Dict[str, Any]:
        """
        최종 보고서 생성
        
        Args:
            step3_result: Step 3 결과
            contract_id: 계약서 ID
            contract_type: 계약 유형
            user_contract_data: 사용자 계약서 원본 데이터
            
        Returns:
            최종 보고서 JSON
        """
        logger.info(f"Step 4 최종 보고서 생성 시작 (contract_id: {contract_id})")
        
        # contract_type을 인스턴스 변수로 저장 (다른 메서드에서 사용)
        self.contract_type = contract_type
        
        # 모든 조항 내용 수집 (사용자 + 표준계약서)
        all_contents = self._collect_all_clause_contents(step3_result, user_contract_data, contract_type)
        
        report = {
            "contract_id": contract_id,
            "contract_type": contract_type,
            "generated_at": datetime.now().isoformat(),
            "summary": self._calculate_statistics(step3_result, contract_type),
            "overall_missing_clauses": self._format_overall_missing(step3_result),
            "user_articles": self._format_user_articles(step3_result, user_contract_data),
            "all_clause_contents": all_contents  # 🔥 추가: 모든 조항 내용
        }
        
        logger.info(f"Step 4 최종 보고서 생성 완료: "
                   f"전역 누락 {len(report['overall_missing_clauses'])}개, "
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
