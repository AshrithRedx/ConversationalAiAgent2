import os
from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware
from pydantic import BaseModel
from langchain_google_genai import (
    ChatGoogleGenerativeAI,
    HarmBlockThreshold,
    HarmCategory,
)
from calendar_utils import book_event, check_availability
import dateparser
from dotenv import load_dotenv
load_dotenv()
from datetime import datetime, timedelta, timezone
import json
import re
import time

GOOGLE_API_KEY = os.getenv("GOOGLE_API_KEY")
CALENDAR_ID = os.getenv("CALENDAR_ID")


llm = ChatGoogleGenerativeAI(
    model="gemini-2.5-flash",
    google_api_key=os.environ["GOOGLE_API_KEY"],
    safety_settings={
        HarmCategory.HARM_CATEGORY_DANGEROUS_CONTENT: HarmBlockThreshold.BLOCK_NONE,
        HarmCategory.HARM_CATEGORY_HATE_SPEECH: HarmBlockThreshold.BLOCK_NONE,
        HarmCategory.HARM_CATEGORY_HARASSMENT: HarmBlockThreshold.BLOCK_NONE,
        HarmCategory.HARM_CATEGORY_SEXUALLY_EXPLICIT: HarmBlockThreshold.BLOCK_NONE,
    },
)
IST = timezone(timedelta(hours=5, minutes=30))

app = FastAPI()
app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)

class ChatRequest(BaseModel):
    session_id: str
    message: str

class ChatResponse(BaseModel):
    reply: str

slot_state = {}

def clean_llm_json(raw):
    """Remove markdown code fences and whitespace from Gemini output."""
    raw = re.sub(r"^``````$", "", raw, flags=re.MULTILINE).strip()
    return raw

def clean_natural_date(natural_str):
    natural_str = re.sub(r'\b(from|to)\s+\1\b', r'\1', natural_str)
    natural_str = re.sub(r'^(from|to)\s+', '', natural_str)
    natural_str = re.sub(r'\b(from|to)\s+(from|to)\b', r'\2', natural_str)
    natural_str = re.sub(r'\b(from|to)$', '', natural_str)
    natural_str = re.sub(r'(\d{1,2}(st|nd|rd|th)?\s+\w+)\s+from\s+', r'\1 ', natural_str, flags=re.IGNORECASE)
    natural_str = re.sub(r'(\d{1,2}(st|nd|rd|th)?\s+\w+)\s+to\s+', r'\1 ', natural_str, flags=re.IGNORECASE)
    return natural_str.strip()

def to_rfc3339(natural_str, base_date=None):
    if not natural_str:
        return None
    natural_str = clean_natural_date(natural_str)
    if base_date is None:
        base_date = datetime.now(IST)
    dt = dateparser.parse(natural_str, settings={'RELATIVE_BASE': base_date})
    if dt is None:
        return None
    dt = dt.replace(tzinfo=IST)
    return dt.isoformat()

def suggest_alternatives(start_time, duration_minutes=60, num_slots=3):
    start_dt = dateparser.parse(start_time)
    if not start_dt:
        return []
    alternatives = []
    check_time = start_dt + timedelta(minutes=duration_minutes)
    for _ in range(num_slots * 2):
        end_time = check_time + timedelta(minutes=duration_minutes)
        busy = check_availability(CALENDAR_ID, check_time.isoformat(), end_time.isoformat())
        if not busy:
            alternatives.append((check_time.isoformat(), end_time.isoformat()))
            if len(alternatives) == num_slots:
                break
        check_time += timedelta(minutes=duration_minutes)
    return alternatives

