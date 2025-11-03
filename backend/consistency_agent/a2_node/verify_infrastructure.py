"""
A2 노드 인프라 검증 스크립트

1. ValidationResult DB 모델 확인
2. 체크리스트 JSON 파일 확인
3. A1 매칭 결과 구조 확인 (상세)
"""

import os
import json
import sys
import logging
from pathlib import Path
from typing import Dict, Any, List

# 프로젝트 루트를 sys.path에 추가
project_root = Path(__file__).parent.parent.parent.parent
sys.path.insert(0, str(project_root))

# 작업 디렉토리를 프로젝트 루트로 변경
os.chdir(project_root)

# .env 파일 로드
from dotenv import load_dotenv
load_dotenv()

from backend.shared.database import ValidationResult, SessionLocal, init_db

# 로깅 설정
logging.basicConfig(level=logging.INFO)
logger = logging.getLogger(__name__)


def verify_db_model():
    """ValidationResult DB 모델 확인"""
    print("=" * 80)
    print("1. ValidationResult DB 모델 확인")
    print("=" * 80)
    
    # 데이터베이스 파일 확인
    db_path = project_root / "data" / "database" / "contracts.db"
    if db_path.exists():
        print(f"\n✓ 데이터베이스 파일 존재: {db_path}")
    else:
        print(f"\n⚠ 데이터베이스 파일 없음: {db_path}")
        print("  (정상 - 첫 실행 시 자동 생성됩니다)")
    
    # 테이블 초기화 (없으면 생성)
    try:
        init_db()
    except Exception as e:
        print(f"\n✗ 데이터베이스 초기화 실패: {e}")
        return False
    
    # ValidationResult 모델 확인
    print("\n✓ ValidationResult 모델 필드:")
    for column in ValidationResult.__table__.columns:
        print(f"  - {column.name}: {column.type}")
    
    # checklist_validation 필드 확인
    if hasattr(ValidationResult, 'checklist_validation'):
        print("\n✓ checklist_validation 필드 존재 확인: OK")
        print(f"  - 타입: {ValidationResult.checklist_validation.type}")
    else:
        print("\n✗ checklist_validation 필드 없음!")
        return False
    
    return True


def verify_checklist_files():
    """체크리스트 JSON 파일 확인"""
    print("\n" + "=" * 80)
    print("2. 체크리스트 JSON 파일 확인")
    print("=" * 80)
    
    checklist_dir = project_root / "data" / "chunked_documents" / "guidebook_chunked_documents" / "checklist_documents"
    
    if not checklist_dir.exists():
        print(f"\n✗ 체크리스트 디렉토리 없음: {checklist_dir}")
        return False
    
    print(f"\n✓ 체크리스트 디렉토리 존재: {checklist_dir}")
    
    # 5종 계약 유형
    contract_types = ['provide', 'create', 'process', 'brokerage_provider', 'brokerage_user']
    
    all_files_exist = True
    for contract_type in contract_types:
        filename = f"{contract_type}_gud_contract_check_chunks_flat.json"
        filepath = checklist_dir / filename
        
        if filepath.exists():
            print(f"\n✓ {contract_type}: {filename}")
            
            # JSON 구조 검증
            try:
                with open(filepath, 'r', encoding='utf-8') as f:
                    data = json.load(f)
                
                if not isinstance(data, list):
                    print(f"  ✗ JSON이 리스트가 아님!")
                    all_files_exist = False
                    continue
                
                print(f"  - 항목 수: {len(data)}개")
                
                # 첫 번째 항목 구조 확인
                if len(data) > 0:
                    first_item = data[0]
                    required_fields = ['check_text', 'reference', 'global_id']
                    
                    missing_fields = [field for field in required_fields if field not in first_item]
                    
                    if missing_fields:
                        print(f"  ✗ 필수 필드 누락: {missing_fields}")
                        all_files_exist = False
                    else:
                        print(f"  ✓ 필수 필드 확인: {required_fields}")
                        print(f"  - 샘플 check_text: {first_item['check_text'][:50]}...")
                        print(f"  - 샘플 global_id: {first_item['global_id']}")
                
            except json.JSONDecodeError as e:
                print(f"  ✗ JSON 파싱 실패: {e}")
                all_files_exist = False
            except Exception as e:
                print(f"  ✗ 파일 읽기 실패: {e}")
                all_files_exist = False
        else:
            print(f"\n✗ {contract_type}: 파일 없음 - {filename}")
            all_files_exist = False
    
    return all_files_exist


