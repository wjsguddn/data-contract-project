import streamlit as st
import time
import requests


st.set_page_config(
    page_title="데이터 표준계약 검증",
    page_icon="",
    layout="centered",
    initial_sidebar_state="expanded",
)


def poll_classification_result(contract_id: str, max_attempts: int = 30, interval: int = 2):
    """
    분류 결과를 폴링하여 조회

    Args:
        contract_id: 계약서 ID
        max_attempts: 최대 시도 횟수 (기본 30회 = 1분)
        interval: 폴링 간격(초) (기본 2초)

    Returns:
        (success: bool, data: dict or None)
    """
    import requests

    for _ in range(max_attempts):
        try:
            classification_url = f"http://localhost:8000/api/classification/{contract_id}"
            class_resp = requests.get(classification_url, timeout=10)

            if class_resp.status_code == 200:
                return True, class_resp.json()
            elif class_resp.status_code == 404:
                # 아직 분류 완료되지 않음 - 계속 대기
                time.sleep(interval)
                continue
            else:
                # 오류 발생
                return False, {"error": f"HTTP {class_resp.status_code}: {class_resp.text}"}
        except Exception as e:
            return False, {"error": str(e)}

    # 타임아웃
    return False, {"error": "분류 작업이 너무 오래 걸립니다. 잠시 후 페이지를 새로고침해주세요."}


