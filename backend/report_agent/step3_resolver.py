"""
Step3Resolver

우선순위 규칙과 LLM 재검증을 사용하여 충돌을 해소합니다.
"""

import logging
import json
from typing import Dict, List, Any, Optional

from backend.report_agent.exceptions import LLMVerificationError

logger = logging.getLogger(__name__)


# LLM 충돌 해소 프롬프트
CONFLICT_RESOLUTION_PROMPT = """
당신은 데이터 표준계약서 검증 전문가입니다.

동일한 표준 조항에 대해 여러 사용자 조항에서 상충되는 평가가 있습니다.
최종 상태를 판단해주세요.

**표준 조항:**
{std_clause_text}

**평가 내역:**
{evaluations}

**질문:**
이 표준 조항의 최종 상태를 판단하고 그 이유를 설명해주세요.

**응답 형식:**
```json
{{
  "final_status": "sufficient" | "insufficient" | "missing",
  "reasoning": "판단 근거..."
}}
```

**판단 기준:**
- sufficient: 표준 조항의 요구사항이 충족됨
- insufficient: 일부 내용이 있으나 불충분함
- missing: 완전히 누락됨
"""


class Step3Resolver:
    """
    Step 3: 충돌 해소 (규칙 + LLM)
    
    - 우선순위 규칙 적용: sufficient > insufficient > missing
    - LLM 재검증 (충돌 시)
    - A3 원본 분석 텍스트 첨부
    """
    
    def __init__(self, llm_client):
        """
        Step3Resolver 초기화
        
        Args:
            llm_client: LLM 클라이언트 (Azure OpenAI 등)
        """
        self.llm = llm_client
    
    def resolve(self, step2_result: Dict[str, Dict], a3_result: Dict[str, Any],
                step1_result: Dict[str, Any]) -> Dict[str, Any]:
        """
        충돌 해소 및 분석 텍스트 첨부
        
        Args:
            step2_result: Step 2 결과
            a3_result: A3 원본 결과 (분석 텍스트 추출용)
            step1_result: Step 1 결과 (구조 참조용)
            
        Returns:
            {
                "overall_missing_clauses": List[Dict],
                "user_articles": Dict[str, Dict]
            }
        """
        logger.info("Step 3 충돌 해소 시작")
        
        # Step 1 구조 복사 (matched 유지)
        resolved = {
            "overall_missing_clauses": step1_result["overall_missing_clauses"],
            "user_articles": {}
        }
        
        for user_article_no, data in step1_result["user_articles"].items():
            resolved["user_articles"][user_article_no] = {
                "matched": data.get("matched", []),
                "insufficient": [],
                "missing": []
            }
        
        # 충돌 해소
        conflict_count = 0
        aggregated = step2_result.get("aggregated", step2_result)  # 하위 호환성
        for std_clause_id, data in aggregated.items():
            if data["has_conflict"]:
                # 우선순위 규칙 적용 (LLM 재검증 생략)
                final_status = self._apply_priority_rules(data)
                conflict_count += 1
            else:
                # 충돌 없음 - 단일 상태 사용
                final_status = data["evaluations"][0]["status"]
            
            # 보정 적용 (std_clause_id 전달)
            self._apply_resolution(resolved, std_clause_id, data, final_status)
        
        logger.info(f"충돌 해소 완료: {conflict_count}개 충돌 처리")
        
        # A3 원본 분석 텍스트 첨부
        self._attach_analysis_text(resolved, a3_result)
        logger.info("A3 원본 분석 텍스트 첨부 완료")
        
        # overall_missing_clauses에 분석 텍스트 추가
        self._generate_overall_missing_analysis(resolved)
        logger.info("전역 누락 조항 분석 생성 완료")
        
        logger.info("Step 3 충돌 해소 완료")
        return resolved
    

    
    def _apply_priority_rules(self, conflict_data: Dict) -> str:
        """
        우선순위 규칙 적용: sufficient > insufficient > missing
        
        Args:
            conflict_data: 충돌 데이터
            
        Returns:
            최종 상태
        """
        statuses = {e["status"] for e in conflict_data["evaluations"]}
        
        if "sufficient" in statuses:
            return "sufficient"
        elif "insufficient" in statuses:
            return "insufficient"
        else:
            return "missing"
    
    def _apply_resolution(self, resolved: Dict, std_clause_id: str, conflict_data: Dict, final_status: str):
        """
        보정 결과 적용
        
        Args:
            resolved: 보정 결과 딕셔너리
            std_clause_id: 표준 조항 ID
            conflict_data: 충돌 데이터
            final_status: 최종 상태
        """
        if final_status == "sufficient":
            # 모든 평가 제거 (문제 없음)
            return
        
        # final_status에 해당하는 사용자 조항만 유지
        for evaluation in conflict_data["evaluations"]:
            if evaluation["status"] == final_status:
                user_article_no = evaluation["user_article"]
                
                # 임시로 ID만 저장 (분석 텍스트는 나중에 첨부)
                if user_article_no in resolved["user_articles"]:
                    resolved["user_articles"][user_article_no][final_status].append(std_clause_id)
    
    def _attach_analysis_text(self, resolved: Dict, a3_result: Dict[str, Any]):
        """
        A3 원본 분석 텍스트 첨부
        
        Args:
            resolved: 보정 결과
            a3_result: A3 원본 결과
        """
        # A3 article_analysis에서 분석 텍스트 추출
        # 하나의 suggestion이 여러 조항을 포함하므로, 모든 조항에 동일한 분석 첨부
        analysis_map = {}
        
        for article in a3_result.get("article_analysis", []):
            user_article_no = f"user_article_{article['user_article_no']}"
            
            if user_article_no not in analysis_map:
                analysis_map[user_article_no] = {
                    "missing": {},
                    "insufficient": {}
                }
            
            for suggestion in article.get("suggestions", []):
                analysis_text = suggestion.get("analysis", "")
                
                # missing_items - 모든 조항에 동일한 분석 저장
                missing_items = suggestion.get("missing_items", [])
                if missing_items and analysis_text:
                    for std_clause_id in missing_items:
                        analysis_map[user_article_no]["missing"][std_clause_id] = analysis_text
                
                # insufficient_items - 모든 조항에 동일한 분석 저장
                insufficient_items = suggestion.get("insufficient_items", [])
                if insufficient_items and analysis_text:
                    for std_clause_id in insufficient_items:
                        analysis_map[user_article_no]["insufficient"][std_clause_id] = analysis_text
        
        # resolved에 분석 텍스트 첨부
        for user_article_no, data in resolved["user_articles"].items():
            # analysis_map에서 분석 가져오기 (없으면 빈 딕셔너리)
            analysis = analysis_map.get(user_article_no, {"insufficient": {}, "missing": {}})
            
            # insufficient - 모든 조항에 분석 첨부
            if data["insufficient"]:
                data["insufficient"] = [{
                    "std_clause_id": std_id,
                    "analysis": analysis["insufficient"].get(std_id, "")
                } for std_id in data["insufficient"]]
            
            # missing - 모든 조항에 분석 첨부
            if data["missing"]:
                data["missing"] = [{
                    "std_clause_id": std_id,
                    "analysis": analysis["missing"].get(std_id, "")
                } for std_id in data["missing"]]
    
    def _generate_overall_missing_analysis(self, resolved: Dict):
        """
        overall_missing_clauses에 대한 분석 생성 (중복 제거)
        
        Args:
            resolved: 보정 결과
        """
        overall_missing_with_analysis = []
        seen_ids = set()
        
        for std_clause_id in resolved["overall_missing_clauses"]:
            # 중복 제거
            if std_clause_id in seen_ids:
                continue
            seen_ids.add(std_clause_id)
            
            # 간단한 분석 텍스트 생성
            analysis = f"사용자 계약서 전체에서 해당 조항을 찾을 수 없습니다. " \
                      f"표준계약서에서는 이 조항이 필수적으로 포함되어야 합니다."
            
            overall_missing_with_analysis.append({
                "std_clause_id": std_clause_id,
                "analysis": analysis
            })
        
        resolved["overall_missing_clauses"] = overall_missing_with_analysis
