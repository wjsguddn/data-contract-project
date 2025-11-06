from celery import Celery, chain, group
from backend.shared.core.celery_app import celery_app
from backend.shared.database import (
    get_db, ValidationResult, ContractDocument, ClassificationResult,
    update_validation_field_with_retry, update_completeness_check_partial_with_retry
)
from backend.shared.services.knowledge_base_loader import KnowledgeBaseLoader
from .a1_node.a1_node import CompletenessCheckNode
from .a2_node.a2_node import ChecklistCheckNode
from .a3_node.a3_node import ContentAnalysisNode
import logging
import os
from typing import List
from openai import AzureOpenAI
from concurrent.futures import ThreadPoolExecutor, as_completed

logger = logging.getLogger(__name__)


class NodeLoggerAdapter(logging.LoggerAdapter):
    """노드별 태그를 자동으로 추가하는 로거 어댑터"""
    def __init__(self, logger, node_tag):
        super().__init__(logger, {})
        self.node_tag = node_tag

    def process(self, msg, kwargs):
        return f"[{self.node_tag}] {msg}", kwargs


@celery_app.task(bind=True, name="consistency.check_completeness", queue="consistency_validation")
def check_completeness_task(self, contract_id: str, text_weight: float = 0.7, title_weight: float = 0.3, dense_weight: float = 0.85):
    """
    A1 노드: 완전성 검증 작업

    사용자 계약서 조문이 표준계약서 조문과 매칭되는지 확인하고 누락 조문을 식별

    Args:
        contract_id: 검증할 계약서 ID
        text_weight: 본문 가중치 (기본값 0.7)
        title_weight: 제목 가중치 (기본값 0.3)
        dense_weight: 시멘틱 가중치 (기본값 0.85)

    Returns:
        매칭 결과 (A3에서 사용)
    """
    logger.info(f"A1 노드 완전성 검증 시작: {contract_id}")

    db = None
    try:
        # 데이터베이스 세션 생성
        db = next(get_db())

        # 계약서 데이터 로드
        contract = db.query(ContractDocument).filter(
            ContractDocument.contract_id == contract_id
        ).first()

        if not contract:
            raise ValueError(f"계약서를 찾을 수 없습니다: {contract_id}")

        # 분류 결과 확인
        classification = db.query(ClassificationResult).filter(
            ClassificationResult.contract_id == contract_id
        ).first()

        if not classification:
            raise ValueError(f"계약서 분류가 완료되지 않았습니다: {contract_id}")

        # 계약 유형
        contract_type = classification.confirmed_type or classification.predicted_type
        if not contract_type:
            raise ValueError(f"계약서 유형을 확인할 수 없습니다: {contract_id}")

        logger.info(f"  계약서 유형: {contract_type}")

        # A1 노드 초기화
        kb_loader = KnowledgeBaseLoader()
        azure_client = _init_azure_client()

        if not azure_client:
            raise ValueError("Azure OpenAI 클라이언트 초기화 실패")

        a1_node = CompletenessCheckNode(
            knowledge_base_loader=kb_loader,
            azure_client=azure_client
        )

        # A1 완전성 검증 수행
        completeness_result = a1_node.check_completeness(
            contract_id=contract_id,
            user_contract=contract.parsed_data,
            contract_type=contract_type,
            text_weight=text_weight,
            title_weight=title_weight,
            dense_weight=dense_weight
        )

        # 기존 검증 결과 확인
        existing_result = db.query(ValidationResult).filter(
            ValidationResult.contract_id == contract_id
        ).first()

        # 검증 결과 저장
        if existing_result:
            # 기존 결과 업데이트
            existing_result.completeness_check = completeness_result
            existing_result.contract_type = contract_type
            db.commit()
            result_id = existing_result.id
        else:
            # 새 결과 생성
            validation_result = ValidationResult(
                contract_id=contract_id,
                contract_type=contract_type,
                completeness_check=completeness_result,
                checklist_validation={"status": "pending"},
                content_analysis={"status": "pending"},
                overall_score=0.0,
                recommendations=[]
            )

            db.add(validation_result)
            db.commit()
            db.refresh(validation_result)
            result_id = validation_result.id

        logger.info(f"A1 노드 검증 완료: {contract_id} "
                   f"(매칭: {completeness_result['matched_user_articles']}/{completeness_result['total_user_articles']}개 조항, "
                   f"누락: {len(completeness_result['missing_standard_articles'])}개)")

        return {
            "status": "completed",
            "contract_id": contract_id,
            "result_id": result_id,
            "completeness_summary": {
                "total_user_articles": completeness_result['total_user_articles'],
                "matched_user_articles": completeness_result['matched_user_articles'],
                "total_standard_articles": completeness_result['total_standard_articles'],
                "matched_standard_articles": completeness_result['matched_standard_articles'],
                "missing_count": len(completeness_result['missing_standard_articles']),
                "processing_time": completeness_result['processing_time']
            }
        }

    except Exception as e:
        logger.error(f"A1 노드 검증 실패: {contract_id}, 오류: {e}")
        return {
            "status": "failed",
            "contract_id": contract_id,
            "error": str(e)
        }

    finally:
        if db:
            db.close()