def main() -> None:
    # 세션 상태 초기화 (가중치)
    if 'text_weight' not in st.session_state:
        st.session_state.text_weight = 0.7
    if 'title_weight' not in st.session_state:
        st.session_state.title_weight = 0.3
    if 'dense_weight' not in st.session_state:
        st.session_state.dense_weight = 0.85
    
    # 사이드바 검색 설정
    with st.sidebar:
        st.header("검색 설정")
        
        st.subheader("본문:제목 가중치")
        text_weight = st.slider(
            "본문 가중치",
            min_value=0.0,
            max_value=1.0,
            value=st.session_state.text_weight,
            step=0.05,
            help="본문과 제목의 가중합 비율 (본문:제목)",
            key="text_weight_slider"
        )
        title_weight = 1.0 - text_weight
        st.caption(f"본문: {text_weight:.0%}, 제목: {title_weight:.0%}")
        
        # 세션 상태 업데이트
        st.session_state.text_weight = text_weight
        st.session_state.title_weight = title_weight
        
        st.subheader("시멘틱:키워드 가중치")
        dense_weight = st.slider(
            "시멘틱 가중치",
            min_value=0.0,
            max_value=1.0,
            value=st.session_state.dense_weight,
            step=0.05,
            help="시멘틱(FAISS)과 키워드(Whoosh)의 가중합 비율",
            key="dense_weight_slider"
        )
        sparse_weight = 1.0 - dense_weight
        st.caption(f"시멘틱: {dense_weight:.0%}, 키워드: {sparse_weight:.0%}")
        
        # 세션 상태 업데이트
        st.session_state.dense_weight = dense_weight
    
    # 상단 헤더
    st.markdown(
        """
        <div style="text-align:center; margin-top: 0.5rem;">
            <div style="text-align:center; font-size:3rem; font-weight:800; margin-bottom:0.5rem;">데이터 표준계약 검증</div>
            <p style="color:#6b7280;">계약서를 업로드하고 표준계약 기반 AI분석 보고서를 확인하세요.</p>
        </div>
        """,
        unsafe_allow_html=True,
    )
    
    st.markdown('<div style="height: 3rem;"></div>', unsafe_allow_html=True)

    # selectbox 텍스트 커서 제거 및 기본 포인터 유지 CSS
    st.markdown("""
        <style>
        /* selectbox의 input 요소에서 텍스트 커서 제거하고 기본 포인터 유지 */
        div[data-baseweb="select"] input {
            cursor: default !important;
            caret-color: transparent !important;
        }
        /* selectbox 전체 영역에서 기본 포인터 */
        div[data-baseweb="select"] {
            cursor: default !important;
        }
        /* selectbox 드롭다운 화살표 영역만 포인터 */
        div[data-baseweb="select"] svg {
            cursor: pointer !important;
        }
        </style>
    """, unsafe_allow_html=True)

    file = st.file_uploader("DOCX 파일을 업로드하세요", type=["docx"], accept_multiple_files=False)

    # session_state 초기화
    if 'uploaded_contract_data' not in st.session_state:
        st.session_state.uploaded_contract_data = None

    # 버튼 레이아웃: 파일 선택 또는 업로드 완료 시 표시
    if file is not None:
        is_classification_done = st.session_state.get('classification_done', False)
        col_btn1, _, col_btn3 = st.columns([2, 6, 2])

        with col_btn1:
            # 업로드하기 버튼 (분류 완료 시 secondary, 아니면 primary)
            upload_button_type = "secondary" if is_classification_done else "primary"
            upload_clicked = st.button("파일 업로드", type=upload_button_type, use_container_width=False)

        with col_btn3:
            # 분류 완료 후에만 검증 버튼 표시
            if is_classification_done:
                validate_clicked = st.button("계약서 검증", type="primary", use_container_width=True)
                if validate_clicked:
                    print("[DEBUG] 계약서 검증 버튼 클릭됨")
                    # 검증 시작: 상태 초기화
                    st.session_state.validation_started = True
                    st.session_state.validation_completed = False

                    # 기존 검증 결과 데이터 삭제
                    if 'validation_result_data' in st.session_state:
                        del st.session_state.validation_result_data

                    # 검증 시작 플래그 설정
                    st.session_state.validation_start_requested = True
                    print(f"[DEBUG] validation_start_requested 설정됨: {st.session_state.validation_start_requested}")
                    st.rerun()

        # 업로드 버튼 클릭 처리
        if upload_clicked:
            try:
                backend_url = "http://localhost:8000/upload"
                files = {"file": (file.name, file.getvalue(), "application/vnd.openxmlformats-officedocument.wordprocessingml.document")}
                resp = requests.post(backend_url, files=files, timeout=60)

                if resp.status_code == 200 and resp.json().get("success"):
                    data = resp.json()
                    contract_id = data.get('contract_id')

                    # session_state에 업로드 데이터 저장
                    st.session_state.uploaded_contract_data = {
                        'contract_id': contract_id,
                        'filename': data.get('filename'),
                        'file_size': len(file.getbuffer()),
                        'parsed_metadata': data.get('parsed_metadata', {}),
                        'structured_data': data.get('structured_data', {})
                    }

                    # 분류 상태 초기화
                    st.session_state.classification_done = False
                    
                    # 검증 상태 초기화
                    st.session_state.validation_started = False
                    st.session_state.validation_completed = False
                    if 'validation_task_id' in st.session_state:
                        del st.session_state.validation_task_id
                    
                    # 기존 검증 결과 데이터 삭제 (같은 파일 재업로드 시 갱신 위해)
                    if 'validation_result_data' in st.session_state:
                        del st.session_state.validation_result_data

                    # 페이지 리렌더링 강제
                    st.rerun()

                else:
                    st.error(f"업로드 실패: {resp.status_code} - {resp.text}")
            except Exception as e:
                st.error(f"연결 오류: {e}")

    # session_state에 업로드된 데이터가 있으면 UI 표시
    if st.session_state.uploaded_contract_data is not None:
        uploaded_data = st.session_state.uploaded_contract_data
        contract_id = uploaded_data['contract_id']

        # 검증 시작 요청 처리 (버튼 클릭 후) - 최우선 처리
        print(f"[DEBUG] validation_start_requested 체크: {st.session_state.get('validation_start_requested', False)}")
        if st.session_state.get('validation_start_requested', False):
            print("[DEBUG] validation_start_requested가 True임, start_validation 호출 예정")
            st.session_state.validation_start_requested = False  # 플래그 초기화
            start_validation(contract_id)
            st.rerun()  # 상태 업데이트를 반영하기 위해 리렌더링

        st.markdown('<div style="height: 2rem;"></div>', unsafe_allow_html=True)

        # 파일 정보
        col1, col2 = st.columns(2)
        with col1:
            st.write("**파일명**", f"`{uploaded_data['filename']}`")
        with col2:
            st.write("**크기**", f"{uploaded_data['file_size']/1024:.1f} KB")

        st.markdown('<div style="height: 1rem;"></div>', unsafe_allow_html=True)

        # 분류 결과 - 상태 표시
        status_placeholder = st.empty()

        # 분류가 아직 안된 경우에만 폴링
        if 'classification_done' not in st.session_state or not st.session_state.classification_done:
            # 초기 상태: 업로드 및 파싱 성공
            status_placeholder.success("업로드 및 파싱 성공")

            # 자동으로 분류 결과 조회
            with st.spinner("분류 작업이 진행 중입니다..."):
                success, result = poll_classification_result(contract_id)

            # 계약 유형 매핑
            type_names = {
                "provide": "데이터 제공형 계약",
                "create": "데이터 창출형 계약",
                "process": "데이터 가공서비스형 계약",
                "brokerage_provider": "데이터 중개거래형 계약 (제공자-운영자)",
                "brokerage_user": "데이터 중개거래형 계약 (이용자-운영자)"
            }

            if success:
                classification = result
                predicted_type = classification.get('predicted_type')
                confidence = classification.get('confidence', 0)

                # session_state에 분류 결과 저장
                st.session_state.classification_done = True
                st.session_state.predicted_type = predicted_type
                st.session_state.confidence = confidence
                st.session_state.user_modified = False  # AI 분류 결과

                # 검증 버튼을 렌더링하기 위해 페이지 리렌더링
                st.rerun()
            else:
                # 분류 실패
                status_placeholder.error(f"분류 실패: {result.get('error', '알 수 없는 오류')}")
                st.session_state.classification_done = False
        else:
            # 이미 분류가 완료된 경우 저장된 정보 표시
            type_names = {
                "provide": "데이터 제공형 계약",
                "create": "데이터 창출형 계약",
                "process": "데이터 가공서비스형 계약",
                "brokerage_provider": "데이터 중개거래형 계약 (제공자-운영자)",
                "brokerage_user": "데이터 중개거래형 계약 (이용자-운영자)"
            }
            predicted_type = st.session_state.predicted_type

            # 검증 상태에 따라 다른 메시지 표시
            if st.session_state.get('validation_completed', False):
                # 검증 완료
                status_placeholder.success("검증 완료")
            else:
                # 분류 완료 (검증 전 또는 검증 진행 중)
                if st.session_state.get('user_modified', False):
                    status_placeholder.success(f"분류 완료: **{type_names.get(predicted_type, predicted_type)}** (선택)")
                else:
                    confidence = st.session_state.confidence
                    status_placeholder.success(f"분류 완료: **{type_names.get(predicted_type, predicted_type)}** (신뢰도: {confidence:.1%})")

        # 파싱 메타데이터
        metadata = uploaded_data['parsed_metadata']

        st.markdown('<div style="height: 1rem;"></div>', unsafe_allow_html=True)

        # 검증 스피너를 위한 placeholder (status_placeholder 바로 아래)
        validation_spinner_placeholder = st.empty()

        # 검증 작업 진행 중 스피너 (placeholder에 표시)
        if st.session_state.get('validation_started', False) and not st.session_state.get('validation_completed', False):
            with validation_spinner_placeholder:
                with st.spinner("검증 작업이 진행 중입니다..."):
                    success, result = poll_validation_result(contract_id)

                if success:
                    # 검증 완료 - 결과를 session_state에 저장
                    st.session_state.validation_completed = True
                    st.session_state.validation_started = False  # 폴링 중지
                    st.session_state.validation_result_data = result  # 결과 저장
                    st.rerun()  # 상태 업데이트 후 리렌더링
                else:
                    # 검증 실패
                    st.error(f"검증 실패: {result.get('error', '알 수 없는 오류')}")
                    st.session_state.validation_started = False
        else:
            # 검증 진행 중이 아닐 때만 selectbox와 나머지 UI 표시
            # 분류 결과가 성공한 경우에만 유형 선택 UI 표시
            if st.session_state.get('classification_done', False):
                # 드롭다운으로 유형 선택
                def on_type_change():
                    """드롭다운 선택 변경 시 호출되는 콜백"""
                    selected = st.session_state[f"contract_type_{contract_id}"]
                    original = st.session_state.get('predicted_type')

                    if selected != original:
                        try:
                            confirm_url = f"http://localhost:8000/api/classification/{contract_id}/confirm?confirmed_type={selected}"
                            confirm_resp = requests.post(confirm_url, timeout=30)

                            if confirm_resp.status_code == 200:
                                st.session_state.predicted_type = selected  # 업데이트
                                st.session_state.user_modified = True  # 사용자가 수동으로 수정함
                        except Exception:
                            pass  # 오류 발생 시 무시

                st.selectbox(
                    "계약서 유형",
                    options=list(type_names.keys()),
                    format_func=lambda x: type_names[x],
                    index=list(type_names.keys()).index(st.session_state.get('predicted_type', predicted_type)) if st.session_state.get('predicted_type', predicted_type) in type_names else 0,
                    key=f"contract_type_{contract_id}",
                    on_change=on_type_change
                )

            st.markdown('<div style="height: 1rem;"></div>', unsafe_allow_html=True)

        # 계약서 구조 미리보기
        st.markdown('<p style="font-size: 0.875rem; font-weight: 400; margin-bottom: 0.5rem;">계약서 구조 미리보기</p>', unsafe_allow_html=True)
        with st.expander(f"인식된 조항: {metadata.get('recognized_articles', 0)}개"):
            # 좌우 패딩을 위한 마진 추가
            st.markdown("")  # 약간의 상단 여백

            structured_data = uploaded_data['structured_data']
            preamble = structured_data.get('preamble', [])
            articles = structured_data.get('articles', [])

            # Preamble 표시 (제1조 이전 텍스트)
            if preamble:
                # 첫 번째 문단 (제목) - 조금 크게
                if len(preamble) > 0:
                    st.markdown(f"<p style='font-size:1.15rem; font-weight:600; margin-bottom:0.5rem; margin-left:1rem; margin-right:1rem;'>{preamble[0]}</p>", unsafe_allow_html=True)

                # 나머지 문단들 - 작게 (줄바꿈 보존)
                if len(preamble) > 1:
                    for line in preamble[1:]:
                        # 줄바꿈을 <br>로 변환
                        line_with_br = line.replace('\n', '<br>')
                        st.markdown(f"<p style='font-size:0.85rem; margin:0.2rem 1rem; color:#d1d5db;'>{line_with_br}</p>", unsafe_allow_html=True)

            # 조항 목록
            if articles:
                st.divider()
                st.markdown(f"<p style='font-weight:600; margin-bottom:0.5rem; margin-left:1rem; margin-right:1rem;'><strong>총 {len(articles)}개 조항</strong></p>", unsafe_allow_html=True)

                # 모든 조항의 타이틀만 표시
                for i, article in enumerate(articles, 1):
                    st.markdown(f"<p style='margin:0.2rem 1rem;'>{i}. {article.get('text', 'N/A')}</p>", unsafe_allow_html=True)

                # 하단 여백
                st.markdown("<div style='height:2rem;'></div>", unsafe_allow_html=True)
            else:
                st.warning("조항을 찾을 수 없습니다.")

        # 검증 결과 표시
        if st.session_state.get('validation_completed', False):
            # 이미 검증이 완료된 경우 - session_state에 저장된 결과 표시
            if 'validation_result_data' in st.session_state:
                display_validation_result(st.session_state.validation_result_data)
            else:
                # fallback: API에서 조회
                try:
                    validation_url = f"http://localhost:8000/api/validation/{contract_id}"
                    resp = requests.get(validation_url, timeout=10)

                    if resp.status_code == 200:
                        data = resp.json()
                        if data.get('status') == 'completed':
                            st.session_state.validation_result_data = data
                            display_validation_result(data)
                except Exception as e:
                    st.error(f"검증 결과 조회 실패: {str(e)}")


