"""
데이터베이스 설정 및 모델
SQLite 사용
"""

from sqlalchemy import create_engine, Column, String, Integer, Float, DateTime, Text, JSON, event
from sqlalchemy.ext.declarative import declarative_base
from sqlalchemy.orm import sessionmaker
from sqlalchemy.exc import OperationalError
from datetime import datetime
import os
import json
import time
import logging

logger = logging.getLogger(__name__)

# 데이터베이스 URL
DATABASE_URL = os.getenv("DATABASE_URL", "sqlite:////app/data/database/contracts.db")

# SQLAlchemy 엔진 생성
engine = create_engine(
    DATABASE_URL,
    connect_args={
        "check_same_thread": False,
        "timeout": 30  # 기본 5초 → 30초로 증가
    } if "sqlite" in DATABASE_URL else {},
    json_serializer=lambda obj: json.dumps(obj, ensure_ascii=False),  # 한글 인코딩 보장
    json_deserializer=lambda obj: json.loads(obj)
)

# SQLite 설정 (병렬 처리 안정성 향상)
# WAL 모드는 비활성화하고 busy_timeout만 설정하여 오탐지 방지
if "sqlite" in DATABASE_URL:
    @event.listens_for(engine, "connect")
    def set_sqlite_pragma(dbapi_conn, connection_record):
        """SQLite 연결 시 busy_timeout 및 격리 레벨 설정"""
        cursor = dbapi_conn.cursor()
        # WAL 모드 비활성화 (오탐지 방지)
        # cursor.execute("PRAGMA journal_mode=WAL")
        cursor.execute("PRAGMA busy_timeout=30000")  # 30초
        # READ UNCOMMITTED 격리 레벨 설정 (다른 트랜잭션의 변경사항 즉시 읽기)
        cursor.execute("PRAGMA read_uncommitted=1")
        cursor.close()
        logger.debug("SQLite busy_timeout 및 read_uncommitted 설정 완료")

# 세션 생성
SessionLocal = sessionmaker(autocommit=False, autoflush=False, bind=engine)

# Base 클래스
Base = declarative_base()


# 모델 정의

class ContractDocument(Base):
    """사용자 계약서 문서"""
    __tablename__ = "contract_documents"

    contract_id = Column(String, primary_key=True, index=True)
    filename = Column(String, nullable=False)
    upload_date = Column(DateTime, default=datetime.utcnow)
    file_path = Column(String, nullable=True)  # 임시 파일 경로
    parsed_data = Column(JSON, nullable=True)  # 파싱된 구조화 데이터
    parsed_metadata = Column(JSON, nullable=True)  # 파싱 메타데이터
    status = Column(String, default="uploaded")  # uploaded, parsing, parsed, classifying, classified, validating, validated, completed, error


class ClassificationResult(Base):
    """계약서 분류 결과"""
    __tablename__ = "classification_results"

    id = Column(Integer, primary_key=True, autoincrement=True)
    contract_id = Column(String, index=True, nullable=False)
    predicted_type = Column(String, nullable=False)  # provide, create, process, brokerage_provider, brokerage_user
    confidence = Column(Float, nullable=False)
    scores = Column(JSON, nullable=True)  # 각 유형별 점수
    reasoning = Column(Text, nullable=True)  # 분류 이유 (내부 로깅용)
    user_override = Column(String, nullable=True)  # 사용자가 수정한 유형
    confirmed_type = Column(String, nullable=False)  # 최종 확정된 유형
    created_at = Column(DateTime, default=datetime.utcnow)


class ValidationResult(Base):
    """정합성 검증 결과"""
    __tablename__ = "validation_results"

    id = Column(Integer, primary_key=True, autoincrement=True)
    contract_id = Column(String, index=True, nullable=False)
    contract_type = Column(String, nullable=True)  # 계약 유형 (A3 노드에서 설정)
    completeness_check = Column(JSON, nullable=True)  # 완전성 검증 결과 (A1 노드)
    checklist_validation = Column(JSON, nullable=True)  # 체크리스트 검증 결과 (A2 노드, primary)
    checklist_validation_recovered = Column(JSON, nullable=True)  # 체크리스트 검증 결과 (A2 노드, recovered)
    manual_checks = Column(JSON, nullable=True)  # 사용자 확인 항목 (A2 노드)
    content_analysis = Column(JSON, nullable=True)  # 내용 분석 결과 (A3 노드, primary)
    content_analysis_recovered = Column(JSON, nullable=True)  # 내용 분석 결과 (A3 노드, recovered)
    overall_score = Column(Float, nullable=True)
    issues = Column(JSON, nullable=True)  # 이슈 리스트
    suggestions = Column(JSON, nullable=True)  # 개선 제안
    recommendations = Column(JSON, nullable=True)  # 권장사항 (agent.py에서 사용)
    # Report Agent 필드
    report_step1_normalized = Column(JSON, nullable=True)  # Step 1: 정규화 결과
    report_step2_aggregated = Column(JSON, nullable=True)  # Step 2: 재집계 결과
    report_step3_resolved = Column(JSON, nullable=True)  # Step 3: 충돌 해소 결과
    report_step4_formatted = Column(JSON, nullable=True)  # Step 4: 포맷팅 결과
    final_report = Column(JSON, nullable=True)  # Step 5: 최종 보고서 (체크리스트 통합)
    article_reports = Column(JSON, nullable=True)  # 조별 보고서 섹션 (파싱된 narrative_report)
    # 검증 타이밍 추적
    validation_timing = Column(JSON, nullable=True)  # 검증 시간 추적 {"start": timestamp, "end": timestamp, "duration": seconds, "stages": {...}}
    created_at = Column(DateTime, default=datetime.utcnow)


