"""
ContextBuilder - 출처 명확화 및 컨텍스트 구성

사용자 계약서와 표준계약서를 명확히 구분하여 LLM에 제공합니다.
"""

import logging
from typing import Dict, Any, List

logger = logging.getLogger(__name__)


class ContextBuilder:
    """
    출처 명확화 및 컨텍스트 구성기
    
    주요 기능:
    1. 수집된 정보를 출처별로 구분
    2. 사용자 계약서와 표준계약서 포맷팅
    3. 명확한 출처 태깅
    """
    
    def __init__(self):
        """초기화"""
        logger.info("ContextBuilder 초기화 완료")
    
    def build_context_from_collected_info(
        self,
        collected_info: Dict[str, Any]
    ) -> str:
        """
        수집된 정보를 출처별로 구분하여 컨텍스트 구성
        
        Args:
            collected_info: 수집된 정보
                {
                    'contract_structure': {...},
                    'search_results': {...},
                    'article_index_results': {...},
                    'article_title_results': {...},
                    'standard_contract_results': {...},
                    'resolved_references': {...}
                }
        
        Returns:
            포맷팅된 컨텍스트 텍스트
        """
        context_parts = []
        
        # 1. 사용자 계약서 내용
        user_contract_context = self._build_user_contract_context(collected_info)
        if user_contract_context:
            context_parts.append("=== 사용자 계약서 내용 ===\n")
            context_parts.append(user_contract_context)
            context_parts.append("\n")
        
        # 2. 표준계약서 내용 (참고용)
        std_contract_context = self._build_std_contract_context(collected_info)
        if std_contract_context:
            context_parts.append("=== 표준계약서 내용 (참고용) ===\n")
            context_parts.append("주의: 표준계약서는 참고 자료일 뿐, 사용자 계약서의 절대 기준이 아닙니다.\n\n")
            context_parts.append(std_contract_context)
            context_parts.append("\n")
        
        if not context_parts:
            return "수집된 정보 없음"
        
        return "".join(context_parts)
    
    def _build_user_contract_context(
        self,
        collected_info: Dict[str, Any]
    ) -> str:
        """
        사용자 계약서 컨텍스트 구성
        
        Args:
            collected_info: 수집된 정보
        
        Returns:
            사용자 계약서 컨텍스트
        """
        parts = []
        
        # 계약서 구조
        if 'contract_structure' in collected_info:
            structure = collected_info['contract_structure']
            parts.append(f"## 계약서 구조\n")
            parts.append(f"- 총 {structure.get('total_articles', 0)}개 조\n")
            parts.append(f"- 총 {structure.get('total_exhibits', 0)}개 별지\n\n")
        
        # 검색 결과 (하이브리드 검색)
        if 'search_results' in collected_info:
            search = collected_info['search_results']
            results = search.get('results', {})
            
            if results:
                parts.append("## 검색된 조항\n")
                for topic, articles in results.items():
                    parts.append(f"\n### 주제: {topic}\n")
                    for article in articles:
                        parts.append(self._format_user_article(article))
                parts.append("\n")
        
        # 조 인덱스 조회 결과
        if 'article_index_results' in collected_info:
            index = collected_info['article_index_results']
            matched = index.get('matched_articles', [])
            
            if matched:
                parts.append("## 조 번호로 조회된 조항\n")
                for article in matched:
                    parts.append(self._format_user_article(article))
                parts.append("\n")
        
        # 조 제목 조회 결과
        if 'article_title_results' in collected_info:
            title = collected_info['article_title_results']
            matched = title.get('matched_articles', [])
            
            if matched:
                parts.append("## 제목으로 조회된 조항\n")
                for article in matched:
                    parts.append(self._format_user_article(article))
                parts.append("\n")
        
        # 해결된 참조
        if 'resolved_references' in collected_info:
            refs = collected_info['resolved_references']
            
            if refs:
                parts.append("## 참조된 조항\n")
                for ref_key, ref_data in refs.items():
                    if 'article_no' in ref_data:
                        parts.append(f"\n### 제{ref_data['article_no']}조 ({ref_data.get('title', '')})\n")
                        parts.append(f"본문: {ref_data.get('text', '')}\n")
                        for i, content in enumerate(ref_data.get('content', []), 1):
                            parts.append(f"{i}. {content}\n")
                    elif 'exhibit_no' in ref_data:
                        parts.append(f"\n### 별지{ref_data['exhibit_no']} ({ref_data.get('title', '')})\n")
                        parts.append(f"본문: {ref_data.get('text', '')}\n")
                        for i, content in enumerate(ref_data.get('content', []), 1):
                            parts.append(f"{i}. {content}\n")
                parts.append("\n")
        
        return "".join(parts)
    
    def _build_std_contract_context(
        self,
        collected_info: Dict[str, Any]
    ) -> str:
        """
        표준계약서 컨텍스트 구성
        
        Args:
            collected_info: 수집된 정보
        
        Returns:
            표준계약서 컨텍스트
        """
        parts = []
        
        if 'standard_contract_results' in collected_info:
            std = collected_info['standard_contract_results']
            articles = std.get('standard_articles', [])
            
            if articles:
                parts.append(f"## 조회 방식: {std.get('method', '알 수 없음')}\n")
                if std.get('topic'):
                    parts.append(f"## 주제: {std.get('topic')}\n")
                if std.get('user_article_numbers'):
                    parts.append(f"## 사용자 조 번호: {', '.join(map(str, std.get('user_article_numbers')))}\n")
                parts.append("\n")
                
                for article in articles:
                    parts.append(self._format_std_article(article))
                
                if std.get('usage_note'):
                    parts.append(f"\n**참고**: {std.get('usage_note')}\n")
        
        return "".join(parts)
    
    def _format_user_article(self, article: Dict[str, Any]) -> str:
        """
        사용자 계약서 조항 포맷팅
        
        Args:
            article: 조항 데이터
                {
                    'article_no': int,
                    'title': str,
                    'text': str,
                    'content': List[str]
                }
        
        Returns:
            포맷팅된 텍스트
        """
        lines = []
        
        article_no = article.get('article_no')
        title = article.get('title', '')
        text = article.get('text', '')
        content = article.get('content', [])
        
        # 제목
        lines.append(f"\n### 제{article_no}조 ({title})\n")
        
        # 본문
        if text:
            lines.append(f"본문: {text}\n")
        
        # 하위 항목
        if content:
            lines.append("하위 항목:\n")
            for i, item in enumerate(content, 1):
                lines.append(f"{i}. {item}\n")
        
        return "".join(lines)
    
    def _format_std_article(self, article: Dict[str, Any]) -> str:
        """
        표준계약서 조항 포맷팅
        
        Args:
            article: 표준계약서 조항 데이터
                {
                    'parent_id': str,
                    'title': str,
                    'full_text': str,
                    'chunks': List[Dict]
                }
        
        Returns:
            포맷팅된 텍스트
        """
        lines = []
        
        parent_id = article.get('parent_id', '')
        title = article.get('title', '')
        full_text = article.get('full_text', '')
        
        # 제목
        lines.append(f"\n### {parent_id} ({title})\n")
        
        # 전체 텍스트
        if full_text:
            lines.append(f"{full_text}\n")
        
        return "".join(lines)
    
    def extract_sources(self, final_response: str) -> List[Dict[str, str]]:
        """
        최종 답변에서 출처 추출
        
        Args:
            final_response: LLM이 생성한 최종 답변
        
        Returns:
            출처 리스트
            [
                {
                    'type': 'user_contract' | 'standard_contract',
                    'reference': str  # 예: "제3조", "별지1"
                },
                ...
            ]
        """
        import re
        
        sources = []
        
        # 조 번호 패턴
        article_pattern = r'제\s*(\d+)\s*조'
        for match in re.finditer(article_pattern, final_response):
            sources.append({
                'type': 'user_contract',  # 기본적으로 사용자 계약서로 간주
                'reference': match.group(0)
            })
        
        # 별지 패턴
        exhibit_pattern = r'별지\s*(\d+)'
        for match in re.finditer(exhibit_pattern, final_response):
            sources.append({
                'type': 'user_contract',
                'reference': match.group(0)
            })
        
        # 표준계약서 명시적 언급
        if '표준계약서' in final_response or '표준 계약서' in final_response:
            # 표준계약서 언급 후 나오는 조 번호는 표준계약서로 분류
            std_pattern = r'표준\s*계약서.*?(제\s*\d+\s*조)'
            for match in re.finditer(std_pattern, final_response):
                sources.append({
                    'type': 'standard_contract',
                    'reference': match.group(1)
                })
        
        # 중복 제거
        unique_sources = []
        seen = set()
        for source in sources:
            key = f"{source['type']}:{source['reference']}"
            if key not in seen:
                seen.add(key)
                unique_sources.append(source)
        
        return unique_sources
    
    def build_system_prompt_with_source_rules(self) -> str:
        """
        출처 구분 규칙이 포함된 시스템 프롬프트 생성
        
        Returns:
            시스템 프롬프트
        """
        prompt = """당신은 계약서 분석 전문가입니다. 사용자의 질문에 답변할 때 다음 규칙을 엄격히 따르세요:

## 출처 구분 규칙

1. **사용자 계약서 우선**
   - 질문에 답할 때는 항상 사용자 계약서의 내용을 우선적으로 참조하세요
   - 사용자 계약서에 명시된 내용을 정확히 인용하세요

2. **표준계약서는 참고 자료**
   - 표준계약서는 참고 자료일 뿐, 사용자 계약서의 절대 기준이 아닙니다
   - 표준계약서를 언급할 때는 반드시 "표준계약서에 따르면..." 등으로 명시하세요
   - 표준계약서와 사용자 계약서가 다를 경우, 사용자 계약서의 내용이 우선입니다

3. **출처 명시**
   - 답변에 사용한 조항의 번호를 명확히 밝히세요 (예: "제3조에 따르면...")
   - 여러 조항을 참조한 경우 모두 나열하세요

4. **추측 금지**
   - 계약서에 명시되지 않은 내용은 추측하지 마세요
   - 정보가 부족한 경우 솔직히 "계약서에 명시되지 않았습니다"라고 답하세요

5. **비교 분석 시**
   - 사용자 계약서와 표준계약서를 비교할 때는 명확히 구분하세요
   - 예: "사용자 계약서 제3조는 ..., 반면 표준계약서 제2조는 ..."

## 답변 형식

- 간결하고 명확하게 답변하세요
- 법률 용어를 사용할 때는 쉽게 풀어서 설명하세요
- 필요한 경우 예시를 들어 설명하세요
"""
        return prompt
