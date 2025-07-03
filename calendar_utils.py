from google.oauth2 import service_account
from googleapiclient.discovery import build
from datetime import datetime, timezone, timedelta
import os

# --- CONFIGURATION ---
SCOPES = ['https://www.googleapis.com/auth/calendar']
SERVICE_ACCOUNT_FILE = os.environ.get("GOOGLE_APPLICATION_CREDENTIALS")

# Use the calendar's email address or unique ID (not 'primary')
calendar_id = 'ashrithreddy125@gmail.com'  # Replace with your actual calendar ID

# --- TIMEZONE SETUP ---
# For IST (Asia/Kolkata)
IST = timezone(timedelta(hours=5, minutes=30))

# --- UTILITY FUNCTIONS ---
def get_calendar_service():
    creds = service_account.Credentials.from_service_account_file(
        SERVICE_ACCOUNT_FILE, scopes=SCOPES)
    return build('calendar', 'v3', credentials=creds)

def check_availability(calendar_id, start_time, end_time):
    """
    start_time, end_time: RFC3339 strings, e.g., '2025-07-02T09:00:00+05:30'
    """
    service = get_calendar_service()
    body = {
        "timeMin": start_time,
        "timeMax": end_time,
        "items": [{"id": calendar_id}]
    }
    events_result = service.freebusy().query(body=body).execute()
    return events_result['calendars'][calendar_id]['busy']

def book_event(calendar_id, summary, start_time, end_time):
    """
    summary: Event title/description
    start_time, end_time: RFC3339 strings, e.g., '2025-07-02T09:00:00+05:30'
    """
    service = get_calendar_service()
    event = {
        'summary': summary,
        'start': {'dateTime': start_time, 'timeZone': 'Asia/Kolkata'},
        'end': {'dateTime': end_time, 'timeZone': 'Asia/Kolkata'},
    }
    return service.events().insert(calendarId=calendar_id, body=event).execute()

