"""
ContentExtractor - 조항 내용 발췌기

DB에서 가져온 조 전체 내용에서 필요한 하위항목만 발췌합니다.
"""

import logging
import json
from typing import Dict, Any, List
from openai import OpenAI

logger = logging.getLogger("uvicorn.error")


class ContentExtractor:
    """
    조항 내용 발췌기
    
    DB에서 가져온 조 전체 내용에서 필요한 하위항목만 발췌합니다.
    """
    
    def __init__(self, openai_client: OpenAI):
        """
        Args:
            openai_client: OpenAI 클라이언트
        """
        self.client = openai_client
        logger.info("ContentExtractor 초기화")
    
    def extract(
        self,
        user_message: str,
        article_data: Dict[str, Any],
        purpose: str
    ) -> List[int]:
        """
        필요한 하위항목 인덱스 선택
        
        Args:
            user_message: 사용자 질문
            article_data: 조 전체 데이터 (title, content 배열)
            purpose: 이 조를 참조하는 목적
            
        Returns:
            선택된 하위항목 인덱스 목록 (0부터 시작)
            
        흐름:
        1. 조 전체 내용을 LLM에게 제공
        2. 사용자 질문과 목적을 고려하여 필요한 하위항목 선택
        3. LLM이 인덱스 목록 반환 (텍스트 생성 X)
        4. 실제 content 배열에서 해당 인덱스의 내용 추출
        """
        try:
            content = article_data.get("content", [])
            
            if not content:
                logger.warning("조항 내용이 비어있습니다")
                return []
            
            # content 배열을 인덱스와 함께 표시
            indexed_content = "\n".join([
                f"[{i}] {item}"
                for i, item in enumerate(content)
            ])
            
            prompt = f"""다음 조항에서 사용자 질문에 답하는데 필요한 모든 하위항목의 인덱스를 선택하세요.

조 제목: {article_data.get("title", "")}
조 내용:
{indexed_content}

사용자 질문: {user_message}
참조 목적: {purpose}

필요한 하위항목의 인덱스를 선택하세요 (0부터 시작).
모든 내용이 필요하면 "all"을 반환하세요.

답변 형식 (JSON):
{{
  "selected_indices": [0, 2, 5] 또는 "all",
  "reason": "선택 이유"
}}"""

            response = self.client.chat.completions.create(
                model="gpt-4o",
                messages=[{"role": "user", "content": prompt}],
                temperature=0.0,
                max_tokens=200
            )
            
            # JSON 파싱
            content_str = response.choices[0].message.content.strip()
            
            # JSON 블록 추출
            if "```json" in content_str:
                content_str = content_str.split("```json")[1].split("```")[0].strip()
            elif "```" in content_str:
                content_str = content_str.split("```")[1].split("```")[0].strip()
            
            result = json.loads(content_str)
            
            if result["selected_indices"] == "all":
                logger.info(f"모든 하위항목 선택: {len(content)}개")
                return list(range(len(content)))
            else:
                indices = result["selected_indices"]
                logger.info(f"하위항목 선택: {len(indices)}개 (인덱스: {indices})")
                return indices
                
        except Exception as e:
            logger.error(f"Content extraction 실패: {e}")
            import traceback
            logger.error(traceback.format_exc())
            
            # 폴백: 모든 내용 반환
            logger.warning("폴백: 모든 하위항목 반환")
            return list(range(len(article_data.get("content", []))))