class A1StructureValidator:
    """A1 노드 출력 구조 검증기"""
    
    def __init__(self):
        self.validation_errors = []
        self.validation_warnings = []
    
    def validate_completeness_check(self, completeness_check: Dict[str, Any]) -> bool:
        """
        completeness_check 구조 검증
        
        Args:
            completeness_check: A1 노드의 check_completeness() 반환값
            
        Returns:
            검증 성공 여부
        """
        logger.info("=" * 80)
        logger.info("A1 매칭 결과 구조 검증 시작")
        logger.info("=" * 80)
        
        self.validation_errors = []
        self.validation_warnings = []
        
        # 1. 최상위 필드 검증
        logger.info("\n[1] 최상위 필드 검증")
        required_top_fields = [
            'contract_id',
            'contract_type',
            'total_user_articles',
            'matched_user_articles',
            'total_standard_articles',
            'matched_standard_articles',
            'missing_standard_articles',
            'matching_details',
            'processing_time',
            'verification_date'
        ]
        
        for field in required_top_fields:
            if field in completeness_check:
                logger.info(f"  ✓ {field}: {type(completeness_check[field]).__name__}")
            else:
                error_msg = f"  ✗ 필수 필드 누락: {field}"
                logger.error(error_msg)
                self.validation_errors.append(error_msg)
        
        # 2. matching_details 배열 구조 검증
        logger.info("\n[2] matching_details 배열 구조 검증")
        matching_details = completeness_check.get('matching_details', [])
        
        if not isinstance(matching_details, list):
            error_msg = f"  ✗ matching_details가 리스트가 아님: {type(matching_details)}"
            logger.error(error_msg)
            self.validation_errors.append(error_msg)
            return False
        
        logger.info(f"  ✓ matching_details 배열 크기: {len(matching_details)}개")
        
        if len(matching_details) == 0:
            warning_msg = "  ⚠ matching_details가 비어있음 (조항이 없는 계약서일 수 있음)"
            logger.warning(warning_msg)
            self.validation_warnings.append(warning_msg)
            return True
        
        # 3. matching_details 항목별 필드 검증
        logger.info("\n[3] matching_details 항목별 필드 검증")
        required_detail_fields = [
            'user_article_no',
            'user_article_id',
            'user_article_title',
            'matched',
            'matched_articles',
            'verification_details'
        ]
        
        # A2 노드에서 필요한 추가 필드
        a2_required_fields = [
            'matched_articles_global_ids',  # A2 노드에서 체크리스트 필터링에 사용
            'matched_articles_details'       # 상세 점수 정보
        ]
        
        sample_detail = matching_details[0]
        logger.info(f"  샘플 항목 (제{sample_detail.get('user_article_no')}조):")
        
        for field in required_detail_fields:
            if field in sample_detail:
                value = sample_detail[field]
                logger.info(f"    ✓ {field}: {type(value).__name__}")
                
                # 타입별 상세 정보
                if field == 'matched' and isinstance(value, bool):
                    logger.info(f"      → 매칭 여부: {value}")
                elif field == 'matched_articles' and isinstance(value, list):
                    logger.info(f"      → 매칭된 조항 수: {len(value)}개")
                    if len(value) > 0:
                        logger.info(f"      → 예시: {value[0]}")
            else:
                error_msg = f"    ✗ 필수 필드 누락: {field}"
                logger.error(error_msg)
                self.validation_errors.append(error_msg)
        
        # A2 노드 필수 필드 검증
        logger.info("\n  [A2 노드 필수 필드 검증]")
        for field in a2_required_fields:
            if field in sample_detail:
                value = sample_detail[field]
                logger.info(f"    ✓ {field}: {type(value).__name__}")
                
                if field == 'matched_articles_global_ids' and isinstance(value, list):
                    logger.info(f"      → global_id 수: {len(value)}개")
                    if len(value) > 0:
                        logger.info(f"      → 예시: {value[0]}")
                elif field == 'matched_articles_details' and isinstance(value, list):
                    logger.info(f"      → 상세 정보 수: {len(value)}개")
                    if len(value) > 0:
                        detail = value[0]
                        logger.info(f"      → 예시 필드: {list(detail.keys())}")
            else:
                error_msg = f"    ✗ A2 필수 필드 누락: {field}"
                logger.error(error_msg)
                self.validation_errors.append(error_msg)
        
        # 4. matched_articles_global_ids 상세 검증
        logger.info("\n[4] matched_articles_global_ids 상세 검증")
        
        matched_items = [d for d in matching_details if d.get('matched', False)]
        logger.info(f"  매칭된 항목 수: {len(matched_items)}개")
        
        if len(matched_items) > 0:
            for i, detail in enumerate(matched_items[:3], 1):  # 최대 3개만 샘플 검증
                user_no = detail.get('user_article_no')
                global_ids = detail.get('matched_articles_global_ids', [])
                parent_ids = detail.get('matched_articles', [])
                
                logger.info(f"\n  샘플 {i}: 제{user_no}조")
                logger.info(f"    - matched_articles (parent_id): {parent_ids}")
                logger.info(f"    - matched_articles_global_ids: {global_ids}")
                
                # global_id 형식 검증
                for gid in global_ids:
                    if not isinstance(gid, str):
                        error_msg = f"    ✗ global_id가 문자열이 아님: {type(gid)}"
                        logger.error(error_msg)
                        self.validation_errors.append(error_msg)
                    elif not gid.startswith('urn:std:'):
                        warning_msg = f"    ⚠ global_id 형식이 예상과 다름: {gid}"
                        logger.warning(warning_msg)
                        self.validation_warnings.append(warning_msg)
                    else:
                        logger.info(f"      ✓ {gid}")
                
                # parent_id와 global_id 개수 일치 확인
                if len(parent_ids) != len(global_ids):
                    error_msg = f"    ✗ parent_id와 global_id 개수 불일치: {len(parent_ids)} vs {len(global_ids)}"
                    logger.error(error_msg)
                    self.validation_errors.append(error_msg)
        
        # 5. missing_standard_articles 구조 검증
        logger.info("\n[5] missing_standard_articles 구조 검증")
        missing_articles = completeness_check.get('missing_standard_articles', [])
        
        if not isinstance(missing_articles, list):
            error_msg = f"  ✗ missing_standard_articles가 리스트가 아님: {type(missing_articles)}"
            logger.error(error_msg)
            self.validation_errors.append(error_msg)
        else:
            logger.info(f"  ✓ 누락 조항 수: {len(missing_articles)}개")
            
            # 누락 조항 상세 출력
            if len(missing_articles) > 0:
                logger.info(f"\n  누락 조항 목록:")
                for i, missing in enumerate(missing_articles[:5], 1):  # 최대 5개만
                    parent_id = missing.get('parent_id')
                    title = missing.get('title')
                    logger.info(f"    {i}. {parent_id} - {title}")
        
        # 6. 검증 결과 요약
        logger.info("\n" + "=" * 80)
        logger.info("검증 결과 요약")
        logger.info("=" * 80)
        
        if len(self.validation_errors) == 0:
            logger.info("✓ 모든 필수 필드 검증 통과")
            if len(self.validation_warnings) > 0:
                logger.warning(f"⚠ 경고 {len(self.validation_warnings)}개:")
                for warning in self.validation_warnings:
                    logger.warning(f"  {warning}")
            return True
        else:
            logger.error(f"✗ 검증 실패: {len(self.validation_errors)}개 오류")
            for error in self.validation_errors:
                logger.error(f"  {error}")
            return False
    
    def print_structure_summary(self, completeness_check: Dict[str, Any]):
        """구조 요약 출력"""
        logger.info("\n" + "=" * 80)
        logger.info("A1 매칭 결과 구조 요약")
        logger.info("=" * 80)
        
        logger.info(f"\n계약서 정보:")
        logger.info(f"  - contract_id: {completeness_check.get('contract_id')}")
        logger.info(f"  - contract_type: {completeness_check.get('contract_type')}")
        
        logger.info(f"\n통계:")
        logger.info(f"  - 사용자 조항: {completeness_check.get('total_user_articles')}개")
        logger.info(f"  - 매칭된 사용자 조항: {completeness_check.get('matched_user_articles')}개")
        logger.info(f"  - 표준 조항: {completeness_check.get('total_standard_articles')}개")
        logger.info(f"  - 매칭된 표준 조항: {completeness_check.get('matched_standard_articles')}개")
        logger.info(f"  - 누락 조항: {len(completeness_check.get('missing_standard_articles', []))}개")
        
        logger.info(f"\n처리 정보:")
        logger.info(f"  - 처리 시간: {completeness_check.get('processing_time'):.2f}초")
        logger.info(f"  - 검증 일시: {completeness_check.get('verification_date')}")


