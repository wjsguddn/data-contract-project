"""
Embedding generator service

Generates and stores embeddings for parsed contract documents.
"""

from __future__ import annotations

import logging
import os
from datetime import datetime, timezone
from typing import Any, Dict, List, Tuple, Optional

from openai import AzureOpenAI

from backend.shared.database import SessionLocal, TokenUsage

logger = logging.getLogger("uvicorn.error")


class EmbeddingService:
    """
    임베딩 생성 핵심 서비스

    모든 에이전트에서 공통으로 사용하는 임베딩 생성 로직:
    - Azure OpenAI Client 관리
    - 단일/배치 임베딩 생성
    - 토큰 사용량 추적
    - 텍스트 정규화
    """

    def __init__(
        self,
        api_key: Optional[str] = None,
        azure_endpoint: Optional[str] = None,
        embedding_model: Optional[str] = None,
        api_version: str = "2024-02-01",
    ):
        """Azure OpenAI Client 초기화"""
        self.api_key = api_key or os.getenv("AZURE_OPENAI_API_KEY")
        self.azure_endpoint = azure_endpoint or os.getenv("AZURE_OPENAI_ENDPOINT")
        self.embedding_model = embedding_model or os.getenv(
            "AZURE_EMBEDDING_DEPLOYMENT", "text-embedding-3-large"
        )

        if not self.api_key or not self.azure_endpoint:
            raise ValueError("Azure OpenAI 자격 증명이 설정되지 않았습니다.")

        self.client = AzureOpenAI(
            api_key=self.api_key,
            api_version=api_version,
            azure_endpoint=self.azure_endpoint,
        )

    def get_embedding(
        self,
        text: str,
        contract_id: Optional[str] = None,
        component: str = "embedding_service"
    ) -> List[float]:
        """
        단일 텍스트 임베딩 생성

        Args:
            text: 임베딩할 텍스트
            contract_id: 계약서 ID (토큰 추적용, 선택)
            component: 호출 컴포넌트명 (토큰 추적용)

        Returns:
            임베딩 벡터 (리스트)
        """
        normalized = self._normalize_text(text)
        if not normalized:
            raise ValueError("유효한 텍스트가 없습니다")

        try:
            response = self.client.embeddings.create(
                model=self.embedding_model,
                input=normalized
            )

            # 토큰 추적
            if contract_id and hasattr(response, 'usage') and response.usage:
                self._log_token_usage(
                    contract_id=contract_id,
                    component=component,
                    prompt_tokens=response.usage.prompt_tokens,
                    total_tokens=response.usage.total_tokens,
                    purpose="single_embedding"
                )

            return response.data[0].embedding

        except Exception as e:
            logger.error(f"임베딩 생성 실패: {e}")
            raise

    def get_embeddings_batch(
        self,
        texts: List[str],
        contract_id: Optional[str] = None,
        component: str = "embedding_service",
        batch_size: int = 16,
        purpose: str = "batch_embedding"
    ) -> List[List[float]]:
        """
        배치 임베딩 생성

        Args:
            texts: 임베딩할 텍스트 리스트
            contract_id: 계약서 ID (토큰 추적용)
            component: 호출 컴포넌트명
            batch_size: 배치 크기
            purpose: 사용 목적 (토큰 추적용)

        Returns:
            임베딩 벡터 리스트
        """
        vectors: List[List[float]] = []

        for start in range(0, len(texts), batch_size):
            batch = texts[start : start + batch_size]
            if not batch:
                continue

            response = self.client.embeddings.create(
                model=self.embedding_model,
                input=batch,
            )

            usage = getattr(response, "usage", None)
            if usage:
                preview = batch[0][:50].replace("\n", " ").strip()
                logger.info(
                    "Embedding batch 생성 완료 (contract=%s, size=%d, prompt_tokens=%d, total_tokens=%d, component=%s, purpose=%s, sample=\"%s%s\")",
                    contract_id,
                    len(batch),
                    usage.prompt_tokens,
                    usage.total_tokens,
                    component,
                    purpose,
                    preview,
                    "..." if len(batch[0]) > 50 else "",
                )

                if contract_id:
                    self._log_token_usage(
                        contract_id=contract_id,
                        component=component,
                        prompt_tokens=usage.prompt_tokens,
                        total_tokens=usage.total_tokens,
                        purpose=purpose,
                    )

            vectors.extend([data.embedding for data in response.data])

        return vectors

    def _log_token_usage(
        self,
        contract_id: str,
        component: str,
        prompt_tokens: int,
        total_tokens: int,
        purpose: str,
    ):
        """토큰 사용량 DB 저장 (재시도 로직 포함)"""
        import time
        from sqlalchemy.exc import OperationalError

        max_retries = 3
        retry_delay = 0.1  # 100ms

        for attempt in range(max_retries):
            db = None
            try:
                db = SessionLocal()
                usage = TokenUsage(
                    contract_id=contract_id,
                    component=component,
                    api_type="embedding",
                    model=self.embedding_model,
                    prompt_tokens=prompt_tokens,
                    completion_tokens=0,
                    total_tokens=total_tokens,
                    extra_info={"purpose": purpose},
                )
                db.add(usage)
                db.commit()
                return  # 성공 시 즉시 반환
            except OperationalError as exc:
                if "database is locked" in str(exc) and attempt < max_retries - 1:
                    logger.warning(f"DB 잠금 감지, 재시도 {attempt + 1}/{max_retries}")
                    time.sleep(retry_delay * (attempt + 1))  # 지수 백오프
                    if db:
                        try:
                            db.rollback()
                        except:
                            pass
                else:
                    logger.error(f"토큰 로깅 실패 (최종): %s", exc)
            except Exception as exc:
                logger.error(f"토큰 로깅 실패: %s", exc)
                break
            finally:
                if db:
                    try:
                        db.close()
                    except Exception:
                        pass

    @staticmethod
    def _normalize_text(text: Optional[str]) -> Optional[str]:
        """텍스트 정규화"""
        if not text:
            return None
        normalized = " ".join(str(text).split())
        return normalized if normalized else None


