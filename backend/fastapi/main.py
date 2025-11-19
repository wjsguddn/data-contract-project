import sys
from pathlib import Path
sys.path.append('/app')

from fastapi import FastAPI, UploadFile, File, HTTPException, Depends
from fastapi.responses import JSONResponse
from sqlalchemy.orm import Session
import logging
import json
logger = logging.getLogger("uvicorn.error")

from backend.fastapi.user_contract_parser import UserContractParser
from backend.shared.database import init_db, get_db, ContractDocument, ClassificationResult, ValidationResult, TokenUsage, ChatbotSession
from backend.classification_agent.agent import classify_contract_task
from backend.consistency_agent.agent import validate_contract_task, validate_contract_parallel_task

app = FastAPI()


# 시작 시 DB 초기화
@app.on_event("startup")
async def startup_event():
    """애플리케이션 시작 시 실행"""
    logger.info("데이터베이스 초기화 중...")
    init_db()
    logger.info("데이터베이스 초기화 완료")
    
    # 지식베이스 상태 확인
    try:
        from backend.shared.services import get_knowledge_base_loader
        loader = get_knowledge_base_loader()
        status = loader.verify_knowledge_base()
        
        logger.info(f"지식베이스 상태: {status['status']}")
        logger.info(f"사용 가능한 계약 유형: {status['available_types']}")
        
        if status['missing_types']:
            logger.warning(f"누락된 계약 유형: {status['missing_types']}")
            logger.warning("ingestion CLI를 실행하여 지식베이스를 구축하세요.")
    except Exception as e:
        logger.error(f"지식베이스 상태 확인 실패: {e}")


@app.get("/")
async def root():
    return {"message": "FastAPI 서버 실행 중"}


@app.get("/api/knowledge-base/status")
async def knowledge_base_status():
    """
    지식베이스 상태 확인
    
    Returns:
        {
            "status": "ok" | "incomplete" | "missing",
            "available_types": [...],
            "missing_types": [...],
            "details": {...}
        }
    """
    try:
        from backend.shared.services import get_knowledge_base_loader
        
        loader = get_knowledge_base_loader()
        status = loader.verify_knowledge_base()
        
        return status
        
    except Exception as e:
        logger.exception(f"지식베이스 상태 확인 중 오류: {e}")
        raise HTTPException(status_code=500, detail=str(e))


def _temp_file_path(filename: str) -> Path:
    """임시 파일 경로 생성"""
    base = Path("/tmp/uploads")
    base.mkdir(parents=True, exist_ok=True)
    return base / filename


@app.post("/upload")
async def upload_file(file: UploadFile = File(...), db: Session = Depends(get_db)):
    """
    사용자 계약서 DOCX 업로드 및 파싱
    
    Args:
        file: 업로드된 DOCX 파일
        db: 데이터베이스 세션
        
    Returns:
        {
            "success": bool,
            "filename": str,
            "contract_id": str,
            "structured_data": dict,
            "parsed_metadata": dict
        }
    """
    try:
        filename = Path(file.filename).name
        
        # DOCX 파일만 허용
        if not filename.lower().endswith('.docx'):
            raise HTTPException(status_code=400, detail="DOCX 파일만 허용됩니다.")

        # 임시 파일 저장
        temp_path = _temp_file_path(filename)
        content = await file.read()
        with open(temp_path, 'wb') as f:
            f.write(content)

        # 사용자 계약서 파싱
        parser = UserContractParser()
        result = parser.parse_to_dict(temp_path)
        
        if not result["success"]:
            raise HTTPException(
                status_code=500, 
                detail=f"파싱 실패: {result.get('error', 'Unknown error')}"
            )
        
        # contract_id 생성
        import uuid
        contract_id = f"contract_{uuid.uuid4().hex[:12]}"
        
        # DB에 저장
        contract_doc = ContractDocument(
            contract_id=contract_id,
            filename=filename,
            file_path=str(temp_path),
            parsed_data=result["structured_data"],
            parsed_metadata=result["parsed_metadata"],
            status="parsed"
        )
        db.add(contract_doc)
        db.commit()
        db.refresh(contract_doc)

        # 파싱된 데이터를 JSON 파일로 저장 (임베딩 전 상태)
        try:
            parsed_contracts_dir = Path("data/parsed_user_contracts")
            parsed_contracts_dir.mkdir(parents=True, exist_ok=True)

            # 원본 파일명.json으로 저장
            output_filename = Path(filename).stem + ".json"
            output_path = parsed_contracts_dir / output_filename

            with open(output_path, 'w', encoding='utf-8') as f:
                json.dump(result["structured_data"], f, ensure_ascii=False, indent=2)

            logger.info(f"Parsed data saved to file: {output_path}")
        except Exception as save_err:
            logger.error(f"Failed to save parsed data to file: {save_err}")

        # 임베딩 생성 및 저장
        try:
            from backend.shared.services.embedding_generator import EmbeddingGenerator

            generator = EmbeddingGenerator()
            embeddings = generator.generate_embeddings(
                contract_id=contract_id,
                parsed_data=contract_doc.parsed_data
            )

            updated_parsed = dict(contract_doc.parsed_data or {})
            updated_parsed["embeddings"] = embeddings
            contract_doc.parsed_data = updated_parsed
            db.commit()

            logger.info(f"Embedding generation completed: {contract_id}")
        except Exception as embed_err:
            logger.error(f"Embedding generation failed: {contract_id}, {embed_err}")

        # 사용자 계약서 인덱싱 (임베딩 생성 직후 실행)
        try:
            from backend.fastapi.user_contract_indexer import index_user_contract

            indexing_result = index_user_contract(contract_id)
            if indexing_result.get("success"):
                logger.info(
                    f"User contract indexing completed: {contract_id} "
                    f"({indexing_result.get('total_chunks', 0)} chunks indexed)"
                )
            else:
                logger.error(
                    f"User contract indexing failed: {contract_id}, "
                    f"{indexing_result.get('error', 'Unknown error')}"
                )
        except Exception as index_err:
            logger.error(f"User contract indexing failed: {contract_id}, {index_err}")
            import traceback
            logger.error(traceback.format_exc())

        logger.info(f"Contract saved: {contract_id}")

        # 임시 파일 삭제
        try:
            temp_path.unlink()
        except Exception as e:
            logger.warning(f"임시 파일 삭제 실패: {e}")

        # Celery를 통해 분류 작업을 큐에 전송 (인덱싱과 병렬 실행)
        try:
            task = classify_contract_task.delay(contract_id)
            logger.info(f"분류 작업 큐에 전송: {contract_id}, Task ID: {task.id}")

            # 계약서 상태를 classifying으로 업데이트
            contract_doc.status = "classifying"
            db.commit()

        except Exception as e:
            logger.error(f"분류 작업 큐 전송 실패: {e}")

        return JSONResponse(
            content={
                "success": True,
                "filename": filename,
                "contract_id": contract_id,
                "structured_data": result["structured_data"],
                "parsed_metadata": result["parsed_metadata"],
                "message": "파싱 완료. 분류 작업이 백그라운드에서 진행 중입니다."
            },
            media_type="application/json; charset=utf-8"
        )
        
    except HTTPException:
        raise
    except Exception as e:
        logger.exception(f"업로드 처리 중 오류: {e}")
        raise HTTPException(status_code=500, detail=str(e))