class Report(Base):
    """최종 보고서"""
    __tablename__ = "reports"

    id = Column(Integer, primary_key=True, autoincrement=True)
    contract_id = Column(String, index=True, nullable=False)
    contract_type = Column(String, nullable=False)
    validation_date = Column(DateTime, default=datetime.utcnow)
    overall_assessment = Column(JSON, nullable=True)  # 전체 평가
    issues = Column(JSON, nullable=True)  # 이슈 리스트
    positive_points = Column(JSON, nullable=True)  # 긍정적 평가
    recommendations = Column(JSON, nullable=True)  # 개선 권장사항
    created_at = Column(DateTime, default=datetime.utcnow)


class TokenUsage(Base):
    """API 토큰 사용량 추적"""
    __tablename__ = "token_usage"

    id = Column(Integer, primary_key=True, autoincrement=True)
    contract_id = Column(String, index=True, nullable=False)
    component = Column(String, nullable=False)  # classification_agent, consistency_agent
    api_type = Column(String, nullable=False)  # chat_completion, embedding
    model = Column(String, nullable=False)  # gpt-4o, text-embedding-3-large
    prompt_tokens = Column(Integer, default=0)  # 입력 토큰 수
    completion_tokens = Column(Integer, default=0)  # 출력 토큰 수 (chat completion만)
    total_tokens = Column(Integer, default=0)  # 총 토큰 수
    created_at = Column(DateTime, default=datetime.utcnow)
    extra_info = Column(JSON, nullable=True)  # 추가 정보 (예: 작업 상세 내용)


class ChatbotSession(Base):
    """챗봇 대화 세션"""
    __tablename__ = "chatbot_sessions"

    id = Column(Integer, primary_key=True, autoincrement=True)
    session_id = Column(String, index=True, nullable=False)
    contract_id = Column(String, index=True, nullable=False)
    role = Column(String, nullable=False)  # 'user' | 'assistant' | 'system'
    content = Column(Text, nullable=False)
    tool_calls = Column(JSON, nullable=True)  # Function Calling 정보
    created_at = Column(DateTime, default=datetime.utcnow, index=True)


# 데이터베이스 초기화 함수
def init_db():
    """데이터베이스 테이블 생성"""
    Base.metadata.create_all(bind=engine)


# 세션 의존성
def get_db():
    """
    데이터베이스 세션 생성 (FastAPI 의존성)

    Yields:
        Session: 데이터베이스 세션
    """
    db = SessionLocal()
    try:
        yield db
    finally:
        db.close()


# DB 재시도 헬퍼 함수
def db_retry_on_lock(max_retries: int = 3, base_delay: float = 0.5):
    """
    DB Lock 에러 발생 시 재시도하는 데코레이터

    병렬 처리 시 SQLite의 "database is locked" 에러를 처리하기 위한 재시도 로직

    Args:
        max_retries: 최대 재시도 횟수 (기본 3회)
        base_delay: 기본 대기 시간 (초, 기본 0.5초)

    Example:
        @db_retry_on_lock(max_retries=3)
        def update_validation_result(contract_id, data):
            db = SessionLocal()
            try:
                result = db.query(ValidationResult).filter(...).first()
                result.completeness_check = data
                db.commit()
            finally:
                db.close()
    """
    def decorator(func):
        def wrapper(*args, **kwargs):
            last_exception = None

            for attempt in range(max_retries):
                try:
                    return func(*args, **kwargs)

                except OperationalError as e:
                    last_exception = e
                    error_msg = str(e).lower()

                    # "database is locked" 에러인 경우만 재시도
                    if "database is locked" in error_msg or "locked" in error_msg:
                        if attempt < max_retries - 1:
                            # Exponential backoff: 0.5초, 1초, 2초...
                            delay = base_delay * (2 ** attempt)
                            logger.warning(
                                f"DB locked, 재시도 {attempt + 1}/{max_retries} "
                                f"(대기: {delay:.1f}초) - {func.__name__}"
                            )
                            time.sleep(delay)
                            continue
                        else:
                            logger.error(
                                f"DB lock 재시도 {max_retries}회 실패 - {func.__name__}: {e}"
                            )
                            raise
                    else:
                        # 다른 DB 에러는 즉시 raise
                        logger.error(f"DB 에러 (재시도 불가) - {func.__name__}: {e}")
                        raise

                except Exception as e:
                    # DB lock 외 다른 에러는 즉시 raise
                    logger.error(f"예외 발생 - {func.__name__}: {e}")
                    raise

            # 모든 재시도 실패
            if last_exception:
                raise last_exception

        return wrapper
    return decorator


