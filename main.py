import os
import json
import httpx
from datetime import datetime, timezone
from typing import Optional

from fastapi import FastAPI, HTTPException
from pydantic import BaseModel
from supabase import create_client, Client

app = FastAPI()

# --- CONFIG ---
SUPABASE_URL = os.environ.get("SUPABASE_URL")
SUPABASE_KEY = os.environ.get("SUPABASE_ANON_KEY")
GEMINI_KEY = os.environ.get("GEMINI_API_KEY")

supabase: Client = create_client(SUPABASE_URL, SUPABASE_KEY)

class CheckoutRequest(BaseModel):
    notes: str
    photo_url: Optional[str] = None
@app.post("/checkin/{job_id}")
async def agent_checkin(job_id: str, hotel_qr: str):
    # 1. Fetch job, base_pay, and the correct QR secret
    response = supabase.table("cleaning_jobs") \
        .select("*, hotels(qr_code_secret)") \
        .eq("id", job_id) \
        .single() \
        .execute()
    
    job_data = response.data
    if not job_data or job_data['hotels']['qr_code_secret'] != hotel_qr:
        raise HTTPException(status_code=403, detail="Invalid QR or Job")

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
    
    # 3. Update Database with the calculated payout
    status = "on-site" if delay_minutes <= 3 else "LATE"
    
    supabase.table("cleaning_jobs").update({
        "check_in_time": check_in_time.isoformat(),
        "final_payout": final_payout, # This was missing!
        "status": status
    }).eq("id", job_id).execute()

    return {
        "message": "Checked in", 
        "status": status, 
        "calculated_payout": final_payout,
        "delay": f"{round(delay_minutes, 1)} minutes"
    }

@app.post("/checkout/{job_id}")
async def agent_checkout(job_id: str, data: CheckoutRequest):
    # 1. Fetch the EXISTING job data to get the final_payout from check-in
    job_response = supabase.table("cleaning_jobs").select("final_payout").eq("id", job_id).single().execute()
    
    if not job_response.data:
        raise HTTPException(status_code=404, detail="Job not found.")
    
    current_payout = job_response.data.get('final_payout')

    # 2. Call Gemini AI (Existing REST Logic)
    gemini_url = f"https://generativelanguage.googleapis.com/v1beta/models/gemini-3-flash-preview:generateContent?key={GEMINI_KEY}"
    payload = {
        "contents": [{"parts": [{"text": f"Analyze: '{data.notes}'. Return JSON: score(0-100), summary(1 sentence), maintenance_needed(bool)."}]}],
        "generationConfig": {"responseMimeType": "application/json"}
    }

    async with httpx.AsyncClient() as client:
        # ... (Keep your existing httpx try/except block here) ...
        response = await client.post(gemini_url, json=payload, timeout=30.0)
        result = response.json()
        ai_text = result['candidates'][0]['content']['parts'][0]['text']
        analysis = json.loads(ai_text)

    # Add a $5 bonus for scores above 90
    if analysis.get('score', 0) >= 90:
        current_payout = float(current_payout) + 5.0
        analysis['summary'] += " (Bonus Awarded!)"
    
    # 3. Update Supabase - INCLUDE final_payout to be safe
    update_data = {
        "status": "completed",
        "check_out_time": datetime.now(timezone.utc).isoformat(),
        "ai_performance_score": analysis.get('score'),
        "summary_report": analysis.get('summary'),
        "needs_maintenance": analysis.get('maintenance_needed'),
        "final_payout": current_payout  # Ensuring we don't lose the value!
    }
    
    supabase.table("cleaning_jobs").update(update_data).eq("id", job_id).execute()

    return {
        "status": "success", 
        "analysis": analysis,
        "payout_verified": current_payout
    }
