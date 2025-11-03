"""
Classification Agent
사용자 계약서의 유형을 5종 표준계약 중 하나로 분류
"""

import logging
import os
from pathlib import Path
from typing import Dict, Any, List, Tuple, Optional
from openai import AzureOpenAI
from backend.shared.core.celery_app import celery_app
from backend.shared.database import SessionLocal, ContractDocument, ClassificationResult, TokenUsage
from backend.shared.services.embedding_loader import EmbeddingLoader

logger = logging.getLogger(__name__)


class ClassificationAgent:
    """
    계약서 분류 에이전트

    Phase 1: 간단한 RAG 기반 유사도 + LLM 판단
    - 5종 표준계약서 각각과 유사도 계산
    - LLM으로 최종 유형 판단
    """

    # 계약 유형 정의
    CONTRACT_TYPES = {
        "provide": "데이터 제공 계약",
        "create": "데이터 생성 계약",
        "process": "데이터 가공 계약",
        "brokerage_provider": "데이터 중개 계약 (제공자용)",
        "brokerage_user": "데이터 중개 계약 (이용자용)"
    }

    # Few-shot 예시 (JSON 출력 형식)
    FEWSHOT_EXAMPLES = """
예시 1: 데이터 제공형 (provide)
---
역할 구조: 데이터제공자가 자신이 보유한 데이터를 데이터이용자에게 제공하거나 접근 권한을 부여하고, 이용자는 그 대가를 지급한다.
핵심 패턴: "대상데이터 제공", "이용허락", "대가 지급", "비밀유지", "반환 또는 폐기"
특징: 새 데이터 생성 없음 (기존 데이터의 제공 중심)
추상 요약: 이미 존재하는 데이터를 일정 조건으로 이용하게 하는 계약. 제공자 → 이용자 방향의 데이터 흐름.

출력:
{
  "type": "provide",
  "confidence": 0.95,
  "reason": "데이터 제공 및 이용허락 구조 중심, 창출·가공 조항 부재"
}



예시 2: 데이터 생성형 (create)
---
역할 구조:
복수의 당사자가 공동으로 데이터를 생성하고, 생성된 데이터(대상데이터 및 파생데이터)의 이용권리, 귀속, 분배를 정한다.

핵심 패턴:
- "공동 생성", "파생데이터", "이용권리 귀속", "이익분배", "공동 저작권"
- 데이터 제공·이용보다 '창출'이 핵심
- 결과물의 소유권·지식재산권 조정이 중요함

추상 요약:
→ 여러 당사자가 협력하여 데이터를 새로 만드는 계약.
→ 데이터 흐름이 쌍방향이며 '공동 창작' 중심.

출력:
{
  "type": "create",
  "confidence": "0.93",
  "reason": "공동 생성과 파생데이터 귀속, 이익분배 조항 존재"
}



예시 3: 데이터 가공형 (process)
---
역할 구조:
데이터이용자가 데이터를 제공하면, 데이터가공사업자가 이를 분석·정제·결합하여 가공데이터를 제작하고 납품한다.

핵심 패턴:
- "가공서비스", "검수", "하자보수", "대가 지급", "가공데이터 귀속"
- 원본 데이터를 입력받아 변형·분석·생성하는 행위
- 공급자는 '가공사업자', 수요자는 '이용자'

추상 요약:
→ 원본 데이터를 입력받아 가공서비스를 수행하는 위탁형 계약.
→ 산출물은 '가공데이터'로 명시됨.

출력:
{
  "type": "process",
  "confidence": "0.96",
  "reason": "대상데이터 제공·가공·검수 및 하자보수 구조 명확"
}



예시 4: 데이터 중개형 - 제공자용 (brokerage_provider)
---
역할 구조:
플랫폼운영자가 데이터 거래 플랫폼을 운영하고, 데이터제공자가 그 플랫폼을 통해 데이터를 판매·유통한다.

핵심 패턴:
- "플랫폼운영자", "정산", "수수료", "플랫폼서비스", "광고·프로모션"
- 제공자는 거래 데이터 등록자, 운영자는 중개자
- "거래 제한", "환불", "청약철회 안내", "정산 유보" 등이 등장

추상 요약:
→ 플랫폼을 매개로 데이터를 판매하는 제공자 중심 계약.
→ 수수료·정산 등 플랫폼 이용 조건 포함.

출력:
{
  "type": "brokerage_provider",
  "confidence": "0.94",
  "reason": "플랫폼 이용 조항과 정산·수수료 구조 명확, 제공자 중심"
}


예시 5: 데이터 중개형 - 이용자용 (brokerage_user)
---
역할 구조:
플랫폼운영자가 데이터 거래 플랫폼을 운영하고, 데이터제공자가 그 플랫폼을 통해 데이터를 판매·유통한다.

핵심 패턴:
- "플랫폼운영자", "정산", "수수료", "플랫폼서비스", "광고·프로모션"
- 제공자는 거래 데이터 등록자, 운영자는 중개자
- "거래 제한", "환불", "청약철회 안내", "정산 유보" 등이 등장

추상 요약:
→ 플랫폼을 매개로 데이터를 판매하는 제공자 중심 계약.
→ 수수료·정산 등 플랫폼 이용 조건 포함.

출력:
{
  "type": "brokerage_user",
  "confidence": "0.94",
  "reason": "플랫폼 이용 조항과 정산·수수료 구조 명확, 제공자 중심"
}


"""

    # Gating threshold
    SCORE_GAP_THRESHOLD = 0.05  # 1위-2위 점수 차이 임계값

    def __init__(
        self,
        api_key: str = None,
        azure_endpoint: str = None,
        embedding_model: str = None,
        chat_model: str = None,
        api_version: str = "2024-02-01"
    ):
        """
        Args:
            api_key: Azure OpenAI API 키
            azure_endpoint: Azure OpenAI 엔드포인트
            embedding_model: 임베딩 모델 deployment 이름
            chat_model: GPT 모델 deployment 이름
            api_version: API 버전
        """
        self.api_key = api_key or os.getenv("AZURE_OPENAI_API_KEY")
        self.azure_endpoint = azure_endpoint or os.getenv("AZURE_OPENAI_ENDPOINT")
        self.embedding_model = embedding_model or os.getenv("AZURE_EMBEDDING_DEPLOYMENT", "text-embedding-3-large")
        self.chat_model = chat_model or os.getenv("AZURE_GPT_DEPLOYMENT", "gpt-4o")

        if not self.api_key or not self.azure_endpoint:
            raise ValueError("Azure OpenAI 자격 증명이 필요합니다")

        self.client = AzureOpenAI(
            api_key=self.api_key,
            api_version=api_version,
            azure_endpoint=self.azure_endpoint
        )

        self.embedding_loader = EmbeddingLoader()

        logger.info("ClassificationAgent 초기화 완료")

    def classify(
        self,
        contract_id: str,
        parsed_data: Dict[str, Any],
        knowledge_base_loader,
        filename: str = None
    ) -> Dict[str, Any]:
        """
        사용자 계약서 분류

        Args:
            contract_id: 계약서 ID
            parsed_data: 파싱된 계약서 데이터
            knowledge_base_loader: 지식베이스 로더 인스턴스
            filename: 계약서 파일명 (분류 참고용)

        Returns:
            {
                "contract_id": str,
                "predicted_type": str,
                "confidence": float,
                "scores": dict,
                "reasoning": str
            }
        """
        try:
            logger.info(f"계약서 분류 시작: {contract_id}")

            # 1. 사용자 계약서에서 주요 조항 추출
            key_articles = self._extract_key_articles(parsed_data)

            # 2. 5종 표준계약서와 유사도 계산
            similarity_scores = self._calculate_similarity_scores(
                key_articles,
                knowledge_base_loader,
                contract_id,
                parsed_data
            )

            # 3. Hybrid Gating을 통한 분류 (임베딩 vs LLM Few-shot)
            result = self._classify_with_gating(
                key_articles,
                similarity_scores,
                contract_id,
                filename
            )

            logger.info(
                f"분류 완료: {contract_id} -> {result['predicted_type']} "
                f"(신뢰도: {result['confidence']:.2%}, 방법: {result.get('classification_method', 'unknown')})"
            )
            return result

        except Exception as e:
            logger.error(f"분류 실패: {contract_id} - {e}")
            raise

    def _extract_key_articles(self, parsed_data: Dict[str, Any]) -> List[Dict[str, str]]:
        """
        주요 조항 추출 (처음 5개 조항)

        Args:
            parsed_data: 파싱된 데이터

        Returns:
            주요 조항 리스트
        """
        articles = parsed_data.get("articles", [])

        # 처음 5개 조항 (목적, 정의, 데이터 범위 등 주요 내용 포함)
        key_articles = []
        for article in articles[:5]:
            text = article.get("text", "")
            content = " ".join(article.get("content", []))

            key_articles.append({
                "number": article.get("number"),
                "title": article.get("title", ""),
                "text": text,
                "content": content,
                "full_text": f"{text} {content}"
            })

        logger.debug(f"주요 조항 {len(key_articles)}개 추출")
        return key_articles

    def _calculate_similarity_scores(
        self,
        key_articles: List[Dict[str, str]],
        knowledge_base_loader,
        contract_id: str = None,
        parsed_data: Optional[Dict[str, Any]] = None
    ) -> Dict[str, float]:
        """Calculate similarity scores against standard contract types."""
        scores: Dict[str, float] = {}

        query_embedding = self._build_query_embedding(
            key_articles=key_articles,
            parsed_data=parsed_data,
            contract_id=contract_id
        )

        if query_embedding is None:
            logger.warning("Failed to build query embedding; returning zero scores.")
            return {contract_type: 0.0 for contract_type in self.CONTRACT_TYPES.keys()}

        for contract_type in self.CONTRACT_TYPES.keys():
            try:
                chunks = knowledge_base_loader.load_chunks(contract_type)

                if not chunks:
                    logger.warning(f"No chunks available: {contract_type}")
                    scores[contract_type] = 0.0
                    continue

                similarities = []
                for chunk in chunks[:20]:
                    chunk_embedding = chunk.get("embedding")
                    if chunk_embedding:
                        sim = self._cosine_similarity(query_embedding, chunk_embedding)
                        similarities.append(sim)

                avg_similarity = sum(similarities) / len(similarities) if similarities else 0.0
                scores[contract_type] = avg_similarity

            except Exception as e:
                logger.error(f"Similarity calculation failed: {contract_type} - {e}")
                scores[contract_type] = 0.0

        logger.debug(f"Similarity scores: {scores}")
        return scores

    def _build_query_embedding(
        self,
        key_articles: List[Dict[str, str]],
        parsed_data: Optional[Dict[str, Any]],
        contract_id: Optional[str],
    ) -> Optional[List[float]]:
        stored_embeddings = self._get_stored_embeddings(contract_id, parsed_data)

        if stored_embeddings:
            combined = self._combine_article_embeddings(stored_embeddings, key_articles)
            if combined:
                return combined
            logger.warning("Stored embeddings incomplete for key articles; falling back to live embedding.")

        query_text = " ".join([art.get("full_text", "") for art in key_articles])
        normalized = " ".join(query_text.split())
        if not normalized:
            return None

        return self._get_embedding(normalized, contract_id)

    def _get_stored_embeddings(
        self,
        contract_id: Optional[str],
        parsed_data: Optional[Dict[str, Any]],
    ) -> Optional[Dict[str, Any]]:
        if isinstance(parsed_data, dict):
            embeddings = parsed_data.get("embeddings")
            if embeddings:
                return embeddings

        if contract_id:
            try:
                return self.embedding_loader.load_embeddings(contract_id)
            except Exception as exc:
                logger.error(f"Failed to load persisted embeddings: {exc}")
        return None

    def _combine_article_embeddings(
        self,
        embeddings_payload: Dict[str, Any],
        key_articles: List[Dict[str, str]],
    ) -> Optional[List[float]]:
        article_entries = embeddings_payload.get("article_embeddings")
        if not article_entries:
            return None

        article_map = {
            entry.get("article_no"): entry
            for entry in article_entries
            if entry.get("article_no") is not None
        }

        aggregated_vectors: List[List[float]] = []

        for article in key_articles:
            article_no = self._safe_int(article.get("number"))
            if article_no is None:
                continue

            entry = article_map.get(article_no)
            if not entry:
                continue

            vectors: List[List[float]] = []
            title_vec = entry.get("title_embedding")
            if title_vec:
                vectors.append(title_vec)

            for sub_item in entry.get("sub_items", []):
                vec = sub_item.get("text_embedding")
                if vec:
                    vectors.append(vec)

            if vectors:
                article_vector = self._average_vectors(vectors)
                if article_vector:
                    aggregated_vectors.append(article_vector)

        if not aggregated_vectors:
            return None

        return self._average_vectors(aggregated_vectors)

    @staticmethod
    def _average_vectors(vectors: List[List[float]]) -> Optional[List[float]]:
        if not vectors:
            return None
        import numpy as np

        array = np.array(vectors, dtype=float)
        if array.size == 0:
            return None
        mean_vector = array.mean(axis=0)
        return mean_vector.tolist()

    @staticmethod
    def _safe_int(value: Any) -> Optional[int]:
        try:
            return int(value)
        except (TypeError, ValueError):
            return None

    def _llm_classify(
        self,
        key_articles: List[Dict[str, str]],
        similarity_scores: Dict[str, float],
        contract_id: str = None,
        filename: str = None
    ) -> Tuple[str, float, str]:
        """
        LLM으로 최종 분류

        Args:
            key_articles: 주요 조항
            similarity_scores: 유사도 점수
            filename: 계약서 파일명 (분류 참고용)

        Returns:
            (predicted_type, confidence, reasoning)
        """
        # 프롬프트 구성
        articles_text = "\n".join([
            f"제{art['number']}조 {art['title']}: {art['content'][:200]}..."
            for art in key_articles
        ])

        scores_text = "\n".join([
            f"- {self.CONTRACT_TYPES[t]}: {score:.3f}"
            for t, score in sorted(similarity_scores.items(), key=lambda x: x[1], reverse=True)
        ])

        # 파일명 정보 추가
        filename_info = f"\n업로드된 파일명: {filename}\n" if filename else ""

        prompt = f"""다음은 사용자가 업로드한 계약서의 주요 조항입니다:{filename_info}

{articles_text}

5종 데이터 표준계약서와의 유사도 점수:
{scores_text}

위 정보를 바탕으로 이 계약서가 어떤 유형인지 판단해주세요.

가능한 유형:
1. provide: 데이터 제공 계약 (데이터 제공자 → 이용자)
2. create: 데이터 생성 계약 (데이터 생성 위탁)
3. process: 데이터 가공 계약 (데이터 가공 위탁)
4. brokerage_provider: 데이터 중개 계약 (제공자용)
5. brokerage_user: 데이터 중개 계약 (이용자용)

**출력 형식** (반드시 JSON만 출력):
{{
  "type": "[provide|create|process|brokerage_provider|brokerage_user]",
  "confidence": [0.0-1.0 사이의 숫자],
  "reason": "[간단한 판단 근거]"
}}
"""

        try:
            response = self.client.chat.completions.create(
                model=self.chat_model,
                messages=[
                    {"role": "system", "content": "당신은 데이터 계약서 분류 전문가입니다."},
                    {"role": "user", "content": prompt}
                ],
                temperature=0.3,
                max_tokens=500,
                response_format={"type": "json_object"}  # JSON 강제
            )

            # 토큰 사용량 로깅
            if hasattr(response, 'usage') and response.usage:
                self._log_token_usage(
                    contract_id=contract_id,
                    api_type="chat_completion",
                    model=self.chat_model,
                    prompt_tokens=response.usage.prompt_tokens,
                    completion_tokens=response.usage.completion_tokens,
                    total_tokens=response.usage.total_tokens,
                    extra_info={"purpose": "contract_classification"}
                )

            answer = response.choices[0].message.content.strip()

            # JSON 파싱 시도
            try:
                import json
                result = json.loads(answer)
                predicted_type = result.get("type")
                confidence = float(result.get("confidence", 0.5))
                reasoning = result.get("reason", "")

                # 유효성 검증
                if predicted_type not in self.CONTRACT_TYPES:
                    raise ValueError(f"Invalid type: {predicted_type}")

                return predicted_type, confidence, reasoning

            except (json.JSONDecodeError, ValueError, KeyError) as parse_error:
                logger.warning(f"JSON 파싱 실패, 텍스트 파싱 폴백: {parse_error}")

                # 폴백: 텍스트 파싱
                predicted_type = None
                confidence = 0.5
                reasoning = answer

                for line in answer.split("\n"):
                    if "type" in line.lower() and ":" in line:
                        type_text = line.split(":", 1)[1].strip().strip('"').strip("'")
                        for t in self.CONTRACT_TYPES.keys():
                            if t in type_text:
                                predicted_type = t
                                break
                    elif "confidence" in line.lower() and ":" in line:
                        try:
                            conf_text = line.split(":", 1)[1].strip()
                            confidence = float(conf_text.split()[0].strip(','))
                        except:
                            pass
                    elif "reason" in line.lower() and ":" in line:
                        reasoning = line.split(":", 1)[1].strip()

                # 파싱 실패 시 유사도 기반
                if not predicted_type:
                    predicted_type = max(similarity_scores.items(), key=lambda x: x[1])[0]
                    confidence = max(similarity_scores.values())
                    reasoning = f"LLM 파싱 실패. 최고 유사도 기반 분류."

                return predicted_type, confidence, reasoning

        except Exception as e:
            logger.error(f"LLM 분류 실패: {e}")
            # Fallback: 유사도 기반
            predicted_type = max(similarity_scores.items(), key=lambda x: x[1])[0]
            confidence = max(similarity_scores.values())
            reasoning = f"LLM 호출 실패. 유사도 기반 분류."
            return predicted_type, confidence, reasoning

    def _get_embedding(self, text: str, contract_id: str = None) -> List[float]:
        """텍스트 임베딩 생성 (EmbeddingService 사용)"""
        from backend.shared.services import get_embedding_service

        return get_embedding_service().get_embedding(
            text=text,
            contract_id=contract_id,
            component="classification_agent"
        )

    def _log_token_usage(
        self,
        contract_id: str,
        api_type: str,
        model: str,
        prompt_tokens: int,
        completion_tokens: int,
        total_tokens: int,
        extra_info: dict = None
    ):
        """토큰 사용량을 DB에 저장 (재시도 로직 포함)"""
        import time
        from sqlalchemy.exc import OperationalError

        max_retries = 3
        retry_delay = 0.1  # 100ms

        for attempt in range(max_retries):
            db = None
            try:
                db = SessionLocal()
                token_usage = TokenUsage(
                    contract_id=contract_id,
                    component="classification_agent",
                    api_type=api_type,
                    model=model,
                    prompt_tokens=prompt_tokens,
                    completion_tokens=completion_tokens,
                    total_tokens=total_tokens,
                    extra_info=extra_info
                )
                db.add(token_usage)
                db.commit()
                logger.info(f"토큰 사용량 로깅: {api_type} - {total_tokens} tokens")
                return  # 성공 시 즉시 반환
            except OperationalError as exc:
                if "database is locked" in str(exc) and attempt < max_retries - 1:
                    logger.warning(
                        f"[ClassificationAgent] DB 잠금 감지, 재시도 {attempt + 1}/{max_retries} "
                        f"(contract_id={contract_id})"
                    )
                    time.sleep(retry_delay * (attempt + 1))  # 지수 백오프
                    if db:
                        try:
                            db.rollback()
                        except:
                            pass
                else:
                    logger.error(f"토큰 사용량 로깅 실패 (최종): {exc}")
                    if db:
                        try:
                            db.rollback()
                        except:
                            pass
                    raise
            except Exception as e:
                logger.error(f"토큰 사용량 로깅 실패: {e}")
                if db:
                    try:
                        db.rollback()
                    except:
                        pass
                break
            finally:
                if db:
                    db.close()

    def _classify_with_gating(
        self,
        key_articles: List[Dict[str, str]],
        similarity_scores: Dict[str, float],
        contract_id: str,
        filename: str = None
    ) -> Dict[str, Any]:
        """
        Hybrid Gating을 통한 분류

        1위-2위 점수 차이가 충분히 크면 임베딩 결과 사용 (LLM 스킵)
        차이가 작으면 LLM Few-shot 분류 수행

        Args:
            key_articles: 주요 조항 리스트
            similarity_scores: 5종 계약 유형별 유사도 점수
            contract_id: 계약서 ID
            filename: 파일명 (옵션)

        Returns:
            분류 결과 딕셔너리
        """
        # 1위와 2위 점수 차이 계산
        sorted_scores = sorted(similarity_scores.items(), key=lambda x: x[1], reverse=True)
        top1_type, top1_score = sorted_scores[0]
        top2_type, top2_score = sorted_scores[1] if len(sorted_scores) > 1 else (None, 0.0)

        score_gap = top1_score - top2_score

        # Gating 임계값 확인
        if score_gap >= self.SCORE_GAP_THRESHOLD:
            # 명확함 → 임베딩 결과 사용 (LLM 호출 없음)
            logger.info(f"✓ 임베딩 기반 결정 (gap={score_gap:.3f}, top1={top1_type}:{top1_score:.3f})")
            return {
                "contract_id": contract_id,
                "predicted_type": top1_type,
                "confidence": top1_score,
                "scores": similarity_scores,
                "reasoning": f"임베딩 유사도 차이가 충분함 (gap={score_gap:.3f})",
                "classification_method": "embedding",
                "score_gap": score_gap
            }
        else:
            # 애매함 → LLM Few-shot 호출
            logger.info(f"⚠ LLM 정밀 분류 필요 (gap={score_gap:.3f}, top1={top1_type}:{top1_score:.3f}, top2={top2_type}:{top2_score:.3f})")
            predicted_type, confidence, reasoning = self._llm_classify_with_fewshot(
                key_articles,
                similarity_scores,
                contract_id,
                filename
            )
            return {
                "contract_id": contract_id,
                "predicted_type": predicted_type,
                "confidence": confidence,
                "scores": similarity_scores,
                "reasoning": reasoning,
                "classification_method": "llm_fewshot",
                "score_gap": score_gap
            }

    def _llm_classify_with_fewshot(
        self,
        key_articles: List[Dict[str, str]],
        similarity_scores: Dict[str, float],
        contract_id: str,
        filename: str = None
    ) -> Tuple[str, float, str]:
        """
        Few-shot 프롬프트를 사용한 LLM 분류 (JSON 모드)

        Args:
            key_articles: 주요 조항 리스트
            similarity_scores: 유사도 점수
            contract_id: 계약서 ID
            filename: 파일명 (옵션)

        Returns:
            (predicted_type, confidence, reasoning) 튜플
        """
        try:
            # 조항 텍스트 구성
            articles_text = ""
            for i, art in enumerate(key_articles, 1):
                title = art.get("title", "")
                text = art.get("text", "")
                content_preview = art.get("content", [""])[0] if art.get("content") else ""

                articles_text += f"[조항 {i}] 제목: {title}\n"
                if text:
                    articles_text += f"  조문: {text}\n"
                if content_preview:
                    preview = content_preview[:200] + "..." if len(content_preview) > 200 else content_preview
                    articles_text += f"  내용: {preview}\n"
                articles_text += "\n"

            # 유사도 점수 텍스트
            scores_text = "\n".join([
                f"- {self.CONTRACT_TYPES[t]}: {score:.3f}"
                for t, score in sorted(similarity_scores.items(), key=lambda x: x[1], reverse=True)
            ])

            # 파일명 정보
            filename_info = f" (파일명: {filename})" if filename else ""

            # Few-shot 프롬프트 구성
            prompt = f"""당신은 데이터 계약서 분류 전문가입니다.

다음은 5가지 데이터 계약 유형의 특징과 출력 예시입니다:

{self.FEWSHOT_EXAMPLES}

---

이제 사용자가 업로드한 계약서의 주요 내용을 분석해주세요:{filename_info}

{articles_text}

임베딩 유사도 점수 (참고용):
{scores_text}

**분석 지침**:
1. 역할 구조 파악 (누가 누구에게 무엇을 제공/위탁/중개하는가)
2. 핵심 패턴 찾기 (제공, 생성, 가공, 중개 관련 키워드)
3. 데이터 흐름 확인 (단방향/양방향, 창출 여부)

**출력 형식** (반드시 JSON만 출력):
{{
  "type": "[provide|create|process|brokerage_provider|brokerage_user]",
  "confidence": [0.0-1.0 사이의 숫자],
  "reason": "[역할 구조와 핵심 패턴 기반 판단 근거]"
}}
"""

            # LLM 호출 (JSON 모드)
            response = self.client.chat.completions.create(
                model=self.chat_model,
                messages=[
                    {"role": "system", "content": "당신은 데이터 계약서 분류 전문가입니다."},
                    {"role": "user", "content": prompt}
                ],
                temperature=0.2,
                max_tokens=600,
                response_format={"type": "json_object"}  # JSON 강제
            )

            # 토큰 사용량 로깅
            self._log_token_usage(
                contract_id=contract_id,
                api_type="chat_completion",
                model=self.chat_model,
                prompt_tokens=response.usage.prompt_tokens,
                completion_tokens=response.usage.completion_tokens,
                total_tokens=response.usage.total_tokens,
                extra_info={"purpose": "classification_fewshot"}
            )

            # 응답 파싱 (JSON 우선)
            answer = response.choices[0].message.content.strip()

            try:
                import json
                result = json.loads(answer)
                predicted_type = result.get("type")
                confidence = float(result.get("confidence", 0.5))
                reasoning = result.get("reason", "")

                # 유효성 검증
                if predicted_type not in self.CONTRACT_TYPES:
                    raise ValueError(f"Invalid type: {predicted_type}")

                return predicted_type, confidence, reasoning

            except (json.JSONDecodeError, ValueError, KeyError) as parse_error:
                logger.warning(f"JSON 파싱 실패, 텍스트 파싱 시도: {parse_error}")

                # 폴백: 텍스트 파싱
                predicted_type = None
                confidence = 0.5
                reasoning = answer

                for line in answer.split("\n"):
                    if "type" in line.lower() and ":" in line:
                        type_text = line.split(":", 1)[1].strip().strip('"').strip("'")
                        for t in self.CONTRACT_TYPES.keys():
                            if t in type_text:
                                predicted_type = t
                                break
                    elif "confidence" in line.lower() and ":" in line:
                        try:
                            conf_text = line.split(":", 1)[1].strip()
                            confidence = float(conf_text.split()[0].strip(','))
                        except:
                            pass
                    elif "reason" in line.lower() and ":" in line:
                        reasoning = line.split(":", 1)[1].strip()

                # 파싱 실패 시 폴백
                if not predicted_type:
                    predicted_type = max(similarity_scores.items(), key=lambda x: x[1])[0]
                    confidence = max(similarity_scores.values())
                    reasoning = f"LLM 파싱 실패. 최고 유사도 기반 분류."

                return predicted_type, confidence, reasoning

        except Exception as e:
            logger.error(f"LLM Few-shot 분류 실패: {e}")
            # Fallback: 유사도 기반
            predicted_type = max(similarity_scores.items(), key=lambda x: x[1])[0]
            confidence = max(similarity_scores.values())
            reasoning = f"LLM 호출 실패. 유사도 기반 분류."
            return predicted_type, confidence, reasoning

    def _cosine_similarity(self, vec1: List[float], vec2: List[float]) -> float:
        """코사인 유사도 계산"""
        import numpy as np

        vec1 = np.array(vec1)
        vec2 = np.array(vec2)

        dot_product = np.dot(vec1, vec2)
        norm1 = np.linalg.norm(vec1)
        norm2 = np.linalg.norm(vec2)

        if norm1 == 0 or norm2 == 0:
            return 0.0

        return float(dot_product / (norm1 * norm2))