@celery_app.task(bind=True, name="consistency.analyze_content", queue="consistency_validation")
def analyze_content_task(self, contract_id: str, matching_types: List[str] = None, text_weight: float = 0.7, title_weight: float = 0.3, dense_weight: float = 0.85):
    """
    A3 노드: 내용 분석 작업

    A1의 매칭 결과를 참조하여 매칭된 조문들의 내용을 분석

    Args:
        contract_id: 검증할 계약서 ID
        matching_types: 처리할 매칭 유형 (["primary"], ["recovered"])
                       None이면 ["primary"] 사용 (기본값, 하위 호환성)
        text_weight: 본문 가중치 (기본값 0.7)
        title_weight: 제목 가중치 (기본값 0.3)
        dense_weight: 시멘틱 가중치 (기본값 0.85)
    """
    if matching_types is None:
        matching_types = ["primary"]
    
    # 로그 태그 설정
    log_tag = "reA3" if "recovered" in matching_types else "A3"
    a3_logger = NodeLoggerAdapter(logger, log_tag)
    a3_logger.info(f"내용 분석 시작: {contract_id}, matching_types={matching_types}, weights: text={text_weight}, title={title_weight}, dense={dense_weight}")

    db = None
    try:
        # 데이터베이스 세션 생성
        db = next(get_db())

        # 계약서 데이터 로드
        contract = db.query(ContractDocument).filter(
            ContractDocument.contract_id == contract_id
        ).first()

        if not contract:
            raise ValueError(f"계약서를 찾을 수 없습니다: {contract_id}")

        # 분류 결과 확인
        classification = db.query(ClassificationResult).filter(
            ClassificationResult.contract_id == contract_id
        ).first()

        if not classification:
            raise ValueError(f"계약서 분류가 완료되지 않았습니다: {contract_id}")

        # 계약 유형
        contract_type = classification.confirmed_type or classification.predicted_type
        if not contract_type:
            raise ValueError(f"계약서 유형을 확인할 수 없습니다: {contract_id}")

        a3_logger.info(f"계약서 유형: {contract_type}")

        # 기존 검증 결과 확인
        existing_result = db.query(ValidationResult).filter(
            ValidationResult.contract_id == contract_id
        ).first()

        if not existing_result:
            raise ValueError(f"A1 결과가 존재하지 않습니다: {contract_id}")

        if not existing_result.completeness_check:
            raise ValueError(f"A1 완전성 검증 결과가 없습니다: {contract_id}")

        completeness_result = existing_result.completeness_check

        # A3 노드 초기화
        kb_loader = KnowledgeBaseLoader()
        azure_client = _init_azure_client()

        if not azure_client:
            raise ValueError("Azure OpenAI 클라이언트 초기화 실패")

        a3_node = ContentAnalysisNode(
            knowledge_base_loader=kb_loader,
            azure_client=azure_client
        )

        # A3 노드에 태그 로거 주입
        import backend.consistency_agent.a3_node.a3_node as a3_module
        original_a3_logger = a3_module.logger
        a3_module.logger = a3_logger

        try:
            # A3 분석 수행 (A1 결과 전달)
            analysis_result = a3_node.analyze_contract(
                contract_id=contract_id,
                user_contract=contract.parsed_data,
                contract_type=contract_type,
                matching_types=matching_types,
                text_weight=text_weight,
                title_weight=title_weight,
                dense_weight=dense_weight
            )
        finally:
            # 원래 로거 복원
            a3_module.logger = original_a3_logger

        # 결과 저장 (matching_types에 따라 필드 선택)
        if existing_result:
            if "recovered" in matching_types:
                existing_result.content_analysis_recovered = analysis_result.to_dict()
                a3_logger.info(f"DB 저장: content_analysis_recovered")
            else:
                existing_result.content_analysis = analysis_result.to_dict()
                a3_logger.info(f"DB 저장: content_analysis")
            db.commit()
            result_id = existing_result.id
        else:
            validation_result = ValidationResult(
                contract_id=contract_id,
                contract_type=contract_type,
                completeness_check={"status": "pending"},
                checklist_validation={"status": "pending"},
                content_analysis=analysis_result.to_dict(),
                overall_score=0.0,
                recommendations=[]
            )

            db.add(validation_result)
            db.commit()
            db.refresh(validation_result)
            result_id = validation_result.id

        a3_logger.info(f"검증 완료: {contract_id} (분석: {analysis_result.analyzed_articles}/{analysis_result.total_articles}개 조항)")

        return {
            "status": "completed",
            "contract_id": contract_id,
            "result_id": result_id,
            "analysis_summary": {
                "total_articles": analysis_result.total_articles,
                "analyzed_articles": analysis_result.analyzed_articles,
                "special_articles": analysis_result.special_articles,
                "processing_time": analysis_result.processing_time
            }
        }

    except Exception as e:
        a3_logger.error(f"검증 실패: {contract_id}, 오류: {e}")
        return {
            "status": "failed",
            "contract_id": contract_id,
            "error": str(e)
        }

    finally:
        if db:
            db.close()


