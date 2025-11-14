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

동일한 표준 조항 "{std_clause_id}"에 대해 여러 평가가 있습니다.
이 평가들의 관계를 분석하고 최종 판단을 내려주세요.

**평가 내역:**
{evaluations}

**판단 기준:**

1. **서로 다른 사용자 조항**: 각각 독립적인 사실
   - 예: user_article_3 (sufficient) vs user_article_9 (missing)
   - 의미: "제3조에는 있지만 제9조에는 없다"
   - 해결: **keep_all** (둘 다 사실이므로 모두 유지)

2. **부분 매칭 (Partial Match)**: 같은 사용자 조항, 일부만 충족
   - 예: user_article_5 (sufficient) vs user_article_5 (missing)
   - 분석 내용이 서로 다른 측면을 다룸:
     * sufficient: "일부 내용(A, B)은 포함됨"
     * missing: "다른 내용(C, D)은 누락됨"
   - 의미: 표준 조항의 일부는 있고 일부는 없음
   - 해결: **keep_all** (부분 매칭이므로 둘 다 유지)

3. **품질 문제**: 같은 사용자 조항, 내용은 있으나 불충분
   - 예: user_article_5 (sufficient) vs user_article_5 (insufficient)
   - 의미: "내용은 있지만 품질이 부족함"
   - 해결: **keep_insufficient** (더 정확한 평가)

4. **진짜 충돌**: 같은 사용자 조항, 같은 내용에 대한 상반된 판단
   - 예: user_article_5 (sufficient: "제5조에 X가 있음") vs user_article_5 (missing: "제5조에 X가 없음")
   - 의미: 완전히 모순되는 판단
   - 해결: 더 정확한 평가 하나만 선택

**부분 매칭 판단 핵심**:
분석 내용을 자세히 읽고 다음을 확인하세요:

1. **sufficient 평가 (A1 매칭 결과)**:
   - "사용자 조항이 표준 조항과 매칭됨" (전체적 판단)
   - 어떤 내용이 포함되었는지 확인

2. **missing/insufficient 평가 (A3 상세 분석)**:
   - "특정 내용이 누락/불충분함" (세부적 판단)
   - 어떤 내용이 문제인지 확인

3. **판단 기준**:
   - missing 분석에 **"일부", "특정", "~에 대한"** 등의 표현이 있으면:
     → **keep_all** (부분 매칭: 일부는 있고 일부는 없음)
   
   - missing 분석이 **"전체", "완전히", "모든"** 등을 언급하면:
     → **keep_missing** (A1 오류: 실제로는 매칭 안 됨)
   
   - insufficient 평가라면:
     → **keep_insufficient** (내용은 있으나 품질 문제)

**예시**:
- "제10조 제2항 내용이 누락" → keep_all (일부 누락)
- "제10조 전체 내용이 없음" → keep_missing (완전 누락)
- "제10조 내용이 불충분함" → keep_insufficient (품질 문제)

**응답 형식 (JSON만 출력):**
```json
{{
  "is_contradiction": true | false,
  "resolution": "keep_all" | "keep_sufficient" | "keep_insufficient" | "keep_missing",
  "reasoning": "판단 근거 (한글로 상세히 설명)"
}}
```

**resolution 설명:**
- "keep_all": 서로 다른 사실 또는 부분 매칭 (모든 평가 유지)
- "keep_sufficient": 진짜 충돌이며, sufficient 평가가 정확함
- "keep_insufficient": 진짜 충돌이며, insufficient 평가가 정확함
- "keep_missing": 진짜 충돌이며, missing 평가가 정확함

