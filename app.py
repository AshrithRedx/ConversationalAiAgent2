import streamlit as st
import requests
import uuid
backend_url = st.secrets.get("BACKEND_URL", "http://localhost:8000")


st.set_page_config(
    page_title="Conversational AI Assistant",
    page_icon="💼",
    layout="centered"
)

# Custom CSS for a professional, modern look
st.markdown("""
    <style>
    .stChatMessage {background-color: #f7f9fa; border-radius: 14px;}
    .stChatMessage.user {background-color: #e9f5ff;}
    .stChatMessage.assistant {background-color: #f1f1f6;}
    .stButton>button {background-color: #3b7ddd; color: white;}
    .stChatInputContainer {background: #f7f9fa;}
    .stTitle {font-size: 2.6rem;}
    .sidebar-content {font-size: 1.1rem; color: #444;}
    </style>
""", unsafe_allow_html=True)

st.title("Conversational AI Assistant")
st.caption("A smart, context-aware scheduling assistant. Type naturally—I'll handle the details! ✨")

# --- Sidebar: About and Instructions ---
with st.sidebar:
    st.header("About")
    st.markdown(
        """
        **How to use this assistant:**

        - You can type requests in **natural language**!  
          _Examples:_  
          - “Book a meeting tomorrow at 10am called Project Sync.”
          - “Schedule a call with John next on 12th July from 2pm to 3pm.”
          - “Book an event a team catch-up on July 10th from 5pm to 8pm.”
        - The assistant will extract all necessary details and help you book the event.
        - If any information is missing, the assistant will ask you for it.

        ---
        _Advanced:_  
        You can also use a strict input format for scheduling:
        ```
        calendar_id, summary, start_time, end_time
        ```
        - **calendar_id:** your Google Calendar email (e.g. `abcxyz@hotmail.com`)
        - **summary:** Title of the Event
        - **start_time/end_time:** RFC3339 format (e.g. `2025-07-10T17:00:00+05:30`)

        ---
        **Tip:** Natural language is easiest. Try:  
        _“Book a meeting called Demo Review next Monday at 11am.”_
        """
    )
    st.divider()
st.markdown("""
    <style>
    .stChatMessage.assistant, .stChatMessage.assistant * {
        background-color: #f1f1f6 !important;
        color: #222 !important;
        border-radius: 14px;
        font-size: 1.1rem;
        font-weight: 500;
    }
    .stChatMessage.user, .stChatMessage.user * {
        background-color: #e9f5ff !important;
        color: #222 !important;
        border-radius: 14px;
        font-size: 1.1rem;
        font-weight: 500;
    }
    .stApp {
        background-color: #181c25 !important;
    }
    </style>
""", unsafe_allow_html=True)


if st.button("Clear Chat"):
        st.session_state["messages"] = []
        st.experimental_rerun()

st.markdown("""
    <style>
    /* Force chat message text to be dark and visible in all themes */
    [data-testid="stChatMessageContent"] {
        color: #222 !important;
        font-size: 1.1rem;
        font-weight: 500;
    }
    </style>
""", unsafe_allow_html=True)


# --- Session State Setup ---
if "session_id" not in st.session_state:
    st.session_state["session_id"] = str(uuid.uuid4())
if "messages" not in st.session_state:
    # Add a welcome message for a friendly start
    st.session_state["messages"] = [
        {"role": "assistant", "content": "Hi! 👋 How can I help you schedule your next meeting?"}
    ]

# --- Display Chat History ---
for msg in st.session_state["messages"]:
    with st.chat_message(msg["role"]):
       st.write(msg["content"])

# --- Chat Input ---
if prompt := st.chat_input("Type your message and press Enter..."):
    # Append user message
    st.session_state["messages"].append({"role": "user", "content": prompt})
    with st.chat_message("user"):
        st.markdown(prompt)
    # Call backend
    try:
        response = requests.post(
            f"{backend_url}/chat",
            json={"session_id": st.session_state["session_id"], "message": prompt}
    )

        bot_reply = response.json().get("reply", "No reply received.")
    except Exception as e:
        bot_reply = f"Error: {e}"
    # Append assistant message
    st.session_state["messages"].append({"role": "assistant", "content": bot_reply})
    with st.chat_message("assistant"):
        st.markdown(bot_reply)
    st.rerun()
