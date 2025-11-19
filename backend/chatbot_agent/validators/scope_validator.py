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
        1. 이전 대화 없음 + contract_indicators ✅ + out_of_scope ❌ → LLM 스킵
        2. 이전 대화 없음 + contract_indicators ❌ → LLM (범위만 판단)
        3. 이전 대화 있음 + contract_indicators ✅ + reference_indicators ✅ + out_of_scope ❌ → LLM 스킵
        4. 이전 대화 있음 + contract_indicators ✅ + out_of_scope ❌ → is_contract_related=true 확정, need_previous_context만 LLM 판단 (신규)
        5. 이전 대화 있음 + 나머지 → LLM 통합 판단
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
        
        # 케이스 3-1: 이전 대화 있음 + contract_indicators ✅ + out_of_scope ❌ (신규)
        # → is_contract_related=true 확정, need_previous_context만 LLM 판단
        if has_previous and has_contract_keyword and not has_out_of_scope_keyword:
            logger.info("범위 검증: 이전 대화 있음 + 계약서 키워드 존재 + 범위 외 키워드 없음 → is_contract_related=true 확정, need_previous_context만 LLM 판단")
            return self._llm_validate_context_only(user_message, previous_turn)
        
        # 케이스 4: 이전 대화 있음 + contract_indicators ✅ + out_of_scope ✅
        if has_previous and has_contract_keyword and has_out_of_scope_keyword:
            logger.info("범위 검증: 이전 대화 있음 + 계약서 키워드 + 범위 외 키워드 동시 존재 → LLM 통합 판단")
            return self._llm_validate_integrated(user_message, previous_turn)
        
        # 케이스 5: 이전 대화 있음 + 나머지
        if has_previous:
            logger.info("범위 검증: 이전 대화 있음 + 기타 케이스 → LLM 통합 판단")
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
- 그냥 계약에 대한 질문 대부분 → true

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
    
    def _llm_validate_context_only(
        self,
        user_message: str,
        previous_turn: List[Dict[str, str]]
    ) -> ValidationResult:
        """
        LLM 기반 이전 대화 참조 판단만 수행 (is_contract_related=true 확정)
        
        Args:
            user_message: 사용자 질문
            previous_turn: 이전 대화
            
        Returns:
            ValidationResult (is_contract_related=true 고정)
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
        
        prompt = f"""다음은 계약서 챗봇과의 대화 내역입니다.
현재 질문이 이전 대화를 참조하는지만 판단하세요.

이전 대화:
{context_text}

현재 질문: {user_message}

**판단 기준**:

참조함 (true):
- 참조어 사용: "그럼", "그거", "그것", "이거", "위에서", "아까", "방금"
- 이전 답변 요청: "요약해줘", "정리해줘", "간단히", "자세히", "뭐라고?"
- 이전 답변의 특정 부분 추가 질문

참조 안 함 (false):
- 독립적인 새 질문 (참조어 없음)
- 이전 대화와 전혀 무관한 질문

예시:
- "요약해줘", "상세화해줘" 등 → true
- 어조상 단독문이 아닌 이전 대화가 존재하는 것 처럼 표현한다면 → true
- 이전 대화에서 계약의 만료나 해지에 대해서 이야기했고, 현재 질문에서는 계약의 목적을 물어본다거나 하는 독립된 주제인 경우 → false

응답 형식 (JSON):
{{
    "need_previous_context": true/false,
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
            
            need_previous_context = result.get("need_previous_context", False)
            reasoning = result.get("reasoning", "")
            
            logger.info(f"LLM 컨텍스트 검증 (참조만): need_previous_context={need_previous_context}")
            
            return ValidationResult(
                is_contract_related=True,  # 고정
                need_previous_context=need_previous_context,
                reasoning=reasoning,
                confidence=0.9,
                method="llm_context_only"
            )
            
        except Exception as e:
            logger.error(f"LLM 컨텍스트 검증 실패: {e}")
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
        
        prompt = f"""다음은 "데이터 계약서 챗봇"과의 대화 내역입니다.
현재 사용자 질문에 대해 두 가지를 판단하세요.

이전 대화:
{context_text}

현재 질문: {user_message}

**판단 순서 (반드시 이 순서대로)**:

1단계: 이전 대화 참조 여부 (need_previous_context)
2단계: 계약서 관련성 (is_contract_related)

---

**1단계: need_previous_context 판단**

참조함 (true):
- 참조어 사용: "그럼", "그거", "그것", "이거", "위에서", "아까", "방금" 등
- 이전 답변 요청: "요약해줘", "정리해줘", "간단히", "자세히", "뭐라고?" 등
- 이전 대화의 특정 부분 추가 질문
- 이전 대화의 주제와 동일/유사한 주제에 대한 질문

참조 안 함 (false):
- 독립적인 새 질문 (참조어 없음)
- 계약서 관련이더라도 이전 대화와 무관한 질문

예시:
- "요약해줘" → true
- "계약서에 청약철회 내용이 있나?" → false (독립적 질문)
- "제3조는?" → false (새 조항 질문)

---

**2단계: is_contract_related 판단**

**중요: 현재 질문 자체의 내용을 먼저 판단하세요**

관련 있음 (true):
- 계약, 조항, 조건, 내용, 당사자, 기간, 대가, 권리, 의무 관련 질문
- 계약에 특정 내용이 있는지 묻는 질문
- 데이터 계약 관련 질문
- **또는** need_previous_context=true이고 이전 대화가 계약서 관련인 경우

관련 없음 (false):
- 일반 상식, 뉴스, 날씨
- 인사, 감사 표현
- 계약서와 무관한 개인적 질문

**핵심 규칙**:
1. 질문에 "계약", "조항", "청약철회", "해지", "대가지급", "면책" 등 계약 키워드가 있으면 → true
2. need_previous_context=true + 이전 대화가 계약서 관련 → true
3. 둘 다 아니면 → false

예시:
- "계약서에 청약철회 내용이 있나?" → true (계약서 키워드)
- "제5조 내용은?" → true (조항 질문)
- "요약해줘" (이전: 계약 조항 설명) → true (이전 대화 참조)
- "날씨 어때?" → false

응답 형식 (JSON):
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
