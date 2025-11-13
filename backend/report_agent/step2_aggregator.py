"""
Step2Aggregator

표준 항목 기준으로 재집계하고 충돌을 감지합니다.
"""

import logging
from typing import Dict, List, Any

logger = logging.getLogger(__name__)


class Step2Aggregator:
    """
    Step 2: 2차 정규화 (표준 항목 기준 재집계)
    
    - 표준 항목 ID를 키로 재구조화
    - 각 표준 항목에 대한 모든 평가 수집
    - 충돌 감지 (insufficient + missing)
    """
    
    def aggregate(self, step1_result: Dict[str, Any]) -> Dict[str, Dict]:
        """
        표준 항목 기준으로 재집계
        
        Args:
            step1_result: Step 1 결과
            
        Returns:
            {
                "std_clause_id": {
                    "evaluations": [
                        {"user_article": str, "status": str}
                    ],
                    "has_conflict": bool
                }
            }
        """
        logger.info("Step 2 재집계 시작")
        
        aggregated = {}
        
        # user_articles 순회
        for user_article_no, data in step1_result["user_articles"].items():
            for status in ["insufficient", "missing"]:
                for std_clause_id in data.get(status, []):
                    if std_clause_id not in aggregated:
                        aggregated[std_clause_id] = {"evaluations": []}
                    
                    aggregated[std_clause_id]["evaluations"].append({
                        "user_article": user_article_no,
                        "status": status
                    })
        
        # 충돌 감지
        conflict_count = 0
        for std_clause_id, data in aggregated.items():
            statuses = {e["status"] for e in data["evaluations"]}
            data["has_conflict"] = len(statuses) > 1
            if data["has_conflict"]:
                conflict_count += 1
        
        logger.info(f"Step 2 재집계 완료: 표준 항목 {len(aggregated)}개, "
                   f"충돌 {conflict_count}개")
        
        return {
            "aggregated": aggregated,
            "conflict_count": conflict_count
        }
