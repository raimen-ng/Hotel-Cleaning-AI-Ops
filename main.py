import os
import json
from datetime import datetime, timezone
from typing import Optional

from fastapi import FastAPI, HTTPException
from pydantic import BaseModel
from supabase import create_client, Client

# Defensive import for Google SDK
try:
    from google import genai
    from google.genai import types
except ImportError:
    # This acts as a secondary check if Render is being difficult
    import sys
    print(f"DEBUG: Python Path is {sys.path}")
    raise

app = FastAPI()

# --- CONFIG & CLIENTS ---
SUPABASE_URL = os.environ.get("SUPABASE_URL")
SUPABASE_KEY = os.environ.get("SUPABASE_ANON_KEY")
GEMINI_KEY = os.environ.get("GEMINI_API_KEY")

supabase: Client = create_client(SUPABASE_URL, SUPABASE_KEY)
gemini_client = genai.Client(api_key=GEMINI_KEY)

# --- DATA MODELS ---
class CheckoutRequest(BaseModel):
    notes: str
    photo_url: Optional[str] = None

# --- ROUTES ---

@app.get("/")
async def root():
    return {"status": "online", "engine": "Gemini 2.0 Flash"}

@app.post("/checkin/{job_id}")
async def agent_checkin(job_id: str, hotel_qr: str):
    response = supabase.table("cleaning_jobs").select("*, hotels(qr_code_secret)").eq("id", job_id).single().execute()
    job_data = response.data
    if not job_data:
        raise HTTPException(status_code=404, detail="Job not found.")

    if job_data['hotels']['qr_code_secret'] != hotel_qr:
        raise HTTPException(status_code=403, detail="Invalid QR Code.")

    check_in_time = datetime.now(timezone.utc)
    scheduled_time = datetime.fromisoformat(job_data['scheduled_start'].replace('Z', '+00:00'))
    delay_minutes = (check_in_time - scheduled_time).total_seconds() / 60
    
    status = "on-site" if delay_minutes <= 3 else "LATE"
    
    supabase.table("cleaning_jobs").update({
        "check_in_time": check_in_time.isoformat(),
        "status": status
    }).eq("id", job_id).execute()

    return {"message": "Checked in", "status": status}

@app.post("/checkout/{job_id}")
async def agent_checkout(job_id: str, data: CheckoutRequest):
    # 1. Gemini AI Analysis
    prompt = f"Analyze cleaning report: '{data.notes}'. Provide score(0-100), summary, and maintenance_needed(true/false)."
    
    try:
        response = gemini_client.models.generate_content(
            model="gemini-2.0-flash",
            contents=prompt,
            config=types.GenerateContentConfig(
                response_mime_type="application/json",
            )
        )
        analysis = json.loads(response.text)
    except Exception as e:
        analysis = {"score": 50, "summary": f"AI Error: {str(e)}", "maintenance_needed": False}

    # 2. Update Supabase
    update_data = {
        "status": "completed",
        "check_out_time": datetime.now(timezone.utc).isoformat(),
        "ai_performance_score": analysis.get('score'),
        "summary_report": analysis.get('summary'),
        "needs_maintenance": analysis.get('maintenance_needed')
    }
    supabase.table("cleaning_jobs").update(update_data).eq("id", job_id).execute()

    return {"status": "success", "analysis": analysis}