@app.post("/api/classification/{contract_id}/start")
async def start_classification(contract_id: str, db: Session = Depends(get_db)):
    """
    계약서 분류 시작 (수동 트리거)

    Args:
        contract_id: 계약서 ID
        db: 데이터베이스 세션

    Returns:
        {
            "success": bool,
            "contract_id": str,
            "task_id": str,
            "message": str
        }
    """
    try:
        # 계약서 조회
        contract = db.query(ContractDocument).filter(
            ContractDocument.contract_id == contract_id
        ).first()

        if not contract:
            raise HTTPException(status_code=404, detail="계약서를 찾을 수 없습니다")

        if not contract.parsed_data:
            raise HTTPException(status_code=400, detail="파싱된 데이터가 없습니다")

        # Celery Task 큐에 전송
        task = classify_contract_task.delay(contract_id)

        # 계약서 상태 업데이트
        contract.status = "classifying"
        db.commit()

        logger.info(f"분류 작업 큐에 전송: {contract_id}, Task ID: {task.id}")

        return {
            "success": True,
            "contract_id": contract_id,
            "task_id": task.id,
            "message": "분류 작업이 시작되었습니다. /api/classification/{contract_id}로 결과를 조회하세요."
        }

    except HTTPException:
        raise
    except Exception as e:
        logger.exception(f"분류 시작 중 오류: {e}")
        raise HTTPException(status_code=500, detail=str(e))


@app.get("/api/classification/{contract_id}")
async def get_classification(contract_id: str, db: Session = Depends(get_db)):
    """
    분류 결과 조회

    Args:
        contract_id: 계약서 ID
        db: 데이터베이스 세션

    Returns:
        분류 결과
    """
    try:
        classification = db.query(ClassificationResult).filter(
            ClassificationResult.contract_id == contract_id
        ).first()

        if not classification:
            raise HTTPException(status_code=404, detail="분류 결과를 찾을 수 없습니다")

        return {
            "contract_id": classification.contract_id,
            "predicted_type": classification.predicted_type,
            "confidence": classification.confidence,
            "scores": classification.scores,
            "confirmed_type": classification.confirmed_type,
            "user_override": classification.user_override
        }

    except HTTPException:
        raise
    except Exception as e:
        logger.exception(f"분류 조회 중 오류: {e}")
        raise HTTPException(status_code=500, detail=str(e))


@app.post("/api/classification/{contract_id}/confirm")
async def confirm_classification(
    contract_id: str,
    confirmed_type: str,
    db: Session = Depends(get_db)
):
    """
    사용자가 분류 유형 확인/수정

    Args:
        contract_id: 계약서 ID
        confirmed_type: 사용자가 확인한 유형
        db: 데이터베이스 세션

    Returns:
        {
            "success": bool,
            "contract_id": str,
            "confirmed_type": str
        }
    """
    try:
        classification = db.query(ClassificationResult).filter(
            ClassificationResult.contract_id == contract_id
        ).first()

        if not classification:
            raise HTTPException(status_code=404, detail="분류 결과를 찾을 수 없습니다")

        # 사용자가 변경한 경우 기록
        if confirmed_type != classification.predicted_type:
            classification.user_override = confirmed_type

        classification.confirmed_type = confirmed_type

        # 계약서 상태 업데이트
        contract = db.query(ContractDocument).filter(
            ContractDocument.contract_id == contract_id
        ).first()

        if contract:
            contract.status = "classified_confirmed"

        db.commit()

        logger.info(f"분류 확인: {contract_id} -> {confirmed_type}")

        return {
            "success": True,
            "contract_id": contract_id,
            "confirmed_type": confirmed_type
        }

    except HTTPException:
        raise
    except Exception as e:
        logger.exception(f"분류 확인 중 오류: {e}")
        raise HTTPException(status_code=500, detail=str(e))


@app.post("/api/validation/{contract_id}/start")
async def start_validation(
    contract_id: str,
    text_weight: float = 0.7,
    title_weight: float = 0.3,
    dense_weight: float = 0.85,
    use_parallel: bool = True,  # 병렬 처리 사용 여부 (기본값: True)
    db: Session = Depends(get_db)
):
    """
    계약서 검증 시작 (병렬 처리)

    Args:
        contract_id: 계약서 ID
        text_weight: 본문 가중치 (기본값: 0.7)
        title_weight: 제목 가중치 (기본값: 0.3)
        dense_weight: 시멘틱 가중치 (기본값: 0.85)
        use_parallel: 병렬 처리 사용 여부 (기본값: True)
        db: 데이터베이스 세션

    Returns:
        {
            "message": str,
            "contract_id": str,
            "task_id": str,
            "status": str
        }
    """
    try:
        # 가중치 검증
        if not (0.0 <= text_weight <= 1.0):
            raise HTTPException(status_code=400, detail="본문 가중치는 0~1 사이여야 합니다")
        if not (0.0 <= title_weight <= 1.0):
            raise HTTPException(status_code=400, detail="제목 가중치는 0~1 사이여야 합니다")
        if not (0.0 <= dense_weight <= 1.0):
            raise HTTPException(status_code=400, detail="시멘틱 가중치는 0~1 사이여야 합니다")
        if abs(text_weight + title_weight - 1.0) > 0.001:
            raise HTTPException(status_code=400, detail="본문 가중치와 제목 가중치의 합은 1.0이어야 합니다")

        # 계약서 존재 확인
        contract = db.query(ContractDocument).filter(
            ContractDocument.contract_id == contract_id
        ).first()

        if not contract:
            raise HTTPException(status_code=404, detail="계약서를 찾을 수 없습니다")

        # 분류 완료 확인
        classification = db.query(ClassificationResult).filter(
            ClassificationResult.contract_id == contract_id
        ).first()

        if not classification:
            raise HTTPException(status_code=400, detail="계약서 분류가 완료되지 않았습니다")

        # 검증 작업 큐에 전송 (병렬 또는 순차)
        if use_parallel:
            # 병렬 처리: A1-Stage1 → [A1-Stage2 || A2 || A3]
            task = validate_contract_parallel_task.delay(
                contract_id,
                text_weight=text_weight,
                title_weight=title_weight,
                dense_weight=dense_weight
            )
            message = "검증이 시작되었습니다 (병렬 처리)"
        else:
            # 순차 처리 (기존 방식)
            task = validate_contract_task.delay(
                contract_id,
                text_weight=text_weight,
                title_weight=title_weight,
                dense_weight=dense_weight
            )
            message = "검증이 시작되었습니다 (순차 처리)"

        # 검증 시작 시간 기록
        import time
        from datetime import datetime
        validation_start_time = time.time()
        
        # ValidationResult에 시작 시간 저장
        validation_result = db.query(ValidationResult).filter(
            ValidationResult.contract_id == contract_id
        ).first()
        
        if not validation_result:
            validation_result = ValidationResult(
                contract_id=contract_id,
                contract_type=classification.confirmed_type or classification.predicted_type,
                validation_timing={
                    'start_time': validation_start_time,
                    'start_datetime': datetime.now().isoformat(),
                    'mode': 'parallel' if use_parallel else 'sequential'
                },
                completeness_check={},
                checklist_validation={},
                content_analysis={},
                overall_score=0.0,
                recommendations=[]
            )
            db.add(validation_result)
        else:
            # 기존 결과가 있으면 시작 시간만 업데이트
            validation_result.validation_timing = {
                'start_time': validation_start_time,
                'start_datetime': datetime.now().isoformat(),
                'mode': 'parallel' if use_parallel else 'sequential'
            }
            from sqlalchemy.orm.attributes import flag_modified
            flag_modified(validation_result, 'validation_timing')
        
        db.commit()
        
        logger.info(f"⏱️ 검증 시작: {contract_id} ({'병렬' if use_parallel else '순차'}), "
                   f"task_id: {task.id}")

        return {
            "message": message,
            "contract_id": contract_id,
            "task_id": task.id,
            "status": "processing",
            "parallel": use_parallel
        }

    except HTTPException:
        raise
    except Exception as e:
        logger.error(f"검증 시작 실패: {e}")
        raise HTTPException(status_code=500, detail=str(e))