def check_checklist_task(contract_id: str, matching_types: List[str] = None):
    """
    A2 노드: 체크리스트 검증 작업
    
    사용자 계약서의 각 조항이 매칭된 표준 조항의 체크리스트 요구사항을 충족하는지 검증
    
    Args:
        contract_id: 검증할 계약서 ID
        matching_types: 처리할 매칭 유형 (["primary"], ["recovered"], ["primary", "recovered"])
                       None이면 ["primary"] 사용 (기본값, 하위 호환성)
    
    Returns:
        체크리스트 검증 결과
    """
    if matching_types is None:
        matching_types = ["primary"]
    
    # 로그 태그 설정
    log_tag = "reA2" if "recovered" in matching_types else "A2"
    a2_logger = NodeLoggerAdapter(logger, log_tag)
    a2_logger.info(f"체크리스트 검증 시작: {contract_id}, matching_types={matching_types}")

    db = None
    try:
        # 데이터베이스 세션 생성
        db = next(get_db())

        # Azure OpenAI 클라이언트 초기화
        azure_client = _init_azure_client()

        if not azure_client:
            raise ValueError("Azure OpenAI 클라이언트 초기화 실패")

        # 지식베이스 로더 초기화
        kb_loader = KnowledgeBaseLoader()

        # A2 노드 초기화
        a2_node = ChecklistCheckNode(
            db_session=db,
            llm_client=azure_client,
            kb_loader=kb_loader
        )

        # A2 노드에 태그 로거 주입
        import backend.consistency_agent.a2_node.a2_node as a2_module
        original_a2_logger = a2_module.logger
        a2_module.logger = a2_logger

        try:
            # A2 체크리스트 검증 수행 (내부에서 DB 저장함)
            checklist_result = a2_node.check_checklist(contract_id, matching_types)
        finally:
            # 원래 로거 복원
            a2_module.logger = original_a2_logger

        a2_logger.info(
            f"검증 완료: {contract_id} "
            f"(전체: {checklist_result.get('total_checklist_items', 0)}개, "
            f"통과: {checklist_result.get('passed_items', 0)}개, "
            f"미충족: {checklist_result.get('failed_items', 0)}개)"
        )

        return {
            "status": "completed",
            "contract_id": contract_id,
            "checklist_summary": {
                "total_checklist_items": checklist_result.get('total_checklist_items', 0),
                "verified_items": checklist_result.get('verified_items', 0),
                "passed_items": checklist_result.get('passed_items', 0),
                "failed_items": checklist_result.get('failed_items', 0),
                "processing_time": checklist_result.get('processing_time', 0.0)
            }
        }

    except Exception as e:
        a2_logger.error(f"검증 실패: {contract_id}, 오류: {e}")
        import traceback
        a2_logger.error(f"{traceback.format_exc()}")
        return {
            "status": "failed",
            "contract_id": contract_id,
            "error": str(e)
        }
    
    finally:
        if db:
            db.close()