def update_validation_field_with_retry(
    contract_id: str,
    field_name: str,
    data: dict,
    max_retries: int = 3
) -> bool:
    """
    ValidationResult의 특정 필드를 재시도 로직과 함께 업데이트

    병렬 처리 시 각 노드가 독립적으로 자신의 필드만 업데이트하기 위한 헬퍼 함수

    Args:
        contract_id: 계약서 ID
        field_name: 업데이트할 필드명 ("completeness_check", "checklist_validation", "content_analysis")
        data: 저장할 데이터 (dict)
        max_retries: 최대 재시도 횟수

    Returns:
        성공 시 True, 실패 시 False

    Example:
        # A1-stage2에서 누락 검증 결과 업데이트
        success = update_validation_field_with_retry(
            contract_id,
            "completeness_check",
            updated_completeness_check
        )
    """
    @db_retry_on_lock(max_retries=max_retries)
    def _update():
        db = SessionLocal()
        try:
            # ValidationResult 조회
            validation_result = db.query(ValidationResult).filter(
                ValidationResult.contract_id == contract_id
            ).first()

            if not validation_result:
                logger.error(f"ValidationResult를 찾을 수 없음: {contract_id}")
                return False

            # 필드 업데이트
            setattr(validation_result, field_name, data)

            # 커밋
            db.commit()
            logger.info(f"ValidationResult.{field_name} 업데이트 완료: {contract_id}")
            return True

        except Exception as e:
            logger.error(f"ValidationResult.{field_name} 업데이트 실패: {contract_id}, {e}")
            db.rollback()
            raise
        finally:
            db.close()

    try:
        return _update()
    except Exception as e:
        logger.error(f"재시도 후에도 업데이트 실패: {field_name}, {contract_id}, {e}")
        return False


def update_completeness_check_partial_with_retry(
    contract_id: str,
    partial_data: dict,
    max_retries: int = 3
) -> bool:
    """
    completeness_check 필드를 부분적으로 업데이트 (merge)

    A1-stage2에서 missing_article_analysis를 기존 completeness_check에 추가할 때 사용

    Args:
        contract_id: 계약서 ID
        partial_data: 추가할 데이터 (예: {"missing_article_analysis": [...]})
        max_retries: 최대 재시도 횟수

    Returns:
        성공 시 True, 실패 시 False
    """
    @db_retry_on_lock(max_retries=max_retries)
    def _update():
        db = SessionLocal()
        try:
            validation_result = db.query(ValidationResult).filter(
                ValidationResult.contract_id == contract_id
            ).first()

            if not validation_result:
                logger.error(f"ValidationResult를 찾을 수 없음: {contract_id}")
                return False

            # 기존 completeness_check 가져오기
            existing_check = validation_result.completeness_check or {}

            # partial_data를 기존 데이터에 merge
            existing_check.update(partial_data)

            # 업데이트 (새로운 dict 객체를 할당하여 SQLAlchemy가 변경 감지하도록)
            validation_result.completeness_check = dict(existing_check)

            # flag_modified로 명시적으로 변경 표시
            from sqlalchemy.orm.attributes import flag_modified
            flag_modified(validation_result, 'completeness_check')

            db.commit()
            logger.info(f"completeness_check 부분 업데이트 완료: {contract_id}, keys={list(partial_data.keys())}")
            return True

        except Exception as e:
            logger.error(f"completeness_check 부분 업데이트 실패: {contract_id}, {e}")
            db.rollback()
            raise
        finally:
            db.close()

    try:
        return _update()
    except Exception as e:
        logger.error(f"재시도 후에도 부분 업데이트 실패: {contract_id}, {e}")
        return False