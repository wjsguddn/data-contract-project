"""
ScopeValidator - 질문 범위 검증 + 이전 대화 참조 판단

계약서 관련 질문인지 + 이전 대화 참조가 필요한지 동시 판단합니다.
"""

import logging
import json
from typing import List, Dict
from openai import OpenAI
from backend.chatbot_agent.models import ValidationResult

logger = logging.getLogger("uvicorn.error")


class ScopeValidator:
    """
    질문 범위 검증 + 이전 대화 참조 판단
    
    두 가지 역할:
    1. 계약서 관련 질문인지 검증
    2. 이전 대화 참조가 필요한지 판단
    """
    
    def __init__(self, openai_client: OpenAI):
        """
        Args:
            openai_client: OpenAI 클라이언트
        """
        self.client = openai_client
        
        # 범위 외 키워드 (계약서와 무관할 가능성 높음)
        self.out_of_scope_keywords = [
            "날씨", "기온", "강수량",
            "코스피", "국회의원",
            "요리", "레시피", "맛집",
            "게임", "영화", "드라마", "음악",
            "스포츠", "축구", "야구",
            "정치", "대통령",
            "아침", "점심", "저녁"
        ]
        
        # 계약서 관련 긍정 신호 키워드
        self.contract_indicators = [
            "계약", "조", "별지", "조항", "항", "내용", "규정",
            "데이터", "제공", "이용", "대가", "지급",
            "기간", "해지", "책임", "의무", "권리",
            "당사자", "제공자", "이용자", "중개자",
            "조건", "명시", "충돌", "검증",
            "가공", "창출", "중개", "거래", "서비스",
            "검수", "절차", "수행", "범위",
            "대금", "비용", "수수료", "보수",
            "손해배상", "위약금", "지체상금",
            "비밀유지", "보안", "개인정보"
        ]
        
        # 이전 대화 참조 지시어
        self.reference_indicators = [
            "그게", "그거", "이거", "저거", "이것", "저것", "그것", "그",
            "그럼", "그러면", "그래서", "그러니까",
            "그건", "그랬", "그런", "그렇",
            "어디", "언제", "왜", "아니",
            "더", "또", "다시", "간단", "간략", "자세", "상세", "요약", "구체", "좀", "추가로",
            "아까", "방금", "전에", "위에서", "앞서"
        ]
        
        logger.info("ScopeValidator 초기화")
    
    def validate(
        self, 
        user_message: str,
        previous_turn: List[Dict[str, str]] = None
    ) -> ValidationResult:
        """
        질문 범위 검증 + 이전 대화 참조 여부 판단
        
        Args:
            user_message: 사용자 질문
            previous_turn: 직전 대화 이력 (선택)
            
        Returns:
            ValidationResult: {
                is_contract_related: bool,
                need_previous_context: bool,
                reasoning: str,
                confidence: float,
                method: str
            }
            
        처리 로직:
        1. 이전 대화 없음 + contract_indicators ✅ → LLM 스킵
        2. 이전 대화 없음 + contract_indicators ❌ → LLM (범위만 판단)
        3. 이전 대화 있음 + 둘 다 ✅ → LLM 스킵
        4. 이전 대화 있음 + 하나라도 ❌ → LLM (통합 판단)
        """
        has_previous = previous_turn and len(previous_turn) > 0
        message_lower = user_message.lower()
        
        # 키워드 매칭
        has_contract_keyword = any(
            kw in user_message for kw in self.contract_indicators
        )
        has_reference_keyword = any(
            indicator in user_message for indicator in self.reference_indicators
        )
        has_out_of_scope_keyword = any(
            keyword in message_lower for keyword in self.out_of_scope_keywords
        )
        
        # 케이스 1: 이전 대화 없음 + contract_indicators ✅ + out_of_scope ❌
        if not has_previous and has_contract_keyword and not has_out_of_scope_keyword:
            logger.info("범위 검증: 이전 대화 없음 + 계약서 키워드 존재 + 범위 외 키워드 없음 → LLM 스킵")
            return ValidationResult(
                is_contract_related=True,
                need_previous_context=False,
                reasoning="계약서 키워드 감지",
                confidence=0.95,
                method="rule_based"
            )
        
        # 케이스 1-1: 이전 대화 없음 + contract_indicators ✅ + out_of_scope ✅
        if not has_previous and has_contract_keyword and has_out_of_scope_keyword:
            logger.info("범위 검증: 이전 대화 없음 + 계약서 키워드 + 범위 외 키워드 동시 존재 → LLM 판단")
            return self._llm_validate_scope_only(user_message)
        
        # 케이스 2: 이전 대화 없음 + contract_indicators ❌
        if not has_previous and not has_contract_keyword:
            logger.info("범위 검증: 이전 대화 없음 + 계약서 키워드 없음 → LLM (범위만 판단)")
            return self._llm_validate_scope_only(user_message)
        
        # 케이스 3: 이전 대화 있음 + 둘 다 ✅ + out_of_scope ❌
        if has_previous and has_contract_keyword and has_reference_keyword and not has_out_of_scope_keyword:
            logger.info("범위 검증: 이전 대화 있음 + 둘 다 매칭 + 범위 외 키워드 없음 → LLM 스킵")
            return ValidationResult(
                is_contract_related=True,
                need_previous_context=True,
                reasoning="계약서 키워드 + 이전 대화 참조 감지",
                confidence=0.95,
                method="rule_based"
            )
        
        # 케이스 3-1: 이전 대화 있음 + 둘 다 ✅ + out_of_scope ✅
        if has_previous and has_contract_keyword and has_reference_keyword and has_out_of_scope_keyword:
            logger.info("범위 검증: 이전 대화 있음 + 둘 다 매칭 + 범위 외 키워드 존재 → LLM 판단")
            return self._llm_validate_integrated(user_message, previous_turn)
        
        # 케이스 4: 이전 대화 있음 + 나머지
        if has_previous:
            logger.info("범위 검증: 이전 대화 있음 + 기타 케이스 → LLM (통합 판단)")
            return self._llm_validate_integrated(user_message, previous_turn)
        
        # 폴백 (도달하지 않아야 함)
        logger.warning("범위 검증: 예상치 못한 케이스, 기본값 반환")
        return ValidationResult(
            is_contract_related=True,
            need_previous_context=False,
            reasoning="예상치 못한 케이스",
            confidence=0.5,
            method="fallback"
        )
    
    def _llm_validate_scope_only(self, user_message: str) -> ValidationResult:
        """
        LLM 기반 범위 검증 (이전 대화 없음)
        
        Args:
            user_message: 사용자 질문
            
        Returns:
            ValidationResult (need_previous_context=False 고정)
        """
        prompt = f"""다음 질문이 계약서 내용과 관련된 질문인지 판단하세요.

질문: {user_message}

계약서 관련 질문의 예:
- 계약 조항 내용 관련 질문 → true
- 계약 당사자, 기간, 대가 등에 대한 질문 → true
- 계약서에 명시된 권리, 의무, 책임에 대한 질문 → true
- 표준계약서에 관한 질문 → true

계약서와 무관한 질문의 예:
- 일반 상식, 뉴스, 날씨 등 → false
- 일반적인 인사, 감사 표현 → false
- 계약서와 무관한 개인적 질문 → false

응답 형식 (JSON):
{{
    "is_contract_related": true/false,
    "reasoning": "판단 근거 (한 문장)"
}}

JSON만 응답하세요."""

        try:
            response = self.client.chat.completions.create(
                model="gpt-4o-mini",
                messages=[{"role": "user", "content": prompt}],
                temperature=0.0,
                max_tokens=100,
                response_format={"type": "json_object"}
            )
            
            content = response.choices[0].message.content.strip()
            result = json.loads(content)
            
            is_contract_related = result.get("is_contract_related", False)
            reasoning = result.get("reasoning", "")
            
            logger.info(f"LLM 범위 검증 (범위만): is_contract_related={is_contract_related}")
            
            return ValidationResult(
                is_contract_related=is_contract_related,
                need_previous_context=False,  # 고정
                reasoning=reasoning,
                confidence=0.8,
                method="llm"
            )
            
        except Exception as e:
            logger.error(f"LLM 범위 검증 실패: {e}")
            # 에러 시 일단 허용
            return ValidationResult(
                is_contract_related=True,
                need_previous_context=False,
                reasoning="LLM 판단 실패, 기본값 사용",
                confidence=0.3,
                method="fallback"
            )
    
    def _llm_validate_integrated(
        self, 
        user_message: str, 
        previous_turn: List[Dict[str, str]]
    ) -> ValidationResult:
        """
        LLM 기반 통합 검증 (범위 + 이전 대화 참조)
        
        Args:
            user_message: 사용자 질문
            previous_turn: 이전 대화
            
        Returns:
            ValidationResult (두 가지 모두 LLM이 판단)
        """
        # 이전 대화 컨텍스트 구성
        context_text = ""
        for msg in previous_turn:
            role = msg.get("role", "")
            content = msg.get("content", "")
            if role == "user":
                context_text += f"사용자: {content}\n"
            elif role == "assistant":
                context_text += f"챗봇: {content}\n"
        
        prompt = f"""다음 자료들은 사용자가 계약서 챗봇(계약서를 기반으로 답변하는 챗봇)과 주고받은 대화/질문 내용입니다.
현재 사용자 질문에 대해 두 가지를 판단하세요.

**판단 순서 (반드시 이 순서대로 판단하세요)**:
1단계: 현재 사용자 질문이 이전 대화 내용을 참조하는지 판단 (need_previous_context)
2단계: 그 다음 계약서 관련성을 판단 (is_contract_related)

이전 대화:
{context_text}

현재 사용자 질문: {user_message}

판단 기준:

**1단계: 이전 대화 참조 (need_previous_context)**

**참조함 (need_previous_context=true)**:
- 현재 사용자 질문에 답변하는데에 이전 대화가 정보로써 필요한 경우
- 명시적 참조어 사용: "그럼", "그것은", "그거", "위에서", "아까", "방금"
- 이전 답변에 대한 요약/정리/재설명 요청: "요약해줘", "정리해줘", "간단히", "자세히"
- 이전 답변의 특정 부분에 대한 추가 질문
- 대명사로 이전 내용 지칭: "이거", "저거", "그게"

**참조 안 함 (need_previous_context=false)**:
- 독립적인 새로운 질문 (참조어 없음)
- 동일하게 계약서에 대한 내용이더라도 이전 대화와는 완전히 독립적인 질문인 경우

need_previous_context 예시:
- "요약해줘" → need_previous_context=true (이전 답변 요약)
- "뭐라고?" 또는 "뭐?" → need_previous_context=true (목적은 애매하지만 이전 답변을 참조해야함)
- 이전:"계약 해지 조건이 어떻게 되지?", 현재:"검수 절차가 어떻게 되지?" → need_previous_context=false (독립적 질문)
- 이전:"제3조 내용은?", 현재:"제5조 내용은?" → need_previous_context=false (새로운 조항 질문)
- 이전 질문:"가공서비스의 검수 절차가 어떻게 되지?", 이전 답변:"가공서비스의 검수 절차는 부분 검수, 최종 검수...", 현재 질문: "부분 검수 과정에 대해 설명해줘" → true (연계 질문)

**2단계: 계약서 관련성 (is_contract_related)**

**관련 있음 (is_contract_related=true)**:
- 계약 조항, 내용, 조건, 작성에 대한 질문
- 계약 당사자, 기간, 대가, 권리, 의무에 대한 질문
- **또는** 1단계에서 need_previous_context=true로 판단했고, 이전 대화가 계약서 관련 내용인 경우
  (예: 이전 대화에서 계약서 조항을 설명했고, 현재 "요약해줘"라고 요청한 경우)

**관련 없음 (is_contract_related=false)**:
- 일반 상식, 뉴스, 날씨 등
- 일반적인 인사, 감사 표현
- 계약서와 무관한 개인적 질문
- **단, 이전 대화를 참조하지 않는 경우에만** (need_previous_context=false인 경우)

**핵심 규칙**:
- "요약해줘", "정리해줘" 같은 질문은 need_previous_context=true
- need_previous_context=true이고 이전 대화가 계약서 관련이면 → is_contract_related=true (자동)
**중오**: 현재 질문 자체는 계약서와 무관해 보여도, 이전 계약서 대화를 참조하면 계약서 관련으로 판단

응답 형식 (JSON, 판단 순서대로):
{{
    "need_previous_context": true/false,
    "is_contract_related": true/false,
    "reasoning": "판단 근거 (한 문장)"
}}

JSON만 응답하세요."""

        try:
            response = self.client.chat.completions.create(
                model="gpt-4o-mini",
                messages=[{"role": "user", "content": prompt}],
                temperature=0.1,
                max_tokens=250,
                response_format={"type": "json_object"}
            )
            
            content = response.choices[0].message.content.strip()
            result = json.loads(content)
            
            is_contract_related = result.get("is_contract_related", False)
            need_previous_context = result.get("need_previous_context", False)
            reasoning = result.get("reasoning", "")
            
            logger.info(
                f"LLM 통합 검증: is_contract_related={is_contract_related}, "
                f"need_previous_context={need_previous_context}"
            )
            
            return ValidationResult(
                is_contract_related=is_contract_related,
                need_previous_context=need_previous_context,
                reasoning=reasoning,
                confidence=0.85,
                method="llm"
            )
            
        except Exception as e:
            logger.error(f"LLM 통합 검증 실패: {e}")
            # 에러 시 일단 허용
            return ValidationResult(
                is_contract_related=True,
                need_previous_context=False,
                reasoning="LLM 판단 실패, 기본값 사용",
                confidence=0.3,
                method="fallback"
            )