@celery_app.task(bind=True, name="consistency.validate_contract", queue="consistency_validation")
def validate_contract_task(self, contract_id: str, text_weight: float = 0.7, title_weight: float = 0.3, dense_weight: float = 0.85):
    """
    통합 검증 작업: A1 (완전성) → A2 (체크리스트) → A3 (내용 분석) 순차 실행

    Args:
        contract_id: 검증할 계약서 ID
        text_weight: 본문 가중치 (기본값 0.7)
        title_weight: 제목 가중치 (기본값 0.3)
        dense_weight: 시멘틱 가중치 (기본값 0.85)

    Returns:
        통합 검증 결과
    """
    logger.info(f"통합 검증 시작: {contract_id}")

    try:
        # A1: 완전성 검증
        logger.info(f"  [1/3] A1 완전성 검증 실행 중...")
        a1_result = check_completeness_task(contract_id, text_weight, title_weight, dense_weight)

        if a1_result['status'] != 'completed':
            logger.error(f"  A1 검증 실패: {a1_result.get('error')}")
            return {
                "status": "failed",
                "contract_id": contract_id,
                "error": f"A1 검증 실패: {a1_result.get('error')}",
                "stage": "completeness_check"
            }

        logger.info(f"  [1/3] A1 완전성 검증 완료")

        # A2: 체크리스트 검증 (A1 결과 참조)
        logger.info(f"  [2/3] A2 체크리스트 검증 실행 중...")
        a2_result = check_checklist_task(contract_id)

        if a2_result['status'] != 'completed':
            logger.error(f"  A2 검증 실패: {a2_result.get('error')}")
            return {
                "status": "partial",
                "contract_id": contract_id,
                "error": f"A2 검증 실패: {a2_result.get('error')}",
                "stage": "checklist_validation",
                "a1_result": a1_result
            }

        logger.info(f"  [2/3] A2 체크리스트 검증 완료")

        # A3: 내용 분석 (A1 결과 참조)
        logger.info(f"  [3/3] A3 내용 분석 실행 중...")
        a3_result = analyze_content_task(contract_id, text_weight, title_weight, dense_weight)

        if a3_result['status'] != 'completed':
            logger.error(f"  A3 분석 실패: {a3_result.get('error')}")
            return {
                "status": "partial",
                "contract_id": contract_id,
                "error": f"A3 분석 실패: {a3_result.get('error')}",
                "stage": "content_analysis",
                "a1_result": a1_result,
                "a2_result": a2_result
            }

        logger.info(f"  [3/3] A3 내용 분석 완료")

        # 통합 결과 반환
        return {
            "status": "completed",
            "contract_id": contract_id,
            "a1_summary": a1_result.get('completeness_summary'),
            "a2_summary": a2_result.get('checklist_summary'),
            "a3_summary": a3_result.get('analysis_summary'),
            "result_id": a3_result.get('result_id')
        }

    except Exception as e:
        logger.error(f"통합 검증 실패: {contract_id}, 오류: {e}")
        import traceback
        logger.error(traceback.format_exc())
        return {
            "status": "failed",
            "contract_id": contract_id,
            "error": str(e)
        }


def _init_azure_client():
    """
    Azure OpenAI 클라이언트 초기화

    Returns:
        AzureOpenAI 클라이언트 또는 None
    """
    try:
        api_key = os.getenv('AZURE_OPENAI_API_KEY')
        endpoint = os.getenv('AZURE_OPENAI_ENDPOINT')
        max_retries = int(os.getenv('AZURE_OPENAI_MAX_RETRIES', '10'))

        if not api_key or not endpoint:
            logger.error("Azure OpenAI 환경 변수가 설정되지 않음")
            return None

        client = AzureOpenAI(
            api_key=api_key,
            azure_endpoint=endpoint,
            api_version="2024-02-01",
            max_retries=max_retries
        )

        logger.info(f"Azure OpenAI 클라이언트 초기화 완료 (max_retries={max_retries})")
        return client

    except Exception as e:
        logger.error(f"Azure OpenAI 클라이언트 초기화 실패: {e}")
        return None


