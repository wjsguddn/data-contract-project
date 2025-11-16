"""
Step3Resolver

우선순위 규칙과 LLM 재검증을 사용하여 충돌을 해소합니다.
"""

import logging
import json
from typing import Dict, List, Any, Optional

from backend.report_agent.exceptions import LLMVerificationError

logger = logging.getLogger(__name__)


# LLM 충돌 해소 프롬프트 제거 (더 이상 사용하지 않음)
# 새로운 규칙:
# 1. 같은 조항 충돌 → 무시 (A1 조 vs A3 항 계층 문제)
# 2. 다른 조항 충돌 → 우선순위 자동 해소 (sufficient > insufficient > missing)


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
        import os
        self.llm = llm_client
        self.gpt_model = os.getenv('AZURE_LLM_DEPLOYMENT', 'gpt-4o')
    
    def resolve(self, step2_result: Dict[str, Dict], a3_result: Dict[str, Any],
                step1_result: Dict[str, Any], user_contract_data: Dict[str, Any]) -> Dict[str, Any]:
        """
        충돌 해소 및 분석 텍스트 첨부
        
        Args:
            step2_result: Step 2 결과
            a3_result: A3 원본 결과 (분석 텍스트 추출용)
            step1_result: Step 1 결과 (구조 참조용)
            user_contract_data: 사용자 계약서 원본 데이터
            
        Returns:
            {
                "overall_missing_clauses": List[Dict],
                "user_articles": Dict[str, Dict]
            }
        """
        logger.info("Step 3 충돌 해소 시작")
        
        # 사용자 계약서 데이터 저장 (LLM 호출 시 사용)
        self.user_contract_data = user_contract_data
        
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
        llm_resolved_count = 0
        auto_resolved_count = 0
        ignored_count = 0  # 같은 조항 충돌 (무시)
        aggregated = step2_result.get("aggregated", step2_result)  # 하위 호환성
        
        for std_clause_id, data in aggregated.items():
            if data["has_conflict"]:
                conflict_count += 1
                
                # 자동 해소 규칙
                statuses = {e["status"] for e in data["evaluations"]}
                user_articles = {e["user_article"] for e in data["evaluations"]}
                
                # 규칙 1: 같은 조항 충돌 → 무시 (계층 문제: A1 조 vs A3 항)
                if len(user_articles) == 1:
                    logger.info(f"충돌 무시: {std_clause_id} (같은 조항 충돌 - A1 조 vs A3 항 계층 문제)")
                    ignored_count += 1
                    # 충돌 없는 것처럼 처리 (첫 번째 평가만 사용)
                    final_status = data["evaluations"][0]["status"]
                    self._apply_resolution(resolved, std_clause_id, data, final_status)
                    continue
                
                # 규칙 2: 다른 조항 + sufficient 있음 → sufficient만 유지
                if "sufficient" in statuses:
                    logger.info(f"자동 해소: {std_clause_id} (다른 조항, sufficient 우선)")
                    # sufficient 평가만 유지 (문제 없음이므로 아무것도 추가 안 함)
                    auto_resolved_count += 1
                    continue
                
                # 규칙 3: 다른 조항 + insufficient vs missing → insufficient 우선
                if "insufficient" in statuses and "missing" in statuses:
                    logger.info(f"자동 해소: {std_clause_id} (다른 조항, insufficient 우선)")
                    # insufficient 평가만 유지
                    insufficient_evals = [e for e in data["evaluations"] if e["status"] == "insufficient"]
                    for evaluation in insufficient_evals:
                        user_article_no = evaluation["user_article"]
                        if user_article_no in resolved["user_articles"]:
                            resolved["user_articles"][user_article_no]["insufficient"].append({
                                "std_clause_id": std_clause_id,
                                "analysis": evaluation.get("analysis", "")
                            })
                    auto_resolved_count += 1
                    continue
                
                # 규칙 4: 다른 조항 + insufficient vs insufficient → LLM 선택
                if statuses == {"insufficient"}:
                    logger.info(f"자동 해소: {std_clause_id} (다른 조항, insufficient 중복 → LLM 선택)")
                    self._resolve_insufficient_duplicates(resolved, std_clause_id, data)
                    auto_resolved_count += 1
                    continue
                
                # 규칙 5: 다른 조항 + missing vs missing → 첫 번째만 유지
                if statuses == {"missing"}:
                    logger.info(f"자동 해소: {std_clause_id} (다른 조항, missing 중복 → 첫 번째만 유지)")
                    evaluation = data["evaluations"][0]
                    user_article_no = evaluation["user_article"]
                    if user_article_no in resolved["user_articles"]:
                        resolved["user_articles"][user_article_no]["missing"].append({
                            "std_clause_id": std_clause_id,
                            "analysis": evaluation.get("analysis", "")
                        })
                    auto_resolved_count += 1
                    continue
                
                # 예외: 알 수 없는 충돌 패턴 (로그만)
                logger.warning(f"알 수 없는 충돌 패턴: {std_clause_id} (statuses={statuses}, user_articles={len(user_articles)})")
                # 첫 번째 평가 사용
                final_status = data["evaluations"][0]["status"]
                self._apply_resolution(resolved, std_clause_id, data, final_status)
            else:
                # 충돌 없음 - 단일 상태 사용
                final_status = data["evaluations"][0]["status"]
                self._apply_resolution(resolved, std_clause_id, data, final_status)
        
        logger.info(f"충돌 해소 완료: {conflict_count}개 충돌 처리 "
                   f"(무시: {ignored_count}개, 자동 해소: {auto_resolved_count}개, LLM 해소: {llm_resolved_count}개)")
        
        # 서문(제0조) 처리: 충돌 해소 후 남은 항목만 overall_missing으로 이동
        preamble_analysis_map = self._process_preamble(resolved)
        logger.info("서문 처리 완료")
        
        # A3 원본 분석 텍스트 첨부
        self._attach_analysis_text(resolved, a3_result)
        logger.info("A3 원본 분석 텍스트 첨부 완료")
        
        # overall_missing_clauses에 분석 텍스트 추가
        self._generate_overall_missing_analysis(resolved, preamble_analysis_map)
        logger.info("전역 누락 조항 분석 생성 완료")
        
        logger.info("Step 3 충돌 해소 완료")
        return resolved
    

    def _process_preamble(self, resolved: Dict) -> Dict[str, str]:
        """
        서문(제0조) 처리: 충돌 해소 후 남은 항목만 overall_missing으로 이동
        
        Args:
            resolved: 충돌 해소 결과
            
        Returns:
            preamble_analysis_map: 서문 항목의 analysis 매핑
        """
        preamble_key = "user_article_0"
        preamble_analysis_map = {}
        
        if preamble_key not in resolved["user_articles"]:
            return preamble_analysis_map
        
        preamble_data = resolved["user_articles"][preamble_key]
        preamble_insufficient = preamble_data.get("insufficient", [])
        preamble_missing = preamble_data.get("missing", [])
        
        logger.info(f"[Step3] 서문 처리: insufficient={len(preamble_insufficient)}, missing={len(preamble_missing)}")
        
        # 누락 항목을 overall_missing으로 이동
        for item in preamble_missing:
            std_clause_id = item.get("std_clause_id") if isinstance(item, dict) else item
            analysis = item.get("analysis", "") if isinstance(item, dict) else ""
            
            if std_clause_id and std_clause_id not in resolved["overall_missing_clauses"]:
                resolved["overall_missing_clauses"].append(std_clause_id)
                if analysis:
                    preamble_analysis_map[std_clause_id] = analysis
                logger.debug(f"  → overall_missing에 추가 (누락): {std_clause_id}")
        
        # 불충분 항목도 overall_missing으로 이동
        for item in preamble_insufficient:
            std_clause_id = item.get("std_clause_id") if isinstance(item, dict) else item
            analysis = item.get("analysis", "") if isinstance(item, dict) else ""
            
            if std_clause_id and std_clause_id not in resolved["overall_missing_clauses"]:
                resolved["overall_missing_clauses"].append(std_clause_id)
                if analysis:
                    preamble_analysis_map[std_clause_id] = analysis
                logger.debug(f"  → overall_missing에 추가 (불충분): {std_clause_id}")
        
        # 서문에서 누락과 불충분 모두 제거
        resolved["user_articles"][preamble_key]["missing"] = []
        resolved["user_articles"][preamble_key]["insufficient"] = []
        
        total_moved = len(preamble_missing) + len(preamble_insufficient)
        if total_moved > 0:
            logger.info(f"[Step3] 서문의 누락/불충분 항목 {total_moved}개를 overall_missing으로 이동 완료")
        
        return preamble_analysis_map
    
    # LLM 충돌 해소 메서드 제거 (더 이상 사용하지 않음)
    # 새로운 규칙: 같은 조항 충돌은 무시, 다른 조항 충돌은 우선순위로 자동 해소
    
    def _resolve_insufficient_duplicates(self, resolved: Dict, std_clause_id: str, conflict_data: Dict):
        """
        insufficient + insufficient → 중복 제거 후 LLM으로 가장 구체적인 것 선택
        
        Args:
            resolved: 보정 결과
            std_clause_id: 표준 조항 ID
            conflict_data: 충돌 데이터
        """
        evaluations = conflict_data["evaluations"]
        
        # 1단계: 분석 텍스트 기반 중복 제거
        unique_evaluations = []
        seen_analyses = set()
        
        for evaluation in evaluations:
            analysis = evaluation.get("analysis", "").strip()
            
            # 분석 텍스트가 비어있거나 이미 본 것이면 스킵
            if not analysis:
                continue
            
            # 정규화: 공백, 구두점 제거 후 비교
            normalized = analysis.replace(" ", "").replace("\n", "").replace(",", "").replace(".", "")
            
            if normalized not in seen_analyses:
                seen_analyses.add(normalized)
                unique_evaluations.append(evaluation)
            else:
                logger.info(f"  중복 제거: {evaluation['user_article']} (동일한 분석 텍스트)")
        
        # 중복 제거 후 1개만 남으면 바로 추가
        if len(unique_evaluations) == 1:
            logger.info(f"  중복 제거 후 1개만 남음 → LLM 호출 생략")
            evaluation = unique_evaluations[0]
            user_article_no = evaluation["user_article"]
            if user_article_no in resolved["user_articles"]:
                resolved["user_articles"][user_article_no]["insufficient"].append({
                    "std_clause_id": std_clause_id,
                    "analysis": evaluation.get("analysis", "")
                })
            return
        
        # 중복 제거 후 0개면 원본 첫 번째 사용
        if len(unique_evaluations) == 0:
            logger.warning(f"  중복 제거 후 0개 → 원본 첫 번째 사용")
            evaluation = evaluations[0]
            user_article_no = evaluation["user_article"]
            if user_article_no in resolved["user_articles"]:
                resolved["user_articles"][user_article_no]["insufficient"].append({
                    "std_clause_id": std_clause_id,
                    "analysis": evaluation.get("analysis", "")
                })
            return
        
        # 2단계: 여전히 2개 이상 남으면 LLM 판단
        logger.info(f"  중복 제거 후 {len(unique_evaluations)}개 남음 → LLM 선택")
        selected_indices = self._llm_select_best_insufficient(std_clause_id, unique_evaluations)
        
        for idx in selected_indices:
            if idx < len(unique_evaluations):
                evaluation = unique_evaluations[idx]
                user_article_no = evaluation["user_article"]
                if user_article_no in resolved["user_articles"]:
                    resolved["user_articles"][user_article_no]["insufficient"].append({
                        "std_clause_id": std_clause_id,
                        "analysis": evaluation.get("analysis", "")
                    })
    
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
                analysis = evaluation.get("analysis", "")
                
                # ID와 분석 텍스트를 함께 저장
                if user_article_no in resolved["user_articles"]:
                    resolved["user_articles"][user_article_no][final_status].append({
                        "std_clause_id": std_clause_id,
                        "analysis": analysis
                    })
    
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
                
                # missing_items - JSON 구조 처리
                missing_items = suggestion.get("missing_items", [])
                if missing_items and analysis_text:
                    for item in missing_items:
                        if isinstance(item, dict):
                            # JSON 구조: {"std_article": "제X조", "std_clause": "제Y항", "reason": "..."}
                            std_article = item.get("std_article", "")
                            std_clause = item.get("std_clause", "")
                            std_clause_id = self._map_json_to_global_id(std_article, std_clause)
                            if std_clause_id:
                                analysis_map[user_article_no]["missing"][std_clause_id] = analysis_text
                        elif isinstance(item, str):
                            # Fallback: 문자열 ID
                            analysis_map[user_article_no]["missing"][item] = analysis_text
                
                # insufficient_items - JSON 구조 처리
                insufficient_items = suggestion.get("insufficient_items", [])
                if insufficient_items and analysis_text:
                    for item in insufficient_items:
                        if isinstance(item, dict):
                            # JSON 구조
                            std_article = item.get("std_article", "")
                            std_clause = item.get("std_clause", "")
                            std_clause_id = self._map_json_to_global_id(std_article, std_clause)
                            if std_clause_id:
                                analysis_map[user_article_no]["insufficient"][std_clause_id] = analysis_text
                        elif isinstance(item, str):
                            # Fallback: 문자열 ID
                            analysis_map[user_article_no]["insufficient"][item] = analysis_text
        
        # resolved에 분석 텍스트 첨부
        # Step1에서 이미 {std_clause_id, analysis} 형식으로 저장되어 있으므로
        # 이 단계는 건너뜀 (이미 분석 텍스트가 포함되어 있음)
        pass
    
    def _generate_overall_missing_analysis(self, resolved: Dict, preamble_analysis_map: Dict = None):
        """
        overall_missing_clauses에 대한 분석 생성 (중복 제거)
        
        Args:
            resolved: 보정 결과
            preamble_analysis_map: 서문 항목의 analysis 매핑 (std_clause_id -> analysis)
        """
        # 서문 항목의 analysis 매핑 (Step1에서 전달)
        if preamble_analysis_map is None:
            preamble_analysis_map = {}
        
        overall_missing_with_analysis = []
        seen_ids = set()
        
        for std_clause_id in resolved["overall_missing_clauses"]:
            # 중복 제거
            if std_clause_id in seen_ids:
                continue
            seen_ids.add(std_clause_id)
            
            # 서문 항목이면 원래 analysis 사용, 아니면 기본 텍스트
            if std_clause_id in preamble_analysis_map:
                analysis = preamble_analysis_map[std_clause_id]
                logger.debug(f"서문 항목 analysis 사용: {std_clause_id}")
            else:
                analysis = f"사용자 계약서 전체에서 해당 조항을 찾을 수 없습니다. " \
                          f"표준계약서에서는 이 조항이 필수적으로 포함되어야 합니다."
            
            overall_missing_with_analysis.append({
                "std_clause_id": std_clause_id,
                "analysis": analysis
            })
        
        resolved["overall_missing_clauses"] = overall_missing_with_analysis

    def _map_json_to_global_id(self, std_article: str, std_clause: str) -> str:
        """
        JSON 구조에서 global_id 매핑 (Step1과 동일한 로직)
        
        Args:
            std_article: "제X조" 형식
            std_clause: "제Y항", "제Y호", 또는 "조본문" 형식
            
        Returns:
            global_id 또는 빈 문자열
        """
        import re
        
        # 조 번호 추출
        article_match = re.search(r'제(\d+)조', std_article)
        if not article_match:
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
        
        # global_id 패턴 생성 (간단한 패턴 매칭)
        # 실제 청크 데이터가 없으므로 패턴만 생성
        if is_article_text:
            return f"urn:std:provide:art:{article_no:03d}:att"
        elif clause_no is not None:
            return f"urn:std:provide:art:{article_no:03d}:cla:{clause_no:03d}"
        elif sub_no is not None:
            return f"urn:std:provide:art:{article_no:03d}:sub:{sub_no:03d}"
        else:
            return f"urn:std:provide:art:{article_no:03d}"

    def _get_user_article_content(self, article_no: int) -> str:
        """
        사용자 조항 내용 가져오기
        
        Args:
            article_no: 조항 번호
            
        Returns:
            조항 내용 (제목 + 본문)
        """
        if not hasattr(self, 'user_contract_data') or not self.user_contract_data:
            return "[사용자 조항 내용 없음]"
        
        articles = self.user_contract_data.get('articles', [])
        
        for article in articles:
            if article.get('number') == article_no:
                title = article.get('title', '')
                content = article.get('content', '')
                
                # 제목과 내용 포맷팅
                if title:
                    return f"제{article_no}조 ({title})\n{content[:500]}"
                else:
                    return f"제{article_no}조\n{content[:500]}"
        
        return f"[제{article_no}조 내용을 찾을 수 없음]"

    def _llm_select_best_insufficient(self, std_clause_id: str, evaluations: List[Dict]) -> List[int]:
        """
        LLM을 사용하여 가장 구체적이고 포괄적인 불충분 평가 선택
        
        Args:
            std_clause_id: 표준 조항 ID
            evaluations: 불충분 평가 목록
            
        Returns:
            유지할 평가의 인덱스 리스트
        """
        # 평가 내역 포맷팅
        evaluations_text = ""
        for i, eval in enumerate(evaluations, 1):
            user_article = eval["user_article"]
            analysis = eval.get("analysis", "")
            evaluations_text += f"\n평가 {i} ({user_article}):\n{analysis}\n"
        
        prompt = f"""
다음은 같은 표준 조항 "{std_clause_id}"에 대한 여러 불충분 평가입니다:

{evaluations_text}

**판단 기준:**
1. **중복 제거**: 같은 내용을 지적하는 평가는 하나만 유지
2. **포괄성**: 여러 평가 중 하나가 다른 것들을 포함하면 그것만 유지
3. **구체성**: 더 구체적이고 상세한 평가를 우선
4. **독립성**: 서로 다른 문제를 지적하면 모두 유지

**응답 형식 (JSON만 출력):**
```json
{{
  "keep": [1, 3],
  "reasoning": "평가 1과 2는 같은 문제(예외 상황 규정 없음)를 지적하므로 1만 유지. 평가 3은 더 구체적인 문제(임직원/전문가 공개 조건)를 지적하므로 유지."
}}
```

**중요**: 
- keep 배열에는 유지할 평가 번호만 포함 (1부터 시작)
- 최소 1개는 유지해야 함
- 모두 다른 문제면 모두 유지
"""
        
        try:
            response = self.llm.chat.completions.create(
                model=self.gpt_model,
                messages=[
                    {"role": "system", "content": "당신은 계약서 검증 전문가입니다."},
                    {"role": "user", "content": prompt}
                ],
                temperature=0.1,
                max_tokens=500
            )
            
            response_text = response.choices[0].message.content.strip()
            
            # JSON 파싱
            if '```json' in response_text:
                json_text = response_text.split('```json')[1].split('```')[0].strip()
            elif '```' in response_text:
                json_text = response_text.split('```')[1].split('```')[0].strip()
            else:
                json_text = response_text
            
            result = json.loads(json_text)
            keep_indices = result.get('keep', [])
            reasoning = result.get('reasoning', '')
            
            # 1-based를 0-based로 변환
            keep_indices = [idx - 1 for idx in keep_indices if 0 < idx <= len(evaluations)]
            
            logger.info(f"LLM 불충분 선택: {std_clause_id}")
            logger.info(f"  - 유지: {[i+1 for i in keep_indices]}")
            logger.info(f"  - 이유: {reasoning}")
            
            return keep_indices if keep_indices else [0]  # 최소 1개는 유지
            
        except Exception as e:
            logger.error(f"LLM 불충분 선택 실패: {e}, 모두 유지")
            return list(range(len(evaluations)))  # 실패 시 모두 유지

    def _collect_insufficient_from_resolved(self, resolved: Dict, std_clause_id: str) -> List[Dict]:
        """
        resolved에서 특정 표준 조항에 대한 모든 insufficient 평가 수집
        
        Args:
            resolved: 보정 결과
            std_clause_id: 표준 조항 ID
            
        Returns:
            [{user_article: str, analysis: str}]
        """
        insufficient_evals = []
        
        for user_article_no, data in resolved["user_articles"].items():
            for item in data.get("insufficient", []):
                if item.get("std_clause_id") == std_clause_id:
                    insufficient_evals.append({
                        "user_article": user_article_no,
                        "analysis": item.get("analysis", "")
                    })
        
        return insufficient_evals
    
    def _deduplicate_insufficient_in_resolved(self, resolved: Dict, std_clause_id: str, 
                                             insufficient_evals: List[Dict]):
        """
        resolved에서 insufficient 중복 제거 (LLM 선택)
        
        Args:
            resolved: 보정 결과
            std_clause_id: 표준 조항 ID
            insufficient_evals: insufficient 평가 목록
        """
        # LLM으로 선택
        selected_indices = self._llm_select_best_insufficient(std_clause_id, insufficient_evals)
        
        # 선택된 평가만 유지
        selected_user_articles = {insufficient_evals[idx]["user_article"] 
                                 for idx in selected_indices if idx < len(insufficient_evals)}
        
        # resolved에서 선택되지 않은 평가 제거
        for user_article_no, data in resolved["user_articles"].items():
            if user_article_no not in selected_user_articles:
                # 이 user_article의 insufficient에서 std_clause_id 제거
                data["insufficient"] = [
                    item for item in data.get("insufficient", [])
                    if item.get("std_clause_id") != std_clause_id
                ]
        
        logger.info(f"  중복 제거 완료: {len(insufficient_evals)}개 → {len(selected_indices)}개")