@app.get("/api/validation/{contract_id}")
async def get_validation_result(contract_id: str, db: Session = Depends(get_db)):
    """
    검증 결과 조회 (병렬 처리 대응)

    병렬 처리 시 A1-Stage2, A2, A3가 독립적으로 완료되므로
    모든 필드가 완료되었는지 확인합니다.

    Args:
        contract_id: 계약서 ID
        db: 데이터베이스 세션

    Returns:
        검증 결과
    """
    try:
        # 검증 결과 조회
        validation = db.query(ValidationResult).filter(
            ValidationResult.contract_id == contract_id
        ).first()
        
        if not validation:
            return {
                "contract_id": contract_id,
                "status": "not_started",
                "message": "검증이 시작되지 않았습니다"
            }

        # 세션 캐시 새로고침 (최신 데이터 로드) - 병렬 처리 시 필수
        # SQLite 트랜잭션 격리 문제 해결: 세션을 닫고 새로 열기
        validation_id = validation.id
        db.close()
        
        # 새 세션으로 다시 조회 (SessionLocal 직접 사용)
        from backend.shared.database import SessionLocal
        db = SessionLocal()
        try:
            validation = db.query(ValidationResult).filter(
                ValidationResult.id == validation_id
            ).first()
            
            if not validation:
                return {
                    "contract_id": contract_id,
                    "status": "error",
                    "message": "검증 결과를 다시 로드할 수 없습니다"
                }
        except Exception as e:
            db.close()
            raise

        # 각 노드 결과 확인 (새 세션에서 읽음)
        completeness_check = validation.completeness_check
        checklist_validation = validation.checklist_validation
        content_analysis = validation.content_analysis
        
        # Recovered 필드는 batch2에서 나중에 저장되므로
        # 트랜잭션 격리 문제 해결을 위해 세션을 다시 닫고 새로 열기
        validation_id_for_recovered = validation.id
        db.close()
        
        # 새 세션으로 recovered 필드만 다시 조회
        db = SessionLocal()
        try:
            validation_for_recovered = db.query(ValidationResult).filter(
                ValidationResult.id == validation_id_for_recovered
            ).first()
            
            if validation_for_recovered:
                checklist_validation_recovered = validation_for_recovered.checklist_validation_recovered
                content_analysis_recovered = validation_for_recovered.content_analysis_recovered
                
                # 디버그: 실제 DB 값 타입 확인
                logger.info(f"[GET-DEBUG] Recovered 필드 조회 성공:")
                logger.info(f"  checklist_recovered type: {type(checklist_validation_recovered)}, value: {checklist_validation_recovered is not None}")
                logger.info(f"  content_recovered type: {type(content_analysis_recovered)}, value: {content_analysis_recovered is not None}")
                if checklist_validation_recovered:
                    logger.info(f"  checklist_recovered keys: {list(checklist_validation_recovered.keys())[:5]}")
                if content_analysis_recovered:
                    logger.info(f"  content_recovered keys: {list(content_analysis_recovered.keys())[:5]}")
            else:
                logger.warning(f"[GET-DEBUG] validation_for_recovered를 찾을 수 없음: id={validation_id_for_recovered}")
                checklist_validation_recovered = None
                content_analysis_recovered = None
        except Exception as e:
            logger.error(f"Recovered 필드 조회 실패: {e}")
            import traceback
            logger.error(traceback.format_exc())
            checklist_validation_recovered = None
            content_analysis_recovered = None

        # 디버그: 실제 DB 값 출력 (간략화)
        logger.info(f"[GET] {contract_id} - completeness_check: {bool(completeness_check)}, "
                   f"checklist: {bool(checklist_validation)}, "
                   f"content: {bool(content_analysis)}, "
                   f"checklist_recovered: {bool(checklist_validation_recovered)}, "
                   f"content_recovered: {bool(content_analysis_recovered)}")



        # 1. completeness_check 없음 → A1-Stage1도 완료 안됨
        if not completeness_check:
            return {
                "contract_id": contract_id,
                "status": "processing",
                "message": "매칭 검증 중입니다 (A1-Stage1)"
            }

        # 2. A1-Stage1 완료 확인 (matching_details 존재 여부로 판단)
        if not completeness_check.get('matching_details'):
            return {
                "contract_id": contract_id,
                "status": "processing",
                "message": "매칭 검증 중입니다 (A1-Stage1)"
            }

        # 3. checklist_validation 없음 또는 미완료 → A2 진행 중
        if not checklist_validation or checklist_validation == {} or checklist_validation.get('status') == 'pending':
            return {
                "contract_id": contract_id,
                "status": "processing",
                "message": "체크리스트 검증 중입니다 (A2)"
            }

        # 4. content_analysis 없음 또는 미완료 → A3 진행 중
        if not content_analysis or content_analysis == {} or content_analysis.get('status') == 'pending':
            return {
                "contract_id": contract_id,
                "status": "processing",
                "message": "내용 분석 중입니다 (A3)"
            }

        # 5. 모든 필드가 실제 데이터를 가지고 있는지 확인
        # A2 필수 필드: statistics.total_checklist_items
        # A3 필수 필드: total_articles
        checklist_stats = checklist_validation.get('statistics', {})
        if not checklist_stats.get('total_checklist_items'):
            return {
                "contract_id": contract_id,
                "status": "processing",
                "message": "체크리스트 검증 데이터 확인 중 (A2)"
            }

        if not content_analysis.get('total_articles'):
            return {
                "contract_id": contract_id,
                "status": "processing",
                "message": "내용 분석 데이터 확인 중 (A3)"
            }

        # 모든 필드 완료 → 검증 완료
        return {
            "contract_id": contract_id,
            "status": "completed",
            "validation_result": {
                "id": validation.id,
                "overall_score": validation.overall_score,
                "content_analysis": content_analysis,
                "content_analysis_recovered": content_analysis_recovered,
                "completeness_check": completeness_check,
                "checklist_validation": checklist_validation,
                "checklist_validation_recovered": checklist_validation_recovered,
                "recommendations": validation.recommendations,
                "created_at": validation.created_at.isoformat() if validation.created_at else None
            }
        }

    except Exception as e:
        logger.error(f"검증 결과 조회 실패: {e}")
        raise HTTPException(status_code=500, detail=str(e))
    
    finally:
        # 세션 확실히 닫기 (커넥션 풀 고갈 방지)
        if db:
            db.close()


