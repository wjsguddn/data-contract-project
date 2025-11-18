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
from backend.report_agent.step5_final_integrator import Step5FinalIntegrator
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
        self.step4 = Step4Reporter(self.kb_loader)  # kb_loader 전달
        self.step5 = Step5FinalIntegrator()
        
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
        import time
        
        logger.info(f"📋 보고서 생성 시작: {contract_id}")
        total_start_time = time.time()
        
        db = None
        try:
            # 데이터베이스 세션 생성
            db = SessionLocal()
            
            # Step 0: 입력 데이터 로드
            step_start = time.time()
            input_data = self._load_input_data(db, contract_id)
            logger.info(f"⏱️ [Step 0] 입력 데이터 로드 완료 ({time.time() - step_start:.1f}초)")
            
            # Step 1: 정규화 (Primary + Recovered 병합)
            step_start = time.time()
            step1_result = self.step1.normalize(
                a1_result=input_data['a1_result'],
                a3_result=input_data['a3_result'],
                a3_recovered_result=input_data.get('a3_recovered_result'),
                contract_type=input_data['contract_type']
            )
            self._save_step_result(db, contract_id, "report_step1_normalized", step1_result)
            logger.info(f"⏱️ [Step 1] 정규화 완료 ({time.time() - step_start:.1f}초)")
            
            # Step 2: 재집계
            step_start = time.time()
            step2_result = self.step2.aggregate(step1_result)
            self._save_step_result(db, contract_id, "report_step2_aggregated", step2_result)
            logger.info(f"⏱️ [Step 2] 재집계 완료 ({time.time() - step_start:.1f}초)")
            
            # Step 3: 충돌 해소
            step_start = time.time()
            step3_result = self.step3.resolve(
                step2_result=step2_result,
                a3_result=input_data['a3_result'],
                step1_result=step1_result,
                user_contract_data=input_data['user_contract_data']
            )
            self._save_step_result(db, contract_id, "report_step3_resolved", step3_result)
            logger.info(f"⏱️ [Step 3] 충돌 해소 완료 ({time.time() - step_start:.1f}초)")
            
            # Step 4: 포맷팅
            step_start = time.time()
            step4_result = self.step4.generate_final_report(
                step3_result=step3_result,
                contract_id=contract_id,
                contract_type=input_data['contract_type'],
                user_contract_data=input_data['user_contract_data'],
                a1_result=input_data.get('a1_result')  # A1 재검증 정보 전달
            )
            self._save_step_result(db, contract_id, "report_step4_formatted", step4_result)
            logger.info(f"⏱️ [Step 4] 포맷팅 완료 ({time.time() - step_start:.1f}초)")
            
            # Step 5: 체크리스트 통합 + 최종 보고서
            step_start = time.time()
            final_report = self.step5.integrate(
                step4_result=step4_result,
                a2_result=input_data['a2_result'],
                a2_recovered_result=input_data.get('a2_recovered_result'),
                user_contract_data=input_data['user_contract_data']
            )
            logger.info(f"⏱️ [Step 5] 최종 통합 완료 ({time.time() - step_start:.1f}초)")
            
            # 최종 보고서 저장
            step_start = time.time()
            self._save_final_report(db, contract_id, final_report)
            logger.info(f"⏱️ [저장] 최종 보고서 저장 완료 ({time.time() - step_start:.1f}초)")
            
            # 조마다 7개 섹션 생성 및 저장
            step_start = time.time()
            self._generate_and_save_article_sections(
                contract_id=contract_id,
                final_report=final_report,
                user_contract_data=input_data['user_contract_data'],
                contract_type=input_data['contract_type']
            )
            logger.info(f"⏱️ [저장] 조별 보고서 섹션 저장 완료 ({time.time() - step_start:.1f}초)")
            
            total_elapsed = time.time() - total_start_time
            logger.info(f"✅ 보고서 생성 완료: {contract_id} | 총 소요 시간: {total_elapsed:.1f}초 ({total_elapsed/60:.1f}분)")
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
        
        # A2 결과 확인 (선택적 - 없어도 진행)
        if not validation_result.checklist_validation:
            logger.warning(f"A2 체크리스트 검증 결과가 없습니다: {contract_id}")
        
        # A3 결과 확인
        if not validation_result.content_analysis:
            raise ValueError(f"A3 내용 분석 결과가 없습니다: {contract_id}")
        
        # 계약서 원본 데이터 로드
        contract = db.query(ContractDocument).filter(
            ContractDocument.contract_id == contract_id
        ).first()
        
        if not contract or not contract.parsed_data:
            raise ValueError(f"계약서 원본 데이터를 찾을 수 없습니다: {contract_id}")
        
        # A2 결과 로드 (없으면 빈 딕셔너리)
        a2_result = validation_result.checklist_validation or {"matched_articles": []}
        
        # A2 Recovered 결과 로드 (선택적)
        a2_recovered_result = validation_result.checklist_validation_recovered
        
        # A3 Recovered 결과 로드 (선택적)
        a3_recovered_result = validation_result.content_analysis_recovered
        
        # 로그 메시지 생성
        log_parts = ["A1"]
        a2_count = len(a2_result.get('matched_articles', [])) or len(a2_result.get('std_article_results', []))
        log_parts.append(f"A2 Primary ({a2_count}개 조항)")
        if a2_recovered_result:
            a2_recovered_count = len(a2_recovered_result.get('std_article_results', []))
            log_parts.append(f"A2 Recovered ({a2_recovered_count}개 조항)")
        log_parts.append("A3 Primary")
        if a3_recovered_result:
            log_parts.append("A3 Recovered")
        log_parts.append("계약서 원본")
        
        logger.info(f"입력 데이터 로드 완료: {', '.join(log_parts)}")
        
        return {
            "a1_result": validation_result.completeness_check,
            "a2_result": a2_result,  # A2 Primary (없으면 빈 딕셔너리)
            "a2_recovered_result": a2_recovered_result,  # A2 Recovered (없으면 None)
            "a3_result": validation_result.content_analysis,
            "a3_recovered_result": a3_recovered_result,  # A3 Recovered (없으면 None)
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
    
    def _generate_and_save_article_sections(
        self,
        contract_id: str,
        final_report: Dict[str, Any],
        user_contract_data: Dict[str, Any],
        contract_type: str
    ):
        """
        narrative_report (JSON 형식)를 DB에 저장
        
        🔥 narrative_report는 이미 JSON 문자열 형식입니다!
        Step5에서 _convert_narrative_to_json()으로 변환되었으므로
        파싱할 필요 없이 바로 저장하면 됩니다.
        """
        import json
        from backend.report_agent.report_section_saver import save_all_article_sections
        
        user_articles = final_report.get("user_articles", [])
        if not user_articles:
            return
        
        # 모든 조의 보고서 저장
        all_article_reports = {}
        for article in user_articles:
            article_no = article.get("user_article_no")
            narrative_json = article.get("narrative_report", "")  # 이미 JSON 문자열
            article_title = article.get("user_article_title", f"제{article_no}조")
            
            # 🔥 narrative_json은 이미 JSON 문자열이므로 바로 파싱
            if narrative_json and len(narrative_json.strip()) > 10:
                try:
                    sections = json.loads(narrative_json)
                    logger.info(f"✅ [{article_no}] JSON 파싱 성공: {len(sections)}개 섹션")
                except json.JSONDecodeError as e:
                    logger.error(f"❌ [{article_no}] JSON 파싱 실패: {e}")
                    sections = {
                        "section_1_overview": "[데이터 없음]",
                        "section_2_fulfilled_criteria": "[데이터 없음]",
                        "section_3_insufficient_elements": "[데이터 없음]",
                        "section_4_missing_core_elements": "[데이터 없음]",
                        "section_5_practical_risks": "[데이터 없음]",
                        "section_6_improvement_recommendations": "[데이터 없음]",
                        "section_7_comprehensive_judgment": "[데이터 없음]"
                    }
            else:
                sections = {
                    "section_1_overview": "[데이터 없음]",
                    "section_2_fulfilled_criteria": "[데이터 없음]",
                    "section_3_insufficient_elements": "[데이터 없음]",
                    "section_4_missing_core_elements": "[데이터 없음]",
                    "section_5_practical_risks": "[데이터 없음]",
                    "section_6_improvement_recommendations": "[데이터 없음]",
                    "section_7_comprehensive_judgment": "[데이터 없음]"
                }
            
            all_article_reports[article_no] = {
                "article_title": article_title,
                "sections": sections
            }
        
        # DB에 저장
        if all_article_reports:
            save_all_article_sections(contract_id, all_article_reports)
            logger.info(f"✅ 조별 보고서 저장: {len(all_article_reports)}개 조")
