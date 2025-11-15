"""
LLMCache - LLM 응답 캐싱

프롬프트 기반으로 LLM 응답을 캐싱하여 중복 호출을 방지합니다.
메모리 캐시와 Redis 캐시를 지원합니다.
"""

import hashlib
import json
import logging
import time
from typing import Optional, Dict, Any, Union
from datetime import datetime, timedelta

logger = logging.getLogger(__name__)


class LLMCache:
    """
    LLM 응답 캐싱 클래스
    
    프롬프트를 MD5 해시로 변환하여 캐시 키로 사용합니다.
    메모리 캐시(dict)와 Redis 캐시를 지원합니다.
    """
    
    def __init__(
        self,
        use_redis: bool = False,
        redis_client=None,
        ttl_seconds: int = 3600,  # 기본 1시간
        max_memory_size: int = 1000  # 메모리 캐시 최대 항목 수
    ):
        """
        초기화
        
        Args:
            use_redis: Redis 캐시 사용 여부
            redis_client: Redis 클라이언트 (use_redis=True인 경우 필수)
            ttl_seconds: 캐시 TTL (초)
            max_memory_size: 메모리 캐시 최대 크기
        """
        self.use_redis = use_redis
        self.redis_client = redis_client
        self.ttl_seconds = ttl_seconds
        self.max_memory_size = max_memory_size
        
        # 메모리 캐시 (항상 사용)
        self._memory_cache: Dict[str, Dict[str, Any]] = {}
        
        # 통계
        self.stats = {
            "hits": 0,
            "misses": 0,
            "memory_hits": 0,
            "redis_hits": 0,
            "evictions": 0
        }
        
        if use_redis and not redis_client:
            logger.warning("Redis 사용이 활성화되었으나 redis_client가 제공되지 않음. 메모리 캐시만 사용합니다.")
            self.use_redis = False
        
        logger.info(f"LLMCache 초기화 완료 (Redis: {self.use_redis}, TTL: {ttl_seconds}s)")
    
    def _generate_cache_key(
        self,
        prompt: Union[str, list],
        model: str,
        temperature: float,
        **kwargs
    ) -> str:
        """
        캐시 키 생성 (MD5 해시)
        
        Args:
            prompt: 프롬프트 (문자열 또는 메시지 리스트)
            model: 모델명
            temperature: 온도
            **kwargs: 추가 파라미터
            
        Returns:
            MD5 해시 문자열
        """
        # 프롬프트를 문자열로 변환
        if isinstance(prompt, list):
            prompt_str = json.dumps(prompt, ensure_ascii=False, sort_keys=True)
        else:
            prompt_str = str(prompt)
        
        # 캐시 키 구성 요소
        key_components = {
            "prompt": prompt_str,
            "model": model,
            "temperature": temperature,
            **kwargs
        }
        
        # JSON 직렬화 후 MD5 해시
        key_str = json.dumps(key_components, ensure_ascii=False, sort_keys=True)
        cache_key = hashlib.md5(key_str.encode('utf-8')).hexdigest()
        
        return cache_key
    
    def get(
        self,
        prompt: Union[str, list],
        model: str,
        temperature: float,
        **kwargs
    ) -> Optional[str]:
        """
        캐시에서 응답 조회
        
        Args:
            prompt: 프롬프트
            model: 모델명
            temperature: 온도
            **kwargs: 추가 파라미터
            
        Returns:
            캐시된 응답 (없으면 None)
        """
        cache_key = self._generate_cache_key(prompt, model, temperature, **kwargs)
        
        # 1. 메모리 캐시 확인
        if cache_key in self._memory_cache:
            entry = self._memory_cache[cache_key]
            
            # TTL 확인
            if self._is_expired(entry):
                del self._memory_cache[cache_key]
                logger.debug(f"메모리 캐시 만료: {cache_key[:8]}...")
            else:
                self.stats["hits"] += 1
                self.stats["memory_hits"] += 1
                logger.info(f"메모리 캐시 히트: {cache_key[:8]}...")
                return entry["response"]
        
        # 2. Redis 캐시 확인 (활성화된 경우)
        if self.use_redis and self.redis_client:
            try:
                redis_key = f"llm_cache:{cache_key}"
                cached_data = self.redis_client.get(redis_key)
                
                if cached_data:
                    entry = json.loads(cached_data)
                    response = entry.get("response")
                    
                    # 메모리 캐시에도 저장 (빠른 재접근)
                    self._memory_cache[cache_key] = entry
                    self._evict_if_needed()
                    
                    self.stats["hits"] += 1
                    self.stats["redis_hits"] += 1
                    logger.info(f"Redis 캐시 히트: {cache_key[:8]}...")
                    return response
            except Exception as e:
                logger.error(f"Redis 캐시 조회 실패: {e}")
        
        # 캐시 미스
        self.stats["misses"] += 1
        logger.debug(f"캐시 미스: {cache_key[:8]}...")
        return None
    
    def set(
        self,
        prompt: Union[str, list],
        model: str,
        temperature: float,
        response: str,
        **kwargs
    ):
        """
        캐시에 응답 저장
        
        Args:
            prompt: 프롬프트
            model: 모델명
            temperature: 온도
            response: LLM 응답
            **kwargs: 추가 파라미터
        """
        cache_key = self._generate_cache_key(prompt, model, temperature, **kwargs)
        
        entry = {
            "response": response,
            "timestamp": time.time(),
            "model": model,
            "temperature": temperature
        }
        
        # 1. 메모리 캐시에 저장
        self._memory_cache[cache_key] = entry
        self._evict_if_needed()
        
        # 2. Redis 캐시에 저장 (활성화된 경우)
        if self.use_redis and self.redis_client:
            try:
                redis_key = f"llm_cache:{cache_key}"
                self.redis_client.setex(
                    redis_key,
                    self.ttl_seconds,
                    json.dumps(entry, ensure_ascii=False)
                )
                logger.debug(f"Redis 캐시 저장: {cache_key[:8]}...")
            except Exception as e:
                logger.error(f"Redis 캐시 저장 실패: {e}")
        
        logger.debug(f"캐시 저장 완료: {cache_key[:8]}...")
    
    def _is_expired(self, entry: Dict[str, Any]) -> bool:
        """
        캐시 항목이 만료되었는지 확인
        
        Args:
            entry: 캐시 항목
            
        Returns:
            만료 여부
        """
        timestamp = entry.get("timestamp", 0)
        age = time.time() - timestamp
        return age > self.ttl_seconds
    
    def _evict_if_needed(self):
        """
        메모리 캐시 크기가 최대치를 초과하면 오래된 항목 제거 (LRU)
        """
        if len(self._memory_cache) <= self.max_memory_size:
            return
        
        # 타임스탬프 기준 정렬 (오래된 순)
        sorted_items = sorted(
            self._memory_cache.items(),
            key=lambda x: x[1].get("timestamp", 0)
        )
        
        # 오래된 항목부터 제거 (10% 제거)
        num_to_evict = max(1, len(self._memory_cache) // 10)
        for i in range(num_to_evict):
            key, _ = sorted_items[i]
            del self._memory_cache[key]
            self.stats["evictions"] += 1
        
        logger.info(f"메모리 캐시 정리: {num_to_evict}개 항목 제거")
    
    def clear(self):
        """모든 캐시 삭제"""
        self._memory_cache.clear()
        
        if self.use_redis and self.redis_client:
            try:
                # Redis에서 llm_cache:* 패턴의 모든 키 삭제
                keys = self.redis_client.keys("llm_cache:*")
                if keys:
                    self.redis_client.delete(*keys)
                logger.info(f"Redis 캐시 삭제: {len(keys)}개 키")
            except Exception as e:
                logger.error(f"Redis 캐시 삭제 실패: {e}")
        
        logger.info("캐시 전체 삭제 완료")
    
    def get_stats(self) -> Dict[str, Any]:
        """
        캐시 통계 조회
        
        Returns:
            {
                "hits": int,
                "misses": int,
                "memory_hits": int,
                "redis_hits": int,
                "evictions": int,
                "hit_rate": float,
                "memory_size": int
            }
        """
        total_requests = self.stats["hits"] + self.stats["misses"]
        hit_rate = self.stats["hits"] / total_requests if total_requests > 0 else 0.0
        
        return {
            **self.stats,
            "hit_rate": hit_rate,
            "memory_size": len(self._memory_cache)
        }
