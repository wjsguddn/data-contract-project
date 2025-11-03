"""
ChecklistLoader - 활용안내서 체크리스트 로더

A2 노드에서 사용하는 체크리스트 데이터 로드 및 필터링 컴포넌트
"""

import os
import json
import logging
from typing import List, Dict, Set
from pathlib import Path

logger = logging.getLogger(__name__)


class ChecklistLoader:
    """
    활용안내서 체크리스트 로더
    
    주요 기능:
    1. 계약 유형별 체크리스트 JSON 파일 로드
    2. 메모리 캐싱으로 성능 최적화
    3. Global ID 기반 체크리스트 필터링
    4. 중복 제거
    """
    
    # 지원하는 계약 유형
    VALID_CONTRACT_TYPES = [
        'provide',              # 데이터 제공형
        'create',               # 데이터 창출형
        'process',              # 데이터 가공서비스형
        'brokerage_provider',   # 데이터 중개거래형 (제공자-운영자)
        'brokerage_user'        # 데이터 중개거래형 (이용자-운영자)
    ]
    
    # 체크리스트 파일 경로 템플릿
    CHECKLIST_PATH_TEMPLATE = "data/chunked_documents/guidebook_chunked_documents/checklist_documents/{contract_type}_gud_contract_check_chunks_flat.json"
    
    def __init__(self):
        """
        ChecklistLoader 초기화
        
        캐시 딕셔너리를 초기화하여 계약 유형별로 체크리스트를 메모리에 저장
        """
        self._cache: Dict[str, List[Dict]] = {}
        logger.info("ChecklistLoader 초기화 완료")
    
    def load_checklist(self, contract_type: str) -> List[Dict]:
        """
        체크리스트 JSON 파일 로드
        
        Args:
            contract_type: 계약 유형
                - "provide": 데이터 제공형
                - "create": 데이터 창출형
                - "process": 데이터 가공서비스형
                - "brokerage_provider": 데이터 중개거래형 (제공자-운영자)
                - "brokerage_user": 데이터 중개거래형 (이용자-운영자)
        
        Returns:
            체크리스트 항목 리스트
            [
                {
                    "check_text": str,      # 체크리스트 질문
                    "reference": str,       # 참조 (예: "제1조 (106쪽)")
                    "global_id": str        # 표준 조항 global_id
                },
                ...
            ]
        
        Raises:
            ValueError: 지원하지 않는 contract_type인 경우
            FileNotFoundError: 체크리스트 파일이 없는 경우
            RuntimeError: 파일 로드 중 오류 발생
        """
        # 1. 계약 유형 유효성 검증
        if contract_type not in self.VALID_CONTRACT_TYPES:
            raise ValueError(
                f"지원하지 않는 계약 유형: {contract_type}. "
                f"유효한 유형: {self.VALID_CONTRACT_TYPES}"
            )
        
        # 2. 캐시 확인
        if contract_type in self._cache:
            logger.info(f"체크리스트 캐시 히트: {contract_type}")
            return self._cache[contract_type]
        
        # 3. 파일 경로 생성
        file_path = self.CHECKLIST_PATH_TEMPLATE.format(contract_type=contract_type)
        
        # 4. 파일 존재 확인
        if not os.path.exists(file_path):
            raise FileNotFoundError(
                f"체크리스트 파일을 찾을 수 없습니다: {file_path}"
            )
        
        # 5. 파일 로드
        try:
            with open(file_path, 'r', encoding='utf-8') as f:
                checklist_data = json.load(f)
            
            logger.info(
                f"체크리스트 로드 완료: {contract_type} "
                f"({len(checklist_data)} 항목)"
            )
            
            # 6. 캐시 저장
            self._cache[contract_type] = checklist_data
            
            return checklist_data
        
        except json.JSONDecodeError as e:
            raise RuntimeError(
                f"체크리스트 JSON 파싱 실패: {file_path}, 오류: {e}"
            )
        except Exception as e:
            raise RuntimeError(
                f"체크리스트 로드 중 오류 발생: {e}"
            )
    
    def filter_by_global_ids(
        self,
        checklist_data: List[Dict],
        global_ids: List[str]
    ) -> List[Dict]:
        """
        global_id로 체크리스트 필터링
        
        Args:
            checklist_data: 전체 체크리스트 항목 리스트
            global_ids: 필터링할 global_id 리스트
                예: ["urn:std:provide:art:001", "urn:std:provide:art:005"]
        
        Returns:
            필터링된 체크리스트 (중복 제거됨)
            
        Example:
            >>> loader = ChecklistLoader()
            >>> all_checklists = loader.load_checklist("provide")
            >>> filtered = loader.filter_by_global_ids(
            ...     all_checklists,
            ...     ["urn:std:provide:art:001"]
            ... )
            >>> len(filtered)
            5  # 제1조 관련 체크리스트 5개
        """
        if not global_ids:
            logger.warning("global_ids가 비어있음, 빈 리스트 반환")
            return []
        
        # global_id를 Set으로 변환하여 검색 성능 향상
        global_id_set: Set[str] = set(global_ids)
        
        filtered: List[Dict] = []
        seen_texts: Set[str] = set()
        
        for item in checklist_data:
            item_global_id = item.get('global_id')
            
            # global_id가 일치하는 항목만 선택
            if item_global_id in global_id_set:
                check_text = item.get('check_text', '')
                
                # 중복 제거 (check_text 기준)
                if check_text and check_text not in seen_texts:
                    filtered.append(item)
                    seen_texts.add(check_text)
        
        logger.info(
            f"체크리스트 필터링 완료: {len(checklist_data)}개 → {len(filtered)}개 "
            f"(global_ids: {len(global_ids)}개)"
        )
        
        return filtered
    
    def clear_cache(self):
        """
        캐시 초기화
        
        메모리 관리가 필요한 경우 호출
        """
        self._cache.clear()
        logger.info("체크리스트 캐시 초기화 완료")
    
    def get_cache_info(self) -> Dict[str, int]:
        """
        캐시 정보 조회
        
        Returns:
            계약 유형별 캐시된 항목 수
            예: {"provide": 150, "create": 120}
        """
        return {
            contract_type: len(items)
            for contract_type, items in self._cache.items()
        }
