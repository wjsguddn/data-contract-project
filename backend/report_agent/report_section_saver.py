"""
보고서 섹션 저장 유틸리티
"""

import logging
import json
import os
from typing import Dict, Any
from backend.shared.database import SessionLocal, ValidationResult

logger = logging.getLogger(__name__)


def parse_narrative_report(narrative_report: str) -> Dict[str, str]:
    """
    ⚠️ 이 함수는 더 이상 사용되지 않습니다.
    
    narrative_report는 이미 JSON 형식으로 변환되어 저장됩니다.
    agent.py에서 json.loads()로 직접 파싱합니다.
    
    (하위 호환성을 위해 유지)
    """
    import json
    
    sections = {
        "section_1_overview": "[데이터 없음]",
        "section_2_fulfilled_criteria": "[데이터 없음]",
        "section_3_insufficient_elements": "[데이터 없음]",
        "section_4_missing_core_elements": "[데이터 없음]",
        "section_5_practical_risks": "[데이터 없음]",
        "section_6_improvement_recommendations": "[데이터 없음]",
        "section_7_comprehensive_judgment": "[데이터 없음]"
    }
    
    if not narrative_report or len(narrative_report.strip()) < 10:
        logger.warning(f"narrative_report가 비어있음: {len(narrative_report) if narrative_report else 0}자")
        return sections
    
    try:
        # JSON 파싱
        parsed = json.loads(narrative_report)
        
        # 유효한 섹션만 업데이트
        for key in sections.keys():
            if key in parsed and parsed[key]:
                sections[key] = parsed[key]
        
        return sections
        
    except json.JSONDecodeError as e:
        logger.error(f"JSON 파싱 실패: {e}")
        sections['section_1_overview'] = narrative_report.strip()
        return sections


def save_all_article_sections(
    contract_id: str,
    all_article_reports: Dict[int, Dict[str, str]]
) -> bool:
    """
    모든 조의 보고서 섹션을 DB에 저장
    """
    db = SessionLocal()
    try:
        validation_result = db.query(ValidationResult).filter(
            ValidationResult.contract_id == contract_id
        ).first()
        
        if not validation_result:
            logger.error(f"ValidationResult 없음: {contract_id}")
            return False
        
        validation_result.article_reports = all_article_reports
        db.commit()
        logger.info(f"✅ 조별 보고서 저장: {contract_id} ({len(all_article_reports)}개 조)")
        return True
        
    except Exception as e:
        logger.error(f"❌ 저장 실패: {e}")
        db.rollback()
        return False
    finally:
        db.close()


def get_all_article_reports(contract_id: str) -> Dict[int, Dict[str, Any]]:
    """
    모든 조 보고서 조회
    """
    db = SessionLocal()
    try:
        validation_result = db.query(ValidationResult).filter(
            ValidationResult.contract_id == contract_id
        ).first()
        
        return validation_result.article_reports if validation_result else {}
        
    except Exception as e:
        logger.error(f"조회 실패: {e}")
        return {}
    finally:
        db.close()


def get_article_report_sections(
    contract_id: str,
    article_number: int
) -> Dict[str, str]:
    """
    특정 조의 7개 섹션 조회
    """
    all_reports = get_all_article_reports(contract_id)
    
    if article_number in all_reports:
        return all_reports[article_number].get("sections", {})
    
    return {}