@app.get("/api/token-usage/{contract_id}")
async def get_token_usage(contract_id: str, db: Session = Depends(get_db)):
    """
    계약서별 토큰 사용량 조회

    Args:
        contract_id: 계약서 ID
        db: 데이터베이스 세션

    Returns:
        {
            "contract_id": str,
            "total_tokens": int,
            "by_component": {
                "classification_agent": {...},
                "consistency_agent": {...}
            },
            "by_api_type": {
                "chat_completion": {...},
                "embedding": {...}
            },
            "details": [...]
        }
    """
    try:
        # 토큰 사용량 조회
        usages = db.query(TokenUsage).filter(
            TokenUsage.contract_id == contract_id
        ).all()

        if not usages:
            return {
                "contract_id": contract_id,
                "total_tokens": 0,
                "by_component": {},
                "by_api_type": {},
                "details": []
            }

        # 집계
        total_tokens = sum(u.total_tokens for u in usages)

        by_component = {}
        by_api_type = {}

        for usage in usages:
            # Component별 집계
            if usage.component not in by_component:
                by_component[usage.component] = {
                    "total_tokens": 0,
                    "prompt_tokens": 0,
                    "completion_tokens": 0,
                    "count": 0
                }
            by_component[usage.component]["total_tokens"] += usage.total_tokens
            by_component[usage.component]["prompt_tokens"] += usage.prompt_tokens
            by_component[usage.component]["completion_tokens"] += usage.completion_tokens
            by_component[usage.component]["count"] += 1

            # API Type별 집계
            if usage.api_type not in by_api_type:
                by_api_type[usage.api_type] = {
                    "total_tokens": 0,
                    "prompt_tokens": 0,
                    "completion_tokens": 0,
                    "count": 0
                }
            by_api_type[usage.api_type]["total_tokens"] += usage.total_tokens
            by_api_type[usage.api_type]["prompt_tokens"] += usage.prompt_tokens
            by_api_type[usage.api_type]["completion_tokens"] += usage.completion_tokens
            by_api_type[usage.api_type]["count"] += 1

        # 상세 내역
        details = []
        for usage in usages:
            details.append({
                "id": usage.id,
                "component": usage.component,
                "api_type": usage.api_type,
                "model": usage.model,
                "prompt_tokens": usage.prompt_tokens,
                "completion_tokens": usage.completion_tokens,
                "total_tokens": usage.total_tokens,
                "created_at": usage.created_at.isoformat() if usage.created_at else None,
                "extra_info": usage.extra_info
            })

        return {
            "contract_id": contract_id,
            "total_tokens": total_tokens,
            "by_component": by_component,
            "by_api_type": by_api_type,
            "details": details
        }

    except Exception as e:
        logger.error(f"토큰 사용량 조회 실패: {e}")
        raise HTTPException(status_code=500, detail=str(e))


if __name__ == "__main__":
    import uvicorn
    uvicorn.run("main:app", host="0.0.0.0", port=8000, reload=True)



@app.post("/api/chatbot/{contract_id}/message")
async def chatbot_message(
    contract_id: str,
    message: str,
    session_id: str = None,
    db: Session = Depends(get_db)
):
    """
    챗봇 메시지 전송 (스트리밍)
    
    Args:
        contract_id: 계약서 ID
        message: 사용자 메시지
        session_id: 세션 ID (선택)
        db: 데이터베이스 세션
        
    Returns:
        챗봇 응답 (Server-Sent Events 스트리밍)
    """
    from fastapi.responses import StreamingResponse
    import json
    import asyncio
    
    async def generate_stream():
        try:
            # 계약서 존재 확인
            contract = db.query(ContractDocument).filter(
                ContractDocument.contract_id == contract_id
            ).first()
            
            if not contract:
                yield f"data: {json.dumps({'error': '계약서를 찾을 수 없습니다'})}\n\n"
                return
            
            # 분류 완료 확인
            classification = db.query(ClassificationResult).filter(
                ClassificationResult.contract_id == contract_id
            ).first()
            
            if not classification:
                yield f"data: {json.dumps({'error': '계약서 분류가 완료되지 않았습니다'})}\n\n"
                return
            
            # ChatbotOrchestrator 초기화
            from backend.chatbot_agent.agent import ChatbotOrchestrator
            from openai import OpenAI
            import os

            openai_client = OpenAI(
                api_key=os.getenv('OPENAI_API_KEY')
            )

            orchestrator = ChatbotOrchestrator(openai_client=openai_client)
            
            # 스트리밍 메시지 처리
            logger.info(f"[chatbot_message] 스트리밍 시작: contract_id={contract_id}, message={message[:50]}")
            
            async for chunk in orchestrator.process_message_stream(
                contract_id=contract_id,
                user_message=message,
                session_id=session_id
            ):
                chunk_type = chunk.get('type', 'unknown')
                logger.debug(f"[chatbot_message] 청크 전송: type={chunk_type}")
                yield f"data: {json.dumps(chunk)}\n\n"
                await asyncio.sleep(0)  # 이벤트 루프에 제어권 양보
            
            logger.info(f"[chatbot_message] 스트리밍 완료")
            
            # 완료 신호
            yield "data: [DONE]\n\n"
        
        except Exception as e:
            logger.exception(f"챗봇 메시지 처리 중 오류: {e}")
            yield f"data: {json.dumps({'error': str(e)})}\n\n"
    
    return StreamingResponse(
        generate_stream(),
        media_type="text/event-stream",
        headers={
            "Cache-Control": "no-cache",
            "Connection": "keep-alive",
        }
    )


@app.get("/api/chatbot/{contract_id}/status")
async def chatbot_status(contract_id: str, db: Session = Depends(get_db)):
    """
    챗봇 활성화 상태 확인
    
    Args:
        contract_id: 계약서 ID
        db: 데이터베이스 세션
        
    Returns:
        {
            "active": bool,
            "reason": str
        }
    """
    try:
        # 계약서 존재 확인
        contract = db.query(ContractDocument).filter(
            ContractDocument.contract_id == contract_id
        ).first()
        
        if not contract:
            return {
                "active": False,
                "reason": "계약서를 찾을 수 없습니다"
            }
        
        # 분류 완료 확인
        classification = db.query(ClassificationResult).filter(
            ClassificationResult.contract_id == contract_id
        ).first()
        
        if not classification:
            return {
                "active": False,
                "reason": "계약서 분류가 완료되지 않았습니다"
            }
        
        return {
            "active": True,
            "reason": "챗봇 사용 가능"
        }
    
    except Exception as e:
        logger.exception(f"챗봇 상태 확인 중 오류: {e}")
        raise HTTPException(status_code=500, detail=str(e))


