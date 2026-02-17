import os
import json
from datetime import datetime, timezone
from typing import Optional

from fastapi import FastAPI, HTTPException
from pydantic import BaseModel
from supabase import create_client, Client
import google.generativeai as genai

app = FastAPI()

# --- 1. CONFIGURATION & CLIENTS ---
# Make sure these variables are set in your Render "Environment" tab
SUPABASE_URL = os.environ.get("SUPABASE_URL")
SUPABASE_KEY = os.environ.get("SUPABASE_ANON_KEY")
GEMINI_KEY = os.environ.get("GEMINI_API_KEY")

supabase: Client = create_client(SUPABASE_URL, SUPABASE_KEY)

# Configure Gemini
genai.configure(api_key=GEMINI_KEY)
# Using gemini-1.5-flash for speed and cost-efficiency
model = genai.GenerativeModel('gemini-1.5-flash')

# --- 2. DATA MODELS ---
class CheckoutRequest(BaseModel):
    notes: str
    photo_url: Optional[str] = None

# --- 3. ROUTES ---

@app.get("/")
async def root():
    return {
        "status": "online",
        "service": "Hotel Cleaning AI Agent",
        "timestamp": datetime.now(timezone.utc).isoformat()
    }

@app.post("/checkin/{job_id}")
async def agent_checkin(job_id: str, hotel_qr: str):
    """
    Verifies the QR code and logs the start time.
    Calculates penalties based on lateness.
    """
    # Fetch job and the correct QR secret from the joined hotels table
    response = supabase.table("cleaning_jobs") \
        .select("*, hotels(qr_code_secret)") \
        .eq("id", job_id) \
        .single() \
        .execute()
    
    job_data = response.data
    if not job_data:
        raise HTTPException(status_code=404, detail="Job not found.")

    # 1. Verify QR Code
    if job_data['hotels']['qr_code_secret'] != hotel_qr:
        raise HTTPException(status_code=403, detail="Invalid QR Code for this location.")

    # 2. Calculate Punctuality
    check_in_time = datetime.now(timezone.utc)
    # Parse scheduled time (handles ISO format from Supabase)
    scheduled_time = datetime.fromisoformat(job_data['scheduled_start'].replace('Z', '+00:00'))
    
    delay_minutes = (check_in_time - scheduled_time).total_seconds() / 60
    base_pay = float(job_data['base_pay'])
    final_payout = base_pay

    # Penalty Logic: 10% for >10 mins, 25% for >20 mins
    if delay_minutes > 20:
        final_payout = base_pay * 0.75
    elif delay_minutes > 10:
        final_payout = base_pay * 0.90
    
    # Status determination (Database trigger also handles 'LATE' status)
    status = "on-site" if delay_minutes <= 3 else "LATE"
    
    # 3. Update Database
    supabase.table("cleaning_jobs").update({
        "check_in_time": check_in_time.isoformat(),
        "final_payout": final_payout,
        "status": status
    }).eq("id", job_id).execute()

    return {
        "message": "Check-in successful",
        "status": status,
        "delay_minutes": round(delay_minutes, 2),
        "payout_locked": final_payout
    }

@app.post("/checkout/{job_id}")
async def agent_checkout(job_id: str, data: CheckoutRequest):
    """
    Logs checkout time and uses Gemini AI to analyze notes for maintenance issues.
    """
    # Verify job exists
    job_check = supabase.table("cleaning_jobs").select("id").eq("id", job_id).single().execute()
    if not job_check.data:
        raise HTTPException(status_code=404, detail="Job not found.")

    # 1. Gemini AI Analysis
    prompt = f"""
    Analyze this hotel cleaning report provided by the staff: "{data.notes}"
    
    Tasks:
    1. Score the cleaning quality (0-100).
    2. Provide a 1-sentence summary of the report.
    3. Determine if any maintenance/repairs are needed (e.g. leaks, broken furniture, burnt bulbs).
    
    Return ONLY a JSON object with these keys: "score", "summary", "maintenance_needed".
    """

    try:
        response = model.generate_content(prompt)
        # Clean potential markdown formatting from Gemini's response
        raw_text = response.text.replace('```json', '').replace('```', '').strip()
        analysis = json.loads(raw_text)
    except Exception as e:
        # Fallback if AI fails
        analysis = {"score": 70, "summary": "Manual review required.", "maintenance_needed": False}

    # 2. Update Supabase
    check_out_time = datetime.now(timezone.utc)
    
    update_data = {
        "status": "completed",
        "check_out_time": check_out_time.isoformat(),
        "ai_performance_score": analysis.get('score'),
        "summary_report": analysis.get('summary'),
        "needs_maintenance": analysis.get('maintenance_needed')
    }

    supabase.table("cleaning_jobs").update(update_data).eq("id", job_id).execute()

    # 3. Response to Frontend
    return {
        "message": "Checkout complete",
        "ai_score": analysis.get('score'),
        "maintenance_flag": analysis.get('maintenance_needed'),
        "summary": analysis.get('summary')
    }
