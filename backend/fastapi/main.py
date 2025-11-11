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
from backend.shared.database import init_db, get_db, ContractDocument, ClassificationResult, ValidationResult, TokenUsage
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

        logger.info(f"검증 작업 시작 ({'병렬' if use_parallel else '순차'}): {contract_id}, "
                   f"task_id: {task.id}, weights: text={text_weight}, title={title_weight}, dense={dense_weight}")

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
    챗봇 메시지 전송
    
    Args:
        contract_id: 계약서 ID
        message: 사용자 메시지
        session_id: 세션 ID (선택)
        db: 데이터베이스 세션
        
    Returns:
        챗봇 응답
    """
    try:
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
        
        # ChatbotOrchestrator 초기화
        from backend.chatbot_agent.agent import ChatbotOrchestrator
        from openai import AzureOpenAI
        import os
        
        azure_client = AzureOpenAI(
            api_key=os.getenv('AZURE_OPENAI_API_KEY'),
            azure_endpoint=os.getenv('AZURE_OPENAI_ENDPOINT'),
            api_version="2024-02-01"
        )
        
        orchestrator = ChatbotOrchestrator(azure_client=azure_client)
        
        # 메시지 처리
        response = orchestrator.process_message(
            contract_id=contract_id,
            user_message=message,
            session_id=session_id
        )
        
        return response.to_dict()
    
    except HTTPException:
        raise
    except Exception as e:
        logger.exception(f"챗봇 메시지 처리 중 오류: {e}")
        raise HTTPException(status_code=500, detail=str(e))


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


if __name__ == "__main__":
    import uvicorn
    uvicorn.run("main:app", host="0.0.0.0", port=8000, reload=True)