@app.get("/api/chatbot/{contract_id}/history")
async def chatbot_history(
    contract_id: str,
    session_id: str = None,
    db: Session = Depends(get_db)
):
    """
    대화 히스토리 조회
    
    Args:
        contract_id: 계약서 ID
        session_id: 세션 ID (선택)
        db: 데이터베이스 세션
        
    Returns:
        대화 히스토리 리스트
    """
    try:
        # 세션 ID가 없으면 모든 세션 조회
        if session_id:
            sessions = db.query(ChatbotSession).filter(
                ChatbotSession.contract_id == contract_id,
                ChatbotSession.session_id == session_id
            ).order_by(ChatbotSession.created_at.asc()).all()
        else:
            sessions = db.query(ChatbotSession).filter(
                ChatbotSession.contract_id == contract_id
            ).order_by(ChatbotSession.created_at.asc()).all()
        
        history = []
        for session in sessions:
            history.append({
                "session_id": session.session_id,
                "role": session.role,
                "content": session.content,
                "created_at": session.created_at.isoformat() if session.created_at else None
            })
        
        return {
            "contract_id": contract_id,
            "session_id": session_id,
            "history": history
        }
    
    except Exception as e:
        logger.exception(f"대화 히스토리 조회 중 오류: {e}")
        raise HTTPException(status_code=500, detail=str(e))


@app.delete("/api/chatbot/{contract_id}/session/{session_id}")
async def delete_chatbot_session(
    contract_id: str,
    session_id: str,
    db: Session = Depends(get_db)
):
    """
    챗봇 세션 삭제 (대화 내역 초기화)
    
    Args:
        contract_id: 계약서 ID
        session_id: 세션 ID
        db: 데이터베이스 세션
        
    Returns:
        삭제된 메시지 개수
    """
    try:
        # 해당 세션의 모든 메시지 삭제
        deleted_count = db.query(ChatbotSession).filter(
            ChatbotSession.contract_id == contract_id,
            ChatbotSession.session_id == session_id
        ).delete()
        
        db.commit()
        
        logger.info(f"챗봇 세션 삭제 완료: contract={contract_id}, session={session_id}, count={deleted_count}")
        
        return {
            "success": True,
            "contract_id": contract_id,
            "session_id": session_id,
            "deleted_count": deleted_count
        }
    
    except Exception as e:
        logger.exception(f"챗봇 세션 삭제 중 오류: {e}")
        db.rollback()
        raise HTTPException(status_code=500, detail=str(e))


@app.delete("/api/contracts/{contract_id}")
async def delete_contract(
    contract_id: str,
    db: Session = Depends(get_db)
):
    """
    계약서 및 관련 데이터 전체 삭제
    
    Args:
        contract_id: 계약서 ID
        db: 데이터베이스 세션
        
    Returns:
        삭제 결과
    """
    try:
        # 1. 챗봇 세션 삭제
        chatbot_deleted = db.query(ChatbotSession).filter(
            ChatbotSession.contract_id == contract_id
        ).delete()
        
        # 2. 분류 결과 삭제
        classification_deleted = db.query(ClassificationResult).filter(
            ClassificationResult.contract_id == contract_id
        ).delete()
        
        # 3. 검증 결과 삭제
        validation_deleted = db.query(ValidationResult).filter(
            ValidationResult.contract_id == contract_id
        ).delete()
        
        # 4. 토큰 사용량 삭제
        token_deleted = db.query(TokenUsage).filter(
            TokenUsage.contract_id == contract_id
        ).delete()
        
        # 5. 계약서 문서 삭제
        contract = db.query(ContractDocument).filter(
            ContractDocument.contract_id == contract_id
        ).first()
        
        if not contract:
            raise HTTPException(status_code=404, detail="계약서를 찾을 수 없습니다")
        
        db.delete(contract)
        db.commit()
        
        logger.info(
            f"계약서 삭제 완료: contract={contract_id}, "
            f"chatbot={chatbot_deleted}, classification={classification_deleted}, "
            f"validation={validation_deleted}, token={token_deleted}"
        )
        
        return {
            "success": True,
            "contract_id": contract_id,
            "deleted": {
                "chatbot_sessions": chatbot_deleted,
                "classification_results": classification_deleted,
                "validation_results": validation_deleted,
                "token_usage": token_deleted,
                "contract_document": 1
            }
        }
    
    except HTTPException:
        raise
    except Exception as e:
        logger.exception(f"계약서 삭제 중 오류: {e}")
        db.rollback()
        raise HTTPException(status_code=500, detail=str(e))


if __name__ == "__main__":
    import uvicorn
    uvicorn.run("main:app", host="0.0.0.0", port=8000, reload=True)


@app.get("/api/report/{contract_id}")
async def get_report(contract_id: str, db: Session = Depends(get_db)):
    """
    최종 보고서 조회
    
    Args:
        contract_id: 계약서 ID
        db: 데이터베이스 세션
        
    Returns:
        최종 보고서 JSON
    """
    try:
        # ValidationResult 조회
        validation = db.query(ValidationResult).filter(
            ValidationResult.contract_id == contract_id
        ).first()
        
        if not validation:
            raise HTTPException(
                status_code=404,
                detail=f"계약서를 찾을 수 없습니다: {contract_id}"
            )
        
        # 최종 보고서 확인
        if not validation.final_report:
            # 상태 확인
            contract = db.query(ContractDocument).filter(
                ContractDocument.contract_id == contract_id
            ).first()
            
            status = contract.status if contract else "unknown"
            
            if status == "generating_report":
                return {
                    "contract_id": contract_id,
                    "status": "generating",
                    "message": "보고서 생성 중입니다"
                }
            elif status == "failed":
                return {
                    "contract_id": contract_id,
                    "status": "failed",
                    "message": "보고서 생성에 실패했습니다"
                }
            else:
                return {
                    "contract_id": contract_id,
                    "status": "not_ready",
                    "message": "보고서가 아직 생성되지 않았습니다"
                }
        
        # 최종 보고서 반환
        return validation.final_report
    
    except HTTPException:
        raise
    except Exception as e:
        logger.exception(f"보고서 조회 중 오류: {e}")
        raise HTTPException(status_code=500, detail=str(e))


@app.post("/api/report/{contract_id}/generate")
async def generate_report_only(contract_id: str, db: Session = Depends(get_db)):
    """
    이미 완료된 검증 결과로 보고서만 다시 생성
    
    Args:
        contract_id: 계약서 ID
        db: 데이터베이스 세션
        
    Returns:
        {
            "success": bool,
            "contract_id": str,
            "task_id": str,
            "message": str
        }
    """
    try:
        # 계약서 존재 확인
        contract = db.query(ContractDocument).filter(
            ContractDocument.contract_id == contract_id
        ).first()
        
        if not contract:
            raise HTTPException(
                status_code=404,
                detail=f"계약서를 찾을 수 없습니다: {contract_id}"
            )
        
        # 검증 결과 확인
        validation = db.query(ValidationResult).filter(
            ValidationResult.contract_id == contract_id
        ).first()
        
        if not validation:
            raise HTTPException(
                status_code=400,
                detail="검증 결과가 없습니다. 먼저 /api/validation/{contract_id}/start를 실행하세요."
            )
        
        # 필수 검증 결과 확인
        if not validation.completeness_check:
            raise HTTPException(
                status_code=400,
                detail="완전성 검증(A1) 결과가 없습니다"
            )
        
        if not validation.checklist_validation:
            raise HTTPException(
                status_code=400,
                detail="체크리스트 검증(A2) 결과가 없습니다"
            )
        
        if not validation.content_analysis:
            raise HTTPException(
                status_code=400,
                detail="내용 분석(A3) 결과가 없습니다"
            )
        
        # Report Agent 트리거
        from backend.report_agent.tasks import generate_report_task
        
        task = generate_report_task.apply_async(
            args=[contract_id],
            queue="report_generation"
        )
        
        logger.info(f"보고서 생성 작업 시작: {contract_id}, task_id: {task.id}")
        
        return {
            "success": True,
            "contract_id": contract_id,
            "task_id": task.id,
            "message": "보고서 생성이 시작되었습니다. /api/report/{contract_id}/status로 진행 상황을 확인하세요."
        }
    
    except HTTPException:
        raise
    except Exception as e:
        logger.exception(f"보고서 생성 시작 중 오류: {e}")
        raise HTTPException(status_code=500, detail=str(e))


