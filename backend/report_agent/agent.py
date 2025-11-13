"""
Report Agent 메인 클래스

A1, A2, A3 결과를 통합하여 최종 보고서를 생성합니다.
"""

import logging
from datetime import datetime
from typing import Dict, Any
from openai import AzureOpenAI
import os

from backend.report_agent.exceptions import ReportAgentError
from backend.report_agent.step1_normalizer import Step1Normalizer
from backend.report_agent.step2_aggregator import Step2Aggregator
from backend.report_agent.step3_resolver import Step3Resolver
from backend.report_agent.step4_reporter import Step4Reporter
from backend.shared.database import SessionLocal, ValidationResult, ContractDocument

logger = logging.getLogger(__name__)


class ReportAgent:
    """
    Report Agent 메인 클래스
    
    Step 1: 정규화 (사용자 조항 기준)
    Step 2: 재집계 (표준 항목 기준)
    Step 3: 충돌 해소 (규칙 + LLM)
    Step 4: 최종 보고서 생성
    """
    
    def __init__(self, kb_loader: 'KnowledgeBaseLoader' = None, azure_client: AzureOpenAI = None):
        """
        ReportAgent 초기화
        
        Args:
            kb_loader: KnowledgeBaseLoader 인스턴스 (Step1에서만 사용, None이면 자동 생성)
            azure_client: Azure OpenAI 클라이언트 (None이면 자동 생성)
        """
        from backend.shared.services.knowledge_base_loader import KnowledgeBaseLoader
        
        self.kb_loader = kb_loader or KnowledgeBaseLoader()
        self.azure_client = azure_client or self._init_azure_client()
        
        # Step 컴포넌트 초기화
        self.step1 = Step1Normalizer(self.kb_loader)
        self.step2 = Step2Aggregator()
        self.step3 = Step3Resolver(self.azure_client)
        self.step4 = Step4Reporter()
        
        logger.info("ReportAgent 초기화 완료")
    
    def generate_report(self, contract_id: str) -> Dict[str, Any]:
        """
        최종 보고서 생성
        
        Args:
            contract_id: 계약서 ID
            
        Returns:
            최종 보고서 JSON
            
        Raises:
            ReportAgentError: 보고서 생성 실패
        """
        logger.info(f"보고서 생성 시작: {contract_id}")
        
        db = None
        try:
            # 데이터베이스 세션 생성
            db = SessionLocal()
            
            # Step 0: 입력 데이터 로드
            logger.info(f"[Step 0] 입력 데이터 로드 중...")
            input_data = self._load_input_data(db, contract_id)
            
            # Step 1: 정규화
            logger.info(f"[Step 1] 정규화 시작...")
            step1_result = self.step1.normalize(
                a1_result=input_data['a1_result'],
                a3_result=input_data['a3_result'],
                contract_type=input_data['contract_type']
            )
            logger.info(f"[Step 1] 정규화 완료: "
                       f"전역 누락 {len(step1_result['overall_missing_clauses'])}개, "
                       f"사용자 조항 {len(step1_result['user_articles'])}개")
            
            # Step 1 결과 저장
            self._save_step_result(db, contract_id, "report_step1_normalized", step1_result)
            
            # Step 2: 재집계
            logger.info(f"[Step 2] 재집계 시작...")
            step2_result = self.step2.aggregate(step1_result)
            logger.info(f"[Step 2] 재집계 완료: "
                       f"충돌 {step2_result['conflict_count']}개")
            
            # Step 2 결과 저장
            self._save_step_result(db, contract_id, "report_step2_aggregated", step2_result)
            
            # Step 3: 충돌 해소
            logger.info(f"[Step 3] 충돌 해소 시작...")
            step3_result = self.step3.resolve(
                step2_result=step2_result,
                a3_result=input_data['a3_result'],
                step1_result=step1_result
            )
            logger.info(f"[Step 3] 충돌 해소 완료: "
                       f"해소된 충돌 {step3_result.get('resolved_conflicts', 0)}개")
            
            # Step 3 결과 저장
            self._save_step_result(db, contract_id, "report_step3_resolved", step3_result)
            
            # Step 4: 최종 보고서 생성
            logger.info(f"[Step 4] 최종 보고서 생성 시작...")
            final_report = self.step4.generate_final_report(
                step3_result=step3_result,
                contract_id=contract_id,
                contract_type=input_data['contract_type'],
                user_contract_data=input_data['user_contract_data']
            )
            logger.info(f"[Step 4] 최종 보고서 생성 완료")
            
            # 최종 보고서 저장
            self._save_final_report(db, contract_id, final_report)
            
            logger.info(f"보고서 생성 완료: {contract_id}")
            return final_report
            
        except Exception as e:
            logger.error(f"보고서 생성 실패: {contract_id}, 오류: {e}")
            
            # 실패 상태 저장
            if db:
                try:
                    self._update_status(db, contract_id, "failed")
                except Exception as save_error:
                    logger.error(f"실패 상태 저장 실패: {save_error}")
            
            raise ReportAgentError(f"보고서 생성 실패: {e}") from e
        
        finally:
            if db:
                db.close()
    
    def _load_input_data(self, db, contract_id: str) -> Dict[str, Any]:
        """
        데이터베이스에서 A1, A3 결과 및 계약서 데이터 로드
        
        Args:
            db: 데이터베이스 세션
            contract_id: 계약서 ID
            
        Returns:
            입력 데이터 딕셔너리
            
        Raises:
            ValueError: 필수 데이터가 없는 경우
        """
        # ValidationResult 조회
        validation_result = db.query(ValidationResult).filter(
            ValidationResult.contract_id == contract_id
        ).first()
        
        if not validation_result:
            raise ValueError(f"검증 결과를 찾을 수 없습니다: {contract_id}")
        
        # A1 결과 확인
        if not validation_result.completeness_check:
            raise ValueError(f"A1 완전성 검증 결과가 없습니다: {contract_id}")
        
        # A3 결과 확인
        if not validation_result.content_analysis:
            raise ValueError(f"A3 내용 분석 결과가 없습니다: {contract_id}")
        
        # 계약서 원본 데이터 로드
        contract = db.query(ContractDocument).filter(
            ContractDocument.contract_id == contract_id
        ).first()
        
        if not contract or not contract.parsed_data:
            raise ValueError(f"계약서 원본 데이터를 찾을 수 없습니다: {contract_id}")
        
        logger.info(f"입력 데이터 로드 완료: A1, A3, 계약서 원본")
        
        return {
            "a1_result": validation_result.completeness_check,
            "a3_result": validation_result.content_analysis,
            "contract_type": validation_result.contract_type,
            "user_contract_data": contract.parsed_data
        }
    
    def _save_step_result(self, db, contract_id: str, field_name: str, data: Dict[str, Any]):
        """
        Step 결과를 데이터베이스에 저장
        
        Args:
            db: 데이터베이스 세션
            contract_id: 계약서 ID
            field_name: 저장할 필드명
            data: 저장할 데이터
        """
        try:
            validation_result = db.query(ValidationResult).filter(
                ValidationResult.contract_id == contract_id
            ).first()
            
            if validation_result:
                setattr(validation_result, field_name, data)
                db.commit()
                logger.info(f"{field_name} 저장 완료")
            else:
                logger.warning(f"ValidationResult를 찾을 수 없음: {contract_id}")
        
        except Exception as e:
            logger.error(f"{field_name} 저장 실패: {e}")
            db.rollback()
    
    def _save_final_report(self, db, contract_id: str, report: Dict[str, Any]):
        """
        최종 보고서를 데이터베이스에 저장
        
        Args:
            db: 데이터베이스 세션
            contract_id: 계약서 ID
            report: 최종 보고서
        """
        try:
            validation_result = db.query(ValidationResult).filter(
                ValidationResult.contract_id == contract_id
            ).first()
            
            if validation_result:
                validation_result.final_report = report
                db.commit()
                logger.info(f"최종 보고서 저장 완료")
                
                # 상태 업데이트
                self._update_status(db, contract_id, "completed")
            else:
                logger.warning(f"ValidationResult를 찾을 수 없음: {contract_id}")
        
        except Exception as e:
            logger.error(f"최종 보고서 저장 실패: {e}")
            db.rollback()
    
    def _update_status(self, db, contract_id: str, status: str):
        """
        검증 상태 업데이트
        
        Args:
            db: 데이터베이스 세션
            contract_id: 계약서 ID
            status: 상태 ("generating_report", "completed", "failed")
        """
        try:
            from backend.shared.database import ContractDocument
            
            contract = db.query(ContractDocument).filter(
                ContractDocument.contract_id == contract_id
            ).first()
            
            if contract:
                contract.status = status
                db.commit()
                logger.info(f"상태 업데이트: {status}")
        
        except Exception as e:
            logger.error(f"상태 업데이트 실패: {e}")
            db.rollback()
    
    def _init_azure_client(self) -> AzureOpenAI:
        """
        Azure OpenAI 클라이언트 초기화
        
        Returns:
            AzureOpenAI 클라이언트
            
        Raises:
            ValueError: 환경 변수가 설정되지 않은 경우
        """
        api_key = os.getenv('AZURE_OPENAI_API_KEY')
        endpoint = os.getenv('AZURE_OPENAI_ENDPOINT')
        
        if not api_key or not endpoint:
            raise ValueError("Azure OpenAI 환경 변수가 설정되지 않았습니다")
        
        client = AzureOpenAI(
            api_key=api_key,
            azure_endpoint=endpoint,
            api_version="2024-02-01"
        )
        
        logger.info("Azure OpenAI 클라이언트 초기화 완료")
        return client
