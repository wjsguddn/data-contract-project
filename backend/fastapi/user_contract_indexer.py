"""
사용자 계약서 인덱서

사용자가 업로드한 계약서에 대해 FAISS + Whoosh 인덱스를 생성합니다.
표준계약서와 달리 업로드 시 실시간으로 인덱스를 생성합니다.
"""

import json
import logging
import numpy as np
from pathlib import Path
from typing import Dict, Any, List, Tuple, Optional

from whoosh.fields import Schema, TEXT, ID, STORED
from whoosh.index import create_in, open_dir, exists_in
from whoosh.analysis import Tokenizer, Token
from whoosh.analysis import StandardAnalyzer

from backend.shared.database import SessionLocal, ContractDocument

logger = logging.getLogger("uvicorn.error")


class KoreanAnalyzer(Tokenizer):
    """
    한국어 형태소 분석기 (Mecab 기반)

    ingestion.indexers.whoosh_indexer.KoreanAnalyzer와 동일한 로직
    """

    def __init__(self):
        """형태소 분석기 초기화"""
        self._mecab = None
        self._dicpath = None
        self._init_mecab()

    def _init_mecab(self):
        """Mecab 초기화 (lazy loading)"""
        if self._mecab is not None:
            return

        try:
            from konlpy.tag import Mecab
            import os
            import site

            # mecab-ko-dic-msvc 사전 경로 찾기
            dicpath = None

            for site_path in site.getsitepackages():
                potential_dicpath = os.path.join(site_path, 'mecab-ko-dic')
                if os.path.exists(potential_dicpath):
                    dicpath = potential_dicpath
                    logger.info(f"✓ mecab-ko-dic 사전 경로 발견: {dicpath}")
                    break

            self._dicpath = dicpath

            if dicpath:
                self._mecab = Mecab(dicpath)
            else:
                logger.warning("mecab-ko-dic 사전을 찾을 수 없습니다. 기본 경로 시도...")
                self._mecab = Mecab()

            logger.info("✓ KoNLPy Mecab 초기화 완료")
        except (ImportError, Exception) as e:
            logger.error(f"✗ Mecab 초기화 실패: {e}")
            raise RuntimeError(f"Mecab 형태소 분석기가 필요합니다: {e}")

    @property
    def mecab(self):
        """Mecab 인스턴스 (lazy loading)"""
        if self._mecab is None:
            self._init_mecab()
        return self._mecab

    def __getstate__(self):
        """pickle 직렬화 시 호출"""
        return {'_dicpath': self._dicpath}

    def __setstate__(self, state):
        """pickle 역직렬화 시 호출"""
        self._dicpath = state.get('_dicpath')
        self._mecab = None

    def __call__(self, value, positions=False, chars=False,
                 keeporiginal=False, removestops=True,
                 start_pos=0, start_char=0, mode='', **kwargs):
        """
        텍스트를 토큰화

        Args:
            value: 토큰화할 텍스트
            positions: 위치 정보 포함 여부
            chars: 문자 위치 정보 포함 여부

        Yields:
            Token 객체
        """
        assert isinstance(value, str), "Value must be string"

        # Mecab 형태소 분석
        morphs = self.mecab.morphs(value)

        # 토큰 생성
        token = Token(positions, chars, removestops=removestops, mode=mode)

        for pos, morph in enumerate(morphs):
            if not morph.strip():
                continue

            token.text = morph
            token.boost = 1.0

            if positions:
                token.pos = start_pos + pos

            if chars:
                token.startchar = start_char
                token.endchar = start_char + len(morph)
                start_char = token.endchar

            yield token


