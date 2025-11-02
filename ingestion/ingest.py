import cmd
import os
import sys
from pathlib import Path
from typing import Optional
import logging
from dotenv import load_dotenv

# .env 파일 로드
load_dotenv()

logging.basicConfig(
    level=logging.INFO,
    format='%(asctime)s - %(name)s - %(levelname)s - %(message)s'
)
logger = logging.getLogger(__name__)


class IngestionCLI(cmd.Cmd):
    """지식베이스 구축 CLI 모듈"""
    
    intro = """

Commands:
  - run       : 작업 실행
  - search    : 하이브리드 검색 (FAISS + Whoosh BM25)
  - s_search  : 간이 검색 (FAISS only)
  - status    : 디렉토리 상태 확인
  - delete    : 청크 또는 인덱스 파일 삭제
  - help      : 도움말
  - exit      : 종료

"""
    prompt = ' ingestion> '
    
    def __init__(self):
        super().__init__()
        # 경로 설정 (Docker와 로컬 모두 지원)
        if os.path.exists("/app/data"):
            self.base_path = Path("/app/data")
            self.index_path = Path("/app/search_indexes")
        else:
            self.base_path = Path("./data")
            self.index_path = Path("./data/search_indexes")
        
        self.extracted_path = self.base_path / "extracted_documents"
        self.chunked_path = self.base_path / "chunked_documents"
    
    def do_run(self, arg):
        """
        작업 실행
        
        사용법:
          run --mode <mode> --file <filename>
          run -m <mode> -f <filename>
          
        예시:
          run --mode parsing --file create_std_contract.pdf
          run -m parsing -f create_std_contract.docx
          run -m full -f all
          run --mode art_chunking --file create_std_contract_structured.json
          run -m embedding -f create_std_contract_art_chunks.jsonl
        
        --mode 옵션:
          - full           : 전체 파이프라인 (파싱→청킹→임베딩→인덱싱)
          - parsing        : 문서 파싱만 (PDF/DOCX 자동 감지)
          - art_chunking   : 조/별지 단위 청킹
          - chunking       : 항/호 단위 청킹
          - embedding      : 임베딩 + 인덱싱
          - s_embedding    : 간이 청킹 및 임베딩 (조/별지 단위)
        
        --file 옵션:
          - all             : 모든 파일 (PDF, DOCX 모두)
          - <filename>      : 특정 파일 하나
        
        참고:
          - 파일 확장자 감지로 파서 자동 선택
          - 파일명에 'guidebook' 포함 시 활용안내서 모듈 사용
          - 그 외 파일은 표준계약서 모듈 사용
        """
        try:
            # 인자 파싱
            args = self._parse_run_args(arg)
            if not args:
                return
            
            mode = args.get('mode')
            filename = args.get('file')
            
            logger.info("=" * 60)
            logger.info(f" 작업 시작")
            logger.info(f"  모드: {mode}")
            logger.info(f"  파일: {filename}")
            logger.info("=" * 60)
            
            # 모드별 실행
            if mode == 'full':
                self._run_full_pipeline(filename)
            elif mode == 'parsing':
                self._run_parsing(filename)
            elif mode == 'art_chunking':
                self._run_art_chunking(filename)
            elif mode == 'chunking':
                self._run_chunking(filename)
            elif mode == 'embedding':
                self._run_embedding(filename)
            elif mode == 's_embedding':
                self._run_simple_embedding(filename)
            else:
                logger.error(f" 알 수 없는 모드: {mode}")
                return
            
            logger.info("=" * 60)
            logger.info(" 작업 완료")
            logger.info("=" * 60)
            
        except Exception as e:
            logger.error(f" 오류 발생: {e}")
            import traceback
            traceback.print_exc()
    
    def _parse_run_args(self, arg):
        """run 명령어 인자 파싱"""
        args = {}
        tokens = arg.split()
        
        i = 0
        while i < len(tokens):
            if tokens[i] in ['--mode', '-m'] and i + 1 < len(tokens):
                mode = tokens[i + 1]
                if mode not in ['full', 'parsing', 'art_chunking', 'chunking', 'embedding', 's_embedding']:
                    logger.error(f" 잘못된 모드: {mode}")
                    logger.error("   사용 가능: full, parsing, art_chunking, chunking, embedding, s_embedding")
                    return None
                args['mode'] = mode
                i += 2
            elif tokens[i] in ['--file', '-f'] and i + 1 < len(tokens):
                args['file'] = tokens[i + 1]
                i += 2
            else:
                i += 1
        
        # 필수 인자 체크
        if 'mode' not in args:
            logger.error(" --mode (-m) 인자가 필요합니다")
            return None
        if 'file' not in args:
            logger.error(" --file (-f) 인자가 필요합니다")
            return None
        
        return args
    
    def _is_guidebook(self, filename):
        if filename == 'all':
            return None  # all은 혼합 타입
        return 'guidebook' in filename.lower()
    
    def _run_full_pipeline(self, filename):
        logger.info("=== 전체 파이프라인 실행 ===")
        self._run_parsing(filename)
        
        # 파싱 결과를 청킹 입력으로
        if filename == 'all':
            chunking_file = 'all'
        else:
            # .pdf 또는 .docx를 .json으로 변환
            chunking_file = filename.replace('.pdf', '.json').replace('.docx', '_structured.json')
        
        self._run_art_chunking(chunking_file)
        
        # 청킹 결과를 임베딩 입력으로
        if filename == 'all':
            embedding_file = 'all'
        else:
            # 확장자 제거 후 _art_chunks.jsonl 추가
            base_name = filename.rsplit('.', 1)[0]
            embedding_file = f"{base_name}_art_chunks.jsonl"
        
        self._run_embedding(embedding_file)
    
    def _get_parser(self, filename: str, file_ext: str):
        """
        파일명과 확장자를 기반으로 적절한 파서 선택
        
        Args:
            filename: 파일명
            file_ext: 파일 확장자 (.pdf, .docx 등)
            
        Returns:
            파서 인스턴스
        """
        is_guidebook = self._is_guidebook(filename)
        
        # 확장자와 문서 유형에 따라 파서 선택
        if file_ext == '.pdf':
            if is_guidebook:
                from ingestion.parsers.guidebook_pdf_parser import GuidebookPdfParser
                return GuidebookPdfParser(), "활용안내서 PDF 파서"
            else:
                from ingestion.parsers.std_contract_pdf_parser import StdContractPdfParser
                return StdContractPdfParser(), "표준계약서 PDF 파서"
        
        elif file_ext == '.docx':
            if is_guidebook:
                from ingestion.parsers.guidebook_docx_parser import GuidebookDocxParser
                return GuidebookDocxParser(), "활용안내서 DOCX 파서"
            else:
                from ingestion.parsers.std_contract_docx_parser import StdContractDocxParser
                return StdContractDocxParser(), "표준계약서 DOCX 파서"
        
        else:
            raise ValueError(f"지원하지 않는 파일 형식: {file_ext}")
    
    def _run_parsing(self, filename):
        logger.info("=== 1단계: 파싱 시작 ===")
        logger.info(f"  입력: {self.source_path}")
        logger.info(f"  출력: {self.extracted_path}")
        
        # 출력 디렉토리 생성
        self.extracted_path.mkdir(parents=True, exist_ok=True)
        
        if filename == 'all':
            # 모든 파일 처리 (PDF와 DOCX)
            pdf_files = list(self.source_path.glob("*.pdf"))
            docx_files = list(self.source_path.glob("*.docx"))
            all_files = pdf_files + docx_files
            
            logger.info(f"  처리할 파일: {len(all_files)}개 (PDF: {len(pdf_files)}, DOCX: {len(docx_files)})")
            
            for file in all_files:
                file_ext = file.suffix.lower()
                
                try:
                    parser, parser_name = self._get_parser(file.name, file_ext)
                    logger.info(f"    - {file.name} ({parser_name})")
                    
                    parser.parse(file, self.extracted_path)
                    logger.info(f"        파싱 완료")
                    
                except ValueError as e:
                    logger.error(f"       [ERROR] {e}")
                except Exception as e:
                    logger.error(f"       [ERROR] 파싱 실패: {e}")
                    import traceback
                    traceback.print_exc()
        else:
            # 특정 파일 처리
            file_path = self.source_path / filename
            if not file_path.exists():
                logger.error(f"   [ERROR] 파일을 찾을 수 없습니다: {filename}")
                return
            
            file_ext = file_path.suffix.lower()
            
            try:
                parser, parser_name = self._get_parser(filename, file_ext)
                logger.info(f"  처리할 파일: {filename}")
                logger.info(f"  사용 파서: {parser_name}")
                
                parser.parse(file_path, self.extracted_path)
                logger.info(f"   [OK] 파싱 완료")
                
            except ValueError as e:
                logger.error(f"   [ERROR] {e}")
            except Exception as e:
                logger.error(f"   [ERROR] 파싱 실패: {e}")
                import traceback
                traceback.print_exc()
    
    def _run_art_chunking(self, filename):
        logger.info("=== 2단계: 조/별지 단위 청킹 시작 ===")
        logger.info(f"  입력: {self.extracted_path}")
        logger.info(f"  출력: {self.chunked_path}")
        
        # 출력 디렉토리 생성
        self.chunked_path.mkdir(parents=True, exist_ok=True)
        
        from ingestion.processors.art_chunker import ArticleChunker
        
        if filename == 'all':
            pattern = "*_structured.json"
            files = list(self.extracted_path.glob(pattern))
            logger.info(f"  처리할 파일: {len(files)}개")
            
            for file in files:
                is_guidebook = self._is_guidebook(file.name)
                
                if is_guidebook:
                    logger.warning(f"    - {file.name} (활용안내서 청커 - 미구현, 건너뜀)")
                    continue
                
                try:
                    logger.info(f"    - {file.name} (조/별지 단위 청커)")
                    
                    # 청커 초기화 및 처리
                    chunker = ArticleChunker()
                    chunks = chunker.chunk_file(file)
                    
                    # 출력 파일명 생성 (provide_std_contract_structured.json -> provide_std_contract_art_chunks.json)
                    output_name = file.name.replace('_structured.json', '_art_chunks.json')
                    output_path = self.chunked_path / output_name
                    
                    # 청크 저장
                    chunker.save_chunks(chunks, output_path)
                    
                    logger.info(f"        청킹 완료: {len(chunks)}개 청크 생성")
                    
                except Exception as e:
                    logger.error(f"       [ERROR] 청킹 실패: {e}")
                    import traceback
                    traceback.print_exc()
        else:
            file_path = self.extracted_path / filename
            if not file_path.exists():
                logger.error(f"   [ERROR] 파일을 찾을 수 없습니다: {filename}")
                return
            
            is_guidebook = self._is_guidebook(filename)
            
            if is_guidebook:
                logger.error(f"   [ERROR] 활용안내서 청커는 아직 구현되지 않았습니다")
                return
            
            try:
                logger.info(f"  처리할 파일: {filename}")
                logger.info(f"  사용 청커: 조/별지 단위 청커")
                
                # 청커 초기화 및 처리
                chunker = ArticleChunker()
                chunks = chunker.chunk_file(file_path)
                
                # 출력 파일명 생성
                output_name = filename.replace('_structured.json', '_art_chunks.json')
                output_path = self.chunked_path / output_name
                
                # 청크 저장
                chunker.save_chunks(chunks, output_path)
                
                logger.info(f"   [OK] 청킹 완료: {len(chunks)}개 청크 생성")
                logger.info(f"   [OK] 출력 파일: {output_path}")
                
            except Exception as e:
                logger.error(f"   [ERROR] 청킹 실패: {e}")
                import traceback
                traceback.print_exc()
    
    def _run_chunking(self, filename):
        logger.info("=== 2단계: 항/호 단위 청킹 시작 ===")
        logger.info(f"  입력: {self.extracted_path}")
        logger.info(f"  출력: {self.chunked_path}")
        
        # 출력 디렉토리 생성
        self.chunked_path.mkdir(parents=True, exist_ok=True)
        
        from ingestion.processors.chunker import ClauseChunker
        
        if filename == 'all':
            pattern = "*_structured.json"
            files = list(self.extracted_path.glob(pattern))
            logger.info(f"  처리할 파일: {len(files)}개")
            
            for file in files:
                is_guidebook = self._is_guidebook(file.name)
                
                if is_guidebook:
                    logger.warning(f"    - {file.name} (활용안내서 청커 - 미구현, 건너뜀)")
                    continue
                
                try:
                    logger.info(f"    - {file.name} (항/호 단위 청커)")
                    
                    # 청커 초기화 및 처리
                    chunker = ClauseChunker()
                    chunks = chunker.chunk_file(file)
                    
                    # 출력 파일명 생성 (provide_std_contract_structured.json -> provide_std_contract_chunks.json)
                    output_name = file.name.replace('_structured.json', '_chunks.json')
                    output_path = self.chunked_path / output_name
                    
                    # 청크 저장
                    chunker.save_chunks(chunks, output_path)
                    
                    logger.info(f"        청킹 완료: {len(chunks)}개 청크 생성")
                    
                except Exception as e:
                    logger.error(f"       [ERROR] 청킹 실패: {e}")
                    import traceback
                    traceback.print_exc()
        else:
            file_path = self.extracted_path / filename
            if not file_path.exists():
                logger.error(f"   [ERROR] 파일을 찾을 수 없습니다: {filename}")
                return
            
            is_guidebook = self._is_guidebook(filename)
            
            if is_guidebook:
                logger.error(f"   [ERROR] 활용안내서 청커는 아직 구현되지 않았습니다")
                return
            
            try:
                logger.info(f"  처리할 파일: {filename}")
                logger.info(f"  사용 청커: 항/호 단위 청커")
                
                # 청커 초기화 및 처리
                chunker = ClauseChunker()
                chunks = chunker.chunk_file(file_path)
                
                # 출력 파일명 생성
                output_name = filename.replace('_structured.json', '_chunks.json')
                output_path = self.chunked_path / output_name
                
                # 청크 저장
                chunker.save_chunks(chunks, output_path)
                
                logger.info(f"   [OK] 청킹 완료: {len(chunks)}개 청크 생성")
                logger.info(f"   [OK] 출력 파일: {output_path}")
                
            except Exception as e:
                logger.error(f"   [ERROR] 청킹 실패: {e}")
                import traceback
                traceback.print_exc()
    
    def _run_embedding(self, filename):
        """임베딩 + 인덱싱 실행"""
        import os
        from ingestion.processors.embedder import TextEmbedder

        logger.info("=== 3단계: 임베딩 시작 ===")
        logger.info(f"  입력: {self.chunked_path}")
        logger.info(f"  출력: {self.index_path}")

        # Azure OpenAI API 키 및 엔드포인트 확인
        api_key = os.getenv('AZURE_OPENAI_API_KEY')
        azure_endpoint = os.getenv('AZURE_OPENAI_ENDPOINT')

        if not api_key:
            logger.error("   [ERROR] AZURE_OPENAI_API_KEY 환경변수가 설정되지 않았습니다")
            return

        if not azure_endpoint:
            logger.error("   [ERROR] AZURE_OPENAI_ENDPOINT 환경변수가 설정되지 않았습니다")
            return

        # Azure OpenAI deployment name 확인 (선택사항, 기본값 사용 가능)
        deployment_name = os.getenv('AZURE_EMBEDDING_DEPLOYMENT', 'text-embedding-3-large')

        logger.info(f"  Azure Endpoint: {azure_endpoint}")
        logger.info(f"  Deployment Name: {deployment_name}")

        # TextEmbedder 초기화
        embedder = TextEmbedder(
            api_key=api_key,
            azure_endpoint=azure_endpoint,
            model=deployment_name
        )

        # 출력 디렉토리
        faiss_output_dir = self.index_path / "faiss"
        whoosh_output_dir = self.index_path / "whoosh"

        if filename == 'all':
            pattern = "*_chunks.json"
            files = list(self.chunked_path.glob(pattern))
            logger.info(f"  처리할 파일: {len(files)}개")

            for file in files:
                is_guidebook = self._is_guidebook(file.name)

                if is_guidebook:
                    logger.warning(f"    - {file.name} (활용안내서 - 건너뜀)")
                    continue

                try:
                    logger.info(f"    - {file.name} (표준계약서)")

                    # 임베딩 및 FAISS/Whoosh 인덱스 생성
                    success = embedder.process_file(file, faiss_output_dir, whoosh_output_dir)

                    if not success:
                        logger.error(f"       [ERROR] 임베딩 실패: {file.name}")
                    else:
                        logger.info(f"        임베딩 및 인덱싱 완료")

                except Exception as e:
                    logger.error(f"       [ERROR] 임베딩 실패: {e}")
                    import traceback
                    traceback.print_exc()
        else:
            file_path = self.chunked_path / filename
            if not file_path.exists():
                logger.error(f"   [ERROR] 파일을 찾을 수 없습니다: {filename}")
                return

            is_guidebook = self._is_guidebook(filename)

            if is_guidebook:
                logger.error(f"   [ERROR] 활용안내서 임베딩은 아직 지원하지 않습니다")
                return

            try:
                logger.info(f"  처리할 파일: {filename}")
                logger.info(f"  문서 타입: 표준계약서")

                # 임베딩 및 FAISS/Whoosh 인덱스 생성
                success = embedder.process_file(file_path, faiss_output_dir, whoosh_output_dir)

                if not success:
                    logger.error(f"   [ERROR] 임베딩 실패")
                    return

                logger.info(f"   [OK] 임베딩 및 인덱싱 완료")

            except Exception as e:
                logger.error(f"   [ERROR] 임베딩 실패: {e}")
                import traceback
                traceback.print_exc()
    
    def _run_simple_embedding(self, filename):
        """
        간이 청킹 및 임베딩 실행
        조/별지 단위로 청킹하고 Azure OpenAI 임베딩 생성 후 FAISS에 저장
        """
        import os
        from ingestion.processors.s_embedder import SimpleEmbedder
        
        logger.info("=== 간이 청킹 및 임베딩 시작 ===")
        logger.info(f"  입력: {self.extracted_path}")
        logger.info(f"  출력: {self.index_path}")
        
        # Azure OpenAI API 키 및 엔드포인트 확인
        api_key = os.getenv('AZURE_OPENAI_API_KEY')
        azure_endpoint = os.getenv('AZURE_OPENAI_ENDPOINT')

        if not api_key:
            logger.error("   [ERROR] AZURE_OPENAI_API_KEY 환경변수가 설정되지 않았습니다")
            return

        if not azure_endpoint:
            logger.error("   [ERROR] AZURE_OPENAI_ENDPOINT 환경변수가 설정되지 않았습니다")
            return
        
        # structured.json 파일 경로 확인
        file_path = self.extracted_path / filename
        if not file_path.exists():
            logger.error(f"   [ERROR] 파일을 찾을 수 없습니다: {filename}")
            return
        
        # Azure OpenAI deployment name 확인 (선택사항, 기본값 사용 가능)
        deployment_name = os.getenv('AZURE_EMBEDDING_DEPLOYMENT', 'text-embedding-3-large')
        
        logger.info(f"  Azure Endpoint: {azure_endpoint}")
        logger.info(f"  Deployment Name: {deployment_name}")
        
        # SimpleEmbedder로 처리
        embedder = SimpleEmbedder(
            api_key=api_key,
            azure_endpoint=azure_endpoint,
            model=deployment_name
        )
        faiss_output_dir = self.index_path / "faiss"
        
        success = embedder.process_file(file_path, faiss_output_dir)
        
        if not success:
            logger.error("   [ERROR] 간이 청킹 및 임베딩 실패")
            return
    
    def do_s_search(self, arg):
        """
        간이 FAISS 검색 (Simple Search)

        사용법:
          s_search --index <index_name> --query <query_text>
          s_search -i <index_name> -q <query_text>
          s_search -i <index_name> -q <query_text> --top <k>

        예시:
          s_search -i provide_std_contract -q "질의"
          s_search -i provide_std_contract -q "질의" --top 3

        --index 옵션:
          - FAISS 인덱스 이름
          - 예: provide_std_contract

        --query 옵션:
          - 검색할 질문

        --top 옵션 (선택):
          - 반환할 결과 개수 (기본값: 5)
        """
        try:
            import os
            from ingestion.processors.s_searcher import SimpleSearcher
            
            # 인자 파싱
            args = self._parse_search_args(arg)
            if not args:
                return
            
            index_name = args.get('index')
            query = args.get('query')
            top_k = args.get('top', 5)
            
            logger.info("=" * 60)
            logger.info(" 간이 RAG 검색 시작")
            logger.info(f"  인덱스: {index_name}")
            logger.info(f"  Top-K: {top_k}")
            logger.info("=" * 60)
            
            # Azure OpenAI API 키 및 엔드포인트 확인
            api_key = os.getenv('AZURE_OPENAI_API_KEY')
            azure_endpoint = os.getenv('AZURE_OPENAI_ENDPOINT')
            deployment_name = os.getenv('AZURE_EMBEDDING_DEPLOYMENT', 'text-embedding-3-large')
            
            if not api_key or not azure_endpoint:
                logger.error("   [ERROR] Azure OpenAI 환경변수가 설정되지 않았습니다")
                return
            
            # SimpleSearcher 초기화
            searcher = SimpleSearcher(
                api_key=api_key,
                azure_endpoint=azure_endpoint,
                embedding_model=deployment_name
            )
            
            # 인덱스 로드
            faiss_dir = self.index_path / "faiss"
            if not searcher.load_index(faiss_dir, index_name):
                return
            
            # 검색 수행
            results = searcher.search(query, top_k=top_k)
            
            # 결과 표시
            searcher.display_results(results)
            
            # 컨텍스트 추출 (LLM 사용 시 활용 가능)
            if results:
                context = searcher.get_context(results)
                logger.info(f"  [INFO] LLM용 컨텍스트 길이: {len(context)} 문자")
            
            logger.info("=" * 60)
            logger.info(" 검색 완료")
            logger.info("=" * 60)
            
        except Exception as e:
            logger.error(f" 오류 발생: {e}")
            import traceback
            traceback.print_exc()
    
    def _parse_search_args(self, arg):
        """search 명령어 인자 파싱"""
        args = {}
        tokens = arg.split()
        
        i = 0
        query_tokens = []
        collecting_query = False
        
        while i < len(tokens):
            if tokens[i] in ['--index', '-i'] and i + 1 < len(tokens):
                args['index'] = tokens[i + 1]
                i += 2
            elif tokens[i] in ['--query', '-q']:
                collecting_query = True
                i += 1
            elif tokens[i] in ['--top', '-t'] and i + 1 < len(tokens):
                try:
                    args['top'] = int(tokens[i + 1])
                except ValueError:
                    logger.error(f" --top 값은 숫자여야 합니다: {tokens[i + 1]}")
                    return None
                collecting_query = False
                i += 2
            elif collecting_query:
                # --top이 나올 때까지 모든 토큰을 쿼리로 수집
                if tokens[i] in ['--top', '-t']:
                    collecting_query = False
                    continue
                query_tokens.append(tokens[i])
                i += 1
            else:
                i += 1
        
        # 쿼리 조립
        if query_tokens:
            args['query'] = ' '.join(query_tokens)
        
        # 필수 인자 체크
        if 'index' not in args:
            logger.error(" --index (-i) 인자가 필요합니다")
            return None
        if 'query' not in args:
            logger.error(" --query (-q) 인자가 필요합니다")
            return None
        
        return args

    def do_search(self, arg):
        """
        하이브리드 검색 (FAISS + Whoosh BM25)

        사용법:
          search --index <index_name> --query <query_text>
          search -i <index_name> -q <query_text>
          search -i <index_name> -q <query_text> --top <k>
          search -i <index_name> -q <query_text> --top <k> --weight <dense_weight>

        예시:
          search -i provide_std_contract -q "계약 해지 조건"
          search -i provide_std_contract -q "데이터 제공 범위" --top 5
          search -i provide_std_contract -q "손해배상" --weight 0.8

        --index 옵션:
          - 인덱스 이름 (FAISS와 Whoosh 공통)
          - 예: provide_std_contract

        --query 옵션:
          - 검색할 질문

        --top 옵션 (선택):
          - 반환할 결과 개수 (기본값: 10)

        --weight 옵션 (선택):
          - Dense 검색 가중치 0~1 (기본값: 0.7)
          - Sparse 가중치 = 1 - dense_weight
        """
        try:
            import os
            from ingestion.processors.searcher import HybridSearcher

            # 인자 파싱
            args = self._parse_hybrid_search_args(arg)
            if not args:
                return

            index_name = args.get('index')
            query = args.get('query')
            top_k = args.get('top', 10)
            dense_weight = args.get('weight', 0.7)

            # Azure OpenAI API 키 및 엔드포인트 확인
            api_key = os.getenv('AZURE_OPENAI_API_KEY')
            azure_endpoint = os.getenv('AZURE_OPENAI_ENDPOINT')
            deployment_name = os.getenv('AZURE_EMBEDDING_DEPLOYMENT', 'text-embedding-3-large')

            if not api_key or not azure_endpoint:
                logger.error("   [ERROR] Azure OpenAI 환경변수가 설정되지 않았습니다")
                return

            # HybridSearcher 초기화
            searcher = HybridSearcher(
                api_key=api_key,
                azure_endpoint=azure_endpoint,
                embedding_model=deployment_name,
                dense_weight=dense_weight
            )

            # 인덱스 로드
            faiss_dir = self.index_path / "faiss"
            whoosh_dir = self.index_path / "whoosh"

            if not searcher.load_indexes(faiss_dir, whoosh_dir, index_name):
                return

            # 하이브리드 검색 수행
            results = searcher.search(query, top_k=top_k)

            # 결과 표시
            searcher.display_results(results)

            # 컨텍스트 추출 (LLM 사용 시 활용 가능)
            if results:
                context = searcher.get_context(results)
                logger.info(f"\n  [INFO] LLM용 컨텍스트 길이: {len(context)} 문자")

            logger.info("\n" + "=" * 60)
            logger.info(" 하이브리드 검색 완료")
            logger.info("=" * 60)

        except Exception as e:
            logger.error(f" 오류 발생: {e}")
            import traceback
            traceback.print_exc()

    def _parse_hybrid_search_args(self, arg):
        """하이브리드 search 명령어 인자 파싱"""
        args = {}
        tokens = arg.split()

        i = 0
        query_tokens = []
        collecting_query = False

        while i < len(tokens):
            if tokens[i] in ['--index', '-i'] and i + 1 < len(tokens):
                args['index'] = tokens[i + 1]
                i += 2
            elif tokens[i] in ['--query', '-q']:
                collecting_query = True
                i += 1
            elif tokens[i] in ['--top', '-t'] and i + 1 < len(tokens):
                try:
                    args['top'] = int(tokens[i + 1])
                except ValueError:
                    logger.error(f" --top 값은 숫자여야 합니다: {tokens[i + 1]}")
                    return None
                collecting_query = False
                i += 2
            elif tokens[i] in ['--weight', '-w'] and i + 1 < len(tokens):
                try:
                    weight = float(tokens[i + 1])
                    if not 0 <= weight <= 1:
                        logger.error(f" --weight 값은 0~1 사이여야 합니다: {weight}")
                        return None
                    args['weight'] = weight
                except ValueError:
                    logger.error(f" --weight 값은 숫자여야 합니다: {tokens[i + 1]}")
                    return None
                collecting_query = False
                i += 2
            elif collecting_query:
                # --top이나 --weight가 나올 때까지 모든 토큰을 쿼리로 수집
                if tokens[i] in ['--top', '-t', '--weight', '-w']:
                    collecting_query = False
                    continue
                query_tokens.append(tokens[i])
                i += 1
            else:
                i += 1

        # 쿼리 조립
        if query_tokens:
            args['query'] = ' '.join(query_tokens)

        # 필수 인자 체크
        if 'index' not in args:
            logger.error(" --index (-i) 인자가 필요합니다")
            return None
        if 'query' not in args:
            logger.error(" --query (-q) 인자가 필요합니다")
            return None

        return args

    def do_status(self, arg):
        """
        현재 디렉토리 상태 확인
        
        사용법:
          status
          status --detail
        """
        logger.info("=== 디렉토리 상태 ===")
        
        # source_documents
        pdf_files = list(self.source_path.glob("*.pdf")) if self.source_path.exists() else []
        docx_files = list(self.source_path.glob("*.docx")) if self.source_path.exists() else []
        logger.info(f"\n [원본 문서] ({self.source_path}):")
        logger.info(f"  총 {len(pdf_files) + len(docx_files)}개 파일 (PDF: {len(pdf_files)}, DOCX: {len(docx_files)})")
        if '--detail' in arg:
            for f in pdf_files + docx_files:
                logger.info(f"    - {f.name}")
        
        # extracted_documents
        json_files = list(self.extracted_path.glob("*.json")) if self.extracted_path.exists() else []
        logger.info(f"\n [파싱 결과] ({self.extracted_path}):")
        logger.info(f"  총 {len(json_files)}개 파일")
        if '--detail' in arg:
            for f in json_files:
                logger.info(f"    - {f.name}")
        
        # chunked_documents
        chunk_files = list(self.chunked_path.glob("*_chunks.json")) if self.chunked_path.exists() else []
        logger.info(f"\n [청킹 결과] ({self.chunked_path}):")
        logger.info(f"  총 {len(chunk_files)}개 파일")
        if '--detail' in arg:
            for f in chunk_files:
                logger.info(f"    - {f.name}")
        
        # search_indexes
        whoosh_status = self._check_whoosh_index()
        faiss_status = self._check_faiss_index()
        
        logger.info(f"\n [검색 인덱스] ({self.index_path}):")
        logger.info(f"  Whoosh: {whoosh_status['icon']} {whoosh_status['message']}")
        logger.info(f"  FAISS: {faiss_status['icon']} {faiss_status['message']}")
    
    def _check_whoosh_index(self) -> dict:
        """
        Whoosh 인덱스 파일 존재 확인
        
        Returns:
            dict: {"icon": str, "message": str, "exists": bool}
        """
        whoosh_dir = self.index_path / "whoosh"
        
        if not whoosh_dir.exists():
            return {"icon": "X", "message": "인덱스 디렉토리 없음", "exists": False}
        
        # 각 계약 유형별 인덱스 디렉토리 확인
        contract_types = ['provide', 'create', 'process', 'brokerage_provider', 'brokerage_user']
        index_dirs = []
        
        for contract_type in contract_types:
            index_dir = whoosh_dir / f"{contract_type}_std_contract"
            if index_dir.exists():
                # _MAIN_*.toc 파일이 있으면 인덱스가 생성된 것
                toc_files = list(index_dir.glob("_MAIN_*.toc"))
                if toc_files:
                    index_dirs.append(contract_type)
        
        if not index_dirs:
            return {"icon": "X", "message": "인덱스 없음", "exists": False}
        
        if len(index_dirs) == len(contract_types):
            return {"icon": "O", "message": f"준비됨 (5종 모두)", "exists": True}
        else:
            return {"icon": "!", "message": f"부분 준비됨 ({len(index_dirs)}/5종: {', '.join(index_dirs)})", "exists": True}
    
    def _check_faiss_index(self) -> dict:
        """
        FAISS 인덱스 파일 존재 확인
        
        Returns:
            dict: {"icon": str, "message": str, "exists": bool}
        """
        faiss_dir = self.index_path / "faiss"
        
        if not faiss_dir.exists():
            return {"icon": "X", "message": "인덱스 디렉토리 없음", "exists": False}
        
        # 각 계약 유형별 FAISS 인덱스 파일 확인
        contract_types = ['provide', 'create', 'process', 'brokerage_provider', 'brokerage_user']
        index_files = []
        
        for contract_type in contract_types:
            index_file = faiss_dir / f"{contract_type}_std_contract.faiss"
            if index_file.exists():
                index_files.append((contract_type, index_file))
        
        if not index_files:
            return {"icon": "X", "message": "인덱스 없음", "exists": False}
        
        total_size = sum(f.stat().st_size for _, f in index_files) / (1024 * 1024)  # MB
        
        if len(index_files) == len(contract_types):
            return {"icon": "O", "message": f"준비됨 (5종 모두, {total_size:.1f}MB)", "exists": True}
        else:
            types_str = ', '.join([t for t, _ in index_files])
            return {"icon": "!", "message": f"부분 준비됨 ({len(index_files)}/5종: {types_str}, {total_size:.1f}MB)", "exists": True}
    
    def do_ls(self, arg):
        """
        파일 목록 보기 (별칭: list)
        
        사용법:
          ls <디렉토리>
          
        디렉토리:
          - source    : 원본 PDF
          - extracted : 파싱 결과
          - chunked   : 청킹 결과 (art_chunks.json)
          - index     : 인덱스
        """
        if not arg:
            logger.error(" 디렉토리를 지정해주세요 (source, extracted, chunked, index)")
            return
        
        path_map = {
            'source': self.source_path,
            'extracted': self.extracted_path,
            'chunked': self.chunked_path,
            'index': self.index_path
        }
        
        if arg not in path_map:
            logger.error(f" 잘못된 디렉토리: {arg}")
            return
        
        target_path = path_map[arg]
        if not target_path.exists():
            logger.warning(f"  디렉토리가 존재하지 않습니다: {target_path}")
            return
        
        logger.info(f"\n {target_path}:")
        files = sorted(target_path.iterdir())
        for f in files:
            if f.is_file():
                size_kb = f.stat().st_size / 1024
                logger.info(f"  {f.name} ({size_kb:.1f} KB)")
            elif f.is_dir():
                logger.info(f"   {f.name}/")
    
    def do_delete(self, arg):
        """
        청크 또는 인덱스 파일 삭제
        
        사용법:
          delete --type chunks
          delete -t chunks
          delete --type indexes
          delete -t indexes
          
        타입:
          - chunks   : 청킹 결과 파일 삭제 (*_chunks.json)
          - indexes  : 인덱스 파일 삭제 (FAISS + Whoosh)
        """
        try:
            # 인자 파싱
            args = self._parse_delete_args(arg)
            if not args:
                return
            
            delete_type = args.get('type')
            
            logger.info("=" * 60)
            logger.info(f" 삭제 작업 시작: {delete_type}")
            logger.info("=" * 60)
            
            if delete_type == 'chunks':
                self._delete_chunks()
            elif delete_type == 'indexes':
                self._delete_indexes()
            else:
                logger.error(f" 알 수 없는 타입: {delete_type}")
                return
            
            logger.info("=" * 60)
            logger.info(" 삭제 완료")
            logger.info("=" * 60)
            
        except Exception as e:
            logger.error(f" 오류 발생: {e}")
            import traceback
            traceback.print_exc()
    
    def _parse_delete_args(self, arg):
        """delete 명령어 인자 파싱"""
        args = {}
        tokens = arg.split()
        
        i = 0
        while i < len(tokens):
            if tokens[i] in ['--type', '-t'] and i + 1 < len(tokens):
                delete_type = tokens[i + 1]
                if delete_type not in ['chunks', 'indexes']:
                    logger.error(f" 잘못된 타입: {delete_type}")
                    logger.error("   사용 가능: chunks, indexes")
                    return None
                args['type'] = delete_type
                i += 2
            else:
                i += 1
        
        # 필수 인자 체크
        if 'type' not in args:
            logger.error(" --type (-t) 인자가 필요합니다")
            return None
        
        return args
    
    def _delete_chunks(self):
        """청크 파일 삭제"""
        if not self.chunked_path.exists():
            logger.warning(f"  청크 디렉토리가 존재하지 않습니다: {self.chunked_path}")
            return
        
        # *_chunks.json 파일 찾기
        chunk_files = list(self.chunked_path.glob("*_chunks.json"))
        
        if not chunk_files:
            logger.info("  삭제할 청크 파일이 없습니다")
            return
        
        logger.info(f"  삭제할 파일: {len(chunk_files)}개")
        
        deleted_count = 0
        for file in chunk_files:
            try:
                logger.info(f"    - {file.name}")
                file.unlink()
                deleted_count += 1
            except Exception as e:
                logger.error(f"       [ERROR] 삭제 실패: {e}")
        
        logger.info(f"  삭제 완료: {deleted_count}/{len(chunk_files)}개")
    
    def _delete_indexes(self):
        """인덱스 파일 삭제 (FAISS + Whoosh)"""
        deleted_faiss = self._delete_faiss_indexes()
        deleted_whoosh = self._delete_whoosh_indexes()
        
        logger.info(f"  FAISS 인덱스 삭제: {deleted_faiss}개")
        logger.info(f"  Whoosh 인덱스 삭제: {deleted_whoosh}개")
    
    def _delete_faiss_indexes(self):
        """FAISS 인덱스 파일 삭제"""
        faiss_dir = self.index_path / "faiss"
        
        if not faiss_dir.exists():
            logger.warning(f"  FAISS 디렉토리가 존재하지 않습니다: {faiss_dir}")
            return 0
        
        # *.faiss 파일 찾기
        faiss_files = list(faiss_dir.glob("*.faiss"))
        
        if not faiss_files:
            logger.info("  삭제할 FAISS 인덱스가 없습니다")
            return 0
        
        logger.info(f"  FAISS 인덱스 삭제 중... ({len(faiss_files)}개)")
        
        deleted_count = 0
        for file in faiss_files:
            try:
                logger.info(f"    - {file.name}")
                file.unlink()
                deleted_count += 1
            except Exception as e:
                logger.error(f"       [ERROR] 삭제 실패: {e}")
        
        return deleted_count
    
    def _delete_whoosh_indexes(self):
        """Whoosh 인덱스 파일 삭제"""
        whoosh_dir = self.index_path / "whoosh"
        
        if not whoosh_dir.exists():
            logger.warning(f"  Whoosh 디렉토리가 존재하지 않습니다: {whoosh_dir}")
            return 0
        
        # 계약 유형별 디렉토리 찾기
        contract_types = ['provide', 'create', 'process', 'brokerage_provider', 'brokerage_user']
        
        deleted_count = 0
        logger.info(f"  Whoosh 인덱스 삭제 중...")
        
        for contract_type in contract_types:
            index_dir = whoosh_dir / f"{contract_type}_std_contract"
            
            if not index_dir.exists():
                continue
            
            # 인덱스 파일들 찾기 (*.toc, *.seg, WRITELOCK)
            toc_files = list(index_dir.glob("*.toc"))
            seg_files = list(index_dir.glob("*.seg"))
            lock_files = list(index_dir.glob("*WRITELOCK"))
            
            all_files = toc_files + seg_files + lock_files
            
            if not all_files:
                continue
            
            logger.info(f"    - {contract_type}: {len(all_files)}개 파일")
            
            for file in all_files:
                try:
                    file.unlink()
                    deleted_count += 1
                except Exception as e:
                    logger.error(f"       [ERROR] 삭제 실패 ({file.name}): {e}")
        
        return deleted_count
    
    def do_exit(self, arg):
        logger.info("ingestion 종료")
        return True
    
    def emptyline(self):
        pass
    
    def default(self, line):
        logger.error(f" 알 수 없는 명령어 {line}")
        logger.info(" 'help'를 입력하여 사용 가능한 명령어 확인")


def main():
    """메인 함수"""
    cli = IngestionCLI()
    try:
        cli.cmdloop()
    except KeyboardInterrupt:
        logger.info("\n\ningestion 종료")
        sys.exit(0)


if __name__ == "__main__":
    main()
