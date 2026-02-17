import os
import json
from datetime import datetime, timezone
from typing import Optional

from fastapi import FastAPI, HTTPException
from pydantic import BaseModel
from supabase import create_client, Client
from google import genai
from google.genai import types

app = FastAPI()

# --- 1. CONFIGURATION & CLIENTS ---
# Set these in Render: GEMINI_API_KEY, SUPABASE_URL, SUPABASE_ANON_KEY
SUPABASE_URL = os.environ.get("SUPABASE_URL")
SUPABASE_KEY = os.environ.get("SUPABASE_ANON_KEY")
GEMINI_KEY = os.environ.get("GEMINI_API_KEY")

# Initialize Clients
supabase: Client = create_client(SUPABASE_URL, SUPABASE_KEY)
gemini_client = genai.Client(api_key=GEMINI_KEY)

# --- 2. DATA MODELS ---
class CheckoutRequest(BaseModel):
    notes: str
    photo_url: Optional[str] = None

# --- 3. ROUTES ---

@app.get("/")
async def root():
    return {
        "status": "online",
        "service": "Hotel AI Cleaning Agent (v2.0)",
        "timestamp": datetime.now(timezone.utc).isoformat()
    }

@app.post("/checkin/{job_id}")
async def agent_checkin(job_id: str, hotel_qr: str):
    """Verifies QR code and logs check-in with punctuality logic."""
    response = supabase.table("cleaning_jobs") \
        .select("*, hotels(qr_code_secret)") \
        .eq("id", job_id) \
        .single() \
        .execute()
    
    job_data = response.data
    if not job_data:
        raise HTTPException(status_code=404, detail="Job not found.")

    if job_data['hotels']['qr_code_secret'] != hotel_qr:
        raise HTTPException(status_code=403, detail="Invalid QR Code for this location.")

    check_in_time = datetime.now(timezone.utc)
    scheduled_time = datetime.fromisoformat(job_data['scheduled_start'].replace('Z', '+00:00'))
    
    delay_minutes = (check_in_time - scheduled_time).total_seconds() / 60
    base_pay = float(job_data['base_pay'])
    final_payout = base_pay

    # Penalty Logic
    if delay_minutes > 20:
        final_payout = base_pay * 0.75
    elif delay_minutes > 10:
        final_payout = base_pay * 0.90
    
    status = "on-site" if delay_minutes <= 3 else "LATE"
    
    supabase.table("cleaning_jobs").update({
        "check_in_time": check_in_time.isoformat(),
        "final_payout": final_payout,
        "status": status
    }).eq("id", job_id).execute()

    return {"message": "Check-in successful", "status": status, "payout": final_payout}

@app.post("/checkout/{job_id}")
async def agent_checkout(job_id: str, data: CheckoutRequest):
    """Uses Gemini 2.0 to evaluate work and flag maintenance issues."""
    job_check = supabase.table("cleaning_jobs").select("id").eq("id", job_id).single().execute()
    if not job_check.data:
        raise HTTPException(status_code=404, detail="Job not found.")

    # 1. Gemini AI Analysis with native JSON output
    prompt = f"Analyze this hotel cleaning report: '{data.notes}'. Return a score (0-100), a 1-sentence summary, and whether maintenance is needed (true/false)."
    
    try:
        response = gemini_client.models.generate_content(
            model
    
