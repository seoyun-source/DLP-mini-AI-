"""
AI 기반 개인정보(PII) 탐지 & 마스킹 데모
- 1차 필터: 정규식으로 구조가 명확한 개인정보(전화번호, 이메일, 주민번호 등) 탐지
- 2차 필터: Gemini API로 문맥적 개인정보(이름+직책 조합, 은근한 주소 언급 등) 탐지
- 최종적으로 두 결과를 합쳐서 마스킹 + 리스크 리포트 생성
"""

import re
import json
import streamlit as st
import google.generativeai as genai

# ----------------------------
# 1. 정규식 패턴 정의 (1차 필터)
# ----------------------------
# 구조가 명확한 개인정보는 굳이 AI를 쓸 필요 없이 정규식이 빠르고 정확함
REGEX_PATTERNS = {
    "전화번호": r"01[016789]-?\d{3,4}-?\d{4}",
    "이메일": r"[a-zA-Z0-9._%+-]+@[a-zA-Z0-9.-]+\.[a-zA-Z]{2,}",
    "주민등록번호": r"\d{6}-?[1-4]\d{6}",
    "계좌번호(추정)": r"\d{2,6}-\d{2,6}-\d{2,6}",
}


def detect_by_regex(text: str):
    """정규식으로 구조화된 개인정보를 찾아 리스트로 반환

    REGEX_PATTERNS에 정의된 순서대로 검사하며, 이미 다른 패턴이 차지한
    위치(span)와 겹치는 매치는 건너뛴다. 예: 전화번호가 먼저 탐지되면
    같은 자리를 계좌번호 패턴이 중복으로 탐지하지 않도록 방지.
    """
    results = []
    occupied_spans = []  # 이미 탐지된 구간: [(start, end), ...]

    for label, pattern in REGEX_PATTERNS.items():
        for match in re.finditer(pattern, text):
            start, end = match.span()

            # 기존에 탐지된 구간과 겹치면 중복이므로 건너뜀
            is_overlapping = any(
                start < occ_end and end > occ_start
                for occ_start, occ_end in occupied_spans
            )
            if is_overlapping:
                continue

            occupied_spans.append((start, end))
            results.append({
                "text": match.group(),
                "type": label,
                "reason": "정규식 패턴 일치",
                "source": "regex",
            })
    return results


# ----------------------------
# 2. Gemini API로 문맥 탐지 (2차 필터)
# ----------------------------
def detect_by_llm(text: str, api_key: str, model_name: str = "gemini-3.6-flash"):
    """정규식으로 못 잡는 문맥적 개인정보를 LLM으로 탐지"""
    genai.configure(api_key=api_key)
    model = genai.GenerativeModel(model_name)

    prompt = f"""당신은 개인정보보호 전문가입니다. 아래 텍스트에서 '정규식으로는 찾기 어려운
문맥적 개인정보'만 찾아주세요. 예: 이름+직책 조합(예: 김민수 대리), 특정 인물을 특정할 수 있는
은근한 위치/주소 언급, 생년월일로 추정되는 표현 등.

전화번호, 이메일, 주민번호처럼 명확한 패턴은 이미 다른 시스템에서 처리하니 제외하세요.
이름만 단독으로 나온 경우, 예시/가상의 이름으로 보이면 포함하지 마세요.

반드시 아래 JSON 형식으로만 응답하세요. 다른 설명은 절대 붙이지 마세요.
[{{"text": "발견된 문자열", "type": "유형", "reason": "왜 개인정보로 판단했는지 한 줄 설명"}}]

발견된 게 없으면 빈 배열 []을 반환하세요.

텍스트:
\"\"\"{text}\"\"\"
"""

    response = model.generate_content(prompt)
    raw = response.text.strip()

    # 모델이 ```json ... ``` 코드블록으로 감싸서 줄 때가 있어서 제거
    raw = re.sub(r"^```json|```$", "", raw.strip(), flags=re.MULTILINE).strip()

    try:
        parsed = json.loads(raw)
        for item in parsed:
            item["source"] = "llm"
        return parsed
    except json.JSONDecodeError:
        st.warning("LLM 응답을 JSON으로 파싱하지 못했습니다. 원본 응답을 확인하세요.")
        st.code(raw)
        return []


# ----------------------------
# 3. 마스킹 처리
# ----------------------------
def mask_text(text: str, findings: list):
    """탐지된 항목들을 [유형]으로 치환"""
    masked = text
    # 긴 문자열부터 치환해야 짧은 문자열이 겹쳐서 깨지는 걸 방지
    for item in sorted(findings, key=lambda x: -len(x["text"])):
        masked = masked.replace(item["text"], f"[{item['type']}]")
    return masked


# ----------------------------
# 4. Streamlit UI
# ----------------------------
st.set_page_config(page_title="PII 탐지 & 마스킹 데모", layout="wide")
st.title("🔒 AI 기반 개인정보(PII) 탐지 & 마스킹 데모")
st.caption("정규식(1차) + Gemini API(2차, 문맥 탐지) 하이브리드 구조")

with st.sidebar:
    st.header("설정")
    api_key = st.text_input("Gemini API Key", type="password",
                             help="https://aistudio.google.com 에서 무료로 발급")
    use_llm = st.checkbox("LLM 문맥 탐지 사용", value=True)
    st.markdown("---")
    st.markdown(
        "⚠️ **실제 개인정보를 절대 입력하지 마세요.** "
        "이 데모는 학습/포트폴리오 목적이며, 무료 API 티어는 입력 데이터가 "
        "서비스 개선에 활용될 수 있습니다."
    )

sample_text = """김민수 대리님이 어제 강남역 근처 카페에서 미팅했다고 하셨어요.
연락처는 010-1234-5678이고, 이메일은 minsu.kim@example.com 입니다.
계좌번호는 123-456-789012 이며, 주민번호는 901231-1234567 입니다."""

text_input = st.text_area("분석할 텍스트를 입력하세요 (더미 데이터만 사용)",
                           value=sample_text, height=180)

if st.button("탐지 시작", type="primary"):
    if not text_input.strip():
        st.error("텍스트를 입력해주세요.")
    elif use_llm and not api_key:
        st.error("LLM 문맥 탐지를 사용하려면 API Key를 입력해주세요.")
    else:
        with st.spinner("탐지 중..."):
            findings = detect_by_regex(text_input)
            if use_llm:
                try:
                    llm_findings = detect_by_llm(text_input, api_key)
                    findings.extend(llm_findings)
                except Exception as e:
                    st.error(f"Gemini API 호출 중 오류가 발생했습니다: {e}")

        masked = mask_text(text_input, findings)

        col1, col2 = st.columns(2)
        with col1:
            st.subheader("원본")
            st.text(text_input)
        with col2:
            st.subheader("마스킹 결과")
            st.text(masked)

        st.subheader("📋 리스크 리포트")
        if findings:
            # 유형별 개수 집계
            from collections import Counter
            counts = Counter(f["type"] for f in findings)
            summary_cols = st.columns(len(counts))
            for col, (ptype, cnt) in zip(summary_cols, counts.items()):
                col.metric(ptype, f"{cnt}건")

            st.dataframe(
                [{"탐지값": f["text"], "유형": f["type"],
                  "탐지방식": "정규식" if f["source"] == "regex" else "LLM(문맥)",
                  "판단근거": f.get("reason", "-")} for f in findings],
                use_container_width=True,
            )
        else:
            st.success("개인정보가 탐지되지 않았습니다.")