# Celery Task 정의
@celery_app.task(name="classification.classify_contract", queue="classification")
def classify_contract_task(contract_id: str):
    """
    Celery Task: 계약서 분류

    Args:
        contract_id: 계약서 ID

    Returns:
        분류 결과
    """
    db = SessionLocal()
    try:
        logger.info(f"[Celery Task] 계약서 분류 시작: {contract_id}")

        # DB에서 계약서 조회
        contract = db.query(ContractDocument).filter(
            ContractDocument.contract_id == contract_id
        ).first()

        if not contract:
            raise ValueError(f"계약서를 찾을 수 없습니다: {contract_id}")

        if not contract.parsed_data:
            raise ValueError(f"파싱된 데이터가 없습니다: {contract_id}")

        # Classification Agent 실행
        agent = ClassificationAgent()
        from backend.shared.services import get_knowledge_base_loader
        kb_loader = get_knowledge_base_loader()

        result = agent.classify(
            contract_id=contract_id,
            parsed_data=contract.parsed_data,
            knowledge_base_loader=kb_loader,
            filename=contract.filename
        )

        # 분류 결과 DB 저장
        classification = ClassificationResult(
            contract_id=contract_id,
            predicted_type=result["predicted_type"],
            confidence=result["confidence"],
            scores=result["scores"],
            reasoning=result["reasoning"],
            confirmed_type=result["predicted_type"]
        )
        db.add(classification)

        # 계약서 상태 업데이트
        contract.status = "classified"
        db.commit()

        logger.info(f"[Celery Task] 분류 완료 및 저장: {contract_id}")

        return {
            "success": True,
            "contract_id": contract_id,
            "predicted_type": result["predicted_type"],
            "confidence": result["confidence"]
        }

    except Exception as e:
        db.rollback()
        logger.error(f"[Celery Task] 분류 실패: {contract_id} - {e}")

        # 계약서 상태를 error로 업데이트
        contract = db.query(ContractDocument).filter(
            ContractDocument.contract_id == contract_id
        ).first()
        if contract:
            contract.status = "classification_error"
            db.commit()

        raise

    finally:
        db.close()