@app.get("/api/contracts/history")
async def get_contract_history(
    limit: int = 50,
    offset: int = 0,
    db: Session = Depends(get_db)
):
    """
    계약서 히스토리 목록 조회
    
    Args:
        limit: 조회할 최대 개수 (기본 50개)
        offset: 시작 위치 (기본 0)
        db: 데이터베이스 세션
        
    Returns:
        {
            "total": int,
            "contracts": [
                {
                    "contract_id": str,
                    "filename": str,
                    "upload_date": str,
                    "status": str,
                    "contract_type": str (optional),
                    "has_classification": bool,
                    "has_validation": bool,
                    "has_report": bool
                }
            ]
        }
    """
    try:
        from sqlalchemy.orm import joinedload
        
        # 전체 개수 조회
        total = db.query(ContractDocument).count()
        
        # 계약서 목록 조회 (최신순) - 최적화: JOIN으로 한 번에 조회
        contracts = db.query(ContractDocument).order_by(
            ContractDocument.upload_date.desc()
        ).limit(limit).offset(offset).all()
        
        # contract_id 리스트 추출
        contract_ids = [c.contract_id for c in contracts]
        
        # 분류 결과 일괄 조회 (N+1 문제 해결)
        classifications = db.query(ClassificationResult).filter(
            ClassificationResult.contract_id.in_(contract_ids)
        ).all()
        classification_map = {c.contract_id: c for c in classifications}
        
        # 검증 결과 일괄 조회 (N+1 문제 해결)
        validations = db.query(ValidationResult).filter(
            ValidationResult.contract_id.in_(contract_ids)
        ).all()
        validation_map = {v.contract_id: v for v in validations}
        
        # 결과 조합
        result = []
        for contract in contracts:
            classification = classification_map.get(contract.contract_id)
            validation = validation_map.get(contract.contract_id)
            
            result.append({
                "contract_id": contract.contract_id,
                "filename": contract.filename,
                "upload_date": contract.upload_date.isoformat() if contract.upload_date else None,
                "status": contract.status,
                "contract_type": classification.confirmed_type if classification else None,
                "has_classification": classification is not None,
                "has_validation": validation is not None and validation.completeness_check is not None,
                "has_report": validation is not None and validation.final_report is not None
            })
        
        return {
            "total": total,
            "contracts": result
        }
        
    except Exception as e:
        logger.exception(f"계약서 히스토리 조회 중 오류: {e}")
        raise HTTPException(status_code=500, detail=str(e))


@app.get("/api/contracts/{contract_id}")
async def get_contract_detail(
    contract_id: str,
    include_classification: bool = True,
    include_validation: bool = True,
    db: Session = Depends(get_db)
):
    """
    계약서 상세 정보 조회 (분류/검증 결과 포함 가능)
    
    Args:
        contract_id: 계약서 ID
        include_classification: 분류 결과 포함 여부 (기본 True)
        include_validation: 검증 결과 포함 여부 (기본 True)
        db: 데이터베이스 세션
        
    Returns:
        {
            "contract_id": str,
            "filename": str,
            "upload_date": str,
            "status": str,
            "parsed_data": dict,
            "parsed_metadata": dict,
            "classification": dict (optional),
            "validation": dict (optional)
        }
    """
    try:
        # 계약서 조회
        contract = db.query(ContractDocument).filter(
            ContractDocument.contract_id == contract_id
        ).first()
        
        if not contract:
            raise HTTPException(
                status_code=404,
                detail=f"계약서를 찾을 수 없습니다: {contract_id}"
            )
        
        result = {
            "contract_id": contract.contract_id,
            "filename": contract.filename,
            "upload_date": contract.upload_date.isoformat() if contract.upload_date else None,
            "status": contract.status,
            "parsed_data": contract.parsed_data,
            "parsed_metadata": contract.parsed_metadata
        }
        
        # 분류 결과 포함
        if include_classification:
            classification = db.query(ClassificationResult).filter(
                ClassificationResult.contract_id == contract_id
            ).first()
            
            if classification:
                result["classification"] = {
                    "predicted_type": classification.predicted_type,
                    "confidence": classification.confidence,
                    "confirmed_type": classification.confirmed_type,
                    "user_override": classification.user_override
                }
        
        # 검증 결과 포함
        if include_validation:
            validation = db.query(ValidationResult).filter(
                ValidationResult.contract_id == contract_id
            ).first()
            
            if validation:
                result["validation"] = {
                    "status": "completed" if validation.completeness_check else "not_started",
                    "has_report": validation.final_report is not None
                }
        
        return result
        
    except HTTPException:
        raise
    except Exception as e:
        logger.exception(f"계약서 상세 조회 중 오류: {e}")
        raise HTTPException(status_code=500, detail=str(e))


@app.get("/api/report/{contract_id}/status")
async def get_report_status(contract_id: str, db: Session = Depends(get_db)):
    """
    보고서 생성 상태 조회
    
    Args:
        contract_id: 계약서 ID
        db: 데이터베이스 세션
        
    Returns:
        {
            "contract_id": str,
            "status": "not_started" | "generating" | "completed" | "failed",
            "message": str,
            "progress": dict (optional)
        }
    """
    try:
        # 계약서 상태 확인
        contract = db.query(ContractDocument).filter(
            ContractDocument.contract_id == contract_id
        ).first()
        
        if not contract:
            raise HTTPException(
                status_code=404,
                detail=f"계약서를 찾을 수 없습니다: {contract_id}"
            )
        
        # ValidationResult 조회
        validation = db.query(ValidationResult).filter(
            ValidationResult.contract_id == contract_id
        ).first()
        
        # 상태 판단
        if validation and validation.final_report:
            return {
                "contract_id": contract_id,
                "status": "completed",
                "message": "보고서 생성 완료",
                "progress": {
                    "step1": bool(validation.report_step1_normalized),
                    "step2": bool(validation.report_step2_aggregated),
                    "step3": bool(validation.report_step3_resolved),
                    "step4": bool(validation.final_report)
                }
            }
        elif contract.status == "generating_report":
            # 진행 상황 확인
            progress = {}
            if validation:
                progress = {
                    "step1": bool(validation.report_step1_normalized),
                    "step2": bool(validation.report_step2_aggregated),
                    "step3": bool(validation.report_step3_resolved),
                    "step4": bool(validation.final_report)
                }
            
            return {
                "contract_id": contract_id,
                "status": "generating",
                "message": "보고서 생성 중",
                "progress": progress
            }
        elif contract.status == "failed":
            return {
                "contract_id": contract_id,
                "status": "failed",
                "message": "보고서 생성 실패"
            }
        else:
            return {
                "contract_id": contract_id,
                "status": "not_started",
                "message": "보고서 생성이 시작되지 않았습니다"
            }
    
    except HTTPException:
        raise
    except Exception as e:
        logger.exception(f"보고서 상태 조회 중 오류: {e}")
        raise HTTPException(status_code=500, detail=str(e))


