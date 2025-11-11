"""
ChatbotOrchestrator - 챗봇 오케스트레이터

전체 대화 흐름을 관리하는 핵심 클래스
"""

import logging
import time
from typing import Dict, Any, List
from openai import AzureOpenAI
from backend.chatbot_agent.models import ChatbotResponse, ToolResult
from backend.chatbot_agent.tools import ToolRegistry
from backend.chatbot_agent.tools.hybrid_search_tool import HybridSearchTool
from backend.chatbot_agent.tools.article_index_tool import ArticleIndexTool
from backend.chatbot_agent.tools.article_title_tool import ArticleTitleTool
from backend.chatbot_agent.validators import ScopeValidator, ResponseValidator
from backend.chatbot_agent.tool_planner import ToolPlanner
from backend.chatbot_agent.content_extractor import ContentExtractor
from backend.chatbot_agent.reference_resolver import ReferenceResolver
from backend.chatbot_agent.context_manager import ContextManager

logger = logging.getLogger("uvicorn.error")


class ChatbotOrchestrator:
    """
    챗봇 오케스트레이터
    
    책임:
    - 질문 범위 검증
    - 대화 컨텍스트 관리
    - LLM Function Calling 실행
    - 도구 실행 및 검증
    - 응답 생성 및 품질 평가
    """
    
    def __init__(
        self,
        azure_client: AzureOpenAI,
        tool_registry: ToolRegistry = None,
        context_manager: ContextManager = None,
        scope_validator: ScopeValidator = None,
        response_validator: ResponseValidator = None,
        tool_planner: ToolPlanner = None,
        content_extractor: ContentExtractor = None,
        reference_resolver: ReferenceResolver = None
    ):
        """
        Args:
            azure_client: Azure OpenAI 클라이언트
            tool_registry: 도구 레지스트리 (선택, 없으면 자동 생성)
            context_manager: 컨텍스트 관리자 (선택)
            scope_validator: 범위 검증기 (선택)
            response_validator: 응답 검증기 (선택)
            tool_planner: 도구 계획기 (선택)
            content_extractor: 내용 발췌기 (선택)
            reference_resolver: 참조 해결기 (선택)
        """
        self.azure_client = azure_client
        
        # 도구 레지스트리 초기화
        if tool_registry is None:
            tool_registry = ToolRegistry()
            # 기본 도구 등록
            tool_registry.register(HybridSearchTool(azure_client))
            tool_registry.register(ArticleIndexTool())
            tool_registry.register(ArticleTitleTool())
        
        self.tool_registry = tool_registry
        
        # 컴포넌트 초기화
        self.context_manager = context_manager or ContextManager()
        self.scope_validator = scope_validator or ScopeValidator(azure_client)
        self.response_validator = response_validator or ResponseValidator()
        self.tool_planner = tool_planner or ToolPlanner(azure_client, tool_registry)
        self.content_extractor = content_extractor or ContentExtractor(azure_client)
        self.reference_resolver = reference_resolver or ReferenceResolver(tool_registry)
        
        logger.info("ChatbotOrchestrator 초기화 완료")
    
    def process_message(
        self,
        contract_id: str,
        user_message: str,
        session_id: str = None
    ) -> ChatbotResponse:
        """
        사용자 메시지 처리
        
        흐름:
        1. 질문 범위 검증 (규칙 기반)
        2. 대화 컨텍스트 로드
        3. Tool Planner (도구 계획 수립)
        4. 도구 실행 (계획에 따라)
        5. 참조 해결 (조항 간 참조 자동 추적)
        6. 응답 생성
        7. 응답 품질 평가 (필요시 재생성)
        8. 대화 히스토리 저장
        
        Args:
            contract_id: 계약서 ID
            user_message: 사용자 메시지
            session_id: 세션 ID (선택, 없으면 자동 생성)
            
        Returns:
            ChatbotResponse: 챗봇 응답
        """
        start_time = time.time()
        
        try:
            # 세션 ID 생성 (없으면)
            if not session_id:
                session_id = self.context_manager.create_session_id(contract_id)
            
            logger.info(f"메시지 처리 시작: {contract_id}, session={session_id}")
            
            # 1. 질문 범위 검증
            scope_result = self.scope_validator.validate(user_message)
            if not scope_result.is_valid:
                logger.warning(f"범위 외 질문: {scope_result.reason}")
                return ChatbotResponse(
                    success=False,
                    message="죄송합니다. 저는 계약서 내용에 대한 질문에만 답변할 수 있습니다. 계약서 조항, 내용, 권리, 의무 등에 대해 질문해주세요.",
                    session_id=session_id,
                    error=scope_result.reason
                )
            
            # 2. 대화 컨텍스트 로드
            conversation_history = self.context_manager.load_history(contract_id, session_id)
            
            # 3. 도구 계획 수립
            tool_plan = self.tool_planner.plan(user_message, conversation_history)
            logger.info(f"도구 계획: {tool_plan.intent}, {len(tool_plan.topics)}개 주제")
            
            # 4. 도구 실행
            tool_results = self._execute_tools(contract_id, tool_plan, user_message)
            
            if not tool_results:
                logger.warning("도구 실행 결과 없음")
                return ChatbotResponse(
                    success=False,
                    message="관련 정보를 찾을 수 없습니다. 다른 방식으로 질문해주세요.",
                    session_id=session_id
                )
            
            # 5. 참조 해결
            additional_results = self.reference_resolver.resolve_references(
                contract_id=contract_id,
                tool_results=tool_results,
                user_message=user_message,
                max_depth=2
            )
            
            if additional_results:
                tool_results.extend(additional_results)
                logger.info(f"참조 해결: {len(additional_results)}개 추가")
            
            # 6. 응답 생성
            response_text, sources = self._generate_response(
                user_message=user_message,
                tool_results=tool_results,
                conversation_history=conversation_history
            )
            
            # 7. 응답 품질 평가
            validation_result = self.response_validator.validate(
                user_message=user_message,
                response=response_text,
                tool_results=tool_results
            )
            
            if not validation_result.is_valid:
                logger.warning(f"응답 품질 불량: {validation_result.reason}, 재생성 시도")
                # 재생성 (1회만)
                response_text, sources = self._generate_response(
                    user_message=user_message,
                    tool_results=tool_results,
                    conversation_history=conversation_history,
                    retry=True
                )
            
            # 8. 대화 히스토리 저장
            self.context_manager.save_message(
                contract_id=contract_id,
                session_id=session_id,
                role="user",
                content=user_message
            )
            
            self.context_manager.save_message(
                contract_id=contract_id,
                session_id=session_id,
                role="assistant",
                content=response_text
            )
            
            elapsed_time = time.time() - start_time
            logger.info(f"메시지 처리 완료: {elapsed_time:.2f}초")
            
            return ChatbotResponse(
                success=True,
                message=response_text,
                sources=sources,
                session_id=session_id
            )
        
        except Exception as e:
            logger.error(f"메시지 처리 실패: {e}")
            import traceback
            logger.error(traceback.format_exc())
            
            return ChatbotResponse(
                success=False,
                message="죄송합니다. 처리 중 오류가 발생했습니다. 다시 시도해주세요.",
                session_id=session_id,
                error=str(e)
            )
    
    def _execute_tools(
        self,
        contract_id: str,
        tool_plan: Any,
        user_message: str
    ) -> List[ToolResult]:
        """
        도구 실행 (계획에 따라)
        
        Args:
            contract_id: 계약서 ID
            tool_plan: 도구 실행 계획
            user_message: 사용자 메시지
            
        Returns:
            도구 실행 결과 리스트
        """
        results = []
        
        for topic in tool_plan.topics:
            tool_name = topic.get("tool")
            args = topic.get("args", {})
            purpose = topic.get("purpose", "")
            
            logger.info(f"도구 실행: {tool_name}, 목적={purpose}")
            logger.info(f"도구 인자: {args}")  # 디버깅용 로그 추가
            
            # 도구 실행
            result = self.tool_registry.execute_tool(
                tool_name=tool_name,
                arguments=args,
                contract_id=contract_id
            )
            
            if result.success:
                # DB 접근 도구의 경우 ContentExtractor 적용
                if tool_name in ["get_article_by_index", "get_article_by_title"]:
                    result = self._apply_content_extraction(
                        result=result,
                        user_message=user_message,
                        purpose=purpose
                    )
                
                results.append(result)
            else:
                logger.warning(f"도구 실행 실패: {tool_name}, {result.error}")
        
        return results
    
    def _apply_content_extraction(
        self,
        result: ToolResult,
        user_message: str,
        purpose: str
    ) -> ToolResult:
        """
        DB 접근 도구 결과에 ContentExtractor 적용
        
        Args:
            result: 도구 실행 결과
            user_message: 사용자 메시지
            purpose: 도구 사용 목적
            
        Returns:
            발췌된 내용이 포함된 ToolResult
        """
        try:
            if not result.data or not isinstance(result.data, dict):
                return result
            
            matched_articles = result.data.get("matched_articles", [])
            
            for article in matched_articles:
                if not isinstance(article, dict):
                    continue
                
                # ContentExtractor로 필요한 하위항목만 선택
                selected_indices = self.content_extractor.extract(
                    user_message=user_message,
                    article_data=article,
                    purpose=purpose
                )
                
                # 선택된 하위항목만 유지
                full_content = article.get("content", [])
                selected_content = [
                    full_content[i] for i in selected_indices
                    if i < len(full_content)
                ]
                
                article["content"] = selected_content
                article["extracted_indices"] = selected_indices
            
            return result
        
        except Exception as e:
            logger.error(f"Content extraction 적용 실패: {e}")
            return result
    
    def _generate_response(
        self,
        user_message: str,
        tool_results: List[ToolResult],
        conversation_history: List[Dict[str, str]],
        retry: bool = False
    ) -> tuple:
        """
        LLM으로 응답 생성
        
        Args:
            user_message: 사용자 메시지
            tool_results: 도구 실행 결과
            conversation_history: 대화 히스토리
            retry: 재시도 여부
            
        Returns:
            (응답 텍스트, 출처 리스트)
        """
        # 도구 결과를 컨텍스트로 변환
        context = self._build_context_from_tools(tool_results)
        
        # 시스템 프롬프트
        system_prompt = """당신은 계약서 질의응답 전문가입니다.

규칙:
1. 제공된 계약서 내용만을 기반으로 답변하세요
2. 계약서에 없는 내용은 추측하지 마세요
3. 참조한 조항의 출처를 명시하세요 (예: "제5조에 따르면...")
4. 명확하고 이해하기 쉽게 답변하세요
5. 불확실한 경우 솔직히 말하세요"""

        if retry:
            system_prompt += "\n\n이전 답변이 불완전했습니다. 더 정확하고 완전한 답변을 제공하세요."
        
        # 사용자 프롬프트
        user_prompt = f"""계약서 내용:
{context}

질문: {user_message}

위 계약서 내용을 바탕으로 질문에 답변해주세요."""

        # LLM 호출
        messages = [
            {"role": "system", "content": system_prompt}
        ]
        
        # 대화 히스토리 추가 (최근 5개만)
        if conversation_history:
            messages.extend(conversation_history[-5:])
        
        messages.append({"role": "user", "content": user_prompt})
        
        response = self.azure_client.chat.completions.create(
            model="gpt-4o",
            messages=messages,
            temperature=0.3,
            max_tokens=1000
        )
        
        response_text = response.choices[0].message.content.strip()
        
        # 출처 추출
        sources = self._extract_sources_from_tools(tool_results)
        
        return response_text, sources
    
    def _build_context_from_tools(
        self,
        tool_results: List[ToolResult]
    ) -> str:
        """
        도구 결과를 LLM 컨텍스트로 변환
        
        Args:
            tool_results: 도구 실행 결과
            
        Returns:
            컨텍스트 문자열
        """
        context_parts = []
        
        for result in tool_results:
            if not result.success or not result.data:
                continue
            
            if isinstance(result.data, dict):
                # HybridSearchTool 결과
                for topic_name, topic_results in result.data.items():
                    if isinstance(topic_results, list):
                        for item in topic_results:
                            if isinstance(item, dict):
                                parent_title = item.get("parent_title", "")
                                chunk_text = item.get("chunk_text", "")
                                context_parts.append(f"[{parent_title}]\n{chunk_text}")
                
                # ArticleIndexTool, ArticleTitleTool 결과
                matched_articles = result.data.get("matched_articles", [])
                for article in matched_articles:
                    if isinstance(article, dict):
                        title = article.get("title", "")
                        article_no = article.get("article_no", "")
                        content = article.get("content", [])
                        
                        if isinstance(content, list):
                            content_text = "\n".join(content)
                            context_parts.append(f"[제{article_no}조 {title}]\n{content_text}")
        
        return "\n\n".join(context_parts)
    
    def _extract_sources_from_tools(
        self,
        tool_results: List[ToolResult]
    ) -> List[Dict[str, Any]]:
        """
        도구 결과에서 출처 정보 추출
        
        Args:
            tool_results: 도구 실행 결과
            
        Returns:
            출처 리스트
        """
        sources = []
        
        for result in tool_results:
            if not result.success or not result.data:
                continue
            
            if isinstance(result.data, dict):
                matched_articles = result.data.get("matched_articles", [])
                for article in matched_articles:
                    if isinstance(article, dict):
                        article_no = article.get("article_no", "")
                        title = article.get("title", "")
                        content = article.get("content", [])
                        
                        sources.append({
                            "article_title": f"제{article_no}조 {title}" if article_no else title,
                            "article_content": content if isinstance(content, list) else [],
                            "tool": result.tool_name
                        })
        
        return sources
    
    async def process_message_stream(
        self,
        contract_id: str,
        user_message: str,
        session_id: str = None
    ):
        """
        사용자 메시지 처리 (스트리밍)
        
        Args:
            contract_id: 계약서 ID
            user_message: 사용자 메시지
            session_id: 세션 ID (선택)
            
        Yields:
            dict: 스트리밍 청크 {'token': str} 또는 {'sources': list}
        """
        start_time = time.time()
        
        try:
            # 세션 ID 생성
            if not session_id:
                session_id = self.context_manager.create_session_id(contract_id)
            
            logger.info(f"스트리밍 메시지 처리 시작: {contract_id}, session={session_id}")
            
            # 1. 질문 범위 검증
            scope_result = self.scope_validator.validate(user_message)
            if not scope_result.is_valid:
                error_msg = "죄송합니다. 저는 계약서 내용에 대한 질문에만 답변할 수 있습니다. 계약서 조항, 내용, 권리, 의무 등에 대해 질문해주세요."
                for char in error_msg:
                    yield {"token": char}
                return
            
            # 2. 대화 컨텍스트 로드
            conversation_history = self.context_manager.load_history(contract_id, session_id)
            
            # 3. 도구 계획 수립
            tool_plan = self.tool_planner.plan(user_message, conversation_history)
            
            # 4. 도구 실행
            tool_results = self._execute_tools(contract_id, tool_plan, user_message)
            
            if not tool_results:
                error_msg = "관련 정보를 찾을 수 없습니다. 다른 방식으로 질문해주세요."
                for char in error_msg:
                    yield {"token": char}
                return
            
            # 5. 참조 해결
            additional_results = self.reference_resolver.resolve_references(
                contract_id=contract_id,
                tool_results=tool_results,
                user_message=user_message,
                max_depth=2
            )
            
            if additional_results:
                tool_results.extend(additional_results)
            
            # 6. 스트리밍 응답 생성
            full_response = ""
            async for chunk in self._generate_response_stream(
                user_message=user_message,
                tool_results=tool_results,
                conversation_history=conversation_history
            ):
                full_response += chunk
                yield {"token": chunk}
            
            # 7. 출처 정보 전송
            sources = self._extract_sources_from_tools(tool_results)
            yield {"sources": sources}
            
            # 8. 대화 히스토리 저장
            self.context_manager.save_message(
                contract_id=contract_id,
                session_id=session_id,
                role="user",
                content=user_message
            )
            
            self.context_manager.save_message(
                contract_id=contract_id,
                session_id=session_id,
                role="assistant",
                content=full_response
            )
            
            elapsed_time = time.time() - start_time
            logger.info(f"스트리밍 메시지 처리 완료: {elapsed_time:.2f}초")
        
        except Exception as e:
            logger.error(f"스트리밍 메시지 처리 실패: {e}")
            import traceback
            logger.error(traceback.format_exc())
            
            error_msg = "죄송합니다. 처리 중 오류가 발생했습니다. 다시 시도해주세요."
            for char in error_msg:
                yield {"token": char}
    
    async def _generate_response_stream(
        self,
        user_message: str,
        tool_results: List[ToolResult],
        conversation_history: List[Dict[str, str]]
    ):
        """
        LLM으로 스트리밍 응답 생성
        
        Args:
            user_message: 사용자 메시지
            tool_results: 도구 실행 결과
            conversation_history: 대화 히스토리
            
        Yields:
            str: 응답 토큰
        """
        # 도구 결과를 컨텍스트로 변환
        context = self._build_context_from_tools(tool_results)
        
        # 시스템 프롬프트
        system_prompt = """당신은 계약서 질의응답 전문가입니다.

규칙:
1. 제공된 계약서 내용만을 기반으로 답변하세요
2. 계약서에 없는 내용은 추측하지 마세요
3. 참조한 조항의 출처를 명시하세요 (예: "제5조에 따르면...")
4. 명확하고 이해하기 쉽게 답변하세요
5. 불확실한 경우 솔직히 말하세요"""
        
        # 사용자 프롬프트
        user_prompt = f"""계약서 내용:
{context}

질문: {user_message}

위 계약서 내용을 바탕으로 질문에 답변해주세요."""

        # LLM 호출 (스트리밍)
        messages = [
            {"role": "system", "content": system_prompt}
        ]
        
        # 대화 히스토리 추가 (최근 5개만)
        if conversation_history:
            messages.extend(conversation_history[-5:])
        
        messages.append({"role": "user", "content": user_prompt})
        
        stream = self.azure_client.chat.completions.create(
            model="gpt-4o",
            messages=messages,
            temperature=0.3,
            max_tokens=1000,
            stream=True
        )
        
        for chunk in stream:
            if chunk.choices and len(chunk.choices) > 0:
                delta = chunk.choices[0].delta
                if delta.content:
                    yield delta.content
