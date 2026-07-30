import streamlit as st
from openai import OpenAI

# 페이지 기본 설정
st.set_page_config(page_title="AI 정보 선생님", page_icon="🤖")
st.title("🤖 AI 정보 선생님")

# 비밀 금고(secrets)에서 API 키를 꺼내 접속 준비
client = OpenAI(
    api_key=st.secrets["SOLAR_API_KEY"],
    base_url="https://api.upstage.ai/v1",
)

BASE_RULE = "반드시 순수 한국어로만 답해."

TONE_PROMPTS = {
    "친절한 선생님": (
        "너는 중고등학생에게 설명하는 친절한 정보 선생님이야. "
        "어려운 말은 쉬운 말로 풀어서 설명해줘."
    ),
    "시크한 전문가": (
        "너는 군더더기 없이 핵심만 간결하고 시크하게 답하는 정보 전문가야. "
        "불필요한 설명은 생략하고 정확한 정보만 전달해."
    ),
    "되물어보는 조교": (
        "너는 학생이 스스로 답을 찾도록 돕는 조교야. "
        "질문을 받으면 정답을 바로 알려주지 말고, 먼저 힌트를 하나만 주고 되물어봐. "
        "학생이 스스로 답을 말하면 그때 맞았는지 확인해줘."
    ),
}

DIFFICULTY_PROMPTS = {
    "초등학생 수준": "초등학생도 이해할 수 있도록 아주 쉬운 단어와 비유를 사용해.",
    "중학생 수준": "중학생 수준에 맞게 설명해.",
    "고등학생 수준": "고등학생 수준에 맞게 조금 더 전문적인 용어도 사용해도 좋아.",
}


def build_default_prompt(tone: str, difficulty: str) -> str:
    return f"{TONE_PROMPTS[tone]} {DIFFICULTY_PROMPTS[difficulty]} {BASE_RULE}"


# ── 사이드바: 말투 / 난이도 / 성격 문장 직접 수정 ──────────
with st.sidebar:
    st.subheader("⚙️ 대화 설정")

    tone = st.radio("말투 고르기", list(TONE_PROMPTS.keys()))
    difficulty = st.radio("설명 난이도", list(DIFFICULTY_PROMPTS.keys()))

    # 말투나 난이도를 바꾸면, 직접 수정 칸의 기본값도 새로 채워준다
    combo_key = (tone, difficulty)
    if st.session_state.get("_combo_key") != combo_key:
        st.session_state.system_prompt_text = build_default_prompt(tone, difficulty)
        st.session_state["_combo_key"] = combo_key

    system_prompt_text = st.text_area(
        "성격 문장 직접 수정 (여기서 고치면 그 내용이 그대로 적용돼요)",
        height=160,
        key="system_prompt_text",
    )

    st.divider()

    if st.button("🗑️ 대화 지우기"):
        st.session_state.messages = []
        st.rerun()

    if st.session_state.get("messages"):
        convo_text = "\n\n".join(
            f"**{'학생' if m['role'] == 'user' else '선생님'}**: {m['content']}"
            for m in st.session_state.messages
        )
        st.download_button(
            "💾 대화 내용 다운로드",
            convo_text,
            file_name="대화_기록.md",
            mime="text/markdown",
        )

# ── 대화 기록 준비 (시스템 문장은 저장하지 않고 매번 새로 붙인다) ──
if "messages" not in st.session_state:
    st.session_state.messages = []
if "regenerate" not in st.session_state:
    st.session_state.regenerate = False

# 지금까지의 대화를 말풍선으로 다시 그리기
for msg in st.session_state.messages:
    with st.chat_message(msg["role"]):
        st.markdown(msg["content"])


def generate_answer():
    """system_prompt_text를 매번 새로 붙여서 API를 부르고, 스트리밍으로 받아온다."""
    api_messages = [{"role": "system", "content": system_prompt_text}] + st.session_state.messages
    stream = client.chat.completions.create(
        model="solar-open2",              # 모델 이름은 그대로 유지
        messages=api_messages,             # 매번 최신 성격 문장 + 대화 기록
        reasoning_effort="none",           # 추론 끄기 -> 바로 답변 시작
        stream=True,                       # 글자가 실시간으로 흐르게
    )
    return st.write_stream(
        chunk.choices[0].delta.content or ""
        for chunk in stream if chunk.choices
    )


# ── 마지막 답변 다시 생성 버튼 (마지막이 assistant일 때만 표시) ──
if (
    st.session_state.messages
    and st.session_state.messages[-1]["role"] == "assistant"
    and not st.session_state.regenerate
):
    if st.button("🔁 답변 다시 생성"):
        st.session_state.messages.pop()  # 마지막 답변만 제거, 질문은 그대로 남김
        st.session_state.regenerate = True
        st.rerun()

# ── 채팅 입력창 ──────────────────────────────────
user_input = st.chat_input("궁금한 것을 물어보세요!")

if user_input:
    st.session_state.messages.append({"role": "user", "content": user_input})
    with st.chat_message("user"):
        st.markdown(user_input)

# 새 질문이 왔거나, 재생성 요청이 있을 때만 답변 생성
if user_input or st.session_state.regenerate:
    with st.chat_message("assistant"):
        try:
            answer = generate_answer()
            st.session_state.messages.append({"role": "assistant", "content": answer})
        except Exception:
            st.error("응답을 받지 못했습니다. 잠시 후 다시 보내 주세요.")
    st.session_state.regenerate = False