def start_validation(contract_id: str):
    """검증 시작 - API 호출 (가중치 전달)"""
    try:
        print(f"[DEBUG] start_validation 호출됨: contract_id={contract_id}")
        
        # 세션 상태에서 가중치 읽기
        text_weight = st.session_state.get('text_weight', 0.7)
        title_weight = st.session_state.get('title_weight', 0.3)
        dense_weight = st.session_state.get('dense_weight', 0.85)
        
        print(f"[DEBUG] 가중치: text={text_weight}, title={title_weight}, dense={dense_weight}")
        
        # API 호출 시 가중치 파라미터 전달
        response = requests.post(
            f"http://localhost:8000/api/validation/{contract_id}/start",
            params={
                'text_weight': text_weight,
                'title_weight': title_weight,
                'dense_weight': dense_weight
            },
            timeout=30
        )
        print(f"[DEBUG] 응답 status_code: {response.status_code}")

        if response.status_code == 200:
            result = response.json()
            print(f"[DEBUG] 응답 데이터: {result}")
            st.session_state.validation_task_id = result.get('task_id')
            # 백엔드가 작업을 시작할 시간 확보
            time.sleep(2)
        else:
            error_detail = response.json().get('detail', '알 수 없는 오류')
            print(f"[DEBUG] 에러 발생: {error_detail}")
            st.error(f"검증 시작 실패: {error_detail}")
            # 실패 시 상태 초기화
            st.session_state.validation_started = False

    except Exception as e:
        print(f"[DEBUG] 예외 발생: {str(e)}")
        st.error(f"검증 시작 중 오류: {str(e)}")
        # 오류 시 상태 초기화
        st.session_state.validation_started = False