def extract_slots_with_llm(user_message, retries=2):
    system_prompt = (
        "You are a helpful, friendly scheduling assistant. "
        "Your ONLY job is to extract event details from the user's message. "
        "ALWAYS return a JSON object with these fields: summary, start_time, end_time. "
        "If a field is missing, set its value to an empty string. "
        "DO NOT return anything except the JSON object. "
        "Examples:\n"
        "User: Book a meeting tomorrow at 10am called Project Sync.\n"
        '{"summary": "Project Sync", "start_time": "tomorrow at 10am", "end_time": ""}\n'
        "User: Schedule a call with John next Friday from 2pm to 3pm\n"
        '{"summary": "call with John", "start_time": "next Friday 2pm", "end_time": "next Friday 3pm"}\n'
        "User: Book an event called MyProj on 5th July 9 AM to 11 AM\n"
        '{"summary": "MyProj", "start_time": "5th July 9 AM", "end_time": "5th July 11 AM"}\n'
        "Return ONLY the JSON object."
    )
    prompt = f"{system_prompt}\nUser: {user_message}"

    for attempt in range(retries):
        result = llm.invoke(prompt)
        raw = result.content.strip() if hasattr(result, "content") else str(result).strip()
        print(f"Gemini raw output (attempt {attempt+1}):", repr(raw))

        # Try to extract JSON object from anywhere in the output
        match = re.search(r"\{.*\}", raw, re.DOTALL)
        if match:
            try:
                return json.loads(match.group())
            except Exception as e:
                print("JSON decode error:", e)
        time.sleep(0.5)
    # If all retries fail, return empty slots and log the error
    print("Failed to extract JSON from Gemini output. Raw output was:", repr(raw))
    return {"summary": "", "start_time": "", "end_time": ""}


def is_small_talk(user_message):
    greetings = ["hi", "hello", "hey", "good morning", "good evening"]
    thanks = ["thank you", "thanks", "thx"]
    about = ["what can you do", "who are you", "help", "capabilities"]
    msg = user_message.lower()
    if any(greet in msg for greet in greetings):
        return "👋 Hi! I can help you schedule meetings on your calendar. Just tell me what you need!"
    if any(t in msg for t in thanks):
        return "You're welcome! 😊 If you need to book another meeting, just let me know."
    if any(a in msg for a in about):
        return "I'm your smart scheduling assistant. I can book, check, and suggest meeting times for your Google Calendar. Try saying 'Book a meeting tomorrow at 10am'."
    return None

def merge_date_and_times(date_str, time_range_str):
    times = re.findall(r"\d{1,2}\s*(?:AM|PM|am|pm)", time_range_str)
    if len(times) == 2:
        start = f"{date_str} {times[0]}"
        end = f"{date_str} {times[1]}"
        return start, end
    return None, None

