"""
ChecklistVerifier - LLM 기반 체크리스트 검증

A2 노드에서 사용하는 체크리스트 항목 검증 컴포넌트
"""

import json
import logging
from typing import Dict, Any, List, Optional
from openai import AzureOpenAI

logger = logging.getLogger(__name__)


class ChecklistVerifier:
    """
    LLM 기반 체크리스트 검증기
    
    주요 기능:
    1. 단일 체크리스트 항목 검증 (LLM)
    2. 배치 체크리스트 검증 (성능 최적화)
    3. 신뢰도 기반 재검증 (표준 조항 컨텍스트 추가)
    4. UNCLEAR 상태 처리
    """
    
    # 신뢰도 임계값
    CONFIDENCE_THRESHOLD = 0.7
    
    def __init__(
        self,
        azure_client: AzureOpenAI,
        model: str = "gpt-4o-mini"  # 🔥 A2는 mini 모델 사용 (속도 향상)
    ):
        """
        ChecklistVerifier 초기화
        
        Args:
            azure_client: Azure OpenAI 클라이언트
            model: 사용할 모델명 (기본: gpt-4o-mini)
        """
        self.azure_client = azure_client
        self.model = model
        
        logger.info(f"ChecklistVerifier 초기화 완료 (model={model})")
    
    def verify_single(
        self,
        user_clause_text: str,
        checklist_item: Dict[str, Any]
    ) -> Dict[str, Any]:
        """
        단일 체크리스트 항목 검증
        
        Args:
            user_clause_text: 사용자 조항 전문 (제목 + 내용)
            checklist_item: 체크리스트 항목
                {
                    "check_text": str,
                    "reference": str,
                    "global_id": str
                }
        
        Returns:
            검증 결과
            {
                "check_text": str,
                "reference": str,
                "std_global_id": str,
                "result": "YES" | "NO",
                "evidence": str | None,
                "confidence": float
            }
        """
        check_text = checklist_item.get('check_text', '')
        reference = checklist_item.get('reference', '')
        global_id = checklist_item.get('global_id', '')
        
        logger.debug(f"  단일 항목 검증: {check_text[:50]}...")
        
        # 프롬프트 생성
        prompt = f"""다음 계약서 조항이 이 요구사항을 충족하는가?

[계약서 조항]
{user_clause_text}

[요구사항]
{check_text}

YES 또는 NO로 답변하고, 판단 근거를 제시해주세요.
신뢰도(0.0~1.0)도 함께 제공해주세요.

**판단 기준:**
- YES: 요구사항이 계약서에 명시되어 있음
- NO: 요구사항이 계약서에 명시되지 않음

JSON 형식:
{{
  "result": "YES" or "NO",
  "evidence": "판단 근거 (YES인 경우 계약서의 해당 부분 인용)" or null,
  "confidence": 0.95
}}"""
        
        try:
            response = self.azure_client.chat.completions.create(
                model=self.model,
                messages=[
                    {
                        "role": "system",
                        "content": "당신은 계약서 검증 전문가입니다. 체크리스트 항목이 계약서에 충족되는지 정확하게 판단해주세요."
                    },
                    {
                        "role": "user",
                        "content": prompt
                    }
                ],
                temperature=0.1,
                max_tokens=500,
                response_format={"type": "json_object"}
            )
            
            response_text = response.choices[0].message.content.strip()
            llm_result = json.loads(response_text)
            
            return {
                "check_text": check_text,
                "reference": reference,
                "std_global_id": global_id,
                "result": llm_result.get('result', 'NO'),
                "evidence": llm_result.get('evidence'),
                "confidence": float(llm_result.get('confidence', 0.5))
            }
        
        except Exception as e:
            logger.error(f"  단일 항목 검증 실패: {e}")
            return {
                "check_text": check_text,
                "reference": reference,
                "std_global_id": global_id,
                "result": "NO",
                "evidence": f"검증 실패: {str(e)}",
                "confidence": 0.0
            }
    
    def verify_batch(
        self,
        user_clause_text: str,
        checklist_items: List[Dict[str, Any]],
        batch_size: int = 5
    ) -> List[Dict[str, Any]]:
        """
        여러 체크리스트 항목을 배치로 검증
        
        Args:
            user_clause_text: 사용자 조항 전문
            checklist_items: 체크리스트 항목 리스트
            batch_size: 배치 크기 (기본 10개)
        
        Returns:
            검증 결과 리스트
            [
                {
                    "check_text": str,
                    "reference": str,
                    "std_global_id": str,
                    "result": "YES" | "NO",
                    "evidence": str | None,
                    "confidence": float
                },
                ...
            ]
        """
        if not checklist_items:
            return []
        
        results = []
        total_items = len(checklist_items)
        
        logger.info(f"  배치 검증 시작: {total_items}개 항목 (배치 크기: {batch_size})")
        
        # 배치 단위로 처리
        for i in range(0, total_items, batch_size):
            batch = checklist_items[i:i+batch_size]
            batch_num = (i // batch_size) + 1
            total_batches = (total_items + batch_size - 1) // batch_size
            
            logger.info(f"  배치 {batch_num}/{total_batches} 처리 중 ({len(batch)}개 항목)...")
            
            try:
                batch_results = self._verify_batch_llm(user_clause_text, batch)
                results.extend(batch_results)
                logger.info(f"  배치 {batch_num}/{total_batches} 완료")
            
            except Exception as e:
                logger.error(f"  배치 {batch_num} 검증 실패: {e}, 개별 검증으로 폴백")
                
                # 배치 실패 시 개별 검증
                for item in batch:
                    try:
                        result = self.verify_single(user_clause_text, item)
                        results.append(result)
                    except Exception as e2:
                        logger.error(f"  개별 검증도 실패: {e2}, 항목 건너뜀")
                        # 실패한 항목도 결과에 포함 (NO 처리)
                        results.append({
                            "check_text": item.get('check_text', ''),
                            "reference": item.get('reference', ''),
                            "std_global_id": item.get('global_id', ''),
                            "result": "NO",
                            "evidence": f"검증 실패: {str(e2)}",
                            "confidence": 0.0
                        })
        
        logger.info(f"  배치 검증 완료: {len(results)}개 결과")
        return results
    
    def _verify_batch_llm(
        self,
        user_clause_text: str,
        checklist_items: List[Dict[str, Any]]
    ) -> List[Dict[str, Any]]:
        """
        LLM을 사용한 배치 검증
        
        Args:
            user_clause_text: 사용자 조항 전문
            checklist_items: 체크리스트 항목 리스트 (최대 batch_size개)
        
        Returns:
            검증 결과 리스트
        """
        # 체크리스트 항목을 번호와 함께 포맷팅
        checklist_text = ""
        for idx, item in enumerate(checklist_items, 1):
            checklist_text += f"{idx}. {item.get('check_text', '')}\n"
        
        prompt = f"""다음 계약서 조항이 아래 체크리스트 요구사항들을 충족하는지 검증해주세요.

[계약서 조항]
{user_clause_text}

[체크리스트]
{checklist_text}

각 항목에 대해 다음 형식으로 답변해주세요:
1. 결과: YES, NO, 또는 MANUAL_CHECK_REQUIRED
2. 근거: 판단 근거 (YES인 경우 계약서의 해당 부분 인용, 간략히)
3. 신뢰도: 0.0~1.0 사이의 값
4. 사용자 확인 필요 시: 이유와 확인 방법
5. NO인 경우: 왜 매칭되지 않는지 구체적 설명 및 위험성 평가

**판단 기준:**
- **YES**: 요구사항이 계약서에 명시되어 있음
- **NO**: 요구사항이 계약서에 명시되지 않음 (내용 자체가 없음)
- **MANUAL_CHECK_REQUIRED**: 계약서에 내용은 있으나 외부 확인이 필요함
  
**MANUAL_CHECK_REQUIRED 판단 기준 (매우 중요!):**
다음 조건을 **모두** 만족해야 MANUAL_CHECK_REQUIRED입니다:
1. **계약서에 해당 내용이 이미 기재되어 있어야 함**
2. **그 내용이 정확한지 외부 문서/정보와 대조가 필요함**

**구체적 예시:**

✅ MANUAL_CHECK_REQUIRED (내용 있음 + 외부 확인 필요):
- 계약서: "갑: 주식회사 ABC, 서울시 강남구..." 
  → 질문: "등기부등본과 일치하는가?" 
  → MANUAL_CHECK_REQUIRED (내용은 있으나 등기부등본 대조 필요)

- 계약서: "대표이사 홍길동"
  → 질문: "적법한 권한을 가진 대표자인가?"
  → MANUAL_CHECK_REQUIRED (내용은 있으나 법적 권한 확인 필요)

- 계약서: "날인란: [   ]"
  → 질문: "날인이 되어 있는가?"
  → MANUAL_CHECK_REQUIRED (날인란은 있으나 실제 날인 여부는 물리적 확인 필요)

❌ NO (내용 자체가 없음):
- 계약서: 당사자 정보 없음
  → 질문: "당사자가 개인인가 법인인가?"
  → NO (당사자 정보 자체가 없으므로 추가 필요)

- 계약서: 대표자 이름 없음
  → 질문: "대표자 성명이 기재되어 있는가?"
  → NO (대표자 정보 자체가 없으므로 추가 필요)

**핵심 원칙**: 
- 내용이 **없으면** → NO (추가 필요)
- 내용이 **있는데 확인이 필요하면** → MANUAL_CHECK_REQUIRED (외부 확인 필요)

**NO 판단 시 추가 정보:**
- missing_explanation: 어떤 키워드/개념을 찾았는지, 왜 충분하지 않은지 구체적 설명
- risk_level: "high" | "medium" | "low" - 누락 시 위험도
- risk_description: 이 항목이 없으면 어떤 법적/실무적 위험이 있는지 설명
- recommendation: 개선 권장사항

JSON 배열 형식으로 답변:
{{
  "results": [
    {{
      "item_number": 1,
      "result": "YES" or "NO" or "MANUAL_CHECK_REQUIRED",
      "evidence": "근거 텍스트" or null,
      "confidence": 0.95,
      "manual_check_reason": "외부 문서 대조 필요" (MANUAL_CHECK_REQUIRED인 경우만),
      "user_action": "등기부등본과 대조하여 회사명, 주소 확인" (MANUAL_CHECK_REQUIRED인 경우만),
      "missing_explanation": "수행계획서 작성 절차 명시 없음, 단순 일정 협의만 있음" (NO인 경우만),
      "risk_level": "high" (NO인 경우만),
      "risk_description": "수행계획서 미작성 시 용역 범위 분쟁 가능성" (NO인 경우만),
      "recommendation": "제1조에 수행계획서 작성 및 제출 절차 추가" (NO인 경우만)
    }},
    ...
  ]
}}"""
        
        response = self.azure_client.chat.completions.create(
            model=self.model,
            messages=[
                {
                    "role": "system",
                    "content": "당신은 계약서 검증 전문가입니다. 체크리스트 항목이 계약서에 충족되는지 정확하게 판단해주세요."
                },
                {
                    "role": "user",
                    "content": prompt
                }
            ],
            temperature=0.1,
            max_tokens=2000,
            response_format={"type": "json_object"}
        )
        
        # 응답 파싱
        response_text = response.choices[0].message.content.strip()
        llm_data = json.loads(response_text)
        llm_results = llm_data.get('results', [])
        
        # 결과 매핑
        results = []
        for idx, item in enumerate(checklist_items):
            # LLM 결과에서 해당 항목 찾기
            llm_result = None
            if idx < len(llm_results):
                llm_result = llm_results[idx]
            
            if llm_result:
                result_data = {
                    "check_text": item.get('check_text', ''),
                    "reference": item.get('reference', ''),
                    "std_global_id": item.get('global_id', ''),
                    "result": llm_result.get('result', 'NO'),
                    "evidence": llm_result.get('evidence'),
                    "confidence": float(llm_result.get('confidence', 0.5))
                }
                
                # MANUAL_CHECK_REQUIRED인 경우 추가 정보 포함
                if llm_result.get('result') == 'MANUAL_CHECK_REQUIRED':
                    result_data['manual_check_reason'] = llm_result.get('manual_check_reason', '')
                    result_data['user_action'] = llm_result.get('user_action', '')
                
                # NO인 경우 추가 정보 포함
                elif llm_result.get('result') == 'NO':
                    result_data['missing_explanation'] = llm_result.get('missing_explanation', '')
                    result_data['risk_level'] = llm_result.get('risk_level', 'medium')
                    result_data['risk_description'] = llm_result.get('risk_description', '')
                    result_data['recommendation'] = llm_result.get('recommendation', '')
                
                results.append(result_data)
            else:
                # LLM 결과가 없으면 NO 처리
                logger.warning(f"  항목 {idx+1}의 LLM 결과 없음, NO 처리")
                results.append({
                    "check_text": item.get('check_text', ''),
                    "reference": item.get('reference', ''),
                    "std_global_id": item.get('global_id', ''),
                    "result": "NO",
                    "evidence": "LLM 응답에서 결과를 찾을 수 없음",
                    "confidence": 0.0
                })
        
        return results

    
    def verify_with_context(
        self,
        user_clause_text: str,
        std_clause_text: str,
        checklist_item: Dict[str, Any]
    ) -> Dict[str, Any]:
        """
        표준 조항 컨텍스트를 포함한 검증
        
        신뢰도가 낮을 때 표준 조항을 참고하여 재검증
        
        Args:
            user_clause_text: 사용자 조항 텍스트
            std_clause_text: 표준 조항 텍스트
            checklist_item: 체크리스트 항목
        
        Returns:
            검증 결과
        """
        check_text = checklist_item.get('check_text', '')
        reference = checklist_item.get('reference', '')
        global_id = checklist_item.get('global_id', '')
        
        logger.info(f"  컨텍스트 포함 재검증: {check_text[:50]}...")
        
        prompt = f"""다음 사용자 계약서 조항이 체크리스트 요구사항을 충족하는지 검증해주세요.

[사용자 계약서 조항]
{user_clause_text}

[참고: 표준계약서 조항]
{std_clause_text}

[체크리스트 요구사항]
{check_text}

표준계약서를 참고하여 더 정확히 판단해주세요.
사용자 조항이 표준과 완전히 동일하지 않아도, 의미적으로 유사하면 YES로 판단할 수 있습니다.

**판단 기준:**
- YES: 요구사항이 사용자 계약서에 명시되어 있음 (표현이 다르더라도 의미가 유사하면 YES)
- NO: 요구사항이 사용자 계약서에 명시되지 않음

JSON 형식으로 답변:
{{
  "result": "YES" or "NO",
  "evidence": "판단 근거 (YES인 경우 사용자 조항의 해당 부분 인용)" or null,
  "confidence": 0.95
}}"""
        
        try:
            response = self.azure_client.chat.completions.create(
                model=self.model,
                messages=[
                    {
                        "role": "system",
                        "content": "당신은 계약서 검증 전문가입니다. 표준계약서를 참고하여 정확하게 판단해주세요."
                    },
                    {
                        "role": "user",
                        "content": prompt
                    }
                ],
                temperature=0.1,
                max_tokens=500,
                response_format={"type": "json_object"}
            )
            
            response_text = response.choices[0].message.content.strip()
            llm_result = json.loads(response_text)
            
            return {
                "check_text": check_text,
                "reference": reference,
                "std_global_id": global_id,
                "result": llm_result.get('result', 'NO'),
                "evidence": llm_result.get('evidence'),
                "confidence": float(llm_result.get('confidence', 0.5))
            }
        
        except Exception as e:
            logger.error(f"  컨텍스트 포함 검증 실패: {e}")
            return {
                "check_text": check_text,
                "reference": reference,
                "std_global_id": global_id,
                "result": "NO",
                "evidence": f"재검증 실패: {str(e)}",
                "confidence": 0.0
            }
    
    def verify_with_low_confidence_handling(
        self,
        user_clause_text: str,
        checklist_item: Dict[str, Any],
        contract_type: str,
        kb_loader
    ) -> Dict[str, Any]:
        """
        신뢰도 기반 재검증 로직
        
        1차 검증에서 신뢰도가 낮을 경우 (< 0.7), 표준 조항 컨텍스트를 추가하여 재검증
        재검증 후에도 신뢰도가 낮으면 "UNCLEAR" 상태로 표시
        
        Args:
            user_clause_text: 사용자 조항 텍스트
            checklist_item: 체크리스트 항목
            contract_type: 계약 유형
            kb_loader: 지식베이스 로더 (표준 조항 로드용)
        
        Returns:
            검증 결과 (result, evidence, confidence, requires_manual_review)
        """
        # 1차 검증
        result = self.verify_single(user_clause_text, checklist_item)
        
        # 신뢰도 충분하면 바로 반환
        if result['confidence'] >= self.CONFIDENCE_THRESHOLD:
            result['requires_manual_review'] = False
            return result
        
        logger.warning(
            f"  신뢰도 낮음 ({result['confidence']:.2f}), "
            f"체크리스트: {checklist_item.get('check_text', '')[:50]}..."
        )
        
        # 표준 조항 로드 및 재검증
        try:
            std_clause_text = self._load_std_clause(
                checklist_item.get('global_id', ''),
                contract_type,
                kb_loader
            )
            
            logger.info("  표준 조항 컨텍스트 추가하여 재검증 시작")
            
            # 2차 검증 (컨텍스트 추가)
            result_v2 = self.verify_with_context(
                user_clause_text,
                std_clause_text,
                checklist_item
            )
            
            logger.info(f"  재검증 완료: 신뢰도 {result_v2['confidence']:.2f}")
            
            # 재검증 후에도 신뢰도 낮으면 UNCLEAR 처리
            if result_v2['confidence'] < self.CONFIDENCE_THRESHOLD:
                logger.warning(f"  재검증 후에도 신뢰도 낮음, UNCLEAR 처리")
                result_v2['result'] = "UNCLEAR"
                result_v2['requires_manual_review'] = True
            else:
                result_v2['requires_manual_review'] = False
            
            return result_v2
        
        except Exception as e:
            logger.error(f"  재검증 실패: {e}, 1차 검증 결과 사용")
            # 재검증 실패 시 1차 결과 사용 (UNCLEAR 처리)
            result['result'] = "UNCLEAR"
            result['requires_manual_review'] = True
            result['evidence'] = f"재검증 실패: {str(e)}"
            return result
    
    def _load_std_clause(
        self,
        std_global_id: str,
        contract_type: str,
        kb_loader
    ) -> str:
        """
        표준 조항 텍스트 로드
        
        Args:
            std_global_id: 표준 조항 global_id (예: "urn:std:provide:art:001")
            contract_type: 계약 유형
            kb_loader: 지식베이스 로더
        
        Returns:
            표준 조항 전문 (제목 + 내용)
        
        Raises:
            ValueError: 표준 조항을 찾을 수 없는 경우
        """
        # 지식베이스에서 청크 로드
        chunks = kb_loader.load_chunks(contract_type)
        
        # global_id가 일치하는 청크들 수집
        matched_chunks = []
        for chunk in chunks:
            chunk_global_id = chunk.get('global_id', '')
            # base global_id 추출 (예: urn:std:provide:art:001)
            base_id = ':'.join(chunk_global_id.split(':')[:5])
            
            if base_id == std_global_id:
                matched_chunks.append(chunk)
        
        if not matched_chunks:
            raise ValueError(f"표준 조항을 찾을 수 없습니다: {std_global_id}")
        
        # 제목 + 내용 결합
        title = matched_chunks[0].get('title', '')
        parent_id = matched_chunks[0].get('parent_id', '')
        
        content_parts = []
        for chunk in matched_chunks:
            text = chunk.get('text_raw', chunk.get('text', ''))
            if text:
                content_parts.append(text)
        
        content = '\n'.join(content_parts)
        
        return f"{parent_id} {title}\n{content}"
