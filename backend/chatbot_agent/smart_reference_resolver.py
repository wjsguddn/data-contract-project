"""
SmartReferenceResolver - LLM 기반 참조 해결

계약서 조항 간 참조를 탐지하고 필요한 참조만 선택적으로 해결합니다.
"""

import logging
import re
from typing import Dict, Any, List, Optional, Tuple
from openai import AzureOpenAI

logger = logging.getLogger(__name__)


class SmartReferenceResolver:
    """
    LLM 기반 스마트 참조 해결기
    
    주요 기능:
    1. 참조 패턴 탐지 (제n조, 별지n, 전조, 본조 등)
    2. LLM으로 참조 필요성 평가
    3. 필요한 참조만 선택적으로 해결
    """
    
    def __init__(self, azure_client: AzureOpenAI, model: str = "gpt-4o"):
        """
        Args:
            azure_client: Azure OpenAI 클라이언트
            model: 사용할 LLM 모델
        """
        self.azure_client = azure_client
        self.model = model
        
        # 참조 패턴 정의
        self.reference_patterns = {
            'article': r'제\s*(\d+)\s*조',  # 제1조, 제 1 조
            'exhibit': r'별지\s*(\d+)',      # 별지1, 별지 1
            'previous_article': r'전\s*조',  # 전조
            'this_article': r'본\s*조',      # 본조
            'following_article': r'다음\s*조', # 다음조
            'paragraph': r'제?\s*(\d+)\s*항', # 제1항, 1항
            'subparagraph': r'제?\s*(\d+)\s*호', # 제1호, 1호
        }
        
        logger.info("SmartReferenceResolver 초기화 완료")
    
    def detect_references(
        self,
        text: str,
        current_article_no: Optional[int] = None
    ) -> List[Dict[str, Any]]:
        """
        텍스트에서 참조 패턴 탐지
        
        Args:
            text: 분석할 텍스트
            current_article_no: 현재 조 번호 (상대 참조 해석용)
        
        Returns:
            참조 정보 리스트
            [
                {
                    'type': 'article' | 'exhibit' | 'previous_article' | ...,
                    'raw_text': str,  # 원본 텍스트 (예: "제3조")
                    'target_no': int | None,  # 참조 대상 번호
                    'position': int  # 텍스트 내 위치
                },
                ...
            ]
        """
        references = []
        
        for ref_type, pattern in self.reference_patterns.items():
            for match in re.finditer(pattern, text):
                ref_info = {
                    'type': ref_type,
                    'raw_text': match.group(0),
                    'position': match.start()
                }
                
                # 참조 대상 번호 추출
                if ref_type in ['article', 'exhibit', 'paragraph', 'subparagraph']:
                    ref_info['target_no'] = int(match.group(1))
                elif ref_type == 'previous_article' and current_article_no:
                    ref_info['target_no'] = current_article_no - 1
                elif ref_type == 'this_article' and current_article_no:
                    ref_info['target_no'] = current_article_no
                elif ref_type == 'following_article' and current_article_no:
                    ref_info['target_no'] = current_article_no + 1
                else:
                    ref_info['target_no'] = None
                
                references.append(ref_info)
        
        # 위치 순으로 정렬
        references.sort(key=lambda x: x['position'])
        
        logger.debug(f"참조 탐지 완료: {len(references)}개 발견")
        return references
    
    def evaluate_reference_necessity(
        self,
        user_question: str,
        collected_info: Dict[str, Any],
        references: List[Dict[str, Any]],
        reference_contexts: Dict[str, str]
    ) -> List[Dict[str, Any]]:
        """
        LLM으로 참조 필요성 평가
        
        Args:
            user_question: 사용자 질문
            collected_info: 이미 수집된 정보
            references: 탐지된 참조 리스트
            reference_contexts: 참조가 포함된 문맥 (참조 ID -> 문맥 텍스트)
        
        Returns:
            필요한 참조 리스트 (우선순위 포함)
            [
                {
                    'type': str,
                    'target_no': int,
                    'raw_text': str,
                    'priority': int,  # 1=높음, 2=중간, 3=낮음
                    'reason': str  # 필요한 이유
                },
                ...
            ]
        """
        if not references:
            return []
        
        # 프롬프트 구성
        prompt = self._build_evaluation_prompt(
            user_question,
            collected_info,
            references,
            reference_contexts
        )
        
        try:
            response = self.azure_client.chat.completions.create(
                model=self.model,
                messages=[
                    {
                        "role": "system",
                        "content": "당신은 계약서 조항 간 참조 관계를 분석하는 전문가입니다. "
                                 "사용자 질문에 답하기 위해 어떤 참조를 해결해야 하는지 판단하세요."
                    },
                    {
                        "role": "user",
                        "content": prompt
                    }
                ],
                temperature=0.2,
                max_tokens=1000,
                response_format={"type": "json_object"}
            )
            
            result_text = response.choices[0].message.content.strip()
            
            # JSON 파싱
            import json
            result = json.loads(result_text)
            
            necessary_refs = result.get('necessary_references', [])
            
            logger.info(f"참조 필요성 평가 완료: {len(necessary_refs)}개 필요")
            return necessary_refs
            
        except Exception as e:
            logger.error(f"참조 필요성 평가 실패: {e}")
            # 실패 시 모든 참조를 중간 우선순위로 반환
            return [
                {
                    'type': ref['type'],
                    'target_no': ref.get('target_no'),
                    'raw_text': ref['raw_text'],
                    'priority': 2,
                    'reason': '평가 실패로 인한 기본 포함'
                }
                for ref in references
            ]
    
    def _build_evaluation_prompt(
        self,
        user_question: str,
        collected_info: Dict[str, Any],
        references: List[Dict[str, Any]],
        reference_contexts: Dict[str, str]
    ) -> str:
        """
        참조 필요성 평가 프롬프트 생성
        
        Args:
            user_question: 사용자 질문
            collected_info: 이미 수집된 정보
            references: 탐지된 참조 리스트
            reference_contexts: 참조 문맥
        
        Returns:
            프롬프트 텍스트
        """
        # 수집된 정보 요약
        info_summary = self._summarize_collected_info(collected_info)
        
        # 참조 목록 포맷팅
        refs_text = ""
        for i, ref in enumerate(references, 1):
            ref_id = f"{ref['type']}_{ref.get('target_no', 'unknown')}"
            context = reference_contexts.get(ref_id, "문맥 없음")
            
            refs_text += f"\n{i}. {ref['raw_text']} (타입: {ref['type']}, 대상: {ref.get('target_no', '?')})\n"
            refs_text += f"   문맥: {context}\n"
        
        prompt = f"""# 참조 필요성 평가

## 사용자 질문
{user_question}

## 이미 수집된 정보
{info_summary}

## 탐지된 참조 목록
{refs_text}

---

**과제**: 위의 참조들 중 사용자 질문에 답하기 위해 **실제로 필요한** 참조만 선택하세요.

**평가 기준**:
1. **직접 관련성**: 질문에 직접 답하는 데 필요한가?
2. **정보 보완**: 이미 수집된 정보를 보완하는가?
3. **맥락 이해**: 답변의 맥락을 이해하는 데 필요한가?

**우선순위**:
- 1 (높음): 질문에 직접 답하는 데 필수
- 2 (중간): 답변 품질을 높이는 데 유용
- 3 (낮음): 있으면 좋지만 없어도 무방

**제외 기준**:
- 이미 수집된 정보에 포함된 참조
- 질문과 무관한 참조
- 단순 형식적 참조 (예: "본조에 따라")

**응답 형식** (JSON):
{{
    "necessary_references": [
        {{
            "type": "article",
            "target_no": 3,
            "raw_text": "제3조",
            "priority": 1,
            "reason": "사용자가 제3조의 내용을 직접 질문했기 때문"
        }},
        ...
    ]
}}

JSON만 응답하세요."""
        
        return prompt
    
    def _summarize_collected_info(self, collected_info: Dict[str, Any]) -> str:
        """
        수집된 정보 요약
        
        Args:
            collected_info: 수집된 정보
        
        Returns:
            요약 텍스트
        """
        if not collected_info:
            return "아직 수집된 정보 없음"
        
        summary_parts = []
        
        # 계약서 구조
        if 'contract_structure' in collected_info:
            structure = collected_info['contract_structure']
            summary_parts.append(
                f"- 계약서 구조: {structure.get('total_articles', 0)}개 조, "
                f"{structure.get('total_exhibits', 0)}개 별지"
            )
        
        # 검색 결과
        if 'search_results' in collected_info:
            search = collected_info['search_results']
            summary_parts.append(
                f"- 검색 결과: {search.get('total_topics', 0)}개 주제, "
                f"{search.get('total_articles', 0)}개 조"
            )
        
        # 조 인덱스 조회
        if 'article_index_results' in collected_info:
            index = collected_info['article_index_results']
            summary_parts.append(
                f"- 조 인덱스 조회: {index.get('total_matched', 0)}개 조"
            )
        
        # 조 제목 조회
        if 'article_title_results' in collected_info:
            title = collected_info['article_title_results']
            summary_parts.append(
                f"- 조 제목 조회: {title.get('total_matched', 0)}개 조"
            )
        
        # 표준계약서 조회
        if 'standard_contract_results' in collected_info:
            std = collected_info['standard_contract_results']
            summary_parts.append(
                f"- 표준계약서 조회: {std.get('total_found', 0)}개 조"
            )
        
        if not summary_parts:
            return "수집된 정보가 있으나 요약 불가"
        
        return "\n".join(summary_parts)
    
    def resolve_references(
        self,
        necessary_refs: List[Dict[str, Any]],
        contract_id: str,
        db_session
    ) -> Dict[str, Any]:
        """
        필요한 참조 해결 (DB에서 조회)
        
        Args:
            necessary_refs: 필요한 참조 리스트
            contract_id: 계약서 ID
            db_session: 데이터베이스 세션
        
        Returns:
            해결된 참조 정보
            {
                'article_3': {
                    'article_no': 3,
                    'title': str,
                    'content': List[str]
                },
                ...
            }
        """
        from backend.shared.database import ContractDocument
        
        resolved = {}
        
        try:
            # 계약서 조회
            contract = db_session.query(ContractDocument).filter(
                ContractDocument.contract_id == contract_id
            ).first()
            
            if not contract or not contract.parsed_data:
                logger.error(f"계약서를 찾을 수 없음: {contract_id}")
                return resolved
            
            parsed_data = contract.parsed_data
            articles = parsed_data.get('articles', [])
            exhibits = parsed_data.get('exhibits', [])
            
            # 각 참조 해결
            for ref in necessary_refs:
                ref_type = ref['type']
                target_no = ref.get('target_no')
                
                if not target_no:
                    continue
                
                if ref_type == 'article':
                    # 조 조회
                    for article in articles:
                        if article.get('number') == target_no:
                            key = f"article_{target_no}"
                            resolved[key] = {
                                'article_no': target_no,
                                'title': article.get('title', ''),
                                'text': article.get('text', ''),
                                'content': article.get('content', []),
                                'priority': ref.get('priority', 2),
                                'reason': ref.get('reason', '')
                            }
                            break
                
                elif ref_type == 'exhibit':
                    # 별지 조회
                    for exhibit in exhibits:
                        if exhibit.get('number') == target_no:
                            key = f"exhibit_{target_no}"
                            resolved[key] = {
                                'exhibit_no': target_no,
                                'title': exhibit.get('title', ''),
                                'text': exhibit.get('text', ''),
                                'content': exhibit.get('content', []),
                                'priority': ref.get('priority', 2),
                                'reason': ref.get('reason', '')
                            }
                            break
            
            logger.info(f"참조 해결 완료: {len(resolved)}개")
            return resolved
            
        except Exception as e:
            logger.error(f"참조 해결 실패: {e}")
            return resolved
    
    def process_references(
        self,
        text: str,
        user_question: str,
        collected_info: Dict[str, Any],
        contract_id: str,
        db_session,
        current_article_no: Optional[int] = None
    ) -> Tuple[List[Dict[str, Any]], Dict[str, Any]]:
        """
        참조 처리 전체 파이프라인
        
        Args:
            text: 분석할 텍스트
            user_question: 사용자 질문
            collected_info: 이미 수집된 정보
            contract_id: 계약서 ID
            db_session: 데이터베이스 세션
            current_article_no: 현재 조 번호
        
        Returns:
            (필요한 참조 리스트, 해결된 참조 정보)
        """
        # 1. 참조 탐지
        references = self.detect_references(text, current_article_no)
        
        if not references:
            logger.debug("참조 없음")
            return [], {}
        
        # 2. 참조 문맥 추출
        reference_contexts = self._extract_reference_contexts(text, references)
        
        # 3. 참조 필요성 평가
        necessary_refs = self.evaluate_reference_necessity(
            user_question,
            collected_info,
            references,
            reference_contexts
        )
        
        if not necessary_refs:
            logger.debug("필요한 참조 없음")
            return [], {}
        
        # 4. 참조 해결
        resolved_refs = self.resolve_references(
            necessary_refs,
            contract_id,
            db_session
        )
        
        return necessary_refs, resolved_refs
    
    def _extract_reference_contexts(
        self,
        text: str,
        references: List[Dict[str, Any]],
        context_window: int = 50
    ) -> Dict[str, str]:
        """
        참조 주변 문맥 추출
        
        Args:
            text: 전체 텍스트
            references: 참조 리스트
            context_window: 문맥 윈도우 크기 (문자 수)
        
        Returns:
            참조 ID -> 문맥 텍스트 매핑
        """
        contexts = {}
        
        for ref in references:
            ref_id = f"{ref['type']}_{ref.get('target_no', 'unknown')}"
            position = ref['position']
            
            # 앞뒤 문맥 추출
            start = max(0, position - context_window)
            end = min(len(text), position + len(ref['raw_text']) + context_window)
            
            context = text[start:end].strip()
            contexts[ref_id] = context
        
        return contexts
