"""
ScopeValidator - 질문 범위 검증기

계약서 검증과 관련없는 질문을 필터링합니다.

전략:
1. 명백한 범위 외 질문만 규칙 기반으로 빠르게 필터링
2. 불확실한 경우 LLM에게 판단 위임
3. 기본적으로 허용 (False Negative 최소화)
"""

import logging
from typing import List
from openai import AzureOpenAI
from backend.chatbot_agent.models import ValidationResult

logger = logging.getLogger("uvicorn.error")


class ScopeValidator:
    """
    질문 범위 검증기
    
    계약서 검증과 관련없는 질문을 필터링합니다.
    """
    
    def __init__(self, azure_client: AzureOpenAI):
        """
        Args:
            azure_client: Azure OpenAI 클라이언트
        """
        self.client = azure_client
        
        # 범위 외 키워드
        self.obvious_out_of_scope = [
            "날씨", "기온", "강수량",
            "주식", "코스피", "환율",
            "요리", "레시피", "맛집",
            "게임", "영화", "드라마", "음악",
            "스포츠", "축구", "야구",
            "정치", "선거", "대통령"
        ]
        
        # 계약서 관련 긍정 신호 키워드
        self.contract_indicators = [
            "계약", "조", "별지", "조항", "내용", "규정",
            "데이터", "제공", "이용", "대가", "지급",
            "기간", "해지", "책임", "의무", "권리",
            "당사자", "제공자", "이용자", "중개자",
            "조건", "명시", "충돌", "검증"
        ]
        
        # 이전 대화 참조 지시어 (대명사, 접속사 등)
        self.reference_indicators = [
            "그게", "그거", "이거", "저거", "이것", "저것",  # 지시대명사
            "그럼", "그러면", "그래서",      # 접속사
            "그건", "그랬", "그런", "그렇",  # 지시 관형사
            "뭐", "어디", "언제", "왜", "아니",      # 의문사 (단독 사용 시)
            "더", "또", "다시", "간단", "자세", "상세",             # 추가/반복
            "아까", "방금", "전에"           # 시간 참조
        ]
        
        logger.info("ScopeValidator 초기화")
    
    def validate(self, user_message: str) -> ValidationResult:
        """
        질문 범위 검증
        
        Args:
            user_message: 사용자 질문
            
        Returns:
            ValidationResult: 검증 결과
            
        흐름:
        1. 계약서 관련 키워드 존재 여부 (빠른 승인)
        2. 범위 외 키워드 + 계약서 키워드 동시 존재 (컨텍스트 고려)
        3. 범위 외 키워드만 존재 (LLM 판단)
        4. 불확실한 경우 LLM 판단
        """
        message_lower = user_message.lower()
        
        # 1단계: 계약서 관련 키워드 존재 여부 (최우선 승인)
        has_contract_keyword = any(
            kw in user_message for kw in self.contract_indicators
        )
        
        # 2단계: 범위 외 키워드 존재 여부
        has_out_of_scope_keyword = any(
            keyword in message_lower for keyword in self.obvious_out_of_scope
        )
        
        # 3단계: 컨텍스트 고려 판단
        if has_contract_keyword and has_out_of_scope_keyword:
            # 계약서 키워드와 범위 외 키워드가 함께 있는 경우
            # 예: "날씨 데이터 제공 조항이 있어?"
            # → 계약서 질문으로 간주 (허용)
            logger.info(f"범위 검증: 계약서 키워드 우선 (허용)")
            return ValidationResult(
                is_valid=True,
                confidence=0.85
            )
        
        if has_contract_keyword and not has_out_of_scope_keyword:
            # 계약서 키워드만 있는 경우 (명확한 승인)
            logger.info(f"범위 검증: 계약서 키워드 존재 (허용)")
            return ValidationResult(
                is_valid=True,
                confidence=0.95
            )
        
        if has_out_of_scope_keyword and not has_contract_keyword:
            # 범위 외 키워드만 있는 경우
            # 즉시 거부하지 않고 LLM에게 판단 위임
            # 예: "주식회사 A와 B의 계약" → "주식" 키워드 있지만 계약 관련일 수 있음
            logger.info(f"범위 검증: 범위 외 키워드 감지, LLM 판단 요청")
            return self._llm_validate(user_message)
        
        # 4단계: 이전 대화 참조 가능성 체크 (키워드 없는 경우)
        has_reference_indicator = any(
            indicator in user_message for indicator in self.reference_indicators
        )
        
        if has_reference_indicator:
            # 이전 대화를 참조하는 것으로 보이는 질문
            # 예: "그게 뭐야?", "그럼 언제야?", "더 알려줘"
            logger.info(f"범위 검증: 이전 대화 참조 가능성 (허용)")
            return ValidationResult(
                is_valid=True,
                confidence=0.75,
                reason="이전 대화 참조 질문으로 추정"
            )
        
        # 5단계: 불확실한 경우 → LLM 판단
        logger.info(f"범위 검증: 불확실, LLM 판단 요청")
        return self._llm_validate(user_message)
    
    def _llm_validate(self, user_message: str) -> ValidationResult:
        """
        LLM 기반 의도 분석
        
        Args:
            user_message: 사용자 질문
            
        Returns:
            ValidationResult: 검증 결과
        """
        prompt = f"""다음 질문이 계약서 내용과 관련된 질문인지 판단하세요.

질문: {user_message}

계약서 관련 질문의 예:
- 계약 조항 내용 관련 질문
- 계약 당사자, 기간, 대가 등에 대한 질문
- 계약서에 명시된 권리, 의무, 책임에 대한 질문
- 표준계약서에 관한 질문

계약서와 무관한 질문의 예:
- 일반 상식, 뉴스, 날씨 등
- 계약서와 무관한 개인적 질문

답변 형식:
관련: yes/no
이유: (한 문장)"""

        try:
            response = self.client.chat.completions.create(
                model="gpt-4.1-nano",
                messages=[{"role": "user", "content": prompt}],
                temperature=0.0,
                max_tokens=100
            )
            
            content = response.choices[0].message.content.strip()
            
            # 파싱
            is_valid = "yes" in content.lower().split("\n")[0]
            reason = content.split("\n")[1] if len(content.split("\n")) > 1 else ""
            
            logger.info(f"LLM 범위 검증: {'허용' if is_valid else '거부'}")
            
            return ValidationResult(
                is_valid=is_valid,
                reason=reason if not is_valid else None,
                confidence=0.8
            )
            
        except Exception as e:
            logger.error(f"LLM 범위 검증 실패: {e}")
            # 에러 시 일단 허용 (False Negative 최소화)
            return ValidationResult(
                is_valid=True,
                confidence=0.3
            )