# 싱글톤 인스턴스
_embedding_service = None


def get_embedding_service() -> EmbeddingService:
    """EmbeddingService 싱글톤 반환"""
    global _embedding_service
    if _embedding_service is None:
        _embedding_service = EmbeddingService()
    return _embedding_service


class EmbeddingGenerator:
    """Generates embeddings for user-uploaded contracts."""

    EMBEDDING_VERSION = "v1"
    _BATCH_SIZE = 16

    def __init__(
        self,
        api_key: Optional[str] = None,
        azure_endpoint: Optional[str] = None,
        embedding_model: Optional[str] = None,
        api_version: str = "2024-02-01",
    ):
        self.api_key = api_key or os.getenv("AZURE_OPENAI_API_KEY")
        self.azure_endpoint = azure_endpoint or os.getenv("AZURE_OPENAI_ENDPOINT")
        self.embedding_model = embedding_model or os.getenv(
            "AZURE_EMBEDDING_DEPLOYMENT", "text-embedding-3-large"
        )

        if not self.api_key or not self.azure_endpoint:
            raise ValueError("Azure OpenAI 자격 증명이 설정되지 않았습니다.")

        # EmbeddingService 인스턴스 생성 (공통 임베딩 로직 사용)
        self.embedding_service = EmbeddingService(
            api_key=self.api_key,
            azure_endpoint=self.azure_endpoint,
            embedding_model=self.embedding_model,
            api_version=api_version
        )

    def generate_embeddings(
        self,
        contract_id: str,
        parsed_data: Dict[str, Any],
    ) -> Dict[str, Any]:
        """
        Create embeddings for the parsed contract.

        Args:
            contract_id: Identifier of the contract document.
            parsed_data: Parsed contract structure.

        Returns:
            Embedding payload (stored under parsed_data["embeddings"]).
        """
        if not parsed_data:
            raise ValueError("parsed_data가 비어 있습니다.")

        existing = parsed_data.get("embeddings")
        if existing and self._is_current(existing):
            logger.info("임베딩이 최신 버전이므로 재생성을 건너뜁니다.")
            return existing

        articles = parsed_data.get("articles", [])
        if not articles:
            logger.warning("조항 정보가 없어 임베딩을 생성하지 않습니다.")
            metadata = self._build_metadata()
            return {"metadata": metadata, "article_embeddings": []}

        title_infos: List[Tuple[int, str]] = []
        sub_item_infos: List[Tuple[int, int, str]] = []

        for article in articles:
            article_no = self._safe_int(article.get("number"))
            title_text = EmbeddingService._normalize_text(article.get("text"))

            if article_no is None:
                logger.debug("조항 번호가 없어 임베딩 생성을 건너뜁니다: %s", article)
                continue

            if title_text:
                title_infos.append((article_no, title_text))

            contents = article.get("content", [])
            if not isinstance(contents, list):
                continue

            for idx, sub_item in enumerate(contents, start=1):
                sub_text = self._extract_content_text(sub_item)
                normalized = EmbeddingService._normalize_text(sub_text)
                if not normalized:
                    continue
                sub_item_infos.append((article_no, idx, normalized))

        article_map: Dict[int, Dict[str, Any]] = {}

        if title_infos:
            title_vectors = self.embedding_service.get_embeddings_batch(
                texts=[info[1] for info in title_infos],
                contract_id=contract_id,
                component="embedding_generator",
                batch_size=self._BATCH_SIZE,
                purpose="article_title",
            )
            for info, vector in zip(title_infos, title_vectors):
                article_no = info[0]
                entry = article_map.setdefault(
                    article_no, {"article_no": article_no, "sub_items": []}
                )
                entry["title_embedding"] = vector

        if sub_item_infos:
            sub_vectors = self.embedding_service.get_embeddings_batch(
                texts=[info[2] for info in sub_item_infos],
                contract_id=contract_id,
                component="embedding_generator",
                batch_size=self._BATCH_SIZE,
                purpose="article_sub_item",
            )
            for info, vector in zip(sub_item_infos, sub_vectors):
                article_no, sub_idx, _ = info
                entry = article_map.setdefault(
                    article_no, {"article_no": article_no, "sub_items": []}
                )
                entry["sub_items"].append(
                    {"index": sub_idx, "text_embedding": vector}
                )

        # 정렬 및 후처리
        article_embeddings = []
        for article_no in sorted(article_map.keys()):
            entry = article_map[article_no]
            entry["sub_items"].sort(key=lambda item: item["index"])
            # title_embedding이 없는 경우 None으로 명시
            if "title_embedding" not in entry:
                entry["title_embedding"] = None
            article_embeddings.append(entry)

        embeddings = {
            "metadata": self._build_metadata(),
            "article_embeddings": article_embeddings,
        }

        return embeddings

    def _build_metadata(self) -> Dict[str, Any]:
        now = datetime.now(timezone.utc).isoformat()
        return {
            "model": self.embedding_model,
            "created_at": now,
            "embedding_version": self.EMBEDDING_VERSION,
        }

    def _is_current(self, embeddings: Dict[str, Any]) -> bool:
        metadata = embeddings.get("metadata") if isinstance(embeddings, dict) else None
        if not metadata:
            return False
        version_match = metadata.get("embedding_version") == self.EMBEDDING_VERSION
        model_match = metadata.get("model") == self.embedding_model
        return version_match and model_match

    @staticmethod
    def _safe_int(value: Any) -> Optional[int]:
        try:
            return int(value)
        except (TypeError, ValueError):
            return None

    def _extract_content_text(self, item: Any) -> Optional[str]:
        if isinstance(item, str):
            return item
        if isinstance(item, dict):
            text = item.get("text")
            if text:
                return text
            # 일부 포맷은 내부 content 배열을 갖고 있을 수 있음
            inner = item.get("content")
            if isinstance(inner, list) and inner:
                parts = [self._extract_content_text(sub) or "" for sub in inner]
                joined = " ".join(part for part in parts if part)
                return joined or None
        return None