def poll_validation_result(contract_id: str, max_attempts: int = 600, interval: int = 3):
    """
    검증 결과를 폴링하여 조회
    
    Args:
        contract_id: 계약서 ID
        max_attempts: 최대 시도 횟수 (기본 600회 = 30분)
        interval: 폴링 간격(초) (기본 3초)
        
    Returns:
        (success: bool, data: dict or None)
    """
    for _ in range(max_attempts):
        try:
            validation_url = f"http://localhost:8000/api/validation/{contract_id}"
            resp = requests.get(validation_url, timeout=10)
            
            if resp.status_code == 200:
                data = resp.json()
                status = data.get('status')
                
                if status == 'completed':
                    return True, data
                elif status == 'processing':
                    time.sleep(interval)
                    continue
                elif status == 'not_started':
                    # 아직 시작 안됨 - 계속 대기
                    time.sleep(interval)
                    continue
                else:
                    return False, {"error": f"알 수 없는 상태: {status}"}
            else:
                return False, {"error": f"HTTP {resp.status_code}: {resp.text}"}
                
        except Exception as e:
            return False, {"error": str(e)}
    
    # 타임아웃
    return False, {"error": "검증 작업이 너무 오래 걸립니다. 잠시 후 페이지를 새로고침해주세요."}


def display_validation_result(validation_data: dict):
    """검증 결과 표시"""
    st.markdown('<div style="height: 2rem;"></div>', unsafe_allow_html=True)

    st.markdown("### 📋 검증 결과")
    
    validation_result = validation_data.get('validation_result', {})
    content_analysis = validation_result.get('content_analysis', {})
    
    col1, col2 = st.columns(2)
    
    with col1:
        total_articles = content_analysis.get('total_articles', 0)
        st.metric("전체 조문", f"{total_articles}개")
    
    with col2:
        analyzed_articles = content_analysis.get('analyzed_articles', 0)
        st.metric("분석 완료", f"{analyzed_articles}개")
    
    st.markdown("---")
    
    # 조항별 상세 분석
    article_analysis = content_analysis.get('article_analysis', [])

    if article_analysis:
        st.markdown('<div style="height: 1rem;"></div>', unsafe_allow_html=True)

        for analysis in article_analysis:
            user_article_no = analysis.get('user_article_no', 'N/A')
            user_article_title = analysis.get('user_article_title', '')
            matched = analysis.get('matched', False)
            similarity = analysis.get('similarity', 0.0)

            st.markdown(f"<h3 style='margin-bottom: 0.5rem;'>제{user_article_no}조 {user_article_title}</h3>", unsafe_allow_html=True)

            if matched:
                # Primary 매칭 조
                std_article_id = analysis.get('std_article_id', '')
                std_article_title = analysis.get('std_article_title', '')
                st.markdown(f"**Primary 매칭**: {std_article_id} ({std_article_title}) - Rank Score: {similarity:.3f}")

                # 다중 매칭 항목 표시
                matched_articles = analysis.get('matched_articles', [])
                if matched_articles and len(matched_articles) > 1:
                    st.markdown(f"**다중 매칭 항목** ({len(matched_articles)}개 조):")
                    for i, article in enumerate(matched_articles, 1):
                        article_id = article.get('parent_id', '')
                        article_title = article.get('title', '')
                        article_score = article.get('score', 0.0)
                        num_sub_items = article.get('num_sub_items', 0)
                        matched_sub_items = article.get('matched_sub_items', [])
                        sub_items_str = ', '.join(map(str, matched_sub_items))

                        # Primary는 강조 표시
                        if i == 1:
                            st.markdown(f"  **{i}. {article_id}** ({article_title}): {article_score:.3f} (하위항목 {num_sub_items}개: {sub_items_str})")
                        else:
                            st.markdown(f"  {i}. {article_id} ({article_title}): {article_score:.3f} (하위항목 {num_sub_items}개: {sub_items_str})")
            else:
                st.markdown(f"**매칭 결과**: 매칭 실패 (검색 결과 없음)")

            # 하위항목별 상세 결과
            sub_item_results = analysis.get('sub_item_results', [])
            if sub_item_results:
                # 하위항목별 상세 결과 (커스텀 토글)
                show_details_key = f"show_details_{user_article_no}"
                if show_details_key not in st.session_state:
                    st.session_state[show_details_key] = False

                # 현재 상태 읽기
                is_expanded = st.session_state[show_details_key]

                # 토글 버튼 (현재 상태 기준으로 레이블 표시)
                button_label = f"{'▼' if is_expanded else '▶'} 하위항목별 상세 ({len(sub_item_results)}개)"

                # 버튼 클릭 시 상태 토글 후 즉시 리렌더링
                if st.button(button_label, key=f"toggle_{user_article_no}", use_container_width=False):
                    st.session_state[show_details_key] = not is_expanded
                    st.rerun()

                if is_expanded:
                    for sub_result in sub_item_results:
                        sub_idx = sub_result.get('sub_item_index', 0)
                        sub_text = sub_result.get('sub_item_text', '')[:50]
                        matched_article = sub_result.get('matched_article_id', '')
                        matched_title = sub_result.get('matched_article_title', '')
                        sub_score = sub_result.get('score', 0.0)
                        
                        # Dense/Sparse 점수 추출 (matched_chunks에서)
                        matched_chunks = sub_result.get('matched_chunks', [])
                        if matched_chunks:
                            # 첫 번째 청크의 점수 사용 (대표값)
                            first_chunk = matched_chunks[0]
                            dense_score = first_chunk.get('dense_score', 0.0)
                            dense_score_raw = first_chunk.get('dense_score_raw', 0.0)
                            sparse_score = first_chunk.get('sparse_score', 0.0)
                            sparse_score_raw = first_chunk.get('sparse_score_raw', 0.0)
                            
                            st.markdown(f"  {sub_idx}. `{sub_text}...`")
                            st.markdown(f"     → {matched_article} ({matched_title})")
                            st.markdown(f"     Rank Score: {sub_score:.3f} (Dense: {dense_score:.3f}[{dense_score_raw:.3f}], Sparse: {sparse_score:.3f}[{sparse_score_raw:.3f}])")
                        else:
                            st.markdown(f"  {sub_idx}. `{sub_text}...`")
                            st.markdown(f"     → {matched_article} ({matched_title}) - Rank Score: {sub_score:.3f}")

            # 분석 이유
            reasoning = analysis.get('reasoning', '')
            if reasoning:
                st.markdown(f"{reasoning}")

            # 내용 분석 (개선 제안 또는 긍정적 평가)
            suggestions = analysis.get('suggestions', [])
            if suggestions:
                for idx, suggestion in enumerate(suggestions, 1):
                    # suggestion이 dict인 경우 analysis 필드만 렌더링
                    if isinstance(suggestion, dict):
                        analysis_text = suggestion.get('analysis', '')
                        severity = suggestion.get('severity', 'low')
                        selected_articles = suggestion.get('selected_standard_articles', [])

                        # 심각도 아이콘 및 레이블
                        severity_config = {
                            'high': {'icon': '🔴', 'label': '개선 필요'},
                            'medium': {'icon': '🟡', 'label': '개선 권장'},
                            'low': {'icon': '🟢', 'label': '경미한 개선'},
                            'info': {'icon': '✅', 'label': '충실히 작성됨'}
                        }
                        config = severity_config.get(severity, {'icon': '⚪', 'label': '분석'})
                        severity_icon = config['icon']
                        severity_label = config['label']

                        # 헤더 표시
                        if selected_articles:
                            articles_str = ', '.join(selected_articles)
                            st.markdown(f"**{severity_icon} {severity_label}** (참조: {articles_str})")
                        else:
                            st.markdown(f"**{severity_icon} {severity_label}**")

                        # analysis 텍스트 렌더링 (개행 적용)
                        if analysis_text:
                            # 개행을 markdown 개행으로 변환하여 표시
                            formatted_text = analysis_text.replace('\n', '  \n')
                            st.markdown(formatted_text)

                        st.markdown("")  # 여백
                    else:
                        # 하위 호환성: 문자열인 경우 그대로 출력
                        st.markdown(f"  - {suggestion}")

            st.markdown("---")

        # 처리 시간 (for loop 외부에 표시)
        processing_time = content_analysis.get('processing_time', 0.0)
        st.markdown(f"<p style='text-align:right; color:#6b7280; font-size:0.85rem;'>처리 시간: {processing_time:.2f}초</p>", unsafe_allow_html=True)
    
    # 체크리스트 검증 결과 표시 (MANUAL_CHECK_REQUIRED 포함)
    checklist_validation = validation_result.get('checklist_validation', {})
    if checklist_validation:
        display_checklist_results(checklist_validation)
    
    # 누락 조문 분석 결과 표시
    completeness_check = validation_result.get('completeness_check', {})
    missing_article_analysis = completeness_check.get('missing_article_analysis', [])
    
    if missing_article_analysis:
        st.markdown('<div style="height: 2rem;"></div>', unsafe_allow_html=True)
        st.markdown("### 🔍 누락 조문 재검증 결과")
        
        # 통계 표시
        total_missing = len(missing_article_analysis)
        truly_missing = sum(1 for item in missing_article_analysis if item.get('is_truly_missing', True))
        false_positive = total_missing - truly_missing
        
        col1, col2, col3 = st.columns(3)
        with col1:
            st.metric("1차 누락 조문", f"{total_missing}개")
        with col2:
            st.metric("실제 누락", f"{truly_missing}개", delta=None, delta_color="off")
        with col3:
            st.metric("오탐지 (포함됨)", f"{false_positive}개", delta=None, delta_color="off")
        
        st.markdown("---")
        
        # 각 누락 조문별 상세 분석
        for idx, analysis in enumerate(missing_article_analysis, 1):
            std_article_id = analysis.get('standard_article_id', '')
            std_article_title = analysis.get('standard_article_title', '')
            is_truly_missing = analysis.get('is_truly_missing', True)
            confidence = analysis.get('confidence', 0.0)
            
            # 헤더
            if is_truly_missing:
                st.markdown(f"<h4 style='color:#ef4444;'>❌ {std_article_id} ({std_article_title})</h4>", unsafe_allow_html=True)
                st.markdown(f"**상태**: 실제 누락 확인 (신뢰도: {confidence:.1%})")
            else:
                matched_user = analysis.get('matched_user_article', {})
                matched_no = matched_user.get('number', '?') if matched_user else '?'
                st.markdown(f"<h4 style='color:#10b981;'>✅ {std_article_id} ({std_article_title})</h4>", unsafe_allow_html=True)
                st.markdown(f"**상태**: 누락 아님 - 제{matched_no}조에 포함 (신뢰도: {confidence:.1%})")
            
            # 판단 근거
            reasoning = analysis.get('reasoning', '')
            if reasoning:
                st.markdown("**판단 근거**:")
                st.markdown(reasoning)
            
            # 증거 (상세 분석)
            evidence = analysis.get('evidence', '')
            if evidence:
                with st.expander("📄 상세 증거 보기"):
                    # 개행을 markdown 개행으로 변환
                    formatted_evidence = evidence.replace('\n', '  \n')
                    st.markdown(formatted_evidence)
            
            # 위험도 평가 (실제 누락인 경우만)
            if is_truly_missing:
                risk_assessment = analysis.get('risk_assessment', '')
                if risk_assessment:
                    st.markdown("**위험도 평가**:")
                    st.warning(risk_assessment)
            
            # 권고사항
            recommendation = analysis.get('recommendation', '')
            if recommendation:
                st.markdown("**권고사항**:")
                st.info(recommendation)
            
            # 후보 조문 분석 (있는 경우)
            top_candidates = analysis.get('top_candidates', [])
            if top_candidates:
                with st.expander(f"🔎 검토된 후보 조문 ({len(top_candidates)}개)"):
                    for i, candidate in enumerate(top_candidates, 1):
                        user_article = candidate.get('user_article', {})
                        user_no = user_article.get('number', '?')
                        user_title = user_article.get('title', '')
                        similarity = candidate.get('similarity', 0.0)
                        
                        st.markdown(f"**후보 {i}**: 제{user_no}조 ({user_title}) - 유사도: {similarity:.3f}")
                        
                        # 후보별 LLM 분석 결과
                        candidates_analysis = analysis.get('candidates_analysis', [])
                        if i <= len(candidates_analysis):
                            cand_analysis = candidates_analysis[i-1]
                            is_match = cand_analysis.get('is_match', False)
                            cand_confidence = cand_analysis.get('confidence', 0.0)
                            match_type = cand_analysis.get('match_type', '')
                            cand_reasoning = cand_analysis.get('reasoning', '')
                            
                            if is_match:
                                st.markdown(f"  - ✅ 매칭 (신뢰도: {cand_confidence:.1%}, 유형: {match_type})")
                            else:
                                st.markdown(f"  - ❌ 매칭 안됨 (신뢰도: {cand_confidence:.1%}, 유형: {match_type})")
                            
                            if cand_reasoning:
                                st.markdown(f"  - 근거: {cand_reasoning}")
                        
                        st.markdown("")  # 여백
            
            st.markdown("---")