# ============================================================================
# 병렬 처리용 Celery Tasks
# ============================================================================

@celery_app.task(bind=True, name="consistency.check_completeness_stage1", queue="consistency_validation")
def check_completeness_stage1_task(self, contract_id: str, text_weight: float = 0.7, title_weight: float = 0.3, dense_weight: float = 0.85):
    """
    A1 노드 Stage 1: 매칭 + LLM 검증

    A2/A3가 필요로 하는 매칭 결과를 생성합니다.
    누락 조문 재검증은 Stage 2에서 병렬로 수행됩니다.

    Args:
        contract_id: 검증할 계약서 ID
        text_weight: 본문 가중치
        title_weight: 제목 가중치
        dense_weight: 시멘틱 가중치

    Returns:
        매칭 결과 (missing_article_analysis 제외)
    """
    logger.info(f"[A1-S1] Task 시작: {contract_id}")

    db = None
    try:
        # 데이터베이스 세션 생성
        db = next(get_db())

        # 계약서 데이터 로드
        contract = db.query(ContractDocument).filter(
            ContractDocument.contract_id == contract_id
        ).first()

        if not contract:
            raise ValueError(f"계약서를 찾을 수 없습니다: {contract_id}")

        # 분류 결과 확인
        classification = db.query(ClassificationResult).filter(
            ClassificationResult.contract_id == contract_id
        ).first()

        if not classification:
            raise ValueError(f"계약서 분류가 완료되지 않았습니다: {contract_id}")

        # 계약 유형
        contract_type = classification.confirmed_type or classification.predicted_type
        if not contract_type:
            raise ValueError(f"계약서 유형을 확인할 수 없습니다: {contract_id}")

        logger.info(f"[A1-S1] 계약서 유형: {contract_type}")

        # A1 노드 초기화
        kb_loader = KnowledgeBaseLoader()
        azure_client = _init_azure_client()

        if not azure_client:
            raise ValueError("Azure OpenAI 클라이언트 초기화 실패")

        a1_node = CompletenessCheckNode(
            knowledge_base_loader=kb_loader,
            azure_client=azure_client
        )

        # A1-Stage1 수행 (매칭 + LLM 검증)
        completeness_result = a1_node.check_completeness_stage1(
            contract_id=contract_id,
            user_contract=contract.parsed_data,
            contract_type=contract_type,
            text_weight=text_weight,
            title_weight=title_weight,
            dense_weight=dense_weight
        )

        # 기존 검증 결과 확인
        existing_result = db.query(ValidationResult).filter(
            ValidationResult.contract_id == contract_id
        ).first()

        # 검증 결과 저장 (재시도 로직 적용)
        if existing_result:
            # 기존 결과 업데이트
            success = update_validation_field_with_retry(
                contract_id,
                "completeness_check",
                completeness_result
            )
            if not success:
                raise RuntimeError("DB 업데이트 실패 (재시도 후)")

            existing_result.contract_type = contract_type
            db.commit()
            result_id = existing_result.id
        else:
            # 새 결과 생성
            validation_result = ValidationResult(
                contract_id=contract_id,
                contract_type=contract_type,
                completeness_check=completeness_result,
                checklist_validation=None,
                content_analysis=None,
                overall_score=0.0,
                recommendations=[]
            )

            db.add(validation_result)
            db.commit()
            db.refresh(validation_result)
            result_id = validation_result.id

        logger.info(f"[A1-S1] Task 완료: {contract_id} "
                   f"(매칭: {completeness_result['matched_user_articles']}/{completeness_result['total_user_articles']}개 조항, "
                   f"누락 식별: {len(completeness_result['missing_standard_articles'])}개)")

        return {
            "status": "completed",
            "contract_id": contract_id,
            "result_id": result_id,
            "completeness_summary": {
                "total_user_articles": completeness_result['total_user_articles'],
                "matched_user_articles": completeness_result['matched_user_articles'],
                "total_standard_articles": completeness_result['total_standard_articles'],
                "matched_standard_articles": completeness_result['matched_standard_articles'],
                "missing_count": len(completeness_result['missing_standard_articles']),
                "processing_time": completeness_result['processing_time']
            }
        }

    except Exception as e:
        logger.error(f"[A1-S1] Task 실패: {contract_id}, 오류: {e}")
        import traceback
        logger.error(f"[A1-S1] {traceback.format_exc()}")
        return {
            "status": "failed",
            "contract_id": contract_id,
            "error": str(e)
        }

    finally:
        if db:
            db.close()


