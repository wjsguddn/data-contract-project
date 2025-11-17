"""
AgentRuntime - 에이전트 실행 환경 통합 관리

LLM 호출, 툴 실행, 메트릭 수집, 에러 처리를 통합 관리합니다.
"""

import logging
import time
from typing import Dict, Any, Optional, List, Union
from datetime import datetime

from backend.chatbot_agent.llm_cache import LLMCache
from backend.chatbot_agent.models import ToolResultType

logger = logging.getLogger(__name__)


class AgentRuntime:
    """
    에이전트 실행 환경 통합 관리 클래스
    
    주요 기능:
    - LLM 호출 통합 (캐싱 포함)
    - 툴 실행 통합 (에러 처리 포함)
    - 메트릭 수집 및 추적
    - 통합 에러 처리
    """
    
    def __init__(
        self,
        openai_client,
        tool_registry,
        llm_cache: Optional[LLMCache] = None,
        enable_cache: bool = True,
        max_retries: int = 2
    ):
        """
        초기화
        
        Args:
            openai_client: OpenAI 클라이언트
            tool_registry: 툴 레지스트리
            llm_cache: LLM 캐시 (None이면 자동 생성)
            enable_cache: 캐시 활성화 여부
            max_retries: 최대 재시도 횟수
        """
        self.openai_client = openai_client
        self.tool_registry = tool_registry
        self.enable_cache = enable_cache
        self.max_retries = max_retries
        
        # LLM 캐시 초기화
        if enable_cache:
            self.llm_cache = llm_cache or LLMCache(
                use_redis=False,  # 기본은 메모리 캐시만
                ttl_seconds=3600
            )
        else:
            self.llm_cache = None
        
        # 메트릭 초기화
        self.metrics = {
            "llm_calls": 0,
            "llm_cache_hits": 0,
            "llm_cache_misses": 0,
            "llm_total_tokens": 0,
            "llm_errors": 0,
            "tool_calls": 0,
            "tool_successes": 0,
            "tool_failures": 0,
            "tool_retries": 0,
            "total_execution_time": 0.0
        }
        
        logger.info(f"AgentRuntime 초기화 완료 (캐시: {enable_cache}, 최대 재시도: {max_retries})")
    
    def call_llm_stream(
        self,
        messages: List[Dict[str, str]],
        model: str = "gpt-4o",
        temperature: Optional[float] = None,
        max_tokens: Optional[int] = None,
        **kwargs
    ):
        """
        LLM 스트리밍 호출 (캐싱 미지원)

        Args:
            messages: 메시지 리스트
            model: 모델명
            temperature: 온도 (None이면 모델 기본값 사용, o1 시리즈는 지원하지 않음)
            max_tokens: 최대 토큰 수
            **kwargs: 추가 파라미터

        Yields:
            LLM 응답 토큰

        Raises:
            Exception: LLM 호출 실패 시
        """
        start_time = time.time()

        try:
            self.metrics["llm_calls"] += 1

            call_params = {
                "model": model,
                "messages": messages,
                "stream": True
            }

            # o1 시리즈 모델은 temperature를 지원하지 않음
            if temperature is not None and not model.startswith("gpt-5"):
                call_params["temperature"] = temperature

            if max_tokens:
                call_params["max_tokens"] = max_tokens

            call_params.update(kwargs)

            stream = self.openai_client.chat.completions.create(**call_params)
            
            for chunk in stream:
                if chunk.choices and len(chunk.choices) > 0:
                    delta = chunk.choices[0].delta
                    if delta.content:
                        yield delta.content
            
            execution_time = time.time() - start_time
            self.metrics["total_execution_time"] += execution_time
            logger.info(f"LLM 스트리밍 호출 완료 (실행 시간: {execution_time:.2f}s)")
        
        except Exception as e:
            self.metrics["llm_errors"] += 1
            execution_time = time.time() - start_time
            self.metrics["total_execution_time"] += execution_time
            logger.error(f"LLM 스트리밍 호출 실패 (실행 시간: {execution_time:.2f}s): {e}")
            raise
    
    def call_llm(
        self,
        messages: List[Dict[str, str]],
        model: str = "gpt-4o",
        temperature: Optional[float] = None,
        max_tokens: Optional[int] = None,
        response_format: Optional[Dict[str, Any]] = None,
        **kwargs
    ) -> str:
        """
        LLM 호출 (캐싱 포함)

        Args:
            messages: 메시지 리스트
            model: 모델명
            temperature: 온도 (None이면 모델 기본값 사용, o1 시리즈는 지원하지 않음)
            max_tokens: 최대 토큰 수
            response_format: 응답 형식
            **kwargs: 추가 파라미터

        Returns:
            LLM 응답 텍스트

        Raises:
            Exception: LLM 호출 실패 시
        """
        start_time = time.time()

        try:
            # 캐시 확인
            if self.enable_cache and self.llm_cache:
                cached_response = self.llm_cache.get(
                    prompt=messages,
                    model=model,
                    temperature=temperature,
                    max_tokens=max_tokens,
                    **kwargs
                )

                if cached_response:
                    self.metrics["llm_cache_hits"] += 1
                    execution_time = time.time() - start_time
                    self.metrics["total_execution_time"] += execution_time
                    logger.info(f"LLM 캐시 히트 (실행 시간: {execution_time:.2f}s)")
                    return cached_response

                self.metrics["llm_cache_misses"] += 1

            # LLM 호출
            self.metrics["llm_calls"] += 1

            call_params = {
                "model": model,
                "messages": messages
            }

            # o1 시리즈 모델은 temperature를 지원하지 않음
            if temperature is not None and not model.startswith("gpt-5"):
                call_params["temperature"] = temperature

            if max_tokens:
                call_params["max_tokens"] = max_tokens

            if response_format:
                call_params["response_format"] = response_format

            call_params.update(kwargs)

            response = self.openai_client.chat.completions.create(**call_params)
            
            # 토큰 사용량 추적
            if hasattr(response, 'usage') and response.usage:
                total_tokens = response.usage.total_tokens
                self.metrics["llm_total_tokens"] += total_tokens
                logger.debug(f"LLM 호출 토큰 사용: {total_tokens}")
            
            # 응답 추출
            content = response.choices[0].message.content.strip()
            
            # 캐시에 저장
            if self.enable_cache and self.llm_cache:
                self.llm_cache.set(
                    prompt=messages,
                    model=model,
                    temperature=temperature,
                    response=content,
                    max_tokens=max_tokens,
                    **kwargs
                )
            
            execution_time = time.time() - start_time
            self.metrics["total_execution_time"] += execution_time
            logger.info(f"LLM 호출 완료 (실행 시간: {execution_time:.2f}s)")
            
            return content
        
        except Exception as e:
            self.metrics["llm_errors"] += 1
            execution_time = time.time() - start_time
            self.metrics["total_execution_time"] += execution_time
            logger.error(f"LLM 호출 실패 (실행 시간: {execution_time:.2f}s): {e}")
            raise
    
    def execute_tool(
        self,
        tool_name: str,
        tool_args: Dict[str, Any],
        retry_on_failure: bool = True
    ) -> ToolResultType:
        """
        툴 실행 (에러 처리 및 재시도 포함)
        
        Args:
            tool_name: 툴 이름
            tool_args: 툴 인자
            retry_on_failure: 실패 시 재시도 여부
            
        Returns:
            툴 실행 결과
            
        Raises:
            Exception: 최대 재시도 후에도 실패 시
        """
        start_time = time.time()
        self.metrics["tool_calls"] += 1
        
        last_error = None
        max_attempts = self.max_retries + 1 if retry_on_failure else 1
        
        for attempt in range(max_attempts):
            try:
                if attempt > 0:
                    self.metrics["tool_retries"] += 1
                    logger.info(f"툴 재시도 {attempt}/{self.max_retries}: {tool_name}")
                
                # 툴 가져오기
                tool = self.tool_registry.get_tool(tool_name)
                if not tool:
                    raise ValueError(f"툴을 찾을 수 없습니다: {tool_name}")
                
                # 파라미터 매핑 (LLM이 잘못된 파라미터를 생성한 경우 수정)
                tool_args = self._map_tool_parameters(tool_name, tool_args)
                
                # 툴 실행 (LangChain BaseTool은 tool_input 파라미터를 받음)
                # tool.run()이 있으면 LangChain 툴, 없으면 커스텀 툴
                if hasattr(tool, 'run'):
                    # LangChain BaseTool
                    result: ToolResultType = tool.run(tool_input=tool_args)
                elif hasattr(tool, 'execute'):
                    # 커스텀 툴 (execute 메서드)
                    result: ToolResultType = tool.execute(**tool_args)
                else:
                    # 직접 호출 가능한 툴
                    result: ToolResultType = tool(**tool_args)
                
                # 성공 여부 확인
                if result.success:
                    self.metrics["tool_successes"] += 1
                    execution_time = time.time() - start_time
                    self.metrics["total_execution_time"] += execution_time
                    logger.info(f"툴 실행 성공: {tool_name} (실행 시간: {execution_time:.2f}s)")
                    return result
                else:
                    # 툴이 실패를 반환한 경우
                    last_error = result.error or "알 수 없는 오류"
                    logger.warning(f"툴 실행 실패 (시도 {attempt + 1}/{max_attempts}): {tool_name} - {last_error}")
                    
                    if attempt < max_attempts - 1:
                        time.sleep(0.5 * (attempt + 1))  # 지수 백오프
                        continue
                    else:
                        # 최대 재시도 도달
                        self.metrics["tool_failures"] += 1
                        execution_time = time.time() - start_time
                        self.metrics["total_execution_time"] += execution_time
                        return result
            
            except Exception as e:
                last_error = str(e)
                logger.error(f"툴 실행 예외 (시도 {attempt + 1}/{max_attempts}): {tool_name} - {e}")
                
                if attempt < max_attempts - 1:
                    time.sleep(0.5 * (attempt + 1))  # 지수 백오프
                    continue
                else:
                    # 최대 재시도 도달
                    self.metrics["tool_failures"] += 1
                    execution_time = time.time() - start_time
                    self.metrics["total_execution_time"] += execution_time
                    raise
        
        # 여기 도달하면 모든 재시도 실패
        self.metrics["tool_failures"] += 1
        execution_time = time.time() - start_time
        self.metrics["total_execution_time"] += execution_time
        raise Exception(f"툴 실행 실패 (최대 재시도 {self.max_retries}회): {tool_name} - {last_error}")
    
    def get_metrics(self) -> Dict[str, Any]:
        """
        메트릭 조회
        
        Returns:
            메트릭 딕셔너리
        """
        metrics = self.metrics.copy()
        
        # 캐시 통계 추가
        if self.enable_cache and self.llm_cache:
            cache_stats = self.llm_cache.get_stats()
            metrics["cache_stats"] = cache_stats
        
        # 계산된 메트릭 추가
        total_llm_requests = metrics["llm_calls"] + metrics["llm_cache_hits"]
        if total_llm_requests > 0:
            metrics["llm_cache_hit_rate"] = metrics["llm_cache_hits"] / total_llm_requests
        else:
            metrics["llm_cache_hit_rate"] = 0.0
        
        total_tool_calls = metrics["tool_successes"] + metrics["tool_failures"]
        if total_tool_calls > 0:
            metrics["tool_success_rate"] = metrics["tool_successes"] / total_tool_calls
        else:
            metrics["tool_success_rate"] = 0.0
        
        return metrics
    
    def reset_metrics(self):
        """메트릭 초기화"""
        self.metrics = {
            "llm_calls": 0,
            "llm_cache_hits": 0,
            "llm_cache_misses": 0,
            "llm_total_tokens": 0,
            "llm_errors": 0,
            "tool_calls": 0,
            "tool_successes": 0,
            "tool_failures": 0,
            "tool_retries": 0,
            "total_execution_time": 0.0
        }
        logger.info("메트릭 초기화 완료")
    
    def clear_cache(self):
        """캐시 삭제"""
        if self.enable_cache and self.llm_cache:
            self.llm_cache.clear()
            logger.info("캐시 삭제 완료")
    
    def _map_tool_parameters(
        self,
        tool_name: str,
        tool_args: Dict[str, Any]
    ) -> Dict[str, Any]:
        """
        툴 파라미터 매핑
        
        LLM이 잘못된 파라미터 이름을 생성한 경우 올바르게 변환합니다.
        
        Args:
            tool_name: 툴 이름
            tool_args: 원본 파라미터
        
        Returns:
            매핑된 파라미터
        """
        # hybrid_search 툴의 경우
        if tool_name == "hybrid_search":
            # 'query' → 'topics' 변환
            if 'query' in tool_args and 'topics' not in tool_args:
                query = tool_args.pop('query')
                # query가 문자열이면 topics 형식으로 변환
                if isinstance(query, str):
                    tool_args['topics'] = [{
                        'topic_name': 'general',
                        'queries': [query]
                    }]
                elif isinstance(query, list):
                    # 리스트면 각 항목을 topics로 변환
                    tool_args['topics'] = [{
                        'topic_name': f'topic_{i}',
                        'queries': [q] if isinstance(q, str) else q
                    } for i, q in enumerate(query)]
                logger.info(f"파라미터 매핑: query → topics")
            
            # 'queries' → 'topics' 변환
            if 'queries' in tool_args and 'topics' not in tool_args:
                queries = tool_args.pop('queries')
                if isinstance(queries, list):
                    tool_args['topics'] = [{
                        'topic_name': 'general',
                        'queries': queries
                    }]
                logger.info(f"파라미터 매핑: queries → topics")
        
        # get_article_by_index 툴의 경우
        elif tool_name == "get_article_by_index":
            # 'articles' → 'article_numbers' 변환
            if 'articles' in tool_args and 'article_numbers' not in tool_args:
                tool_args['article_numbers'] = tool_args.pop('articles')
                logger.info(f"파라미터 매핑: articles → article_numbers")
            
            # 'exhibits' → 'exhibit_numbers' 변환
            if 'exhibits' in tool_args and 'exhibit_numbers' not in tool_args:
                tool_args['exhibit_numbers'] = tool_args.pop('exhibits')
                logger.info(f"파라미터 매핑: exhibits → exhibit_numbers")
        
        # get_article_by_title 툴의 경우
        elif tool_name == "get_article_by_title":
            # 'title' → 'titles' 변환
            if 'title' in tool_args and 'titles' not in tool_args:
                title = tool_args.pop('title')
                tool_args['titles'] = [title] if isinstance(title, str) else title
                logger.info(f"파라미터 매핑: title → titles")
            
            # 'title_keywords' → 'titles' 변환
            if 'title_keywords' in tool_args and 'titles' not in tool_args:
                tool_args['titles'] = tool_args.pop('title_keywords')
                logger.info(f"파라미터 매핑: title_keywords → titles")
            
            # 'keywords' → 'titles' 변환
            if 'keywords' in tool_args and 'titles' not in tool_args:
                tool_args['titles'] = tool_args.pop('keywords')
                logger.info(f"파라미터 매핑: keywords → titles")
        
        return tool_args
