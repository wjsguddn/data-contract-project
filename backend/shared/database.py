"""
데이터베이스 설정 및 모델
SQLite 사용
"""

from sqlalchemy import create_engine, Column, String, Integer, Float, DateTime, Text, JSON
from sqlalchemy.ext.declarative import declarative_base
from sqlalchemy.orm import sessionmaker
from datetime import datetime
import os
import json

# 데이터베이스 URL
DATABASE_URL = os.getenv("DATABASE_URL", "sqlite:////app/data/database/contracts.db")

# SQLAlchemy 엔진 생성
engine = create_engine(
    DATABASE_URL,
    connect_args={"check_same_thread": False} if "sqlite" in DATABASE_URL else {},
    json_serializer=lambda obj: json.dumps(obj, ensure_ascii=False),  # 한글 인코딩 보장
    json_deserializer=lambda obj: json.loads(obj)
)

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
    checklist_validation = Column(JSON, nullable=True)  # 체크리스트 검증 결과 (A2 노드)
    manual_checks = Column(JSON, nullable=True)  # 사용자 확인 항목 (A2 노드)
    content_analysis = Column(JSON, nullable=True)  # 내용 분석 결과 (A3 노드)
    overall_score = Column(Float, nullable=True)
    issues = Column(JSON, nullable=True)  # 이슈 리스트
    suggestions = Column(JSON, nullable=True)  # 개선 제안
    recommendations = Column(JSON, nullable=True)  # 권장사항 (agent.py에서 사용)
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