@celery_app.task(bind=True, name="consistency.check_missing_articles", queue="consistency_validation")
def check_missing_articles_task(self, contract_id: str, text_weight: float = 0.7, title_weight: float = 0.3, dense_weight: float = 0.85):
    """
    A1 노드 Stage 2: 누락 조문 재검증 (병렬 실행)

    DB에서 Stage 1 결과를 로드하여 누락 조문만 재검증합니다.
    A2, A3와 병렬로 실행됩니다.

    Args:
        contract_id: 검증할 계약서 ID
        text_weight: 본문 가중치
        title_weight: 제목 가중치
        dense_weight: 시멘틱 가중치

    Returns:
        누락 검증 결과
    """
    logger.info(f"[A1-S2] Task 시작: {contract_id}")

    db = None
    try:
        # 데이터베이스 세션 생성
        db = next(get_db())

        # 분류 결과 확인
        classification = db.query(ClassificationResult).filter(
            ClassificationResult.contract_id == contract_id
        ).first()

        if not classification:
            raise ValueError(f"계약서 분류가 완료되지 않았습니다: {contract_id}")

        contract_type = classification.confirmed_type or classification.predicted_type
        if not contract_type:
            raise ValueError(f"계약서 유형을 확인할 수 없습니다: {contract_id}")

        logger.info(f"[A1-S2] 계약서 유형: {contract_type}")

        # A1 노드 초기화
        kb_loader = KnowledgeBaseLoader()
        azure_client = _init_azure_client()

        if not azure_client:
            raise ValueError("Azure OpenAI 클라이언트 초기화 실패")

        a1_node = CompletenessCheckNode(
            knowledge_base_loader=kb_loader,
            azure_client=azure_client
        )

        # A1-Stage2 수행 (누락 조문 재검증)
        missing_result = a1_node.check_missing_articles(
            contract_id=contract_id,
            contract_type=contract_type,
            text_weight=text_weight,
            title_weight=title_weight,
            dense_weight=dense_weight
        )

        missing_article_analysis = missing_result['missing_article_analysis']

        # DB 업데이트 (부분 업데이트 - missing_article_analysis 추가)
        success = update_completeness_check_partial_with_retry(
            contract_id,
            {"missing_article_analysis": missing_article_analysis}
        )

        if not success:
            raise RuntimeError("DB 부분 업데이트 실패 (재시도 후)")

        logger.info(f"[A1-S2] 누락 재검증 완료: {len(missing_article_analysis)}개")

        # 오탐지 추출 및 재구조화
        from backend.consistency_agent.a1_node.article_matcher import extract_and_restructure_false_positives

        recovered_matching_details = extract_and_restructure_false_positives(missing_article_analysis)

        # recovered_matching_details가 있으면 DB 저장 및 batch2 트리거
        if recovered_matching_details:
            logger.info(f"[reA1-S2] ========== 오탐지 복구 매칭 시작 ==========")
            logger.info(f"[reA1-S2] 복구된 매칭: {len(recovered_matching_details)}개")
            
            # 복구된 조문 상세 로그
            for detail in recovered_matching_details:
                user_no = detail.get('user_article_no')
                user_title = detail.get('user_article_title', 'N/A')
                matched_ids = detail.get('matched_articles', [])
                logger.info(f"[reA1-S2]   - 사용자 제{user_no}조 ({user_title}) → 표준 조문 {len(matched_ids)}개 매칭")

            # DB 저장
            success = update_completeness_check_partial_with_retry(
                contract_id,
                {"recovered_matching_details": recovered_matching_details}
            )

            if success:
                logger.info(f"[reA1-S2] recovered_matching_details DB 저장 완료")

                # batch2 트리거 (비동기)
                from concurrent.futures import ThreadPoolExecutor

                def trigger_batch2():
                    try:
                        logger.info(f"[reA1-S2] ========== batch2 트리거 시작 ==========")
                        with ThreadPoolExecutor(max_workers=2) as executor:
                            future_a2 = executor.submit(
                                check_checklist_task, contract_id, ["recovered"]
                            )
                            future_a3 = executor.submit(
                                analyze_content_task, contract_id, ["recovered"],
                                text_weight, title_weight, dense_weight
                            )

                            # 결과 대기 (에러 처리)
                            try:
                                a2_result = future_a2.result()
                                if a2_result.get('status') == 'completed':
                                    logger.info(f"[reA1-S2] [reA2] batch2 완료: {a2_result.get('checklist_summary', {})}")
                                else:
                                    logger.error(f"[reA1-S2] [reA2] batch2 실패: {a2_result.get('error')}")
                            except Exception as e:
                                logger.error(f"[reA1-S2] [reA2] batch2 실패: {e}")

                            try:
                                a3_result = future_a3.result()
                                if a3_result.get('status') == 'completed':
                                    logger.info(f"[reA1-S2] [reA3] batch2 완료: {a3_result.get('analysis_summary', {})}")
                                else:
                                    logger.error(f"[reA1-S2] [reA3] batch2 실패: {a3_result.get('error')}")
                            except Exception as e:
                                logger.error(f"[reA1-S2] [reA3] batch2 실패: {e}")

                        logger.info(f"[reA1-S2] ========== batch2 완료 ==========")

                    except Exception as e:
                        logger.error(f"[reA1-S2] batch2 트리거 실패: {e}")

                # 비동기 실행 (A1-Stage2는 계속 진행)
                import threading
                batch2_thread = threading.Thread(target=trigger_batch2, daemon=True)
                batch2_thread.start()

                logger.info(f"[reA1-S2] batch2 트리거 완료 (비동기 실행)")
            else:
                logger.error(f"[reA1-S2] recovered_matching_details 저장 실패")
        else:
            logger.info(f"[A1-S2] 오탐지 없음, batch2 건너뜀")

        logger.info(f"[A1-S2] Task 완료: {contract_id}")

        return {
            "status": "completed",
            "contract_id": contract_id,
            "missing_summary": {
                "verified_missing": len(missing_article_analysis),
                "recovered_matching": len(recovered_matching_details),
                "processing_time": missing_result['processing_time']
            }
        }

    except Exception as e:
        logger.error(f"[A1-S2] Task 실패: {contract_id}, 오류: {e}")
        import traceback
        logger.error(f"[A1-S2] {traceback.format_exc()}")
        return {
            "status": "failed",
            "contract_id": contract_id,
            "error": str(e)
        }

    finally:
        if db:
            db.close()


