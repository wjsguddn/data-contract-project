
# 임베딩 생성 모듈
from typing import List, Dict, Any
import numpy as np
import json
import logging
from pathlib import Path
import faiss
from openai import AzureOpenAI

logger = logging.getLogger(__name__)


class TextEmbedder:
    """
    텍스트 임베딩 생성 클래스
    chunks.json 파일을 읽어서 text_norm을 임베딩하고 FAISS 인덱스로 저장
    """

    def __init__(
        self,
        api_key: str,
        azure_endpoint: str,
        model: str = "text-embedding-3-large",
        api_version: str = "2024-02-01"
    ):
        """
        Args:
            api_key: Azure OpenAI API 키
            azure_endpoint: Azure OpenAI 엔드포인트
            model: 사용할 임베딩 모델 (Azure deployment name)
            api_version: Azure OpenAI API 버전
        """
        self.client = AzureOpenAI(
            api_key=api_key,
            api_version=api_version,
            azure_endpoint=azure_endpoint
        )
        self.model = model

    def process_file(self, input_path: Path, faiss_output_dir: Path, whoosh_output_dir: Path) -> bool:
        """
        chunks.json 파일을 처리하여 FAISS 및 Whoosh 인덱스 생성

        Args:
            input_path: 입력 chunks.json 파일 경로
            faiss_output_dir: FAISS 인덱스 출력 디렉토리
            whoosh_output_dir: Whoosh 인덱스 출력 디렉토리

        Returns:
            성공 여부
        """
        try:
            # 1. 파일 읽기
            logger.info(f"  파일 읽기: {input_path.name}")
            with open(input_path, 'r', encoding='utf-8') as f:
                all_chunks = json.load(f)

            if not isinstance(all_chunks, list):
                logger.error("   [ERROR] chunks는 리스트 형식이어야 합니다")
                return False

            logger.info(f"  총 {len(all_chunks)}개 청크 (필터링 전)")

            # 2. 별지 항목 제외 (global_id에서 ':ex:' 패턴으로 판별)
            chunks = [
                chunk for chunk in all_chunks
                if ':ex:' not in chunk.get('global_id', '')
            ]

            excluded_count = len(all_chunks) - len(chunks)
            logger.info(f"  별지 항목 {excluded_count}개 제외")
            logger.info(f"  임베딩 대상: {len(chunks)}개 청크")

            if not chunks:
                logger.error("   [ERROR] 임베딩할 청크가 없습니다")
                return False

            # 2. 이중 임베딩 생성 (text_norm, title)
            logger.info("\n  [1/3] 이중 임베딩 생성 중 (text_norm, title)...")
            text_embeddings, title_embeddings = self.create_dual_embeddings(chunks)

            logger.info(f"    text_norm 임베딩 수: {len([e for e in text_embeddings if e is not None])}")
            logger.info(f"    title 임베딩 수: {len([e for e in title_embeddings if e is not None])}")

            # 3. FAISS 인덱스 저장 (두 개의 인덱스)
            logger.info("\n  [2/3] FAISS 인덱스 생성 중 (text, title)...")
            self.save_dual_faiss_indexes(text_embeddings, title_embeddings, input_path.name, faiss_output_dir)

            # 4. Whoosh 인덱스 생성 (기존 로직 유지)
            logger.info("\n  [3/3] Whoosh 인덱스 생성 중...")
            self.save_to_whoosh(chunks, input_path.name, whoosh_output_dir)

            logger.info("\n     임베딩 및 인덱싱 완료")
            return True

        except Exception as e:
            logger.error(f"   [ERROR] 처리 실패: {e}")
            import traceback
            traceback.print_exc()
            return False

    def create_embeddings(self, chunks: List[Dict]) -> List[Any]:
        """
        청크 리스트에 대해 임베딩 생성
        각 청크의 text_norm 필드를 사용

        Args:
            chunks: 청크 리스트

        Returns:
            임베딩 리스트 (실패한 경우 None 포함)
        """
        embeddings = []

        for i, chunk in enumerate(chunks):
            try:
                # text_norm 필드 사용
                text_norm = chunk.get('text_norm', '')
                if not text_norm or not text_norm.strip():
                    logger.warning(f"    [WARNING] 청크 {i}의 text_norm이 비어있습니다")
                    embeddings.append(None)
                    continue

                response = self.client.embeddings.create(
                    model=self.model,
                    input=text_norm
                )
                embedding = response.data[0].embedding
                embeddings.append(embedding)

                if (i + 1) % 10 == 0:
                    logger.info(f"    진행: {i + 1}/{len(chunks)}")

            except Exception as e:
                logger.error(f"    [ERROR] 청크 {i} 임베딩 실패: {e}")
                embeddings.append(None)

        return embeddings

    def create_dual_embeddings(self, chunks: List[Dict]) -> tuple:
        """
        청크 리스트에 대해 text_norm과 title을 각각 임베딩 생성
        배치 처리로 API 호출 최적화

        Args:
            chunks: 청크 리스트

        Returns:
            (text_norm_embeddings, title_embeddings) 튜플
            각 리스트는 실패한 경우 None 포함
        """
        text_embeddings = []
        title_embeddings = []

        # 배치 처리를 위한 텍스트 수집
        batch_size = 100  # Azure OpenAI 배치 제한
        
        for batch_start in range(0, len(chunks), batch_size):
            batch_end = min(batch_start + batch_size, len(chunks))
            batch_chunks = chunks[batch_start:batch_end]
            
            # text_norm 배치 처리
            text_batch = []
            text_indices = []
            for i, chunk in enumerate(batch_chunks):
                text_norm = chunk.get('text_norm', '')
                if text_norm and text_norm.strip():
                    text_batch.append(text_norm)
                    text_indices.append(i)
            
            # title 배치 처리
            title_batch = []
            title_indices = []
            for i, chunk in enumerate(batch_chunks):
                title = chunk.get('title', '')
                if title and title.strip():
                    title_batch.append(title)
                    title_indices.append(i)
            
            # text_norm 임베딩 생성
            batch_text_embeddings = [None] * len(batch_chunks)
            if text_batch:
                try:
                    response = self.client.embeddings.create(
                        model=self.model,
                        input=text_batch
                    )
                    for idx, emb_data in enumerate(response.data):
                        batch_text_embeddings[text_indices[idx]] = emb_data.embedding
                except Exception as e:
                    logger.error(f"    [ERROR] text_norm 배치 임베딩 실패 (batch {batch_start}-{batch_end}): {e}")
                    # 개별 처리로 폴백
                    for idx in text_indices:
                        try:
                            text_norm = batch_chunks[idx].get('text_norm', '')
                            response = self.client.embeddings.create(
                                model=self.model,
                                input=text_norm
                            )
                            batch_text_embeddings[idx] = response.data[0].embedding
                        except Exception as e2:
                            logger.error(f"    [ERROR] 청크 {batch_start + idx} text_norm 임베딩 실패: {e2}")
            
            # title 임베딩 생성
            batch_title_embeddings = [None] * len(batch_chunks)
            if title_batch:
                try:
                    response = self.client.embeddings.create(
                        model=self.model,
                        input=title_batch
                    )
                    for idx, emb_data in enumerate(response.data):
                        batch_title_embeddings[title_indices[idx]] = emb_data.embedding
                except Exception as e:
                    logger.error(f"    [ERROR] title 배치 임베딩 실패 (batch {batch_start}-{batch_end}): {e}")
                    # 개별 처리로 폴백
                    for idx in title_indices:
                        try:
                            title = batch_chunks[idx].get('title', '')
                            response = self.client.embeddings.create(
                                model=self.model,
                                input=title
                            )
                            batch_title_embeddings[idx] = response.data[0].embedding
                        except Exception as e2:
                            logger.error(f"    [ERROR] 청크 {batch_start + idx} title 임베딩 실패: {e2}")
            
            # 결과 추가
            text_embeddings.extend(batch_text_embeddings)
            title_embeddings.extend(batch_title_embeddings)
            
            # 진행 상황 로그
            logger.info(f"    진행: {batch_end}/{len(chunks)} (text: {len([e for e in batch_text_embeddings if e])}, title: {len([e for e in batch_title_embeddings if e])})")
        
        # 빈 문자열 경고
        empty_text_count = sum(1 for e in text_embeddings if e is None)
        empty_title_count = sum(1 for e in title_embeddings if e is None)
        
        if empty_text_count > 0:
            logger.warning(f"    [WARNING] {empty_text_count}개 청크의 text_norm이 비어있거나 임베딩 실패")
        if empty_title_count > 0:
            logger.warning(f"    [WARNING] {empty_title_count}개 청크의 title이 비어있거나 임베딩 실패")
        
        return (text_embeddings, title_embeddings)

    def save_to_faiss(
        self,
        embeddings: List[List[float]],
        chunks: List[Dict],
        source_filename: str,
        output_dir: Path
    ):
        """
        FAISS 인덱스 저장

        Args:
            embeddings: 임베딩 벡터 리스트
            chunks: 청크 데이터 리스트 (사용하지 않음, 호환성 유지)
            source_filename: 원본 파일명
            output_dir: 출력 디렉토리
        """
        # 출력 디렉토리 생성
        output_dir.mkdir(parents=True, exist_ok=True)

        # 임베딩을 numpy 배열로 변환
        embeddings_array = np.array(embeddings, dtype=np.float32)
        dimension = embeddings_array.shape[1]

        logger.info(f"    임베딩 차원: {dimension}")
        logger.info(f"    벡터 수: {len(embeddings_array)}")

        # FAISS 인덱스 생성 (L2 거리 사용)
        index = faiss.IndexFlatL2(dimension)
        index.add(embeddings_array)

        # 파일명에서 확장자 제거
        base_name = source_filename.replace('_chunks.json', '')

        # FAISS 인덱스 저장
        index_path = output_dir / f"{base_name}.faiss"
        faiss.write_index(index, str(index_path))
        logger.info(f"    FAISS 인덱스 저장: {index_path}")

    def save_dual_faiss_indexes(
        self,
        text_norm_embeddings: List[List[float]],
        title_embeddings: List[List[float]],
        source_filename: str,
        output_dir: Path
    ):
        """
        두 개의 FAISS 인덱스 저장 (text_norm, title)

        Args:
            text_norm_embeddings: text_norm 임베딩 벡터 리스트
            title_embeddings: title 임베딩 벡터 리스트
            source_filename: 원본 파일명
            output_dir: 출력 디렉토리
        """
        try:
            # 출력 디렉토리 생성
            output_dir.mkdir(parents=True, exist_ok=True)

            # 파일명에서 확장자 제거
            base_name = source_filename.replace('_chunks.json', '')

            # text_norm 인덱스 저장
            valid_text_embeddings = [e for e in text_norm_embeddings if e is not None]
            if valid_text_embeddings:
                text_array = np.array(valid_text_embeddings, dtype=np.float32)
                text_dimension = text_array.shape[1]
                
                logger.info(f"    text_norm 임베딩 차원: {text_dimension}")
                logger.info(f"    text_norm 벡터 수: {len(text_array)}")
                
                text_index = faiss.IndexFlatL2(text_dimension)
                text_index.add(text_array)
                
                text_index_path = output_dir / f"{base_name}_text.faiss"
                faiss.write_index(text_index, str(text_index_path))
                logger.info(f"    text_norm FAISS 인덱스 저장: {text_index_path}")
            else:
                error_msg = f"text_norm 임베딩이 없어 인덱스를 생성할 수 없습니다: {base_name}"
                logger.error(f"    [ERROR] {error_msg}")
                raise ValueError(error_msg)

            # title 인덱스 저장
            valid_title_embeddings = [e for e in title_embeddings if e is not None]
            if valid_title_embeddings:
                title_array = np.array(valid_title_embeddings, dtype=np.float32)
                title_dimension = title_array.shape[1]
                
                logger.info(f"    title 임베딩 차원: {title_dimension}")
                logger.info(f"    title 벡터 수: {len(title_array)}")
                
                title_index = faiss.IndexFlatL2(title_dimension)
                title_index.add(title_array)
                
                title_index_path = output_dir / f"{base_name}_title.faiss"
                faiss.write_index(title_index, str(title_index_path))
                logger.info(f"    title FAISS 인덱스 저장: {title_index_path}")
            else:
                error_msg = f"title 임베딩이 없어 인덱스를 생성할 수 없습니다: {base_name}"
                logger.error(f"    [ERROR] {error_msg}")
                raise ValueError(error_msg)

        except Exception as e:
            error_msg = f"FAISS 인덱스 저장 실패 ({base_name}): {e}"
            logger.error(f"    [ERROR] {error_msg}")
            raise RuntimeError(error_msg) from e

    def save_to_whoosh(
        self,
        chunks: List[Dict],
        source_filename: str,
        output_dir: Path
    ):
        """
        Whoosh 인덱스 저장

        Args:
            chunks: 청크 데이터 리스트
            source_filename: 원본 파일명
            output_dir: 출력 디렉토리
        """
        from ingestion.indexers.whoosh_indexer import WhooshIndexer

        # 파일명에서 확장자 제거
        base_name = source_filename.replace('_chunks.json', '')

        # Whoosh 인덱스 디렉토리 (파일별로 별도 디렉토리)
        whoosh_index_dir = output_dir / base_name

        # WhooshIndexer 초기화 및 빌드
        indexer = WhooshIndexer(whoosh_index_dir)
        indexer.build(chunks)

        logger.info(f"    Whoosh 인덱스 저장: {whoosh_index_dir}")