@app.post("/chat", response_model=ChatResponse)
async def chat_endpoint(request: ChatRequest):
    session_id = request.session_id
    user_message = request.message.strip()

    # Small talk/thanks/what can you do
    small_talk_reply = is_small_talk(user_message)
    if small_talk_reply:
        return ChatResponse(reply=small_talk_reply)

    base_date = datetime.now(IST)
    if session_id not in slot_state:
        slot_state[session_id] = {
            "summary": None, "start_time": None, "end_time": None, "alternatives": [], "last_date_phrase": None
        }

    slots = slot_state[session_id]

    if slots.get("alternatives"):
        if re.search(r"\b(yes|book|first)\b", user_message):
            alt = slots["alternatives"][0]
            slots["start_time"], slots["end_time"] = alt
            slots["alternatives"] = []
            event = book_event(CALENDAR_ID, slots["summary"], slots["start_time"], slots["end_time"])
            slot_state.pop(session_id, None)
            return ChatResponse(
                reply=(
                    f'✅ Your event "{slots["summary"]}" is booked on {dateparser.parse(slots["start_time"]).strftime("%A, %d %b %Y")} '
                    f'from {dateparser.parse(slots["start_time"]).strftime("%I:%M %p")} to {dateparser.parse(slots["end_time"]).strftime("%I:%M %p")}.'
                )
            )
        elif re.search(r"\b(no|cancel|none)\b", user_message):
            slots["alternatives"] = []
            return ChatResponse(reply="No problem! Let me know another time you'd like to book.")
        else:
            return ChatResponse(reply="Would you like to book the first suggested slot? Reply 'yes' to confirm, or 'no' to cancel.")

    # Always re-extract all slots from every message
    extracted = extract_slots_with_llm(user_message)
    print("Extracted fields:", extracted)
    for k in ["summary", "start_time", "end_time"]:
        if k in extracted and extracted[k]:
            slots[k] = extracted[k]
        if not extracted or not any(extracted.values()):
            return ChatResponse(
             reply="Sorry, I couldn't understand your request. Please rephrase, e.g., 'Book a meeting called Project Sync on 5th July from 12 AM to 2 PM.'"
    )

    # --- Merge date and time if user only gave times in this turn ---
    if (
        slots.get("start_time") and slots.get("end_time")
        and not re.search(r"\d{4}-\d{2}-\d{2}", slots["start_time"])
        and not re.search(r"\d{4}-\d{2}-\d{2}", slots["end_time"])
    ):
        date_match = re.search(r"\d{1,2}(st|nd|rd|th)?\s+\w+", slots.get("summary", ""), re.IGNORECASE)
        if date_match:
            date_str = date_match.group()
            start, end = merge_date_and_times(date_str, slots["start_time"])
            if start and end:
                slots["start_time"] = start
                slots["end_time"] = end

    # Parse times to RFC3339 using RELATIVE_BASE, and check for parse errors
    for time_field in ["start_time", "end_time"]:
        if slots[time_field]:
            rfc = to_rfc3339(slots[time_field], base_date=base_date)
            if rfc:
                slots[time_field] = rfc
            else:
                return ChatResponse(
                    reply=(
                        f"I couldn't understand the date '{slots[time_field]}'. "
                        "Please specify the date and time as 'July 7th 9 PM to 11 PM' or '2025-07-07T21:00:00+05:30 to 23:00:00+05:30'."
                    )
                )

    # Slot filling: check for missing info
    missing = [k for k, v in slots.items() if not v and k in ["summary", "start_time", "end_time"]]
    if missing:
        prompts = {
            "summary": "What should I call this event?",
            "start_time": "When should the event start?",
            "end_time": "And when should it end?"
        }
        ask = prompts.get(missing[0], "Could you provide more details?")
        slot_state[session_id] = slots
        return ChatResponse(reply=ask)

    # User Feedback/Confirmation for Alternatives
    if slots.get("alternatives"):
        if re.search(r"\b(yes|book|first)\b", user_message.lower()):
            alt = slots["alternatives"][0]
            slots["start_time"], slots["end_time"] = alt
            slots["alternatives"] = []
            event = book_event(CALENDAR_ID, slots["summary"], slots["start_time"], slots["end_time"])
            slot_state.pop(session_id, None)
            return ChatResponse(
                reply=(
                    f'✅ Your event "{slots["summary"]}" is booked on {dateparser.parse(slots["start_time"]).strftime("%A, %d %b %Y")} '
                    f'from {dateparser.parse(slots["start_time"]).strftime("%I:%M %p")} to {dateparser.parse(slots["end_time"]).strftime("%I:%M %p")}.'
                )
            )
        elif re.search(r"\b(no|cancel|none)\b", user_message.lower()):
            slots["alternatives"] = []
            return ChatResponse(reply="No problem! Let me know another time you'd like to book.")
        else:
            return ChatResponse(reply="Would you like to book the first suggested slot? Reply 'yes' to confirm, or 'no' to cancel.")

    # Check calendar availability
    busy = check_availability(CALENDAR_ID, slots["start_time"], slots["end_time"])
    if busy:
        alternatives = suggest_alternatives(slots["end_time"])
        if alternatives:
            slots["alternatives"] = alternatives  # Store for confirmation
            alt_str = "\n".join(
                f"- {dateparser.parse(start).strftime('%A, %d %b %Y %I:%M %p')} to {dateparser.parse(end).strftime('%I:%M %p')}"
                for start, end in alternatives
            )
            reply = (
                "That time slot is busy! Here are some alternative free slots:\n\n"
                f"{alt_str}\n\nWould you like to book the first one? Reply 'yes' to confirm or 'no' to cancel."
            )
        else:
            reply = "That time slot is busy and I couldn't find alternatives right now. Want to try a different time?"
        slot_state[session_id] = slots
        return ChatResponse(reply=reply)

    # Book event and confirm
    event = book_event(CALENDAR_ID, slots["summary"], slots["start_time"], slots["end_time"])
    slot_state.pop(session_id, None)
    return ChatResponse(
        reply=(
            f'✅ Your event "{slots["summary"]}" is booked on {dateparser.parse(slots["start_time"]).strftime("%A, %d %b %Y")} '
            f'from {dateparser.parse(slots["start_time"]).strftime("%I:%M %p")} to {dateparser.parse(slots["end_time"]).strftime("%I:%M %p")}.'
        )
    )

@app.get("/")
def read_root():
    return {"message": "Backend is running"}