@celery_app.task(bind=True, name="consistency.check_checklist_parallel", queue="consistency_validation")
def check_checklist_parallel_task(self, contract_id: str, matching_types: List[str] = None):
    """
    A2 노드: 체크리스트 검증 (병렬 실행용)

    A1-Stage2, A3와 병렬로 실행됩니다.

    Args:
        contract_id: 검증할 계약서 ID
        matching_types: 처리할 매칭 유형 (["primary"], ["recovered"], ["primary", "recovered"])
                       None이면 ["primary"] 사용 (기본값)

    Returns:
        체크리스트 검증 결과
    """
    if matching_types is None:
        matching_types = ["primary"]

    logger.info(f"[A2] Task 시작: {contract_id}, matching_types={matching_types}")

    # A2 노드에 matching_types 파라미터 전달
    result = check_checklist_task(contract_id, matching_types)

    if result.get('status') == 'completed':
        logger.info(f"[A2] Task 완료: {contract_id}")

    return result


@celery_app.task(bind=True, name="consistency.analyze_content_parallel", queue="consistency_validation")
def analyze_content_parallel_task(self, contract_id: str, matching_types: List[str] = None, text_weight: float = 0.7, title_weight: float = 0.3, dense_weight: float = 0.85):
    """
    A3 노드: 내용 분석 (병렬 실행용)

    A1-Stage2, A2와 병렬로 실행됩니다.

    Args:
        contract_id: 검증할 계약서 ID
        matching_types: 처리할 매칭 유형 (["primary"], ["recovered"], ["primary", "recovered"])
                       None이면 ["primary"] 사용 (기본값)
        text_weight: 본문 가중치
        title_weight: 제목 가중치
        dense_weight: 시멘틱 가중치

    Returns:
        내용 분석 결과
    """
    if matching_types is None:
        matching_types = ["primary"]

    logger.info(f"[A3] Task 시작: {contract_id}, matching_types={matching_types}")

    # A3 노드에 matching_types 파라미터 전달
    result = analyze_content_task(contract_id, matching_types, text_weight, title_weight, dense_weight)

    if result.get('status') == 'completed':
        logger.info(f"[A3] Task 완료: {contract_id}")

    return result