def _format_std_reference(global_id: str) -> str:
    """
    표준 조항 global_id를 읽기 쉬운 형식으로 변환
    
    Args:
        global_id: 예: "urn:std:provide:art:001"
    
    Returns:
        예: "제1조"
    """
    try:
        parts = global_id.split(':')
        if len(parts) >= 5:
            article_num = parts[4]  # "001"
            return f"제{int(article_num)}조"
    except (ValueError, IndexError):
        pass
    return global_id


def _format_matching_info(user_article_no, reference: str) -> str:
    """
    매칭 정보를 읽기 쉬운 형식으로 변환
    
    Args:
        user_article_no: 사용자 조항 번호
        reference: 표준 조항 참조 (예: "제1조", "서문 또는 제1조")
    
    Returns:
        예: "사용자 제3조 - 표준 제1조 매칭"
        예: "사용자 서문 - 표준 서문 + 제1조 매칭"
    """
    if not reference:
        return ""
    
    # 사용자 조항 참조 생성
    if user_article_no == 0 or user_article_no == "preamble":
        user_ref = "사용자 서문"
    else:
        user_ref = f"사용자 제{user_article_no}조"
    
    # 표준 조항 참조 정리 (중복 제거)
    std_ref = reference
    
    return f"{user_ref} - 표준 {std_ref} 매칭"


