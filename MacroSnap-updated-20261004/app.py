import time
from twilio.rest import Client
from google import genai
from google.genai import types
import streamlit as st

from prompts import SYSTEM_PROMPT, WELCOME_MESSAGE_TEMPLATE, SUMMARY_REQUEST_PROMPT

gemini_api_key      = st.secrets["gemini_api_key"]
twilio_account_sid  = st.secrets["twilio_account_sid"]
twilio_auth_token   = st.secrets["twilio_auth_token"]
twilio_from_number  = st.secrets["twilio_from_number"]   # a Twilio phone number, e.g. +1xxxxxxxxxx

@st.cache_resource
def get_gemini_client():
    return genai.Client(api_key=gemini_api_key)

@st.cache_resource
def get_twilio_client():
    return Client(twilio_account_sid, twilio_auth_token)

gemini_client = get_gemini_client()
twilio_client  = get_twilio_client()
model_name = "gemini-3.8-flash"


def send_sms(to_number, user_name, summary):
    """Send a plain SMS to the user's mobile number via Twilio."""
    try:
        body = f"MacroSnap Daily Summary for {user_name}\n\n{summary}"
        # Twilio SMS body limit is 1600 chars
        body = body[:1597] + "..." if len(body) > 1600 else body
        message = twilio_client.messages.create(
            body=body,
            from_=twilio_from_number,
            to=to_number,
        )
        return True, message.sid
    except Exception as error:
        return False, str(error)


def render_message(message):
    with st.chat_message(message["role"]):
        if message["kind"] == "text":
            st.write(message["content"])
        elif message["kind"] == "image":
            st.image(message["content"])


def add_message(role, kind, content):
    st.session_state.messages.append({"role": role, "kind": kind, "content": content})
    render_message(st.session_state.messages[-1])


def ask_gemini(parts, retries=3, delay=2):
    """Send a message to Gemini, retrying on transient 503 errors."""
    for attempt in range(1, retries + 1):
        try:
            return st.session_state.chat.send_message(parts).text
        except Exception as error:
            error_str = str(error)
            is_503 = "503" in error_str or "UNAVAILABLE" in error_str
            if is_503 and attempt < retries:
                time.sleep(delay)
                continue
            # Non-retryable error or out of retries
            if is_503:
                return (
                    "⚠️ Google's AI servers are busy right now. "
                    "Please wait a moment and try again."
                )
            return f"Sorry, something went wrong: {error}"


# ── Onboarding ────────────────────────────────────────────────────────────────

if "onboarded" not in st.session_state:
    st.title("MacroSnap 🥗")
    st.caption("Snap it. Track it.")

    with st.form("onboarding_form"):
        name = st.text_input("What's your name?")
        mobile_number = st.text_input(
            "Your mobile number (with country code)",
            placeholder="e.g. +917984105339",
            help="We'll send your daily nutrition summary as an SMS to this number.",
        )
        submit_button = st.form_submit_button("Let's start! 🚀")

        if submit_button:
            if not name.strip() or not mobile_number.strip():
                st.warning("Please enter both your name and mobile number.")
            elif not mobile_number.strip().startswith("+"):
                st.warning("Please include the country code (e.g. +91 for India).")
            else:
                st.session_state.name          = name.strip()
                st.session_state.mobile_number = mobile_number.strip()

                st.session_state.chat = gemini_client.chats.create(
                    model=model_name,
                    config=types.GenerateContentConfig(
                        system_instruction=SYSTEM_PROMPT
                    ),
                )
                st.session_state.messages = []
                st.session_state.onboarded = True
                st.rerun()

    st.stop()


# ── Sidebar: Chat History ────────────────────────────────────────────────────

with st.sidebar:
    st.markdown("## 🗂️ Chat History")
    st.caption(f"Session for **{st.session_state.name}**")
    st.divider()

    messages = st.session_state.get("messages", [])
    if not messages:
        st.info("No messages yet. Start chatting!")
    else:
        # Count stats
        user_msgs = sum(1 for m in messages if m["role"] == "user")
        st.markdown(
            f"<small>💬 {len(messages)} messages &nbsp;|&nbsp; 🧑 {user_msgs} from you</small>",
            unsafe_allow_html=True,
        )
        st.markdown("")

        for i, msg in enumerate(messages):
            role_emoji = "🧑" if msg["role"] == "user" else "🤖"
            role_label = "You" if msg["role"] == "user" else "MacroSnap"

            if msg["kind"] == "image":
                # Show a thumbnail + expander
                with st.expander(f"{role_emoji} {role_label} — 📷 Photo", expanded=False):
                    st.image(msg["content"], use_container_width=True)
            else:
                # Truncate long messages for the preview label
                preview = msg["content"][:60].replace("\n", " ")
                if len(msg["content"]) > 60:
                    preview += "…"
                with st.expander(f"{role_emoji} {role_label}: {preview}", expanded=False):
                    st.write(msg["content"])

        st.divider()
        if st.button("🗑️ Clear Chat", use_container_width=True):
            st.session_state.messages = []
            st.session_state.chat = gemini_client.chats.create(
                model=model_name,
                config=types.GenerateContentConfig(
                    system_instruction=SYSTEM_PROMPT
                ),
            )
            st.rerun()


# ── Main Chat UI ──────────────────────────────────────────────────────────────

header_col, button_col = st.columns([5, 2], vertical_alignment="center")

with header_col:
    st.title("MacroSnap 🥗")

with button_col:
    send_disabled = len(st.session_state.messages) <= 1
    if st.button(
        "📤 Send Summary via SMS",
        disabled=send_disabled,
        use_container_width=True,
    ):
        with st.spinner("Summarizing your day..."):
            summary = ask_gemini([SUMMARY_REQUEST_PROMPT])
        success, info = send_sms(
            st.session_state.mobile_number,
            st.session_state.name,
            summary,
        )
        if success:
            st.success(f"Sent! Check your messages on {st.session_state.mobile_number} 📲")
        else:
            st.error(f"Couldn't send SMS: {info}")

st.caption(
    f"Logged in as **{st.session_state.name}** · "
    f"summaries → SMS to `{st.session_state.mobile_number}`"
)

if not st.session_state.messages:
    add_message(
        "assistant",
        "text",
        WELCOME_MESSAGE_TEMPLATE.format(name=st.session_state.name),
    )
else:
    for message in st.session_state.messages:
        render_message(message)

user_input = st.chat_input(
    "Ask a question or attach a photo of your meal",
    accept_file=True,
    file_type=["jpg", "jpeg", "png"],
)

if user_input:
    photo = user_input.files[0] if user_input.files else None
    text = user_input.text
    parts = []

    if photo is not None:
        photo_bytes = photo.getvalue()
        add_message("user", "image", photo_bytes)
        parts.append(types.Part.from_bytes(data=photo_bytes, mime_type=photo.type))

    if text:
        add_message("user", "text", text)
        parts.append(text)
    elif photo is not None:
        parts.append("What is this meal? Give me the calories and macros.")

    with st.spinner("Thinking..."):
        answer = ask_gemini(parts)
    add_message("assistant", "text", answer)

        