@app.get("/api/report/{contract_id}/article-reports")
async def get_article_reports(contract_id: str, db: Session = Depends(get_db)):
    """
    조별 보고서 섹션 조회
    
    step5에서 생성된 narrative_report를 파싱한 7개 섹션을 조회합니다.
    
    Args:
        contract_id: 계약서 ID
        db: 데이터베이스 세션
        
    Returns:
        {
            "contract_id": str,
            "status": "ok" | "not_found" | "not_generated",
            "article_reports": {
                "10": {
                    "article_title": "비밀유지 의무",
                    "sections": {
                        "section_1_overview": "검토 개요 텍스트",
                        "section_2_fulfilled_criteria": "충족된 기준 텍스트",
                        ...
                        "section_7_comprehensive_judgment": "종합 판단 텍스트"
                    }
                },
                ...
            }
        }
    """
    try:
        from backend.report_agent.report_section_saver import ReportSectionSaver
        
        # ValidationResult 조회
        validation = db.query(ValidationResult).filter(
            ValidationResult.contract_id == contract_id
        ).first()
        
        if not validation:
            return {
                "contract_id": contract_id,
                "status": "not_found",
                "message": "검증 결과를 찾을 수 없습니다"
            }
        
        # article_reports 확인
        if not validation.article_reports:
            return {
                "contract_id": contract_id,
                "status": "not_generated",
                "message": "조별 보고서가 아직 생성되지 않았습니다",
                "article_reports": {}
            }
        
        return {
            "contract_id": contract_id,
            "status": "ok",
            "article_reports": validation.article_reports
        }
    
    except Exception as e:
        logger.exception(f"조별 보고서 조회 중 오류: {e}")
        raise HTTPException(status_code=500, detail=str(e))


@app.get("/api/report/{contract_id}/article-reports/{article_number}")
async def get_article_report_sections(
    contract_id: str,
    article_number: int,
    db: Session = Depends(get_db)
):
    """
    특정 조의 7개 섹션 조회
    
    Args:
        contract_id: 계약서 ID
        article_number: 조 번호 (예: 10)
        db: 데이터베이스 세션
        
    Returns:
        {
            "contract_id": str,
            "article_number": int,
            "article_title": str,
            "sections": {
                "section_1_overview": "텍스트",
                "section_2_fulfilled_criteria": "텍스트",
                ...
                "section_7_comprehensive_judgment": "텍스트"
            }
        }
    """
    try:
        from backend.report_agent.report_section_saver import ReportSectionSaver
        
        # ValidationResult 조회
        validation = db.query(ValidationResult).filter(
            ValidationResult.contract_id == contract_id
        ).first()
        
        if not validation or not validation.article_reports:
            raise HTTPException(
                status_code=404,
                detail=f"조별 보고서를 찾을 수 없습니다: {contract_id}"
            )
        
        # 특정 조 조회
        article_reports = validation.article_reports
        article_key = str(article_number)
        
        if article_key not in article_reports:
            raise HTTPException(
                status_code=404,
                detail=f"제{article_number}조 보고서를 찾을 수 없습니다"
            )
        
        article_data = article_reports[article_key]
        
        return {
            "contract_id": contract_id,
            "article_number": article_number,
            "article_title": article_data.get("article_title", f"제{article_number}조"),
            "sections": article_data.get("sections", {})
        }
    
    except HTTPException:
        raise
    except Exception as e:
        logger.exception(f"조별 보고서 섹션 조회 중 오류: {e}")
        raise HTTPException(status_code=500, detail=str(e))