def display_checklist_results(checklist_validation: dict):
    """
    체크리스트 검증 결과 표시
    
    Args:
        checklist_validation: 체크리스트 검증 결과 딕셔너리
    """
    if not checklist_validation:
        return
    
    st.markdown('<div style="height: 2rem;"></div>', unsafe_allow_html=True)
    
    # 체크리스트 검증 결과 헤더
    st.markdown("### 📋 체크리스트 검증 결과")
    st.markdown('<div style="height: 1rem;"></div>', unsafe_allow_html=True)
    
    # 통계 표시
    total_items = checklist_validation.get('total_checklist_items', 0)
    verified_items = checklist_validation.get('verified_items', 0)
    passed_items = checklist_validation.get('passed_items', 0)
    failed_items = checklist_validation.get('failed_items', 0)
    
    col1, col2, col3 = st.columns(3)
    with col1:
        st.metric("전체 항목", f"{total_items}개")
    with col2:
        st.metric("통과", f"{passed_items}개")
    with col3:
        st.metric("미충족", f"{failed_items}개")
    
    st.markdown("---")
    
    # 조항별 체크리스트 결과 표시
    user_article_results = checklist_validation.get('user_article_results', [])
    
    if not user_article_results:
        st.info("체크리스트 검증이 수행되지 않았습니다")
        return
    
    for article_result in user_article_results:
        user_article_no = article_result.get('user_article_no', 'N/A')
        user_article_title = article_result.get('user_article_title', '')
        matched_std_global_ids = article_result.get('matched_std_global_ids', [])
        checklist_results = article_result.get('checklist_results', [])
        
        if not checklist_results:
            continue
        
        # 조항 헤더 (중복 제거)
        if user_article_no == 0 or user_article_no == "preamble":
            st.markdown(f"<h4>서문</h4>", unsafe_allow_html=True)
        else:
            st.markdown(f"<h4>제{user_article_no}조 ({user_article_title})</h4>", unsafe_allow_html=True)
        
        # 매칭된 표준 조항 정보 표시
        if matched_std_global_ids:
            std_refs = [_format_std_reference(gid) for gid in matched_std_global_ids]
            st.caption(f"매칭된 표준 조항: {', '.join(std_refs)}")
        
        # 각 체크리스트 항목 표시
        for item in checklist_results:
            check_text = item.get('check_text', '')
            reference = item.get('reference', '')
            result = item.get('result', '')
            evidence = item.get('evidence', '')
            confidence = item.get('confidence', 0.0)
            requires_manual_review = item.get('requires_manual_review', False)
            
            # 매칭 정보 생성
            matching_info = _format_matching_info(user_article_no, reference)
            
            # 결과에 따라 다른 스타일 적용
            if result == 'YES':
                # 녹색 체크 아이콘
                st.success(f"✅ {check_text}")
                if evidence:
                    st.caption(f"근거: {evidence}")
                if matching_info:
                    st.caption(f"매칭 정보: {matching_info}")
            
            elif result == 'NO':
                # 빨간색 X 아이콘
                missing_explanation = item.get('missing_explanation', '')
                risk_level = item.get('risk_level', 'medium')
                risk_description = item.get('risk_description', '')
                recommendation = item.get('recommendation', '')
                
                st.error(f"❌ {check_text}")
                
                # 매칭 정보
                if matching_info:
                    st.caption(f"매칭 정보: {matching_info}")
                
                # 누락 설명
                if missing_explanation:
                    st.markdown(f"**누락 상세**: {missing_explanation}")
                else:
                    st.caption("해당 내용이 계약서에 명시되지 않았습니다")
                
                # 위험도 (단순 텍스트)
                if risk_description:
                    risk_labels = {'high': '높음', 'medium': '보통', 'low': '낮음'}
                    risk_label = risk_labels.get(risk_level, '알 수 없음')
                    st.markdown(f"위험도 {risk_label}: {risk_description}")
                
                # 권장사항 (단순 텍스트)
                if recommendation:
                    st.markdown(f"권장사항: {recommendation}")
            
            elif result == 'UNCLEAR':
                # 노란색 물음표 아이콘
                st.warning(f"❓ {check_text}")
                st.caption(f"판단이 불명확합니다 (신뢰도: {confidence:.1%})")
                if requires_manual_review:
                    st.caption("⚠️ 수동 검토가 필요합니다")
                if matching_info:
                    st.caption(f"매칭 정보: {matching_info}")
            
            elif result == 'MANUAL_CHECK_REQUIRED':
                # 주황색 경고 아이콘 - 사용자 확인 필요
                user_action = item.get('user_action', '')
                manual_check_reason = item.get('manual_check_reason', '')
                
                st.warning(f"⚠️ {check_text}")
                st.caption("AI가 자동으로 검증할 수 없습니다")
                if user_action:
                    st.caption(f"💡 확인 방법: {user_action}")
                if manual_check_reason:
                    st.caption(f"이유: {manual_check_reason}")
                if matching_info:
                    st.caption(f"매칭 정보: {matching_info}")
            
            st.markdown("")  # 여백
        
        st.markdown("---")
    
    # 처리 시간 표시
    processing_time = checklist_validation.get('processing_time', 0.0)
    verification_date = checklist_validation.get('verification_date', '')
    
    if processing_time > 0:
        st.markdown(f"<p style='text-align:right; color:#6b7280; font-size:0.85rem;'>처리 시간: {processing_time:.2f}초</p>", unsafe_allow_html=True)


