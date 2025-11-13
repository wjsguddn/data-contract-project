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
    
    def __init__(self):
        """
        Step4Reporter 초기화
        """
        pass
    
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
        
        report = {
            "contract_id": contract_id,
            "contract_type": contract_type,
            "generated_at": datetime.now().isoformat(),
            "summary": self._calculate_statistics(step3_result, contract_type),
            "overall_missing_clauses": self._format_overall_missing(step3_result),
            "user_articles": self._format_user_articles(step3_result, user_contract_data)
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
            clause_ids: 표준 조항 ID 목록
            
        Returns:
            [{std_clause_id, std_clause_title}]
        """
        formatted = []
        
        for std_clause_id in clause_ids:
            title = self._get_clause_title(std_clause_id)
            formatted.append({
                "std_clause_id": std_clause_id,
                "std_clause_title": title
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
            # global_id 파싱: urn:std:provide:art:005 -> 제5조
            parts = std_clause_id.split(':')
            if len(parts) >= 5:
                item_type = parts[3]  # "art" 또는 "ex"
                item_num = parts[4]   # "005"
                
                if item_type == 'art':
                    return f"제{int(item_num)}조"
                elif item_type == 'ex':
                    return f"별지{int(item_num)}"
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
