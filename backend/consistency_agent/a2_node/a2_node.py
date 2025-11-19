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
        llm_client: AzureOpenAI = None,
        kb_loader: Optional[KnowledgeBaseLoader] = None
    ):
        """
        ChecklistCheckNode 초기화
        
        Args:
            db_session: 데이터베이스 세션
            llm_client: Azure OpenAI 클라이언트 (선택적, A2 전용 클라이언트 생성 가능)
            kb_loader: 지식베이스 로더 (표준 조항 로드용, 선택적)
        """
        import os
        from openai import OpenAI
        
        self.db = db_session
        self.kb_loader = kb_loader or KnowledgeBaseLoader()
        
        # A2 전용 OpenAI 클라이언트 생성
        # 환경변수 우선순위: OPENAI_API_KEY_A2 > OPENAI_API_KEY
        a2_api_key = os.getenv('OPENAI_API_KEY_A2') or os.getenv('OPENAI_API_KEY')
        
        if a2_api_key:
            # OpenAI API 사용 (개인 키)
            self.llm_client = OpenAI(api_key=a2_api_key)
            logger.info("A2 노드: OpenAI API 사용 (개인 키)")
        elif llm_client:
            # 전달받은 Azure 클라이언트 사용 (폴백)
            self.llm_client = llm_client
            logger.info("A2 노드: Azure OpenAI 사용 (폴백)")
        else:
            raise ValueError("A2 노드: OpenAI API 키 또는 Azure 클라이언트가 필요합니다")
        
        # 컴포넌트 초기화
        self.checklist_loader = ChecklistLoader()
        self.verifier = ChecklistVerifier(self.llm_client, model="gpt-4o-mini")  # A2는 gpt-4o-mini 사용
        
        # 개발 중: 캐시 초기화 (코드 변경 반영 위해)
        self.checklist_loader.clear_cache()
        
        logger.info("ChecklistCheckNode 초기화 완료")
    
    def check_checklist(self, contract_id: str, matching_types: List[str] = None) -> Dict[str, Any]:
        """
        체크리스트 검증 메인 함수 (표준 조항 기준)
        
        표준 조항별로 체크리스트를 검증하고 결과를 반환합니다.
        Preamble 검증은 제외됩니다.
        
        Args:
            contract_id: 계약서 ID
            matching_types: 처리할 매칭 유형 (["primary"], ["recovered"])
                           None이면 ["primary"] 사용 (기본값, 하위 호환성)
        
        Returns:
            검증 결과 딕셔너리
            {
                "std_article_results": [
                    {
                        "std_article_id": str,
                        "std_article_title": str,
                        "std_article_number": str,
                        "matched_user_articles": [...],
                        "checklist_results": [...],
                        "statistics": {...}
                    }
                ],
                "unmatched_std_articles": [...],
                "statistics": {...},
                "processing_time": float,
                "verification_date": str
            }
        
        Raises:
            ValueError: A1 결과 또는 계약 유형이 없는 경우
        """
        if matching_types is None:
            matching_types = ["primary"]
        
        logger.info(f"=== 체크리스트 검증 시작 (표준 조항 기준) ===")
        logger.info(f"  contract_id={contract_id}, matching_types={matching_types}")
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
        
        # 2. 표준 조항 → 사용자 조항 매핑 생성
        logger.info("2. 표준 조항 → 사용자 조항 매핑 생성 중...")
        std_to_user_map = self._build_std_to_user_mapping(matching_details)
        logger.info(f"  - 매핑된 표준 조항: {len(std_to_user_map)}개")
        if std_to_user_map:
            logger.info(f"  - 매핑된 표준 조항 ID 목록: {list(std_to_user_map.keys())[:5]}...")
        
        # 3. 전체 체크리스트 로드 (preamble 제외)
        logger.info(f"3. 체크리스트 로드 중 (contract_type={contract_type})...")
        all_checklists = self.checklist_loader.load_checklist(contract_type, has_preamble=False)
        logger.info(f"  - 전체 체크리스트 항목: {len(all_checklists)}개")
        
        # 4. 표준 조항별로 그룹화
        logger.info("4. 체크리스트를 표준 조항별로 그룹화 중...")
        checklist_by_std = {}
        for item in all_checklists:
            std_id = item['global_id']
            if std_id not in checklist_by_std:
                checklist_by_std[std_id] = []
            checklist_by_std[std_id].append(item)
        
        logger.info(f"  - 그룹화된 표준 조항: {len(checklist_by_std)}개")
        if checklist_by_std:
            logger.info(f"  - 체크리스트 표준 조항 ID 목록: {list(checklist_by_std.keys())[:5]}...")
        
        # 5. 표준 조항 기준으로 검증
        logger.info("5. 표준 조항별 체크리스트 검증 시작...")
        
        # 디버그: 매칭 교집합 확인
        matched_std_ids = set(std_to_user_map.keys())
        checklist_std_ids = set(checklist_by_std.keys())
        intersection = matched_std_ids & checklist_std_ids
        logger.info(f"  - 매칭된 표준 조항: {len(matched_std_ids)}개")
        logger.info(f"  - 체크리스트 표준 조항: {len(checklist_std_ids)}개")
        logger.info(f"  - 교집합 (검증 대상): {len(intersection)}개")
        if len(intersection) == 0:
            logger.warning(f"  - 매칭 조항과 체크리스트 조항이 겹치지 않음!")
            logger.warning(f"  - 매칭 조항 샘플: {list(matched_std_ids)[:3]}")
            logger.warning(f"  - 체크리스트 조항 샘플: {list(checklist_std_ids)[:3]}")
        
        # 병렬 체크리스트 검증
        from concurrent.futures import ThreadPoolExecutor, as_completed
        
        # 검증 대상 필터링 (매칭된 조항만)
        items_to_verify = [
            (std_global_id, checklist_items)
            for std_global_id, checklist_items in checklist_by_std.items()
            if std_to_user_map.get(std_global_id)
        ]
        
        logger.info(f"🚀 A2 체크리스트 검증 병렬 처리 시작: {len(items_to_verify)}개 표준 조항 (max_workers=5)")
        
        def process_single_std_article(item_data):
            """단일 표준 조항 체크리스트 검증"""
            std_global_id, checklist_items = item_data
            
            try:
                # 매칭된 사용자 조항들
                matched_users = std_to_user_map.get(std_global_id, [])
                
                logger.info(f"  {std_global_id} 검증 중...")
                logger.info(f"    - 매칭된 사용자 조항: {len(matched_users)}개")
                logger.info(f"    - 체크리스트 항목: {len(checklist_items)}개")
                
                # 사용자 조항 텍스트 합치기
                combined_text = self._combine_user_article_texts(contract_id, matched_users)
                
                if not combined_text:
                    logger.warning(f"    사용자 조항 텍스트를 로드할 수 없음, 건너뜀")
                    return None
                
                # LLM 검증
                checklist_results = self.verifier.verify_batch(
                    combined_text,
                    checklist_items
                )
                
                logger.info(f"    검증 완료: {len(checklist_results)}개 결과")
                
                # 표준 조항 정보 추출
                std_article_title = checklist_items[0].get('reference', '') if checklist_items else ''
                std_article_number = std_article_title  # "제3조" 형식
                
                # 조항별 통계 계산
                article_stats = self._calculate_article_statistics(checklist_results)
                
                logger.info("--------------------------------------------------------------------------------")
                
                # 결과 반환
                return {
                    "std_article_id": std_global_id,
                    "std_article_title": std_article_title,
                    "std_article_number": std_article_number,
                    "matched_user_articles": matched_users,
                    "checklist_results": checklist_results,
                    "statistics": article_stats
                }
            except Exception as e:
                logger.error(f"  {std_global_id} 검증 실패: {e}")
                logger.info("--------------------------------------------------------------------------------")
                return None
        
        # 병렬 실행
        std_article_results = []
        with ThreadPoolExecutor(max_workers=5) as executor:
            future_to_item = {
                executor.submit(process_single_std_article, item): item
                for item in items_to_verify
            }
            
            for future in as_completed(future_to_item):
                result = future.result()
                
                if result:
                    std_article_results.append(result)
        
        logger.info(f"✨ A2 체크리스트 검증 병렬 처리 완료")
        
        # 6. 전체 통계 계산
        logger.info("6. 전체 통계 계산 중...")
        overall_statistics = self._calculate_overall_statistics(std_article_results)
        
        # 8. 최종 결과 구성
        processing_time = time.time() - start_time
        
        result = {
            "std_article_results": std_article_results,
            "statistics": overall_statistics,
            "processing_time": processing_time,
            "verification_date": datetime.now().isoformat()
        }
        
        # 7. DB 저장
        logger.info("7. DB 저장 중...")
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

    
    def _calculate_article_statistics(self, checklist_results: List[Dict[str, Any]]) -> Dict[str, Any]:
        """
        표준 조항별 체크리스트 통계 계산
        
        Args:
            checklist_results: 해당 표준 조항의 체크리스트 검증 결과
        
        Returns:
            {
                "total_items": int,
                "passed_items": int,
                "failed_items": int,
                "unclear_items": int,
                "manual_check_items": int,
                "pass_rate": float
            }
        """
        total_items = len(checklist_results)
        passed_items = 0
        failed_items = 0
        unclear_items = 0
        manual_check_items = 0
        
        for item in checklist_results:
            result_value = item.get('result', 'NO')
            
            if result_value == 'YES':
                passed_items += 1
            elif result_value == 'NO':
                failed_items += 1
            elif result_value == 'UNCLEAR':
                unclear_items += 1
            elif result_value == 'MANUAL_CHECK_REQUIRED':
                manual_check_items += 1
        
        pass_rate = passed_items / total_items if total_items > 0 else 0.0
        
        return {
            "total_items": total_items,
            "passed_items": passed_items,
            "failed_items": failed_items,
            "unclear_items": unclear_items,
            "manual_check_items": manual_check_items,
            "pass_rate": round(pass_rate, 2)
        }
    
    def _calculate_overall_statistics(
        self,
        std_article_results: List[Dict[str, Any]]
    ) -> Dict[str, Any]:
        """
        전체 통계 계산
        
        Args:
            std_article_results: 표준 조항별 검증 결과
        
        Returns:
            {
                "matched_std_articles": int,
                "total_checklist_items": int,
                "passed_items": int,
                "failed_items": int,
                "unclear_items": int,
                "manual_check_items": int,
                "overall_pass_rate": float
            }
        """
        matched_std_articles = len(std_article_results)
        
        # 체크리스트 통계 합산
        total_checklist_items = 0
        passed_items = 0
        failed_items = 0
        unclear_items = 0
        manual_check_items = 0
        
        for result in std_article_results:
            stats = result.get('statistics', {})
            total_checklist_items += stats.get('total_items', 0)
            passed_items += stats.get('passed_items', 0)
            failed_items += stats.get('failed_items', 0)
            unclear_items += stats.get('unclear_items', 0)
            manual_check_items += stats.get('manual_check_items', 0)
        
        overall_pass_rate = passed_items / total_checklist_items if total_checklist_items > 0 else 0.0
        
        return {
            "matched_std_articles": matched_std_articles,
            "total_checklist_items": total_checklist_items,
            "passed_items": passed_items,
            "failed_items": failed_items,
            "unclear_items": unclear_items,
            "manual_check_items": manual_check_items,
            "overall_pass_rate": round(overall_pass_rate, 2)
        }
    
    def _identify_unmatched_std_articles(
        self,
        a1_results: Dict[str, Any],
        checklist_by_std: Dict[str, List[Dict[str, Any]]],
        contract_type: str
    ) -> List[Dict[str, Any]]:
        """
        미매칭 표준 조항 식별 및 위험도 평가
        
        A1의 missing_standard_articles를 활용하여 미매칭 표준 조항의
        체크리스트 정보와 위험도를 생성합니다.
        
        Args:
            a1_results: A1 검증 결과
            checklist_by_std: 표준 조항별 체크리스트 그룹
            contract_type: 계약 유형
        
        Returns:
            미매칭 표준 조항 리스트
            [
                {
                    "std_article_id": str,
                    "std_article_title": str,
                    "std_article_number": str,
                    "checklist_items": [...],
                    "risk_assessment": {
                        "severity": "high" | "medium" | "low",
                        "description": str,
                        "recommendation": str,
                        "legal_risk": str
                    }
                }
            ]
        """
        unmatched_articles = []
        
        # A1의 missing_article_analysis 활용
        missing_analysis = a1_results.get('missing_article_analysis', [])
        
        for missing in missing_analysis:
            # 실제로 누락된 조항만 처리
            if not missing.get('is_truly_missing', True):
                continue
            
            std_article_id = missing.get('standard_article_id', '')
            std_article_title = missing.get('standard_article_title', '')
            
            # 해당 표준 조항의 체크리스트 가져오기
            checklist_items = checklist_by_std.get(std_article_id, [])
            
            # 체크리스트를 간단한 형식으로 변환
            simple_checklist = [
                {
                    "check_text": item.get('check_text', ''),
                    "reference": item.get('reference', '')
                }
                for item in checklist_items
            ]
            
            # 위험도 평가 (A1의 정보 활용 + 체크리스트 개수 고려)
            risk_assessment = self._assess_missing_article_risk(
                std_article_id,
                std_article_title,
                len(simple_checklist),
                missing
            )
            
            unmatched_articles.append({
                "std_article_id": std_article_id,
                "std_article_title": std_article_title,
                "std_article_number": std_article_title,  # "제5조" 형식
                "checklist_items": simple_checklist,
                "risk_assessment": risk_assessment
            })
        
        return unmatched_articles
    
    def _assess_missing_article_risk(
        self,
        std_article_id: str,
        std_article_title: str,
        checklist_count: int,
        missing_info: Dict[str, Any]
    ) -> Dict[str, str]:
        """
        미매칭 표준 조항의 위험도 평가
        
        Args:
            std_article_id: 표준 조항 global_id
            std_article_title: 표준 조항 제목
            checklist_count: 체크리스트 항목 수
            missing_info: A1의 missing_article_analysis 정보
        
        Returns:
            {
                "severity": "high" | "medium" | "low",
                "description": str,
                "recommendation": str,
                "legal_risk": str
            }
        """
        # 필수 조항 리스트 (하드코딩)
        critical_articles = [
            "urn:std:provide:art:001",  # 목적
            "urn:std:provide:art:003",  # 제공 목적
            "urn:std:provide:art:005",  # 보유 기간
            "urn:std:process:art:001",
            "urn:std:process:art:003",
            "urn:std:transfer:art:001",
            "urn:std:transfer:art:003",
        ]
        
        # 위험도 판단
        if std_article_id in critical_articles:
            severity = "high"
        elif checklist_count >= 5:  # 체크리스트가 많으면 중요한 조항
            severity = "medium"
        else:
            severity = "low"
        
        # A1의 정보 활용
        description = missing_info.get('reasoning', f"필수 조항 '{std_article_title}' 누락")
        recommendation = missing_info.get('recommendation', f"'{std_article_title}' 조항 추가 필요")
        legal_risk = missing_info.get('risk_assessment', "계약 유효성 및 법적 리스크 존재")
        
        return {
            "severity": severity,
            "description": description,
            "recommendation": recommendation,
            "legal_risk": legal_risk
        }

    
    def _build_std_to_user_mapping(self, matching_details: List[Dict[str, Any]]) -> Dict[str, List[Dict[str, Any]]]:
        """
        A1 매칭 결과를 표준 조항 → 사용자 조항 매핑으로 재조립
        
        Args:
            matching_details: A1의 matching_details (사용자 조항 기준)
        
        Returns:
            표준 조항 global_id를 키로 하는 매핑
            {
                "urn:std:provide:art:003": [
                    {
                        "user_article_no": 7,
                        "user_article_id": "user_article_007",
                        "user_article_title": "제공 목적 및 범위"
                    },
                    ...
                ]
            }
        """
        std_to_user_map = {}
        
        for detail in matching_details:
            if not detail.get('matched', False):
                continue
            
            # 사용자 조항 정보
            user_info = {
                'user_article_no': detail['user_article_no'],
                'user_article_id': detail['user_article_id'],
                'user_article_title': detail['user_article_title']
            }
            
            # 매칭된 표준 조항들
            matched_global_ids = detail.get('matched_articles_global_ids', [])
            
            for std_global_id in matched_global_ids:
                if std_global_id not in std_to_user_map:
                    std_to_user_map[std_global_id] = []
                
                # 중복 방지 (같은 사용자 조항이 여러 번 추가되지 않도록)
                if user_info not in std_to_user_map[std_global_id]:
                    std_to_user_map[std_global_id].append(user_info)
        
        logger.info(f"표준 조항 → 사용자 조항 매핑 생성 완료: {len(std_to_user_map)}개 표준 조항")
        
        return std_to_user_map
    
    def _combine_user_article_texts(
        self,
        contract_id: str,
        matched_users: List[Dict[str, Any]]
    ) -> str:
        """
        여러 사용자 조항 텍스트를 합침
        
        Args:
            contract_id: 계약서 ID
            matched_users: 매칭된 사용자 조항 정보 리스트
                [
                    {"user_article_no": 7, "user_article_id": "user_article_007", ...},
                    {"user_article_no": 8, "user_article_id": "user_article_008", ...}
                ]
        
        Returns:
            합쳐진 텍스트
            "[사용자 제7조: ...]\n...\n\n[사용자 제8조: ...]\n..."
        """
        texts = []
        
        for user in matched_users:
            article_no = user['user_article_no']
            article_title = user['user_article_title']
            article_text = self._get_user_clause_text(
                contract_id,
                user['user_article_id']
            )
            
            if article_text:
                texts.append(f"[사용자 제{article_no}조: {article_title}]\n{article_text}")
        
        combined = "\n\n".join(texts)
        logger.debug(f"사용자 조항 텍스트 합치기 완료: {len(matched_users)}개 조항, {len(combined)} 문자")
        
        return combined
    
    def _enrich_with_article_info(
        self,
        llm_results: List[Dict[str, Any]],
        matched_users: List[Dict[str, Any]]
    ) -> List[Dict[str, Any]]:
        """
        LLM 결과에 사용자 조항 전체 정보 추가
        
        LLM이 반환한 조항 번호를 전체 정보로 변환합니다.
        
        Args:
            llm_results: LLM 검증 결과 (조항 번호만 포함)
            matched_users: 매칭된 사용자 조항 전체 정보
        
        Returns:
            전체 정보가 포함된 체크리스트 결과
        """
        # 조항 번호 → 전체 정보 매핑
        article_map = {
            article['user_article_no']: {
                'user_article_no': article['user_article_no'],
                'user_article_id': article['user_article_id'],
                'user_article_title': article['user_article_title']
            }
            for article in matched_users
        }
        
        enriched_results = []
        
        for result in llm_results:
            # ChecklistVerifier가 이미 전체 정보를 반환하므로
            # 여기서는 추가 처리 없이 그대로 사용
            enriched_results.append(result)
        
        return enriched_results
    

    def _save_to_db(self, contract_id: str, result: Dict[str, Any], matching_types: List[str] = None):
        """
        체크리스트 검증 결과 DB 저장
        
        matching_types에 따라 적절한 필드에 저장합니다:
        - ["primary"]: checklist_validation
        - ["recovered"]: checklist_validation_recovered
        
        Args:
            contract_id: 계약서 ID
            result: 검증 결과 딕셔너리 (표준 조항 기준)
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
                logger.info(f"recovered 필드 설정 완료: {len(result.get('std_article_results', []))}개 표준 조항")
            else:
                field_name = "checklist_validation"
                validation_result.checklist_validation = dict(result)
                flag_modified(validation_result, 'checklist_validation')
                logger.info(f"primary 필드 설정 완료: {len(result.get('std_article_results', []))}개 표준 조항")
            
            # DB 커밋 전 확인
            logger.info(f"DB 커밋 시도: {field_name}")
            self.db.commit()
            
            # 커밋 후 재확인
            self.db.refresh(validation_result)
            saved_value = getattr(validation_result, field_name)
            if saved_value:
                logger.info(f"DB 저장 완료 확인: {field_name}, {len(saved_value.get('std_article_results', []))}개 표준 조항")
            else:
                logger.error(f"DB 저장 실패: {field_name}이 None입니다")
        
        except Exception as e:
            logger.error(f"DB 저장 실패: {e}")
            import traceback
            logger.error(f"{traceback.format_exc()}")
            self.db.rollback()
            raise