def display_manual_checks(manual_checks: dict):
    """
    사용자 수동 확인 항목 표시
    
    Args:
        manual_checks: 수동 확인 항목 딕셔너리
    """
    if not manual_checks:
        return
    
    st.markdown('<div style="height: 2rem;"></div>', unsafe_allow_html=True)
    
    # 수동 확인 항목 헤더
    st.markdown("### ⚠️ 사용자 확인 필요 항목")
    st.markdown(
        '<p style="color:#6b7280; font-size:0.95rem; margin-top:-0.5rem;">AI가 자동으로 검증할 수 없는 항목들입니다. 직접 확인해주세요.</p>',
        unsafe_allow_html=True
    )
    st.markdown('<div style="height: 1rem;"></div>', unsafe_allow_html=True)
    
    # 통계 표시
    total_items = manual_checks.get('total_manual_items', 0)
    high_priority = manual_checks.get('high_priority_items', 0)
    medium_priority = manual_checks.get('medium_priority_items', 0)
    low_priority = manual_checks.get('low_priority_items', 0)
    
    col1, col2, col3, col4 = st.columns(4)
    with col1:
        st.metric("전체 항목", f"{total_items}개")
    with col2:
        st.metric("🔴 높음", f"{high_priority}개")
    with col3:
        st.metric("🟡 보통", f"{medium_priority}개")
    with col4:
        st.metric("🟢 낮음", f"{low_priority}개")
    
    st.markdown("---")
    
    # 카테고리별 항목 표시
    categories = manual_checks.get('categories', [])
    
    if not categories:
        st.info("수동 확인 항목이 없습니다")
        return
    
    for category_data in categories:
        category = category_data.get('category', '')
        description = category_data.get('description', '')
        items = category_data.get('items', [])
        
        if not items:
            continue
        
        # 카테고리 헤더
        st.markdown(f"#### 📌 {category}")
        if description:
            st.markdown(f"<p style='color:#6b7280; font-size:0.9rem; margin-top:-0.5rem;'>{description}</p>", unsafe_allow_html=True)
        
        # 각 항목 표시
        for item in items:
            check_text = item.get('check_text', '')
            user_action = item.get('user_action', '')
            priority = item.get('priority', 'medium')
            reference = item.get('reference', '')
            why_manual = item.get('why_manual', '')
            
            # 우선순위에 따른 아이콘 및 색상
            if priority == 'high':
                priority_icon = "🔴"
                priority_text = "높음"
                border_color = "#ef4444"
            elif priority == 'medium':
                priority_icon = "🟡"
                priority_text = "보통"
                border_color = "#f59e0b"
            else:  # low
                priority_icon = "🟢"
                priority_text = "낮음"
                border_color = "#10b981"
            
            # 항목 박스
            st.markdown(
                f"""
                <div style="border-left: 4px solid {border_color}; padding: 1rem; background-color: #f9fafb; border-radius: 0.5rem; margin-bottom: 1rem;">
                    <div style="display: flex; align-items: center; margin-bottom: 0.5rem;">
                        <span style="font-size: 1.2rem; margin-right: 0.5rem;">{priority_icon}</span>
                        <span style="font-weight: 600; color: #1f2937;">{check_text}</span>
                        <span style="margin-left: auto; font-size: 0.85rem; color: #6b7280;">우선순위: {priority_text}</span>
                    </div>
                    <div style="color: #4b5563; font-size: 0.9rem; margin-bottom: 0.5rem;">
                        💡 <strong>확인 방법:</strong> {user_action}
                    </div>
                    <div style="color: #6b7280; font-size: 0.85rem;">
                        📍 <strong>참조:</strong> {reference}
                    </div>
                </div>
                """,
                unsafe_allow_html=True
            )
        
        st.markdown("---")
    
    # 처리 시간 표시
    processing_time = manual_checks.get('processing_time', 0.0)
    generation_date = manual_checks.get('generation_date', '')
    
    if processing_time > 0:
        st.markdown(f"<p style='text-align:right; color:#6b7280; font-size:0.85rem;'>처리 시간: {processing_time:.2f}초</p>", unsafe_allow_html=True)


if __name__ == "__main__":
    main()


