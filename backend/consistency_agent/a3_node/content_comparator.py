"""
ContentComparator - LLM 기반 조항 내용 비교
표준계약서 조항과 사용자 조항의 내용 충실도 분석
"""

import logging
from typing import Dict, Any, List, Optional
from openai import AzureOpenAI

logger = logging.getLogger(__name__)


class ContentComparator:
    """
    LLM 기반 내용 비교기

    주요 기능:
    1. 표준계약서 조항과 사용자 조항 포맷팅
    2. LLM을 통한 내용 비교 및 분석
    3. 누락/불충분/문제점 식별
    """

    def __init__(self, azure_client: AzureOpenAI, model: str = "gpt-4o"):
        """
        Args:
            azure_client: Azure OpenAI 클라이언트
            model: 사용할 모델명 (기본: gpt-4o)
        """
        self.azure_client = azure_client
        self.model = model

        logger.info(f"ContentComparator 초기화 완료 (model={model})")

    def compare_articles(
        self,
        user_article: Dict[str, Any],
        standard_chunks_list: List[List[Dict[str, Any]]],
        contract_type: str,
        all_chunks: List[Dict[str, Any]] = None
    ) -> Dict[str, Any]:
        """
        조항 내용 비교

        A1에서 이미 관련 조항을 선택했으므로, 여기서는 내용 분석만 수행

        Args:
            user_article: 사용자 조항 (content 배열 포함)
            standard_chunks_list: 표준계약서 조항들의 청크 리스트 (A1에서 선택된 조항들)
            contract_type: 계약 유형
            all_chunks: 전체 청크 리스트 (참조 로드용, 선택적)

        Returns:
            {
                "has_issues": bool,
                "missing_items": List[str],
                "insufficient_items": List[str],
                "analysis": str,
                "selected_articles": List[str],  # 조항 ID 목록
                "prompt_tokens": int,
                "completion_tokens": int,
                "total_tokens": int
            }
        """
        # 전체 청크 저장 (참조 로드용)
        self.all_chunks = all_chunks or []

        # 사용자 조항 포맷팅
        user_text = self._format_user_article(user_article)

        # 단일 매칭 vs 다중 매칭
        if len(standard_chunks_list) == 1:
            # 1개: 직접 비교
            return self._compare_single_article(
                user_article, standard_chunks_list[0], user_text, contract_type
            )
        else:
            # 2개 이상: 모든 조항을 종합하여 비교 (A1에서 이미 선택됨)
            return self._compare_multiple_selected_articles(
                user_article, standard_chunks_list, user_text, contract_type
            )

    def _compare_single_article(
        self,
        user_article: Dict[str, Any],
        standard_chunks: List[Dict[str, Any]],
        user_text: str,
        contract_type: str
    ) -> Dict[str, Any]:
        """
        단일 표준 조항과 비교

        Args:
            user_article: 사용자 조항
            standard_chunks: 표준계약서 조의 모든 청크들
            user_text: 포맷팅된 사용자 조항 텍스트
            contract_type: 계약 유형

        Returns:
            비교 결과
        """
        # 표준계약서 조항 포맷팅
        standard_text = self._format_standard_article(standard_chunks)

        # 프롬프트 생성
        prompt = self._build_comparison_prompt(
            user_article_no=user_article.get('number'),
            user_article_title=user_article.get('title', ''),
            standard_text=standard_text,
            user_text=user_text,
            contract_type=contract_type,
            is_multiple=False,
            num_articles=1
        )

        # LLM 호출
        try:
            response = self.azure_client.chat.completions.create(
                model=self.model,
                messages=[
                    {
                        "role": "system",
                        "content": self._get_system_message(is_multiple=False)
                    },
                    {
                        "role": "user",
                        "content": prompt
                    }
                ],
                temperature=0.3,
                max_tokens=2000
            )

            analysis_text = response.choices[0].message.content.strip()
            usage = response.usage

            # 분석 결과 파싱
            result = self._parse_llm_response(analysis_text)
            result["prompt_tokens"] = usage.prompt_tokens
            result["completion_tokens"] = usage.completion_tokens
            result["total_tokens"] = usage.total_tokens
            result["selected_articles"] = [standard_chunks[0].get('parent_id')] if standard_chunks else []

            logger.info(f"  LLM 단일 비교 완료 (토큰: {usage.total_tokens})")

            return result

        except Exception as e:
            logger.error(f"  LLM 비교 실패: {e}")
            return {
                "has_issues": False,
                "missing_items": [],
                "insufficient_items": [],
                "analysis": f"LLM 분석 실패: {str(e)}",
                "selected_articles": [],
                "prompt_tokens": 0,
                "completion_tokens": 0,
                "total_tokens": 0
            }

    def _compare_multiple_selected_articles(
        self,
        user_article: Dict[str, Any],
        standard_chunks_list: List[List[Dict[str, Any]]],
        user_text: str,
        contract_type: str
    ) -> Dict[str, Any]:
        """
        다중 표준 조항과 비교 (A1에서 이미 선택된 조항들)

        A1에서 매칭 검증을 거친 조항들을 모두 종합하여 내용 분석

        Args:
            user_article: 사용자 조항
            standard_chunks_list: 표준계약서 조항들의 청크 리스트 (A1에서 선택됨)
            user_text: 포맷팅된 사용자 조항 텍스트
            contract_type: 계약 유형

        Returns:
            비교 결과
        """
        # 조항 ID 추출
        selected_article_ids = [
            chunks[0].get('parent_id') for chunks in standard_chunks_list
            if chunks and chunks[0].get('parent_id')
        ]

        logger.info(f"  내용 분석 대상: {', '.join(selected_article_ids)}")

        # 내용 분석 수행
        analysis_result = self._analyze_selected_articles(
            user_article, standard_chunks_list, user_text, contract_type
        )

        analysis_result['selected_articles'] = selected_article_ids

        logger.info(f"  LLM 다중 비교 완료 (토큰: {analysis_result.get('total_tokens', 0)})")

        return analysis_result

    def _get_system_message(self, is_multiple: bool = False) -> str:
        """
        공통 시스템 메시지

        Args:
            is_multiple: 다중 조항 비교 여부

        Returns:
            시스템 메시지 텍스트
        """
        if is_multiple:
            mission = """당신은 데이터 계약서 전문 분석가입니다.  
당신의 임무는 "표준계약서", "활용안내서", "별지" 등의 참고 자료를 종합적으로 활용하여 
"사용자 계약서"의 조항을 분석하고, 사용자가 표준계약서의 핵심 취지를 얼마나 충실히 반영했는지를 평가하는 것입니다."""
        else:
            mission = """당신은 데이터 계약서 전문 분석가입니다.  
당신의 임무는 "표준계약서"의 조항들과 "사용자 계약서"의 조항을 비교하여, 사용자 계약서 조항의 정합성을 평가하는 것입니다."""

        return f"""{mission}

**표준계약서의 개념**
- 표준계약서는 특정 계약 상황을 완성형으로 제시하는 예시가 아니라, 계약서 작성 시 참고할 수 있는 권장 템플릿입니다.  
- 따라서 표준계약서는 일반적이고 포괄적인 표현을 사용하며, 실제 계약서에서는 이를 각 당사자의 상황에 맞게 구체화하거나 특화하는 것이 자연스럽고 바람직합니다.
- 사용자가 표준조항을 구체화하거나 특정 사례(예: 회사명, 데이터 유형, 세부 절차 등)를 명시한 경우, 이는 표준을 실질적으로 구현한 것으로, 잘못된 것이 아닙니다.

**검증의 방향**
- 비교의 기준은 "표준계약서가 권장하는 핵심 의미가 사용자 계약서에 포함되어 있는가"입니다.  
- 표준보다 구체적이거나 특화된 내용은 '포괄성이 줄었다'고 보지 말고, **표준의 정신을 실제 상황에 맞게 반영한 합리적 구체화**로 해석하십시오.
- 오히려 사용자 계약의 특성에 맞추어 구체화 되어야 할 부분이 표준계약서의 그것과 동일하게 포괄적인 의미만을 담고 있다면 문제될 수 있습니다.
- 누락 판정은 표준조항의 **핵심 내용이나 의무가 의미적으로 결여된 경우에만** 해당됩니다.
- 불충분 판정은 **핵심 취지의 결여나, 표현의 모호함, 명확한 정립의 필요성** 등을 판단합니다.

**표현 형식에 대한 원칙**
- 목록·표 형식과 서술형 표현의 차이는 중요하지 않습니다.  
- 같은 의미를 담고 있다면 표현 방식이 달라도 동일하게 간주하십시오.
- 단어·순서·문체 차이는 문제로 보지 마십시오. 의미가 유지되는지, 내용이 명확한지를 판단하십시오.

**참고 자료 활용 원칙**
분석 시 다음 참고 자료를 적극 활용하십시오:
1. **[해설]**: 활용안내서의 해설 내용
   - 조항의 법적 의미, 배경, 적용 사례 등을 설명
   - 인용 시: "활용안내서에서는 ~" 또는 "활용안내서에 따르면 ~"
   
2. **[참조 별지]**: 별지의 상세 내용
   - 계약서 본문에서 참조하는 구체적 항목 (데이터 목록, 요구사항 등)
   - 인용 시: "별지에서는 ~" 또는 "별지○에서는 ~"
   
3. **[참조 조항]**: 다른 조항의 내용
   - 본 조항과 연관된 다른 조항의 규정
   - 인용 시: "제○조에서는 ~" 또는 "제○조에 따르면 ~"

이러한 참고 자료는 표준계약서의 취지를 이해하고 사용자 계약서를 평가하는 데 중요한 근거가 됩니다.
이 원칙에 따라 사용자의 조항이 표준과 활용의 취지를 얼마나 충실히 반영했는지, 논리적·실질적 측면에서 분석하십시오."""

    def _format_standard_article(self, chunks: List[Dict[str, Any]]) -> str:
        """
        표준계약서 조항 포맷팅 (신규 청크 구조 지원)

        parent_id (title)
        id: text_norm
        [해설] commentary_summary (있는 경우)
        [참조] references 내용 (있는 경우)

        Args:
            chunks: 동일한 parent_id를 가진 청크들

        Returns:
            포맷팅된 텍스트
        """
        if not chunks:
            return ""

        # parent_id와 title
        parent_id = chunks[0].get('parent_id', '')
        title = chunks[0].get('title', '')

        lines = [f"{parent_id} ({title})"]

        # 각 청크 처리
        for chunk in chunks:
            chunk_id = chunk.get('id', '')
            text_norm = chunk.get('text_norm', '').strip()
            commentary_summary = chunk.get('commentary_summary', '').strip()
            references = chunk.get('references', [])

            if not chunk_id or not text_norm:
                continue

            # 1. 기본 텍스트 (text_norm)
            lines.append(f"{chunk_id}: {text_norm}")

            # 2. references 처리
            if references:
                logger.info(f"      청크 {chunk_id}에 references 발견: {len(references)}개")
                # 별지 참조가 있는지 확인
                has_exhibit_ref = any(':ex:' in ref for ref in references)
                
                if has_exhibit_ref:
                    logger.info(f"      별지 참조 감지: {[r for r in references if ':ex:' in r]}")
                    # 별지 참조: text_llm만 로드
                    exhibit_contents = self._load_referenced_exhibits(references)
                    if exhibit_contents:
                        lines.append("\n[참조 별지]")
                        for ref_id, ref_content in exhibit_contents.items():
                            lines.append(f"  {ref_id}: {ref_content}")
                    else:
                        logger.warning(f"      별지 참조 로드 실패")
                else:
                    logger.info(f"      조항 참조 감지: {references}")
                    # 조항 참조: text_norm + commentary_summary 로드
                    article_contents = self._load_referenced_articles(references)
                    if article_contents:
                        lines.append("\n[참조 조항]")
                        for ref_id, ref_content in article_contents.items():
                            lines.append(f"  {ref_id}: {ref_content}")
                    else:
                        logger.warning(f"      조항 참조 로드 실패")

            # 3. commentary_summary (별지 참조가 없는 경우만)
            if commentary_summary and not any(':ex:' in ref for ref in references):
                lines.append(f"\n[해설] {commentary_summary}")

        return "\n".join(lines)

    def _format_user_article(self, user_article: Dict[str, Any]) -> str:
        """
        사용자 조항 포맷팅

        text
        content[0]
        content[1]
        ...

        Args:
            user_article: 사용자 조항

        Returns:
            포맷팅된 텍스트
        """
        lines = []

        # text (조 본문)
        text = user_article.get('text', '').strip()
        if text:
            lines.append(text)

        # content 배열 (하위항목들)
        content_items = user_article.get('content', [])
        for item in content_items:
            if isinstance(item, str) and item.strip():
                lines.append(item.strip())

        return "\n".join(lines)

    # _select_relevant_articles 메서드는 A1의 MatchingVerifier로 이동됨
    # A1에서 이미 관련 조항을 선택하므로 여기서는 제거

    def _analyze_selected_articles(
        self,
        user_article: Dict[str, Any],
        selected_chunks_list: List[List[Dict[str, Any]]],
        user_text: str,
        contract_type: str
    ) -> Dict[str, Any]:
        """
        선택된 표준 조항들을 기준으로 내용 분석 (2단계)

        Args:
            user_article: 사용자 조항
            selected_chunks_list: 선택된 표준계약서 조항들의 청크 리스트
            user_text: 포맷팅된 사용자 조항 텍스트
            contract_type: 계약 유형

        Returns:
            비교 결과
        """
        # 선택된 조항들 포맷팅
        standard_text = ""
        for chunks in selected_chunks_list:
            if chunks:
                standard_text += self._format_standard_article(chunks) + "\n\n"

        # 분석 프롬프트 생성
        prompt = self._build_comparison_prompt(
            user_article_no=user_article.get('number'),
            user_article_title=user_article.get('title', ''),
            standard_text=standard_text,
            user_text=user_text,
            contract_type=contract_type,
            is_multiple=True,
            num_articles=len(selected_chunks_list)
        )

        try:
            response = self.azure_client.chat.completions.create(
                model=self.model,
                messages=[
                    {
                        "role": "system",
                        "content": self._get_system_message(is_multiple=True)
                    },
                    {
                        "role": "user",
                        "content": prompt
                    }
                ],
                temperature=0.3,
                max_tokens=2000
            )

            analysis_text = response.choices[0].message.content.strip()
            usage = response.usage

            # 분석 결과 파싱
            result = self._parse_llm_response(analysis_text)
            result["prompt_tokens"] = usage.prompt_tokens
            result["completion_tokens"] = usage.completion_tokens
            result["total_tokens"] = usage.total_tokens

            return result

        except Exception as e:
            logger.error(f"  내용 분석 실패: {e}")
            return {
                "has_issues": False,
                "missing_items": [],
                "insufficient_items": [],
                "analysis": f"LLM 분석 실패: {str(e)}",
                "prompt_tokens": 0,
                "completion_tokens": 0
            }

    # _build_selection_prompt 메서드는 A1의 MatchingVerifier로 이동됨

    def _build_comparison_prompt(
        self,
        user_article_no: int,
        user_article_title: str,
        standard_text: str,
        user_text: str,
        contract_type: str,
        is_multiple: bool = False,
        num_articles: int = 1
    ) -> str:
        """
        통합 조항 비교 프롬프트 생성

        Args:
            user_article_no: 사용자 조항 번호
            user_article_title: 사용자 조항 제목
            standard_text: 포맷팅된 표준계약서 조항(들)
            user_text: 포맷팅된 사용자 조항
            contract_type: 계약 유형
            is_multiple: 다중 조항 비교 여부
            num_articles: 표준 조항 개수 (다중일 때만 사용)

        Returns:
            프롬프트 텍스트
        """
        contract_type_names = {
            "provide": "데이터 제공 계약",
            "create": "데이터 생성 계약",
            "process": "데이터 가공 계약",
            "brokerage_provider": "데이터 중개 계약 (제공자용)",
            "brokerage_user": "데이터 중개 계약 (이용자용)"
        }

        contract_name = contract_type_names.get(contract_type, contract_type)

        # 표준 조항 섹션 헤더
        if is_multiple:
            standard_section = f"""## 표준계약서 조항들 (총 {num_articles}개)
아래 조항들은 사용자 조항과 관련있는 표준계약서 조항들입니다.

{standard_text}"""
            instruction = """위의 표준계약서 조항들을 **모두 종합**하여, 사용자 계약서 조항의 내용 충실도를 분석해주세요.

**중요**: 표준계약서에 [해설], [참조 별지], [참조 조항]이 포함되어 있다면, 이를 반드시 활용하여 분석하고, 분석 내용에서 명시적으로 인용하세요."""
            missing_desc = "표준계약서 조항들에 있지만 사용자 조항에 누락된 내용이 있다면 구체적으로 나열, 없으면 \"없음\""
            analysis_desc = "사용자 조항이 표준계약서 조항들과 비교하여 얼마나 충실하게 작성되었는지 종합적으로 평가. 긍정적인 부분과 개선이 필요한 부분을 모두 포함."
        else:
            standard_section = f"""## 표준계약서 조항
{standard_text}"""
            instruction = """위의 표준계약서 조항을 기준으로, 사용자 계약서 조항의 내용 충실도를 분석해주세요.

**중요**: 표준계약서에 [해설], [참조 별지], [참조 조항]이 포함되어 있다면, 이를 반드시 활용하여 분석하고, 분석 내용에서 명시적으로 인용하세요."""
            missing_desc = "누락된 항목이 있다면 구체적으로 나열, 없으면 \"없음\""
            analysis_desc = "사용자 조항이 표준계약서 조항과 비교하여 얼마나 충실하게 작성되었는지 종합적으로 평가. 긍정적인 부분과 개선이 필요한 부분을 모두 포함."

        prompt = f"""# 계약서 조항 내용 비교 분석

## 계약 유형
{contract_name}

{standard_section}

## 사용자 계약서 조항
제{user_article_no}조 ({user_article_title})
{user_text}

---

{instruction}

답변은 다음 형식을 반드시 지키시오:

**문제 여부**: [있음/없음]

**누락된 내용**:
- [{missing_desc}]

**불충분한 내용**:
- [표준계약서에 비해 불충분하거나 모호한 내용이 있다면 구체적으로 나열, 없으면 "없음"]

**종합 분석**:
[{analysis_desc}]

---

**중요**:
- 사용자 계약서는 표준계약서와 완전히 동일할 필요가 없다. 핵심 내용이 포함되어 있고 논리적으로 문제가 없다면 긍정적으로 평가해라.
- 사용자 계약서 조항의 제목을 근거로 사용자가 해당 조항에 어떤 내용을 작성하려 했는지 의도를 짐작하여, 이를 토대로 표준계약서의 각 항목이 사용자의 조항에 포함되어야 하는지, 혹은 제외되어도 되는지를 판단하라.
- 단순한 표현 차이나 순서 차이는 문제로 보지 마라.
- 누락된 내용의 경우 단순 단어나 표현에 대한 누락이 아닌, 의미상의 누락을 감지해야 한다.
- 실질적으로 누락되었거나 불충분한 내용만 지적해라.
- 어투는 경어체로 통일하라.

**참고 자료 활용 필수**:
- [해설]이 있다면: "활용안내서에서는 ~" 또는 "활용안내서에 따르면 ~"로 반드시 인용
- [참조 별지]가 있다면: "별지에서는 ~" 또는 "별지○에서는 ~"로 반드시 인용
- [참조 조항]이 있다면: "제○조에서는 ~" 또는 "제○조에 따르면 ~"로 반드시 인용
- 참고 자료를 활용하지 않고 분석하면 불완전한 평가가 됩니다.
"""

        return prompt

    def _load_referenced_exhibits(self, references: List[str]) -> Dict[str, str]:
        """
        별지 참조 로드 (text_llm만 사용)

        Args:
            references: 참조 ID 리스트 (예: ["urn:std:process:ex:001:idx:001"])

        Returns:
            {chunk_id: text_llm} 딕셔너리
        """
        exhibit_contents = {}

        if not hasattr(self, 'all_chunks') or not self.all_chunks:
            logger.warning("    전체 청크가 로드되지 않아 별지 참조를 로드할 수 없습니다")
            return exhibit_contents

        for ref_id in references:
            if ':ex:' not in ref_id:
                continue

            # global_id로 청크 찾기
            for chunk in self.all_chunks:
                if chunk.get('global_id') == ref_id:
                    chunk_id = chunk.get('id', ref_id)
                    text_llm = chunk.get('text_llm', '').strip()
                    
                    if text_llm:
                        exhibit_contents[chunk_id] = text_llm
                        logger.debug(f"      별지 참조 로드 완료: {chunk_id}")
                    else:
                        logger.warning(f"      별지 {chunk_id}에 text_llm이 없습니다")
                    break

        return exhibit_contents

    def _load_referenced_articles(self, references: List[str]) -> Dict[str, str]:
        """
        조항 참조 로드 (text_norm + commentary_summary)

        Args:
            references: 참조 ID 리스트 (예: ["urn:std:process:art:023:cla:002"])

        Returns:
            {chunk_id: formatted_content} 딕셔너리
        """
        article_contents = {}

        if not hasattr(self, 'all_chunks') or not self.all_chunks:
            logger.warning("    전체 청크가 로드되지 않아 조항 참조를 로드할 수 없습니다")
            return article_contents

        for ref_id in references:
            if ':art:' not in ref_id:
                continue

            # global_id로 청크 찾기
            for chunk in self.all_chunks:
                if chunk.get('global_id') == ref_id:
                    chunk_id = chunk.get('id', ref_id)
                    text_norm = chunk.get('text_norm', '').strip()
                    commentary_summary = chunk.get('commentary_summary', '').strip()
                    
                    if text_norm:
                        # text_norm + commentary_summary 결합
                        content_parts = [text_norm]
                        if commentary_summary:
                            content_parts.append(f"해설 {commentary_summary}")
                        
                        article_contents[chunk_id] = "\n".join(content_parts)
                        logger.debug(f"      조항 참조 로드 완료: {chunk_id}")
                    else:
                        logger.warning(f"      조항 {chunk_id}에 text_norm이 없습니다")
                    break

        return article_contents

    def _parse_llm_response(self, response_text: str) -> Dict[str, Any]:
        """
        LLM 응답 파싱

        Args:
            response_text: LLM 응답 텍스트

        Returns:
            {
                "has_issues": bool,
                "missing_items": List[str],
                "insufficient_items": List[str],
                "analysis": str
            }
        """
        lines = response_text.split('\n')

        has_issues = False
        missing_items = []
        insufficient_items = []
        analysis = response_text  # 전체 분석 내용

        # "문제 여부" 파싱
        for line in lines:
            if '문제 여부' in line or '문제여부' in line:
                if '있음' in line:
                    has_issues = True
                break

        # "누락된 내용" 섹션 파싱
        in_missing_section = False
        in_insufficient_section = False

        for line in lines:
            line_stripped = line.strip()

            if '누락된 내용' in line_stripped:
                in_missing_section = True
                in_insufficient_section = False
                continue
            elif '불충분한 내용' in line_stripped:
                in_missing_section = False
                in_insufficient_section = True
                continue
            elif '종합 분석' in line_stripped or '**종합' in line_stripped:
                in_missing_section = False
                in_insufficient_section = False
                continue

            # 리스트 항목 파싱
            if in_missing_section and line_stripped.startswith('-'):
                item = line_stripped[1:].strip()
                if item and item.lower() != '없음':
                    missing_items.append(item)

            if in_insufficient_section and line_stripped.startswith('-'):
                item = line_stripped[1:].strip()
                if item and item.lower() != '없음':
                    insufficient_items.append(item)

        # 실제로 문제가 있는지 재확인
        if not missing_items and not insufficient_items:
            has_issues = False

        return {
            "has_issues": has_issues,
            "missing_items": missing_items,
            "insufficient_items": insufficient_items,
            "analysis": analysis
        }
