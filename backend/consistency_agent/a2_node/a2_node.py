"""
A2 노드 - 체크리스트 검증

사용자 계약서의 각 조항이 매칭된 표준 조항의 체크리스트 요구사항을 충족하는지 검증합니다.
"""

import logging
import time
from datetime import datetime
from typing import Dict, Any, List, Optional
from sqlalchemy.orm import Session
from openai import AzureOpenAI

from backend.consistency_agent.a2_node.checklist_loader import ChecklistLoader
from backend.consistency_agent.a2_node.checklist_verifier import ChecklistVerifier
from backend.shared.database import ValidationResult, ClassificationResult, ContractDocument
from backend.shared.services.knowledge_base_loader import KnowledgeBaseLoader

logger = logging.getLogger(__name__)


class ChecklistCheckNode:
    """
    A2 노드: 체크리스트 검증
    
    주요 기능:
    1. A1 매칭 결과 로드
    2. 계약 유형별 체크리스트 로드
    3. 사용자 조항별 체크리스트 검증 (LLM)
    4. 검증 결과 집계 및 통계 계산
    5. DB 저장
    """
    
    def __init__(
        self,
        db_session: Session,
        llm_client: AzureOpenAI,
        kb_loader: Optional[KnowledgeBaseLoader] = None
    ):
        """
        ChecklistCheckNode 초기화
        
        Args:
            db_session: 데이터베이스 세션
            llm_client: Azure OpenAI 클라이언트
            kb_loader: 지식베이스 로더 (표준 조항 로드용, 선택적)
        """
        self.db = db_session
        self.llm_client = llm_client
        self.kb_loader = kb_loader or KnowledgeBaseLoader()
        
        # 컴포넌트 초기화
        self.checklist_loader = ChecklistLoader()
        self.verifier = ChecklistVerifier(llm_client)
        
        # 개발 중: 캐시 초기화 (코드 변경 반영 위해)
        self.checklist_loader.clear_cache()
        
        logger.info("ChecklistCheckNode 초기화 완료")
    
    def check_checklist(self, contract_id: str, matching_types: List[str] = None) -> Dict[str, Any]:
        """
        체크리스트 검증 메인 함수
        
        체크리스트 항목을 검증하고 결과를 반환합니다.
        MANUAL_CHECK_REQUIRED 항목은 user_article_results 내에 포함됩니다.
        
        Args:
            contract_id: 계약서 ID
            matching_types: 처리할 매칭 유형 (["primary"], ["recovered"])
                           None이면 ["primary"] 사용 (기본값, 하위 호환성)
        
        Returns:
            검증 결과 딕셔너리
            {
                "total_checklist_items": int,
                "verified_items": int,
                "passed_items": int,
                "failed_items": int,
                "user_article_results": [
                    {
                        "user_article_no": int,
                        "checklist_results": [
                            {
                                "check_text": str,
                                "reference": str,
                                "result": "YES" | "NO" | "UNCLEAR" | "MANUAL_CHECK_REQUIRED",
                                "evidence": str | None,
                                "user_action": str (MANUAL_CHECK_REQUIRED인 경우),
                                "manual_check_reason": str (MANUAL_CHECK_REQUIRED인 경우)
                            }
                        ]
                    }
                ],
                "processing_time": float,
                "verification_date": str
            }
        
        Raises:
            ValueError: A1 결과 또는 계약 유형이 없는 경우
        """
        if matching_types is None:
            matching_types = ["primary"]
        
        logger.info(f"=== 체크리스트 검증 시작 (contract_id={contract_id}, matching_types={matching_types}) ===")
        start_time = time.time()
        
        # 1. A1 매칭 결과 로드
        logger.info("1. A1 매칭 결과 로드 중...")
        a1_results = self._load_a1_results(contract_id)
        
        # matching_types에 따라 필터링
        all_matching_details = []
        if "primary" in matching_types:
            all_matching_details.extend(a1_results.get('matching_details', []))
        if "recovered" in matching_types:
            all_matching_details.extend(a1_results.get('recovered_matching_details', []))
        
        matching_details = all_matching_details
        contract_type = a1_results.get('contract_type')
        
        logger.info(f"  - 계약 유형: {contract_type}")
        logger.info(f"  - 매칭된 조항 수: {len(matching_details)}개")
        
        # 2. Preamble 존재 여부 확인 및 텍스트 로드
        preamble_text = self._get_preamble_text(contract_id)
        has_preamble = bool(preamble_text)
        logger.info(f"  - Preamble 존재 여부: {has_preamble}")
        if has_preamble:
            logger.info(f"  - Preamble 길이: {len(preamble_text)} 문자")
        
        # 3. 체크리스트 로드 (preamble 정보 전달)
        logger.info(f"2. 체크리스트 로드 중 (contract_type={contract_type})...")
        all_checklists = self.checklist_loader.load_checklist(contract_type, has_preamble)
        logger.info(f"  - 전체 체크리스트 항목: {len(all_checklists)}개")
        
        # 3. Preamble 체크리스트 검증 (있는 경우)
        user_article_results = []
        verified_yes_items = set()  # YES인 체크리스트 추적 (중복 방지)
        
        if has_preamble:
            logger.info("3-1. Preamble 체크리스트 검증 시작...")
            preamble_result = self._verify_preamble_checklist(
                contract_id,
                preamble_text,
                all_checklists,
                contract_type
            )
            if preamble_result:
                user_article_results.append(preamble_result)
                logger.info(f"  Preamble 검증 완료: {len(preamble_result.get('checklist_results', []))}개 항목")
                
                # YES인 항목 추적
                for result in preamble_result.get('checklist_results', []):
                    if result.get('result') == 'YES':
                        verified_yes_items.add(result.get('check_text', ''))
                
                logger.info(f"  YES 항목: {len(verified_yes_items)}개 (다음 조항에서 제외)")
        
        # 4. 사용자 조항별 검증
        logger.info("3-2. 사용자 조항별 체크리스트 검증 시작...")
        article_start_idx = len(user_article_results) + 1
        
        for idx, detail in enumerate(matching_details, article_start_idx):
            if not detail.get('matched', False):
                logger.info(f"  [{idx}/{len(matching_details)}] 조항 {detail.get('user_article_no')}: 매칭 없음, 건너뜀")
                continue
            
            # 사용자 조항 정보
            user_article_no = detail['user_article_no']
            user_article_id = detail['user_article_id']
            user_article_title = detail['user_article_title']
            
            # 매칭된 표준 조항 global_id
            matched_global_ids = detail.get('matched_articles_global_ids', [])
            
            logger.info(
                f"  [{idx}/{len(matching_details)}] 조항 {user_article_no} ({user_article_title}) 검증 중... "
                f"(매칭된 표준 조항: {len(matched_global_ids)}개)"
            )
            
            # 관련 체크리스트 필터링
            relevant_checklists = self.checklist_loader.filter_by_global_ids(
                all_checklists,
                matched_global_ids
            )
            
            if not relevant_checklists:
                logger.info(f"    관련 체크리스트 없음, 건너뜀")
                continue
            
            # 이미 YES인 항목 제외
            new_checklists = [
                item for item in relevant_checklists
                if item.get('check_text', '') not in verified_yes_items
            ]
            
            if not new_checklists:
                logger.info(f"    모든 체크리스트 항목이 이미 검증됨 (YES), 건너뜀")
                continue
            
            logger.info(f"    관련 체크리스트: {len(relevant_checklists)}개 (이미 YES: {len(relevant_checklists) - len(new_checklists)}개, 검증 필요: {len(new_checklists)}개)")
            
            # 사용자 조항 텍스트 로드
            user_clause_text = self._get_user_clause_text(contract_id, user_article_id)
            
            if not user_clause_text:
                logger.warning(f"    사용자 조항 텍스트를 찾을 수 없음, 건너뜀")
                continue
            
            # LLM 검증 (새로운 항목만)
            checklist_results = self.verifier.verify_batch(
                user_clause_text,
                new_checklists
            )
            
            # YES인 항목 추적
            for result in checklist_results:
                if result.get('result') == 'YES':
                    verified_yes_items.add(result.get('check_text', ''))
            
            logger.info(f"    검증 완료: {len(checklist_results)}개 결과 (누적 YES: {len(verified_yes_items)}개)")
            
            # 결과 수집
            user_article_results.append({
                "user_article_no": user_article_no,
                "user_article_id": user_article_id,
                "user_article_title": user_article_title,
                "matched_std_global_ids": matched_global_ids,
                "checklist_results": checklist_results
            })
            
            # 조항별 체크리스트 검증 완료 구분선
            logger.info("--------------------------------------------------------------------------------")
        
        # 5. 통계 계산
        logger.info("4. 통계 계산 중...")
        statistics = self._calculate_statistics(user_article_results)
        logger.info(
            f"  - 전체 항목: {statistics['total_checklist_items']}개\n"
            f"  - 검증 완료: {statistics['verified_items']}개\n"
            f"  - 통과: {statistics['passed_items']}개\n"
            f"  - 미충족: {statistics['failed_items']}개"
        )
        
        # 6. 최종 결과 구성
        processing_time = time.time() - start_time
        
        result = {
            **statistics,
            "user_article_results": user_article_results,
            "processing_time": processing_time,
            "verification_date": datetime.now().isoformat()
        }
        
        # 7. DB 저장
        logger.info("5. DB 저장 중...")
        self._save_to_db(contract_id, result, matching_types)
        
        logger.info(f"=== A2 노드 완료 (처리 시간: {processing_time:.2f}초) ===")
        logger.info("================================================================================")
        logger.info("================================================================================")
        
        return result

    
    def _load_a1_results(self, contract_id: str) -> Dict[str, Any]:
        """
        A1 매칭 결과 및 계약 유형 로드
        
        Args:
            contract_id: 계약서 ID
        
        Returns:
            {
                "matching_details": [...],
                "contract_type": str,
                "missing_standard_articles": [...]
            }
        
        Raises:
            ValueError: A1 결과 또는 계약 유형이 없는 경우
        """
        # ValidationResult에서 A1 결과 조회
        validation_result = self.db.query(ValidationResult).filter(
            ValidationResult.contract_id == contract_id
        ).first()
        
        if not validation_result or not validation_result.completeness_check:
            raise ValueError(
                f"A1 매칭 결과가 없습니다: {contract_id}. "
                f"A1 노드를 먼저 실행해주세요."
            )
        
        completeness_check = validation_result.completeness_check
        
        # ClassificationResult에서 계약 유형 조회
        classification = self.db.query(ClassificationResult).filter(
            ClassificationResult.contract_id == contract_id
        ).first()
        
        if not classification or not classification.confirmed_type:
            raise ValueError(
                f"계약 유형이 확정되지 않았습니다: {contract_id}. "
                f"분류 단계를 먼저 완료해주세요."
            )
        
        contract_type = classification.confirmed_type
        
        # 유효한 계약 유형인지 검증
        valid_types = ChecklistLoader.VALID_CONTRACT_TYPES
        if contract_type not in valid_types:
            raise ValueError(
                f"지원하지 않는 계약 유형: {contract_type}. "
                f"유효한 유형: {valid_types}"
            )
        
        logger.info(
            f"A1 결과 로드 완료: {contract_id}\n"
            f"  - 계약 유형: {contract_type}\n"
            f"  - 매칭 상세: {len(completeness_check.get('matching_details', []))}개"
        )
        
        return {
            **completeness_check,
            "contract_type": contract_type
        }

    
    def _get_user_clause_text(self, contract_id: str, user_article_id: str) -> str:
        """
        사용자 조항 텍스트 로드
        
        ContractDocument.parsed_data에서 조항을 조회하고 제목 + 내용을 결합합니다.
        
        Args:
            contract_id: 계약서 ID
            user_article_id: 사용자 조항 ID (예: "user_article_001")
        
        Returns:
            조항 전문 (제목 + 내용)
            빈 문자열: 조항을 찾을 수 없는 경우
        """
        contract = self.db.query(ContractDocument).filter(
            ContractDocument.contract_id == contract_id
        ).first()
        
        if not contract or not contract.parsed_data:
            logger.error(f"계약서 데이터를 찾을 수 없음: {contract_id}")
            return ""
        
        parsed_data = contract.parsed_data
        articles = parsed_data.get('articles', [])
        
        for article in articles:
            if article.get('article_id') == user_article_id:
                # 제목 추출
                title = article.get('text', '')
                
                # 내용 추출 (리스트를 줄바꿈으로 결합)
                content_items = article.get('content', [])
                if isinstance(content_items, list):
                    content = '\n'.join(str(item) for item in content_items if item)
                else:
                    content = str(content_items) if content_items else ''
                
                # 제목 + 내용 결합
                full_text = f"{title}\n{content}".strip()
                
                logger.debug(f"사용자 조항 텍스트 로드: {user_article_id} ({len(full_text)} 문자)")
                
                return full_text
        
        logger.warning(f"사용자 조항을 찾을 수 없음: {user_article_id}")
        return ""

    
    def _calculate_statistics(self, user_article_results: List[Dict[str, Any]]) -> Dict[str, int]:
        """
        통계 계산
        
        Args:
            user_article_results: 사용자 조항별 검증 결과 리스트
        
        Returns:
            {
                "total_checklist_items": int,    # 전체 체크리스트 항목 수
                "verified_items": int,           # 검증 완료된 항목 수
                "passed_items": int,             # 통과한 항목 수 (YES)
                "failed_items": int              # 미충족 항목 수 (NO)
            }
        """
        total_items = 0
        verified_items = 0
        passed_items = 0
        failed_items = 0
        
        for result in user_article_results:
            checklist_results = result.get('checklist_results', [])
            
            for item in checklist_results:
                total_items += 1
                verified_items += 1
                
                result_value = item.get('result', 'NO')
                
                if result_value == 'YES':
                    passed_items += 1
                elif result_value == 'NO':
                    failed_items += 1
                # UNCLEAR는 failed_items에 포함하지 않음
        
        return {
            "total_checklist_items": total_items,
            "verified_items": verified_items,
            "passed_items": passed_items,
            "failed_items": failed_items
        }

    
    def _get_preamble_text(self, contract_id: str) -> str:
        """
        사용자 계약서의 preamble 텍스트 로드
        
        Args:
            contract_id: 계약서 ID
        
        Returns:
            preamble 전문 (줄바꿈으로 결합)
            빈 문자열: preamble이 없는 경우
        """
        contract = self.db.query(ContractDocument).filter(
            ContractDocument.contract_id == contract_id
        ).first()
        
        if not contract or not contract.parsed_data:
            return ""
        
        parsed_data = contract.parsed_data
        preamble = parsed_data.get('preamble', [])
        
        if not preamble:
            return ""
        
        # 리스트를 줄바꿈으로 결합
        if isinstance(preamble, list):
            return '\n'.join(str(line) for line in preamble if line)
        else:
            return str(preamble) if preamble else ""
    
    def _verify_preamble_checklist(
        self,
        contract_id: str,
        preamble_text: str,
        all_checklists: List[Dict[str, Any]],
        contract_type: str
    ) -> Optional[Dict[str, Any]]:
        """
        Preamble 체크리스트 검증
        
        제1조 관련 체크리스트 중 preamble에서 확인해야 하는 항목들을 검증합니다.
        
        Args:
            contract_id: 계약서 ID
            preamble_text: preamble 전문
            all_checklists: 전체 체크리스트 항목
            contract_type: 계약 유형
        
        Returns:
            preamble 검증 결과 또는 None (관련 체크리스트가 없는 경우)
        """
        # 제1조 global_id
        art1_global_id = f"urn:std:{contract_type}:art:001"
        
        # 제1조 관련 체크리스트 필터링
        art1_checklists = self.checklist_loader.filter_by_global_ids(
            all_checklists,
            [art1_global_id]
        )
        
        if not art1_checklists:
            logger.warning("  제1조 관련 체크리스트가 없음")
            return None
        
        logger.info(f"  제1조 관련 체크리스트: {len(art1_checklists)}개")
        
        # 제1조 조문 텍스트도 함께 로드 (있는 경우)
        art1_text = self._get_user_clause_text(contract_id, "user_article_001")
        
        # Preamble + 제1조 결합
        combined_text = preamble_text
        if art1_text:
            combined_text = f"{preamble_text}\n\n{art1_text}"
        
        # LLM 검증
        checklist_results = self.verifier.verify_batch(
            combined_text,
            art1_checklists
        )
        
        # reference에 "서문 + " 추가 (서문 검증이므로)
        for result in checklist_results:
            reference = result.get('reference', '')
            if reference and '제1조' in reference:
                result['reference'] = f"서문 + {reference}"
        
        return {
            "user_article_no": 0,  # preamble은 0번으로 표시
            "user_article_id": "preamble",
            "user_article_title": "서문",
            "matched_std_global_ids": [art1_global_id],
            "checklist_results": checklist_results
        }
    
    def _save_to_db(self, contract_id: str, result: Dict[str, Any], matching_types: List[str] = None):
        """
        체크리스트 검증 결과 DB 저장
        
        matching_types에 따라 적절한 필드에 저장합니다:
        - ["primary"]: checklist_validation
        - ["recovered"]: checklist_validation_recovered
        
        Args:
            contract_id: 계약서 ID
            result: 검증 결과 딕셔너리
            matching_types: 매칭 유형 (None이면 ["primary"])
        
        Raises:
            Exception: DB 저장 실패 시
        """
        if matching_types is None:
            matching_types = ["primary"]
        
        try:
            validation_result = self.db.query(ValidationResult).filter(
                ValidationResult.contract_id == contract_id
            ).first()
            
            if not validation_result:
                # ValidationResult가 없으면 생성
                validation_result = ValidationResult(contract_id=contract_id)
                self.db.add(validation_result)
                logger.info(f"새로운 ValidationResult 생성: {contract_id}")
            
            # matching_types에 따라 필드 선택
            from sqlalchemy.orm.attributes import flag_modified
            
            if "recovered" in matching_types:
                field_name = "checklist_validation_recovered"
                # dict() 생성자로 새 객체 생성하여 SQLAlchemy가 변경 감지하도록
                validation_result.checklist_validation_recovered = dict(result)
                flag_modified(validation_result, 'checklist_validation_recovered')
                logger.info(f"recovered 필드 설정 완료: {len(result.get('user_article_results', []))}개 조항")
            else:
                field_name = "checklist_validation"
                validation_result.checklist_validation = dict(result)
                flag_modified(validation_result, 'checklist_validation')
                logger.info(f"primary 필드 설정 완료: {len(result.get('user_article_results', []))}개 조항")
            
            # DB 커밋 전 확인
            logger.info(f"DB 커밋 시도: {field_name}")
            self.db.commit()
            
            # 커밋 후 재확인
            self.db.refresh(validation_result)
            saved_value = getattr(validation_result, field_name)
            if saved_value:
                logger.info(f"DB 저장 완료 확인: {field_name}, {len(saved_value.get('user_article_results', []))}개 조항")
            else:
                logger.error(f"DB 저장 실패: {field_name}이 None입니다")
        
        except Exception as e:
            logger.error(f"DB 저장 실패: {e}")
            import traceback
            logger.error(f"{traceback.format_exc()}")
            self.db.rollback()
            raise