def verify_a1_structure():
    """A1 매칭 결과 구조 확인 (상세)"""
    print("\n" + "=" * 80)
    print("3. A1 매칭 결과 구조 확인 (상세)")
    print("=" * 80)
    
    # DB에서 샘플 데이터 조회
    db = SessionLocal()
    try:
        # completeness_check가 있는 ValidationResult 조회
        validation_result = db.query(ValidationResult).filter(
            ValidationResult.completeness_check.isnot(None)
        ).first()
        
        if not validation_result:
            print("\n⚠ DB에 A1 결과가 없습니다 (정상 - 아직 실행 전)")
            print("  예상 구조:")
            print("  {")
            print('    "matching_details": [')
            print("      {")
            print('        "user_article_no": 1,')
            print('        "user_article_id": "user_article_001",')
            print('        "user_article_title": "목적",')
            print('        "matched": true,')
            print('        "matched_articles": ["제1조"],')
            print('        "matched_articles_global_ids": ["urn:std:provide:art:001"],')
            print('        "matched_articles_details": [...]')
            print("      }")
            print("    ]")
            print("  }")
            return True
        
        print(f"\n✓ ValidationResult 발견: contract_id={validation_result.contract_id}")
        
        completeness_check = validation_result.completeness_check
        
        # 상세 검증 수행
        validator = A1StructureValidator()
        
        # 구조 요약 출력
        validator.print_structure_summary(completeness_check)
        
        # 검증 수행
        is_valid = validator.validate_completeness_check(completeness_check)
        
        return is_valid
        
    except Exception as e:
        print(f"\n✗ A1 구조 확인 실패: {e}")
        import traceback
        traceback.print_exc()
        return False
    finally:
        db.close()


def main():
    """메인 검증 함수"""
    print("\n" + "=" * 80)
    print("A2 노드 인프라 검증")
    print("=" * 80)
    
    results = []
    
    # 1. DB 모델 확인
    results.append(("DB 모델", verify_db_model()))
    
    # 2. 체크리스트 파일 확인
    results.append(("체크리스트 파일", verify_checklist_files()))
    
    # 3. A1 구조 확인
    results.append(("A1 매칭 결과", verify_a1_structure()))
    
    # 결과 요약
    print("\n" + "=" * 80)
    print("검증 결과 요약")
    print("=" * 80)
    
    all_passed = True
    for name, passed in results:
        status = "✓ PASS" if passed else "✗ FAIL"
        print(f"{status}: {name}")
        if not passed:
            all_passed = False
    
    print("\n" + "=" * 80)
    if all_passed:
        print("✓ 모든 인프라 검증 통과!")
        print("A2 노드 구현을 시작할 수 있습니다.")
    else:
        print("✗ 일부 검증 실패")
        print("실패한 항목을 확인하고 수정해주세요.")
    print("=" * 80)
    
    return 0 if all_passed else 1


if __name__ == "__main__":
    sys.exit(main())
