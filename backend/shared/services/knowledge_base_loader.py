"""
지식베이스 로더
Ingestion에서 생성한 인덱스 및 청크 데이터를 로드
"""

from pathlib import Path
from typing import Dict, Any, Optional
import json
import logging
import pickle

import faiss

logger = logging.getLogger(__name__)


class KnowledgeBaseLoader:
    """
    지식베이스 로더
    
    Ingestion에서 생성한 데이터를 로드:
    - FAISS 인덱스
    - Whoosh 인덱스
    - 청크 메타데이터
    """
    
    def __init__(
        self,
        data_dir: Path = Path("/app/data"),
        index_dir: Path = Path("/app/search_indexes")
    ):
        """
        초기화
        
        Args:
            data_dir: 데이터 디렉토리 경로
            index_dir: 인덱스 디렉토리 경로
        """
        self.data_dir = data_dir
        self.index_dir = index_dir
        
        self.chunked_dir = data_dir / "chunked_documents"
        self.faiss_dir = index_dir / "faiss"
        self.whoosh_dir = index_dir / "whoosh"
        
        # 캐시
        self._faiss_cache: Dict[str, Any] = {}
        self._faiss_dual_cache: Dict[tuple, Any] = {}  # (contract_type, 'text'|'title') -> index
        self._chunks_cache: Dict[str, list] = {}
    
    def load_faiss_index(self, contract_type: str) -> Optional[Any]:
        """
        FAISS 인덱스 로드 (단일 인덱스 - Deprecated)
        
        .. deprecated::
            이 메서드는 더 이상 사용되지 않습니다. 
            대신 load_faiss_indexes()를 사용하세요.
        
        Args:
            contract_type: 계약 유형 (provide, create, process, brokerage_provider, brokerage_user)
            
        Returns:
            FAISS 인덱스 또는 None
        """
        logger.warning(
            f"load_faiss_index()는 deprecated되었습니다. "
            f"load_faiss_indexes()를 사용하세요."
        )
        
        # 캐시 확인
        if contract_type in self._faiss_cache:
            logger.info(f"FAISS 인덱스 캐시 히트: {contract_type}")
            return self._faiss_cache[contract_type]
        
        # 파일 경로
        index_file = self.faiss_dir / f"{contract_type}_std_contract.faiss"
        
        if not index_file.exists():
            logger.error(f"FAISS 인덱스 파일을 찾을 수 없습니다: {index_file}")
            return None
        
        try:
            # FAISS 인덱스 로드
            index = faiss.read_index(str(index_file))
            
            # 캐시 저장
            self._faiss_cache[contract_type] = index
            
            logger.info(f"FAISS 인덱스 로드 완료: {contract_type} ({index.ntotal} vectors)")
            return index
            
        except Exception as e:
            logger.error(f"FAISS 인덱스 로드 실패: {e}")
            return None
    
    def load_faiss_indexes(self, contract_type: str) -> Optional[tuple]:
        """
        FAISS 인덱스 로드 (이중 인덱스: text_norm, title)
        
        Args:
            contract_type: 계약 유형 (provide, create, process, brokerage_provider, brokerage_user)
            
        Returns:
            (text_index, title_index) 튜플 또는 None
            
        Raises:
            ValueError: 인덱스 파일이 불완전한 경우
        """
        # 캐시 확인
        text_cache_key = (contract_type, 'text')
        title_cache_key = (contract_type, 'title')
        
        if text_cache_key in self._faiss_dual_cache and title_cache_key in self._faiss_dual_cache:
            logger.info(f"FAISS 이중 인덱스 캐시 히트: {contract_type}")
            return (
                self._faiss_dual_cache[text_cache_key],
                self._faiss_dual_cache[title_cache_key]
            )
        
        # 파일 경로
        text_index_file = self.faiss_dir / f"{contract_type}_std_contract_text.faiss"
        title_index_file = self.faiss_dir / f"{contract_type}_std_contract_title.faiss"
        
        # 두 파일 모두 존재하는지 확인
        text_exists = text_index_file.exists()
        title_exists = title_index_file.exists()
        
        if not text_exists and not title_exists:
            logger.error(
                f"FAISS 이중 인덱스 파일을 찾을 수 없습니다: {contract_type}\n"
                f"  - text 인덱스: {text_index_file}\n"
                f"  - title 인덱스: {title_index_file}"
            )
            return None
        
        if not text_exists:
            error_msg = (
                f"text_norm FAISS 인덱스 파일이 없습니다: {text_index_file}\n"
                f"title 인덱스는 존재하지만 text 인덱스가 없습니다.\n"
                f"Ingestion Container를 실행하여 새로운 인덱스를 생성하세요:\n"
                f"  docker-compose -f docker/docker-compose.yml --profile ingestion run --rm ingestion"
            )
            logger.error(error_msg)
            raise ValueError(error_msg)
        
        if not title_exists:
            error_msg = (
                f"title FAISS 인덱스 파일이 없습니다: {title_index_file}\n"
                f"text 인덱스는 존재하지만 title 인덱스가 없습니다.\n"
                f"Ingestion Container를 실행하여 새로운 인덱스를 생성하세요:\n"
                f"  docker-compose -f docker/docker-compose.yml --profile ingestion run --rm ingestion"
            )
            logger.error(error_msg)
            raise ValueError(error_msg)
        
        try:
            # FAISS 인덱스 로드
            text_index = faiss.read_index(str(text_index_file))
            title_index = faiss.read_index(str(title_index_file))
            
            # 캐시 저장
            self._faiss_dual_cache[text_cache_key] = text_index
            self._faiss_dual_cache[title_cache_key] = title_index
            
            logger.info(
                f"FAISS 이중 인덱스 로드 완료: {contract_type}\n"
                f"  - text_norm: {text_index.ntotal} vectors\n"
                f"  - title: {title_index.ntotal} vectors"
            )
            return (text_index, title_index)
            
        except Exception as e:
            logger.error(f"FAISS 이중 인덱스 로드 실패: {e}")
            import traceback
            logger.error(traceback.format_exc())
            return None
    
    def load_chunks(self, contract_type: str) -> Optional[list]:
        """
        청크 메타데이터 로드
        
        Args:
            contract_type: 계약 유형
            
        Returns:
            청크 리스트 또는 None
        """
        # 캐시 확인
        if contract_type in self._chunks_cache:
            logger.info(f"청크 메타데이터 캐시 히트: {contract_type}")
            return self._chunks_cache[contract_type]
        
        # 파일 경로 (chunks.json)
        chunks_file = self.chunked_dir / f"{contract_type}_std_contract_chunks.json"
        
        if not chunks_file.exists():
            logger.error(f"청크 파일을 찾을 수 없습니다: {chunks_file}")
            return None
        
        try:
            # 청크 로드
            with open(chunks_file, 'r', encoding='utf-8') as f:
                chunks = json.load(f)
            
            # 캐시 저장
            self._chunks_cache[contract_type] = chunks
            
            logger.info(f"청크 메타데이터 로드 완료: {contract_type} ({len(chunks)} chunks)")
            return chunks
            
        except Exception as e:
            logger.error(f"청크 로드 실패: {e}")
            return None
    
    def load_whoosh_index(self, contract_type: str):
        """
        Whoosh 인덱스 로드

        Args:
            contract_type: 계약 유형

        Returns:
            WhooshSearcher 인스턴스 또는 None
        """
        whoosh_path = self.whoosh_dir / f"{contract_type}_std_contract"

        logger.info(f"Whoosh 인덱스 로드 시도: {whoosh_path}")

        if not whoosh_path.exists():
            logger.error(f"Whoosh 인덱스 디렉토리를 찾을 수 없습니다: {whoosh_path}")
            return None

        # 인덱스 파일들 확인
        index_files = list(whoosh_path.glob("*"))
        logger.info(f"  인덱스 디렉토리 내 파일: {len(index_files)}개")
        for f in index_files[:5]:  # 최대 5개만 출력
            logger.debug(f"    - {f.name}")

        try:
            # WhooshSearcher 임포트 및 초기화
            from backend.shared.services.whoosh_searcher import WhooshSearcher

            searcher = WhooshSearcher(whoosh_path)

            # 인덱스 상태 확인 (문서 개수)
            with searcher.ix.searcher() as s:
                doc_count = s.doc_count_all()
                logger.info(f"Whoosh 인덱스 로드 완료: {contract_type} ({doc_count} 문서)")

            return searcher

        except Exception as e:
            logger.error(f"Whoosh 인덱스 로드 실패: {e}")
            import traceback
            logger.error(traceback.format_exc())
            return None
    
    def get_available_contract_types(self) -> list:
        """
        사용 가능한 계약 유형 목록 반환 (이중 인덱스 기준)
        
        Returns:
            계약 유형 리스트
        """
        available_types = []
        
        for contract_type in ['provide', 'create', 'process', 'brokerage_provider', 'brokerage_user']:
            text_faiss_file = self.faiss_dir / f"{contract_type}_std_contract_text.faiss"
            title_faiss_file = self.faiss_dir / f"{contract_type}_std_contract_title.faiss"
            chunks_file = self.chunked_dir / f"{contract_type}_std_contract_chunks.json"
            
            # 이중 인덱스와 청크 파일이 모두 존재하는 경우만 사용 가능
            if text_faiss_file.exists() and title_faiss_file.exists() and chunks_file.exists():
                available_types.append(contract_type)
        
        return available_types
    
    def verify_knowledge_base(self) -> Dict[str, Any]:
        """
        지식베이스 상태 확인 (이중 인덱스 형식 검증 포함)
        
        Returns:
            {
                "status": "ok" | "incomplete" | "missing" | "legacy_format",
                "available_types": [...],
                "missing_types": [...],
                "legacy_types": [...],
                "details": {...},
                "warnings": [...]
            }
        """
        all_types = ['provide', 'create', 'process', 'brokerage_provider', 'brokerage_user']
        available_types = self.get_available_contract_types()
        missing_types = [t for t in all_types if t not in available_types]
        legacy_types = []
        warnings = []
        
        details = {}
        for contract_type in all_types:
            # 기존 단일 인덱스 파일
            old_faiss_file = self.faiss_dir / f"{contract_type}_std_contract.faiss"
            
            # 새로운 이중 인덱스 파일
            text_faiss_file = self.faiss_dir / f"{contract_type}_std_contract_text.faiss"
            title_faiss_file = self.faiss_dir / f"{contract_type}_std_contract_title.faiss"
            
            chunks_file = self.chunked_dir / f"{contract_type}_std_contract_chunks.json"
            whoosh_dir = self.whoosh_dir / f"{contract_type}_std_contract"
            
            old_faiss_exists = old_faiss_file.exists()
            text_faiss_exists = text_faiss_file.exists()
            title_faiss_exists = title_faiss_file.exists()
            
            details[contract_type] = {
                "faiss_legacy": old_faiss_exists,
                "faiss_text": text_faiss_exists,
                "faiss_title": title_faiss_exists,
                "chunks": chunks_file.exists(),
                "whoosh": whoosh_dir.exists()
            }
            
            # 기존 인덱스만 존재하고 새로운 인덱스가 없는 경우
            if old_faiss_exists and not (text_faiss_exists and title_faiss_exists):
                legacy_types.append(contract_type)
                warning_msg = (
                    f"{contract_type}: 기존 FAISS 인덱스 형식이 감지되었습니다. "
                    f"새로운 이중 인덱스 형식으로 재생성이 필요합니다."
                )
                warnings.append(warning_msg)
                logger.warning(warning_msg)
            
            # 이중 인덱스가 불완전한 경우 (하나만 존재)
            if (text_faiss_exists and not title_faiss_exists) or (not text_faiss_exists and title_faiss_exists):
                warning_msg = (
                    f"{contract_type}: FAISS 이중 인덱스가 불완전합니다. "
                    f"(text: {text_faiss_exists}, title: {title_faiss_exists})"
                )
                warnings.append(warning_msg)
                logger.warning(warning_msg)
        
        # 상태 결정
        if legacy_types:
            status = "legacy_format"
            migration_msg = (
                "기존 FAISS 인덱스 형식이 감지되었습니다. "
                "새로운 이중 인덱스 형식으로 재생성하려면 다음 명령을 실행하세요:\n"
                "  docker-compose -f docker/docker-compose.yml --profile ingestion run --rm ingestion"
            )
            warnings.append(migration_msg)
            logger.warning(migration_msg)
        elif len(available_types) == len(all_types):
            status = "ok"
        elif len(available_types) > 0:
            status = "incomplete"
        else:
            status = "missing"
        
        return {
            "status": status,
            "available_types": available_types,
            "missing_types": missing_types,
            "legacy_types": legacy_types,
            "details": details,
            "warnings": warnings
        }
    
    def load_user_contract_indexes(self, contract_id: str) -> Optional[tuple]:
        """
        사용자 계약서 인덱스 로드 (챗봇용)
        
        Args:
            contract_id: 계약서 ID
            
        Returns:
            (text_index, title_index, whoosh_searcher) 튜플 또는 None
        """
        try:
            # 인덱스 경로
            user_index_base = Path("data/user_contract_indexes")
            faiss_text_path = user_index_base / "faiss" / f"{contract_id}_text.faiss"
            faiss_title_path = user_index_base / "faiss" / f"{contract_id}_title.faiss"
            whoosh_dir = user_index_base / "whoosh" / contract_id
            
            # 인덱스 존재 확인
            if not faiss_text_path.exists() or not faiss_title_path.exists():
                logger.error(f"사용자 계약서 FAISS 인덱스가 존재하지 않습니다: {contract_id}")
                return None
            
            if not whoosh_dir.exists():
                logger.error(f"사용자 계약서 Whoosh 인덱스가 존재하지 않습니다: {contract_id}")
                return None
            
            # FAISS 인덱스 로드
            text_index = faiss.read_index(str(faiss_text_path))
            title_index = faiss.read_index(str(faiss_title_path))
            
            # Whoosh 인덱스 로드
            from backend.shared.services.whoosh_searcher import WhooshSearcher
            whoosh_searcher = WhooshSearcher(whoosh_dir)
            
            logger.info(
                f"사용자 계약서 인덱스 로드 완료: {contract_id}\n"
                f"  - text: {text_index.ntotal} vectors\n"
                f"  - title: {title_index.ntotal} vectors"
            )
            
            return (text_index, title_index, whoosh_searcher)
        
        except Exception as e:
            logger.error(f"사용자 계약서 인덱스 로드 실패: {e}")
            import traceback
            logger.error(traceback.format_exc())
            return None


# 싱글톤 인스턴스
_knowledge_base_loader = None


def get_knowledge_base_loader() -> KnowledgeBaseLoader:
    """
    KnowledgeBaseLoader 싱글톤 인스턴스 반환
    
    Returns:
        KnowledgeBaseLoader 인스턴스
    """
    global _knowledge_base_loader
    if _knowledge_base_loader is None:
        _knowledge_base_loader = KnowledgeBaseLoader()
    return _knowledge_base_loader
