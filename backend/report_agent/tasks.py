"""
Report Agent Celery Tasks
보고서 생성 비동기 작업
"""
import logging
from celery import shared_task
from backend.report_agent.agent import ReportAgent

logger = logging.getLogger(__name__)


@shared_task(name="report_agent.generate_report", bind=True)
def generate_report_task(self, contract_id: str):
    """
    보고서 생성 Celery 작업
    
    Args:
        contract_id: 계약서 ID
        
    Returns:
        dict: 보고서 생성 결과
    """
    try:
        logger.info(f"[REPORT] 보고서 생성 시작: {contract_id}")
        
        # Report Agent 실행
        agent = ReportAgent()
        result = agent.generate_report(contract_id)
        
        logger.info(f"[REPORT] 보고서 생성 완료: {contract_id}")
        return result
        
    except Exception as e:
        logger.error(f"[REPORT] 보고서 생성 실패: {contract_id}, error={str(e)}", exc_info=True)
        raise