@app.post("/api/report/{contract_id}/generate-article-revision")
async def generate_article_revision(
    contract_id: str,
    request: dict,
    db: Session = Depends(get_db)
):
    """
    특정 조항의 수정본 생성 (리스크 + 권고사항 반영)
    
    Args:
        contract_id: 계약서 ID
        request: {"article_number": int}
        
    Returns:
        {
            "contract_id": str,
            "article_number": int,
            "original_content": str,
            "revised_content": str,
            "changes": [...]
        }
    """
    try:
        from openai import AzureOpenAI
        import os
        
        # 요청 데이터 추출
        article_number = request.get("article_number")
        
        if not article_number:
            raise HTTPException(status_code=400, detail="article_number is required")
        
        # DB에서 ValidationResult 조회
        validation = db.query(ValidationResult).filter(
            ValidationResult.contract_id == contract_id
        ).first()
        
        if not validation:
            raise HTTPException(status_code=404, detail="검증 결과를 찾을 수 없습니다")
        
        # article_reports에서 해당 조항 데이터 가져오기
        article_reports = validation.article_reports or {}
        article_key = str(article_number)
        
        logger.info(f"[REVISION DEBUG] article_reports keys: {list(article_reports.keys())}")
        
        if article_key not in article_reports:
            raise HTTPException(status_code=404, detail=f"제{article_number}조 보고서를 찾을 수 없습니다")
        
        article_data = article_reports[article_key]
        sections_data = article_data.get("sections", {})
        
        logger.info(f"[REVISION DEBUG] sections_data keys: {list(sections_data.keys())}")
        
        # sections_data가 {"article_title": "...", "sections": {...}} 구조인 경우
        # 실제 섹션 데이터는 sections_data["sections"]에 있음
        if "sections" in sections_data and isinstance(sections_data["sections"], dict):
            sections = sections_data["sections"]
            logger.info(f"[REVISION DEBUG] 중첩 구조 감지, 내부 sections keys: {list(sections.keys())}")
        else:
            sections = sections_data
        
        # 사용자 조항 내용, 리스크, 권고사항 추출
        # final_report에서 사용자 조항 내용 가져오기
        final_report = validation.final_report or {}
        
        # user_articles에서 제목 가져오기
        user_articles = final_report.get("user_articles", [])
        article_title = f"제{article_number}조"
        for article in user_articles:
            if article.get("user_article_no") == article_number:
                article_title = article.get("user_article_title", f"제{article_number}조")
                break
        
        # all_clause_contents["user_articles"]에서 user_article_{번호} 키로 접근
        all_clause_contents = final_report.get("all_clause_contents", {})
        user_articles_contents = all_clause_contents.get("user_articles", {})
        
        user_article_key = f"user_article_{article_number}"
        user_content_data = user_articles_contents.get(user_article_key, {})
        
        # content 추출
        original_content = ""
        if isinstance(user_content_data, dict):
            # content 필드가 있는지 확인
            if "content" in user_content_data:
                content = user_content_data.get("content")
                
                # content가 dict이고 그 안에 또 content가 있는 경우
                if isinstance(content, dict) and "content" in content:
                    inner_content = content.get("content")
                    if isinstance(inner_content, list):
                        original_content = "\n".join(str(item) for item in inner_content if item)
                    else:
                        original_content = str(inner_content)
                # content가 리스트인 경우
                elif isinstance(content, list):
                    original_content = "\n".join(str(item) for item in content if item)
                # content가 문자열인 경우
                else:
                    original_content = str(content)
        
        if not original_content:
            raise HTTPException(status_code=404, detail=f"제{article_number}조 내용을 찾을 수 없습니다")
        
        # 리스크와 권고사항
        risks = sections.get("section_5_practical_risks", "")
        recommendations = sections.get("section_6_improvement_recommendations", "")
        
        logger.info(f"[REVISION] 제{article_number}조: 원본={len(original_content)}자, 리스크={len(risks)}자, 권고={len(recommendations)}자")
        
        # Azure OpenAI 클라이언트 초기화
        api_key = os.getenv('AZURE_OPENAI_API_KEY')
        endpoint = os.getenv('AZURE_OPENAI_ENDPOINT')
        
        if not api_key or not endpoint:
            raise ValueError("Azure OpenAI 환경 변수가 설정되지 않음")
        
        client = AzureOpenAI(
            api_key=api_key,
            azure_endpoint=endpoint,
            api_version="2024-02-01"
        )
        
        # LLM 프롬프트
        prompt = f"""당신은 데이터 계약서 전문 검토자이며, 사용자가 제공한 “기존 조항”을 최소한으로 개선하는 전문가입니다.

이번 작업은 다음의 개선 규칙을 반드시 지키면서 수행해야 합니다.

────────────────────────────────────
📌 개선 절대 원칙 (필수 준수)

1) 조(條)·항(項)·호(號)의 번호는 절대 변경하지 않는다.
   - ① ② ③ 등 번호 그대로 유지.
   - 문단 순서도 동일하게 유지.
   - 항 새로 생성 금지, 삭제 금지, 병합 금지.

2) 전체 문장을 재작성하거나 문체를 통째로 바꾸지 않는다.
   - “리스크·권고사항”에서 지적된 부분에 한해 필요한 최소한의 수정만 한다.
   - 원본 의미를 변경하는 수정 금지.
   - 원본에 없는 개념·절차를 임의 도입 금지.

3) 표준계약서 문구의 직접 복사 금지.
   - 의미는 반영하되 표현은 자연스럽고 최소한으로 조정.

4) 수정이 필요 없는 문장은 그대로 둔다.
   - 수정이 발생한 문장만 정확히 표시해야 한다.

5) 전체 길이를 원본보다 과도하게 늘리지 않는다.
────────────────────────────────────

【원본 조항】
제{article_number}조
{original_content}

【실무적 리스크】
{risks if risks else '없음'}

【개선 권고사항】
{recommendations if recommendations else '없음'}

────────────────────────────────────
📌 작업 지침
1. 원본 조항의 조 → 항 → 호 구조는 그대로 유지한다.
2. 리스크/권고사항에 해당하는 문장만 최소한으로 보완한다.
3. 개선된 전체 조항을 먼저 작성한다.
4. 이후 "변경된 부분만" 목록으로 정리한다.
────────────────────────────────────

📌 출력 형식 (반드시 준수)
개선된 조항:
[여기에 최종 개선본]

변경 사항:
1. [추가] 변경 이유 포함
2. [수정] 변경 이유 포함
3. [삭제] 변경 이유 포함
(없으면 “해당 없음”)

────────────────────────────────────
📌 출력 규칙
- Markdown의 **굵게**만 사용 가능.
- HTML 태그(<div>, <span>, <p> 등)는 절대 사용하지 않는다.
- 색상·배경 등 스타일 사용 금지.
- 반드시 텍스트 기반 Markdown만 출력할 것.
────────────────────────────────────

출력을 시작하세요."""
        
        response = client.chat.completions.create(
            model="gpt-5",
            messages=[
                {
                    "role": "system",
                    "content": (
                        "당신은 데이터 계약서 전문 검토자입니다. "
                        "사용자 조항을 원본 구조 그대로 유지하면서 "
                        "리스크와 권고사항에 해당하는 부분만 최소한으로 수정합니다."
                    )
                },
                {"role": "user", "content": prompt}
            ],
        )
        
        revised_text = response.choices[0].message.content
        
        logger.info(f"[REVISION DEBUG] LLM 응답 길이: {len(revised_text)}")
        logger.info(f"[REVISION DEBUG] LLM 응답 미리보기: {revised_text[:500]}")
        
        # 응답 파싱 (유연한 방식)
        revised_content = ""
        changes = []
        
        lines = revised_text.split('\n')
        in_revised = False
        in_changes = False
        
        for line in lines:
            # 코드블록 마커 스킵
            if line.strip().startswith("```"):
                continue
            
            # 공백 제거한 normalized 버전
            normalized = line.replace(" ", "").replace(":", "").lower()
            
            # "개선된 조항" 섹션 시작 감지 (유연하게)
            if any(key in normalized for key in ["개선된조항", "개선된사항", "수정된조항", "최종조항"]):
                in_revised = True
                in_changes = False
                logger.info(f"[REVISION DEBUG] '개선된 조항' 섹션 시작: {line}")
                continue
            # Markdown 헤더로 시작하는 경우
            elif line.strip().startswith("#") and "개선" in line and "조항" in line:
                in_revised = True
                in_changes = False
                logger.info(f"[REVISION DEBUG] '개선된 조항' 섹션 시작 (헤더): {line}")
                continue
            
            # "변경 사항" 섹션 시작 감지 (유연하게)
            if any(key in normalized for key in ["변경사항", "변경내역", "변경내용", "수정사항"]):
                in_revised = False
                in_changes = True
                logger.info(f"[REVISION DEBUG] '변경 사항' 섹션 시작, revised_content 길이: {len(revised_content)}")
                continue
            # Markdown 헤더로 시작하는 경우
            elif line.strip().startswith("#") and "변경" in line:
                in_revised = False
                in_changes = True
                logger.info(f"[REVISION DEBUG] '변경 사항' 섹션 시작 (헤더): {line}")
                continue
            
            if in_revised and line.strip():
                revised_content += line + '\n'
            elif in_changes and line.strip() and line.startswith(('1.', '2.', '3.', '4.', '5.')):
                # 변경 사항 파싱
                change_text = line.split('.', 1)[1].strip() if '.' in line else line
                
                if '[추가]' in change_text:
                    change_type = 'added'
                    reason = change_text.replace('[추가]', '').strip()
                elif '[수정]' in change_text:
                    change_type = 'modified'
                    reason = change_text.replace('[수정]', '').strip()
                elif '[삭제]' in change_text:
                    change_type = 'deleted'
                    reason = change_text.replace('[삭제]', '').strip()
                else:
                    continue
                
                changes.append({
                    "type": change_type,
                    "reason": reason
                })
        
        logger.info(f"조항 수정본 생성 완료: {contract_id}, 제{article_number}조")
        
        return {
            "contract_id": contract_id,
            "article_number": article_number,
            "article_title": article_title,
            "original_content": original_content,
            "revised_content": revised_content.strip(),
            "changes": changes
        }
    
    except HTTPException:
        raise
    except Exception as e:
        logger.exception(f"조항 수정본 생성 중 오류: {e}")
        raise HTTPException(status_code=500, detail=str(e))