**중요**: 
- 대부분의 경우 "keep_all"입니다 (서로 다른 조항 또는 부분 매칭)
- 진짜 충돌은 매우 드뭅니다
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
        aggregated = step2_result.get("aggregated", step2_result)  # 하위 호환성
        
        for std_clause_id, data in aggregated.items():
            if data["has_conflict"]:
                conflict_count += 1
                
                # 자동 해소 규칙
                statuses = {e["status"] for e in data["evaluations"]}
                
                # 규칙 1: sufficient/insufficient + missing
                if "missing" in statuses and len(statuses) > 1:
                    # 같은 user_article인지 확인
                    user_articles = {e["user_article"] for e in data["evaluations"]}
                    
                    if len(user_articles) == 1:
                        # 같은 조항 → 모순 (A1: sufficient, A3: missing)
                        # A3가 더 정확하므로 missing만 유지
                        logger.info(f"자동 해소: {std_clause_id} (같은 조항의 sufficient + missing → missing 우선)")
                        missing_evals = [e for e in data["evaluations"] if e["status"] == "missing"]
                        for evaluation in missing_evals:
                            user_article_no = evaluation["user_article"]
                            if user_article_no in resolved["user_articles"]:
                                resolved["user_articles"][user_article_no]["missing"].append({
                                    "std_clause_id": std_clause_id,
                                    "analysis": evaluation.get("analysis", "")
                                })
                        auto_resolved_count += 1
                    else:
                        # 다른 조항 → 불충분 (일부는 있고 일부는 없음)
                        logger.info(f"자동 해소: {std_clause_id} (다른 조항의 {statuses} → insufficient)")
                        # missing을 insufficient로 변환
                        for evaluation in data["evaluations"]:
                            if evaluation["status"] == "missing":
                                evaluation["status"] = "insufficient"
                                # 분석 텍스트에 [누락됨] 표시
                                if not evaluation.get("analysis", "").startswith("[누락됨]"):
                                    evaluation["analysis"] = f"[누락됨] {evaluation.get('analysis', '')}"
                        # 이제 모두 insufficient → LLM 선택
                        self._resolve_insufficient_duplicates(resolved, std_clause_id, data)
                        auto_resolved_count += 1
                
                # 규칙 2: insufficient만 있는 경우 → LLM 선택
                elif statuses == {"insufficient"}:
                    logger.info(f"자동 해소: {std_clause_id} (insufficient + insufficient → LLM 선택)")
                    self._resolve_insufficient_duplicates(resolved, std_clause_id, data)
                    auto_resolved_count += 1
                
                else:
                    # LLM 충돌 해소
                    resolution = self._resolve_conflict_with_llm(std_clause_id, data)
                    
                    if resolution["resolution"] == "keep_all":
                        # 모든 평가 유지 (서로 다른 사실)
                        self._apply_resolution_keep_all(resolved, std_clause_id, data)
                        llm_resolved_count += 1
                    else:
                        # 하나만 선택 (진짜 충돌)
                        final_status = self._map_resolution_to_status(resolution["resolution"])
                        self._apply_resolution(resolved, std_clause_id, data, final_status)
            else:
                # 충돌 없음 - 단일 상태 사용
                final_status = data["evaluations"][0]["status"]
                self._apply_resolution(resolved, std_clause_id, data, final_status)
        
        logger.info(f"충돌 해소 완료: {conflict_count}개 충돌 처리 "
                   f"(자동 해소: {auto_resolved_count}개, LLM 해소: {llm_resolved_count}개)")
        
        # A3 원본 분석 텍스트 첨부
        self._attach_analysis_text(resolved, a3_result)
        logger.info("A3 원본 분석 텍스트 첨부 완료")
        
        # overall_missing_clauses에 분석 텍스트 추가
        self._generate_overall_missing_analysis(resolved)
        logger.info("전역 누락 조항 분석 생성 완료")
        
        logger.info("Step 3 충돌 해소 완료")
        return resolved
    

    def _resolve_conflict_with_llm(self, std_clause_id: str, conflict_data: Dict) -> Dict:
        """
        LLM을 사용한 충돌 해소
        
        Args:
            std_clause_id: 표준 조항 ID
            conflict_data: 충돌 데이터
            
        Returns:
            {
                "is_contradiction": bool,
                "resolution": str,
                "reasoning": str
            }
        """
        # 충돌 정보 로깅
        logger.info(f"충돌 분석 시작: {std_clause_id}")
        logger.info(f"  - 평가 개수: {len(conflict_data['evaluations'])}개")
        for eval in conflict_data["evaluations"]:
            logger.info(f"    * {eval['user_article']}: {eval['status']}")
        
        # 평가 내역 포맷팅
        evaluations_text = ""
        for i, eval in enumerate(conflict_data["evaluations"], 1):
            user_article = eval["user_article"]
            status = eval["status"]
            analysis = eval.get("analysis", "")
            
            status_kr = {
                "sufficient": "충족",
                "insufficient": "불충분",
                "missing": "누락"
            }.get(status, status)
            
            # 사용자 조항 내용 가져오기
            user_article_no = int(user_article.replace("user_article_", ""))
            user_article_content = self._get_user_article_content(user_article_no)
            
            evaluations_text += f"\n평가 {i}:\n"
            evaluations_text += f"  - 사용자 조항: {user_article}\n"
            evaluations_text += f"  - 사용자 조항 내용:\n{user_article_content}\n"
            evaluations_text += f"  - 상태: {status_kr}\n"
            evaluations_text += f"  - 분석: {analysis[:300]}...\n"
        
        # 프롬프트 생성
        prompt = CONFLICT_RESOLUTION_PROMPT.format(
            std_clause_id=std_clause_id,
            evaluations=evaluations_text
        )
        
        # LLM 호출
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
            import json
            if '```json' in response_text:
                json_text = response_text.split('```json')[1].split('```')[0].strip()
            elif '```' in response_text:
                json_text = response_text.split('```')[1].split('```')[0].strip()
            else:
                json_text = response_text
            
            result = json.loads(json_text)
            
            # 상세 로그
            resolution = result['resolution']
            reasoning = result.get('reasoning', '')
            is_contradiction = result.get('is_contradiction', False)
            
            # 충돌 유형 표시
            conflict_type = "진짜 충돌" if is_contradiction else "서로 다른 사실/부분 매칭"
            
            logger.info(f"LLM 충돌 해소: {std_clause_id}")
            logger.info(f"  - 충돌 유형: {conflict_type}")
            logger.info(f"  - 해소 방법: {resolution}")
            logger.info(f"  - 판단 근거: {reasoning}")
            
            return result
            
        except Exception as e:
            logger.error(f"LLM 충돌 해소 실패: {e}, fallback to priority rules")
            # Fallback: 우선순위 규칙
            return {
                "is_contradiction": True,
                "resolution": f"keep_{self._apply_priority_rules(conflict_data)}",
                "reasoning": f"LLM 오류로 인한 fallback: {str(e)}"
            }
    
    def _map_resolution_to_status(self, resolution: str) -> str:
        """
        resolution을 status로 매핑
        
        Args:
            resolution: "keep_sufficient", "keep_insufficient", "keep_missing"
            
        Returns:
            "sufficient", "insufficient", "missing"
        """
        mapping = {
            "keep_sufficient": "sufficient",
            "keep_insufficient": "insufficient",
            "keep_missing": "missing"
        }
        return mapping.get(resolution, "sufficient")
    
    def _apply_resolution_insufficient_merge(self, resolved: Dict, std_clause_id: str, conflict_data: Dict):
        """
        sufficient/insufficient + missing → insufficient로 병합
        
        논리: 일부는 있고 일부는 없으면 = 불충분
        
        Args:
            resolved: 보정 결과
            std_clause_id: 표준 조항 ID
            conflict_data: 충돌 데이터
        """
        # 모든 평가를 insufficient로 통합
        merged_analysis_parts = []
        user_articles_involved = set()
        
        for evaluation in conflict_data["evaluations"]:
            user_article_no = evaluation["user_article"]
            status = evaluation["status"]
            analysis = evaluation.get("analysis", "")
            
            user_articles_involved.add(user_article_no)
            
            if status == "sufficient":
                merged_analysis_parts.append(f"[매칭됨] {analysis if analysis else '표준 조항과 매칭됨'}")
            elif status == "insufficient":
                merged_analysis_parts.append(f"[불충분] {analysis}")
            elif status == "missing":
                merged_analysis_parts.append(f"[누락됨] {analysis}")
        
        # 통합된 분석 텍스트
        merged_analysis = " | ".join(merged_analysis_parts)
        
        # 각 관련 user_article에 insufficient로 추가
        for user_article_no in user_articles_involved:
            if user_article_no in resolved["user_articles"]:
                resolved["user_articles"][user_article_no]["insufficient"].append({
                    "std_clause_id": std_clause_id,
                    "analysis": merged_analysis
                })
    
    def _resolve_insufficient_duplicates(self, resolved: Dict, std_clause_id: str, conflict_data: Dict):
        """
        insufficient + insufficient → LLM으로 가장 구체적인 것 선택
        
        Args:
            resolved: 보정 결과
            std_clause_id: 표준 조항 ID
            conflict_data: 충돌 데이터
        """
        evaluations = conflict_data["evaluations"]
        
        # 같은 user_article인지 확인
        user_articles = {e["user_article"] for e in evaluations}
        
        if len(user_articles) == 1:
            # 같은 조항 → 중복 제거 (첫 번째만 유지)
            logger.info(f"  같은 조항의 중복 → 첫 번째만 유지")
            evaluation = evaluations[0]
            user_article_no = evaluation["user_article"]
            if user_article_no in resolved["user_articles"]:
                resolved["user_articles"][user_article_no]["insufficient"].append({
                    "std_clause_id": std_clause_id,
                    "analysis": evaluation.get("analysis", "")
                })
        else:
            # 다른 조항 → LLM 판단
            logger.info(f"  다른 조항의 불충분 → LLM 선택")
            selected_indices = self._llm_select_best_insufficient(std_clause_id, evaluations)
            
            for idx in selected_indices:
                if idx < len(evaluations):
                    evaluation = evaluations[idx]
                    user_article_no = evaluation["user_article"]
                    if user_article_no in resolved["user_articles"]:
                        resolved["user_articles"][user_article_no]["insufficient"].append({
                            "std_clause_id": std_clause_id,
                            "analysis": evaluation.get("analysis", "")
                        })
    
    def _apply_resolution_keep_all(self, resolved: Dict, std_clause_id: str, conflict_data: Dict):
        """
        모든 평가 유지 (서로 다른 사실)
        
        Args:
            resolved: 보정 결과
            std_clause_id: 표준 조항 ID
            conflict_data: 충돌 데이터
        """
        # 각 평가를 해당 user_article에 추가
        for evaluation in conflict_data["evaluations"]:
            user_article_no = evaluation["user_article"]
            status = evaluation["status"]
            analysis = evaluation.get("analysis", "")
            
            if user_article_no in resolved["user_articles"]:
                # matched도 {id, analysis} 형식으로 통일
                if status == "sufficient":
                    # 중복 체크 (std_clause_id 기준)
                    existing_ids = [m.get("std_clause_id") if isinstance(m, dict) else m 
                                   for m in resolved["user_articles"][user_article_no]["matched"]]
                    if std_clause_id not in existing_ids:
                        resolved["user_articles"][user_article_no]["matched"].append({
                            "std_clause_id": std_clause_id,
                            "analysis": analysis if analysis else "표준 조항과 매칭됨"
                        })
                else:
                    resolved["user_articles"][user_article_no][status].append({
                        "std_clause_id": std_clause_id,
                        "analysis": analysis
                    })
    
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