@celery_app.task(bind=True, name="consistency.validate_contract_parallel", queue="consistency_validation")
def validate_contract_parallel_task(self, contract_id: str, text_weight: float = 0.7, title_weight: float = 0.3, dense_weight: float = 0.85):
    """
    통합 검증 작업 (병렬 처리): A1-Stage1 → [A1-Stage2 || A2 || A3]

    워크플로우:
    1. A1-Stage1: 매칭 + LLM 검증 (순차)
    2. group 병렬 실행:
       - A1-Stage2: 누락 조문 재검증
       - A2: 체크리스트 검증
       - A3: 내용 분석
    3. 결과 통합

    Args:
        contract_id: 검증할 계약서 ID
        text_weight: 본문 가중치
        title_weight: 제목 가중치
        dense_weight: 시멘틱 가중치

    Returns:
        통합 검증 결과
    """
    logger.info(f"[PARALLEL] 통합 검증 시작: {contract_id}")

    try:
        # Step 1: A1-Stage1 실행 (순차)
        logger.info(f"[PARALLEL] [1/2] A1-Stage1 실행 중 (매칭 + LLM 검증)...")
        a1_stage1_result = check_completeness_stage1_task(contract_id, text_weight, title_weight, dense_weight)

        if a1_stage1_result['status'] != 'completed':
            logger.error(f"[PARALLEL] A1-Stage1 실패: {a1_stage1_result.get('error')}")
            return {
                "status": "failed",
                "contract_id": contract_id,
                "error": f"A1-Stage1 실패: {a1_stage1_result.get('error')}",
                "stage": "completeness_stage1"
            }

        logger.info(f"[PARALLEL] [1/2] A1-Stage1 완료")

        # Step 2: A1-Stage2, A2, A3 병렬 실행
        logger.info(f"[PARALLEL] [2/2] A1-Stage2, A2, A3 병렬 실행 중...")

        # ThreadPoolExecutor를 사용한 병렬 실행
        # 주의: 같은 worker 내에서 실행되므로 I/O 바운드 작업만 병렬화됨
        with ThreadPoolExecutor(max_workers=3) as executor:
            # 3개 태스크를 동시 제출
            future_a1_s2 = executor.submit(
                check_missing_articles_task, contract_id, text_weight, title_weight, dense_weight
            )
            future_a2 = executor.submit(
                check_checklist_task, contract_id, ["primary"]
            )
            future_a3 = executor.submit(
                analyze_content_task, contract_id, ["primary"], text_weight, title_weight, dense_weight
            )

            # 결과 수집
            a1_stage2_result = future_a1_s2.result()
            a2_result = future_a2.result()
            a3_result = future_a3.result()

        logger.info(f"[PARALLEL] [2/2] 병렬 실행 완료")

        # 부분 실패 처리
        all_success = all(
            r.get('status') == 'completed'
            for r in [a1_stage2_result, a2_result, a3_result]
        )

        status = "completed" if all_success else "partial"

        if not all_success:
            logger.warning(f"[PARALLEL] 일부 노드 실패: A1-Stage2={a1_stage2_result.get('status')}, "
                          f"A2={a2_result.get('status')}, A3={a3_result.get('status')}")

        logger.info(f"[PARALLEL] 통합 검증 완료: {contract_id}, status={status}")

        return {
            "status": status,
            "contract_id": contract_id,
            "a1_stage1_summary": a1_stage1_result.get('completeness_summary'),
            "a1_stage2_summary": a1_stage2_result.get('missing_summary'),
            "a2_summary": a2_result.get('checklist_summary'),
            "a3_summary": a3_result.get('analysis_summary'),
            "result_id": a3_result.get('result_id') or a1_stage1_result.get('result_id')
        }

    except Exception as e:
        logger.error(f"[PARALLEL] 통합 검증 실패: {contract_id}, 오류: {e}")
        import traceback
        logger.error(f"[PARALLEL] {traceback.format_exc()}")
        return {
            "status": "failed",
            "contract_id": contract_id,
            "error": str(e)
        }