class UserContractIndexer:
    """
    사용자 계약서 인덱서

    - DB에서 파싱 데이터 및 임베딩 로드
    - FAISS 인덱스 생성 (시맨틱 검색)
    - Whoosh 인덱스 생성 (키워드 검색)
    - 인덱스는 data/user_contract_indexes/ 에 저장
    """

    INDEX_BASE_DIR = Path("data/user_contract_indexes")
    EMBEDDING_DIMENSION = 3072  # text-embedding-3-large

    def __init__(self, contract_id: str):
        """
        Args:
            contract_id: 계약서 ID
        """
        self.contract_id = contract_id

        # 인덱스 경로
        self.faiss_dir = self.INDEX_BASE_DIR / "faiss"
        self.whoosh_dir = self.INDEX_BASE_DIR / "whoosh"

        self.faiss_dir.mkdir(parents=True, exist_ok=True)
        self.whoosh_dir.mkdir(parents=True, exist_ok=True)

        # FAISS: text와 title 별도 인덱스
        self.faiss_text_index_path = self.faiss_dir / f"{contract_id}_text.faiss"
        self.faiss_title_index_path = self.faiss_dir / f"{contract_id}_title.faiss"
        self.whoosh_index_dir = self.whoosh_dir / contract_id

    def build_indexes(self) -> Dict[str, Any]:
        """
        사용자 계약서 인덱스 구축

        Returns:
            {
                "success": bool,
                "contract_id": str,
                "faiss_index_path": str,
                "whoosh_index_dir": str,
                "total_chunks": int,
                "articles_count": int,
                "exhibits_count": int
            }
        """
        try:
            logger.info(f"사용자 계약서 인덱싱 시작: {self.contract_id}")

            # DB에서 데이터 로드
            parsed_data = self._load_contract_data()
            if not parsed_data:
                raise ValueError(f"계약서 데이터를 찾을 수 없습니다: {self.contract_id}")

            # 청크 및 벡터 준비
            chunks, text_vectors, title_vectors, mapping = self._prepare_chunks_and_vectors(parsed_data)

            if not chunks:
                logger.warning(f"인덱싱할 청크가 없습니다: {self.contract_id}")
                return {
                    "success": False,
                    "contract_id": self.contract_id,
                    "error": "No chunks to index"
                }

            # FAISS 인덱스 생성 (text와 title 별도)
            self._build_faiss_indexes(text_vectors, title_vectors)

            # Whoosh 인덱스 생성
            self._build_whoosh_index(chunks)

            # 매핑 정보 저장 (인덱스 번호 -> 원본 데이터 참조)
            mapping_path = self.faiss_dir / f"{self.contract_id}_mapping.json"
            with open(mapping_path, 'w', encoding='utf-8') as f:
                json.dump(mapping, f, ensure_ascii=False, indent=2)

            articles_count = len([c for c in chunks if c['unit_type'].startswith('article')])
            exhibits_count = len([c for c in chunks if c['unit_type'].startswith('exhibit')])

            logger.info(
                f"인덱싱 완료: {self.contract_id} "
                f"(총 {len(chunks)}개 청크, {articles_count}개 조항, {exhibits_count}개 별지)"
            )

            return {
                "success": True,
                "contract_id": self.contract_id,
                "faiss_text_index_path": str(self.faiss_text_index_path),
                "faiss_title_index_path": str(self.faiss_title_index_path),
                "whoosh_index_dir": str(self.whoosh_index_dir),
                "total_chunks": len(chunks),
                "articles_count": articles_count,
                "exhibits_count": exhibits_count
            }

        except Exception as e:
            logger.error(f"인덱싱 실패: {self.contract_id}, {e}")
            import traceback
            logger.error(traceback.format_exc())
            return {
                "success": False,
                "contract_id": self.contract_id,
                "error": str(e)
            }

    def _load_contract_data(self) -> Optional[Dict[str, Any]]:
        """
        DB에서 계약서 데이터 로드

        Returns:
            parsed_data (파싱 결과 + 임베딩)
        """
        db = SessionLocal()
        try:
            contract = db.query(ContractDocument).filter(
                ContractDocument.contract_id == self.contract_id
            ).first()

            if not contract:
                return None

            return contract.parsed_data

        finally:
            db.close()

    def _prepare_chunks_and_vectors(
        self,
        parsed_data: Dict[str, Any]
    ) -> Tuple[List[Dict[str, Any]], np.ndarray, np.ndarray, List[Dict[str, Any]]]:
        """
        파싱 데이터에서 청크 및 벡터 준비

        Args:
            parsed_data: DB의 parsed_data (파싱 + 임베딩)

        Returns:
            (chunks, text_vectors, title_vectors, mapping)
            - chunks: Whoosh용 청크 리스트
            - text_vectors: FAISS용 텍스트 벡터 배열
            - title_vectors: FAISS용 타이틀 벡터 배열
            - mapping: 인덱스 번호 -> 원본 데이터 참조
        """
        chunks = []
        text_vectors = []
        title_vectors = []
        mapping = []

        articles = parsed_data.get("articles", [])
        exhibits = parsed_data.get("exhibits", [])
        embeddings = parsed_data.get("embeddings", {})

        article_embeddings = embeddings.get("article_embeddings", [])
        exhibit_embeddings = embeddings.get("exhibit_embeddings", [])

        # Articles 처리
        for article, article_emb in zip(articles, article_embeddings):
            article_no = article.get("number")
            article_id = article.get("article_id")
            title = article.get("title", "")
            text = article.get("text", "")

            # Title 청크 (조 본문 - articleText)
            if article_emb.get("title_embedding"):
                chunk_id = f"제{article_no}조 조본문"
                global_id = f"urn:user:{self.contract_id}:art:{article_no:03d}:att"

                chunks.append({
                    "id": chunk_id,
                    "global_id": global_id,
                    "unit_type": "articleText",
                    "parent_id": f"제{article_no}조",
                    "title": title,
                    "order_index": article_no,
                    "text_raw": text,
                    "text_norm": self._normalize_text(text),
                    "contract_id": self.contract_id
                })

                # text 벡터: 본문 내용 (text)
                text_vectors.append(article_emb["title_embedding"])
                # title 벡터: 조 제목 (title)
                title_vectors.append(article_emb["title_embedding"])

                mapping.append({
                    "text_index": len(text_vectors) - 1,
                    "title_index": len(title_vectors) - 1,
                    "type": "article_title",
                    "article_no": article_no,
                    "article_id": article_id
                })

            # Sub-items (하위 항목 - subClause)
            for sub_item, sub_emb in zip(article.get("content", []), article_emb.get("sub_items", [])):
                sub_idx = sub_emb["index"]
                sub_text = sub_item if isinstance(sub_item, str) else str(sub_item)

                chunk_id = f"제{article_no}조 제{sub_idx}항"
                global_id = f"urn:user:{self.contract_id}:art:{article_no:03d}:sub:{sub_idx:03d}"

                chunks.append({
                    "id": chunk_id,
                    "global_id": global_id,
                    "unit_type": "subClause",
                    "parent_id": f"제{article_no}조",
                    "title": title,
                    "order_index": article_no * 1000 + sub_idx,
                    "text_raw": sub_text,
                    "text_norm": self._normalize_text(sub_text),
                    "contract_id": self.contract_id
                })

                # text 벡터: 하위 항목 내용 (sub_text)
                text_vectors.append(sub_emb["text_embedding"])
                # title 벡터: 조 제목 (상위 조의 제목 사용)
                title_vectors.append(article_emb.get("title_embedding") or sub_emb["text_embedding"])

                mapping.append({
                    "text_index": len(text_vectors) - 1,
                    "title_index": len(title_vectors) - 1,
                    "type": "article_sub_item",
                    "article_no": article_no,
                    "article_id": article_id,
                    "sub_item_index": sub_idx
                })

        # Exhibits 처리
        for exhibit, exhibit_emb in zip(exhibits, exhibit_embeddings):
            exhibit_no = exhibit.get("number")
            exhibit_id = exhibit.get("exhibit_id")
            title = exhibit.get("title", "")
            text = exhibit.get("text", "")

            # Title 청크 (별지 본문 - exhibitText)
            if exhibit_emb.get("title_embedding"):
                chunk_id = f"별지{exhibit_no} 본문"
                global_id = f"urn:user:{self.contract_id}:exh:{exhibit_no:03d}:att"

                chunks.append({
                    "id": chunk_id,
                    "global_id": global_id,
                    "unit_type": "exhibitText",
                    "parent_id": f"별지{exhibit_no}",
                    "title": title,
                    "order_index": 10000 + exhibit_no,  # Articles 뒤에 배치
                    "text_raw": text,
                    "text_norm": self._normalize_text(text),
                    "contract_id": self.contract_id
                })

                # text 벡터: 본문 내용 (text)
                text_vectors.append(exhibit_emb["title_embedding"])
                # title 벡터: 별지 제목 (title)
                title_vectors.append(exhibit_emb["title_embedding"])

                mapping.append({
                    "text_index": len(text_vectors) - 1,
                    "title_index": len(title_vectors) - 1,
                    "type": "exhibit_title",
                    "exhibit_no": exhibit_no,
                    "exhibit_id": exhibit_id
                })

            # Sub-items (하위 항목 - exhibitSubItem)
            for sub_item, sub_emb in zip(exhibit.get("content", []), exhibit_emb.get("sub_items", [])):
                sub_idx = sub_emb["index"]
                sub_text = sub_item if isinstance(sub_item, str) else str(sub_item)

                chunk_id = f"별지{exhibit_no} 제{sub_idx}항"
                global_id = f"urn:user:{self.contract_id}:exh:{exhibit_no:03d}:sub:{sub_idx:03d}"

                chunks.append({
                    "id": chunk_id,
                    "global_id": global_id,
                    "unit_type": "exhibitSubItem",
                    "parent_id": f"별지{exhibit_no}",
                    "title": title,
                    "order_index": 10000 + exhibit_no * 1000 + sub_idx,
                    "text_raw": sub_text,
                    "text_norm": self._normalize_text(sub_text),
                    "contract_id": self.contract_id
                })

                # text 벡터: 하위 항목 내용 (sub_text)
                text_vectors.append(sub_emb["text_embedding"])
                # title 벡터: 별지 제목 (상위 별지의 제목 사용)
                title_vectors.append(exhibit_emb.get("title_embedding") or sub_emb["text_embedding"])

                mapping.append({
                    "text_index": len(text_vectors) - 1,
                    "title_index": len(title_vectors) - 1,
                    "type": "exhibit_sub_item",
                    "exhibit_no": exhibit_no,
                    "exhibit_id": exhibit_id,
                    "sub_item_index": sub_idx
                })

        # numpy 배열로 변환
        text_vectors_array = np.array(text_vectors, dtype=np.float32) if text_vectors else np.array([], dtype=np.float32)
        title_vectors_array = np.array(title_vectors, dtype=np.float32) if title_vectors else np.array([], dtype=np.float32)

        return chunks, text_vectors_array, title_vectors_array, mapping

    def _build_faiss_indexes(self, text_vectors: np.ndarray, title_vectors: np.ndarray) -> None:
        """
        FAISS 인덱스 구축 (text와 title 별도 인덱스)

        Args:
            text_vectors: 텍스트 임베딩 벡터 배열 (N x 3072)
            title_vectors: 타이틀 임베딩 벡터 배열 (N x 3072)
        """
        try:
            import faiss

            # Text 인덱스 생성
            if len(text_vectors) > 0:
                text_index = faiss.IndexFlatL2(self.EMBEDDING_DIMENSION)
                text_index.add(text_vectors)
                faiss.write_index(text_index, str(self.faiss_text_index_path))
                logger.info(
                    f"FAISS text 인덱스 생성 완료: {self.faiss_text_index_path} "
                    f"({len(text_vectors)}개 벡터, {self.EMBEDDING_DIMENSION}차원)"
                )
            else:
                logger.warning(f"text 벡터가 없어 FAISS text 인덱스를 생성하지 않습니다: {self.contract_id}")

            # Title 인덱스 생성
            if len(title_vectors) > 0:
                title_index = faiss.IndexFlatL2(self.EMBEDDING_DIMENSION)
                title_index.add(title_vectors)
                faiss.write_index(title_index, str(self.faiss_title_index_path))
                logger.info(
                    f"FAISS title 인덱스 생성 완료: {self.faiss_title_index_path} "
                    f"({len(title_vectors)}개 벡터, {self.EMBEDDING_DIMENSION}차원)"
                )
            else:
                logger.warning(f"title 벡터가 없어 FAISS title 인덱스를 생성하지 않습니다: {self.contract_id}")

        except Exception as e:
            logger.error(f"FAISS 인덱스 생성 실패: {e}")
            raise

    def _build_whoosh_index(self, chunks: List[Dict[str, Any]]) -> None:
        """
        Whoosh 인덱스 구축

        Args:
            chunks: 청크 리스트
        """
        try:
            # Whoosh 디렉토리 생성
            self.whoosh_index_dir.mkdir(parents=True, exist_ok=True)

            # 한국어 분석기
            korean_analyzer = KoreanAnalyzer()

            # 스키마 정의
            schema = Schema(
                id=ID(stored=True, unique=True),
                global_id=ID(stored=True),
                text_norm=TEXT(analyzer=StandardAnalyzer(), stored=True),
                title=TEXT(analyzer=StandardAnalyzer(), stored=True),
                text_raw=STORED,
                metadata=STORED
            )

            # 인덱스 생성 또는 열기
            if not exists_in(str(self.whoosh_index_dir)):
                ix = create_in(str(self.whoosh_index_dir), schema)
                logger.info(f"새 Whoosh 인덱스 생성: {self.whoosh_index_dir}")
            else:
                ix = open_dir(str(self.whoosh_index_dir))
                logger.info(f"기존 Whoosh 인덱스 열기: {self.whoosh_index_dir}")

            # 문서 추가
            writer = ix.writer()

            for chunk in chunks:
                # 메타데이터 JSON 직렬화
                metadata = {
                    'unit_type': chunk.get('unit_type', ''),
                    'parent_id': chunk.get('parent_id', ''),
                    'contract_id': chunk.get('contract_id', ''),
                    'order_index': chunk.get('order_index', 0)
                }
                metadata_json = json.dumps(metadata, ensure_ascii=False)

                # 텍스트를 Mecab으로 토크나이징
                text_norm_tokenized = " ".join(korean_analyzer.mecab.morphs(chunk['text_norm']))
                title_tokenized = " ".join(korean_analyzer.mecab.morphs(chunk['title']))

                writer.add_document(
                    id=chunk['id'],
                    global_id=chunk['global_id'],
                    text_norm=text_norm_tokenized,
                    title=title_tokenized,
                    text_raw=chunk['text_raw'],
                    metadata=metadata_json
                )

            writer.commit()

            logger.info(f"Whoosh 인덱스 생성 완료: {self.whoosh_index_dir} ({len(chunks)}개 청크)")

        except Exception as e:
            logger.error(f"Whoosh 인덱스 생성 실패: {e}")
            raise

    @staticmethod
    def _normalize_text(text: str) -> str:
        """텍스트 정규화 (공백 제거)"""
        if not text:
            return ""
        return " ".join(str(text).split())


def index_user_contract(contract_id: str) -> Dict[str, Any]:
    """
    사용자 계약서 인덱싱 실행 함수

    Args:
        contract_id: 계약서 ID

    Returns:
        인덱싱 결과
    """
    indexer = UserContractIndexer(contract_id)
    return indexer.build_indexes()
