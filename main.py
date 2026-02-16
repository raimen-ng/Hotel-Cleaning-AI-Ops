from fastapi import FastAPI, HTTPException
from supabase import create_client, Client
from datetime import datetime, timezone
from pydantic import BaseModel
import os

app = FastAPI()

# Get these from Render Environment Variables
URL = os.environ.get("SUPABASE_URL")
KEY = os.environ.get("SUPABASE_ANON_KEY")
supabase: Client = create_client(URL, KEY)

@app.post("/checkin/{job_id}")
async def agent_checkin(job_id: str, hotel_qr: str):
    # 1. Fetch Job and associated Hotel Secret using a Join
    response = supabase.table("cleaning_jobs") \
        .select("*, hotels(qr_code_secret)") \
        .eq("id", job_id) \
        .single() \
        .execute()
    
    job_data = response.data
    if not job_data:
        raise HTTPException(status_code=404, detail="Job not found.")

    # 2. Verify QR Code
    if job_data['hotels']['qr_code_secret'] != hotel_qr:
        raise HTTPException(status_code=403, detail="Invalid QR Code for this location.")

    # 3. Calculate Punctuality & Penalty
    check_in_time = datetime.now(timezone.utc)
    scheduled_time = datetime.fromisoformat(job_data['scheduled_start'].replace('Z', '+00:00'))
    
    # Calculate delay in minutes
    delay = (check_in_time - scheduled_time).total_seconds() / 60
    base_pay = float(job_data['base_pay'])
    final_payout = base_pay

    # Penalty Logic
    if delay > 20:
        final_payout = base_pay * 0.75
    elif delay > 10:
        final_payout = base_pay * 0.90
    
    # 4. Update Database
    # Note: The 'status' will be automatically updated to 'LATE' by your 
    # Supabase trigger if delay > 3 mins, but we set it here for immediate UI feedback.
    status = "on-site" if delay <= 3 else "LATE"
    
    update = supabase.table("cleaning_jobs").update({
        "check_in_time": check_in_time.isoformat(),
        "final_payout": final_payout,
        "status": status
    }).eq("id", job_id).execute()

    return {
        "message": f"Check-in successful. Status: {status}",
        "delay_minutes": round(delay, 2),
        "final_payout": final_payout
    }



class CheckoutRequest(BaseModel):
    notes: str
    photo_url: str = None

@app.post("/checkout/{job_id}")
async def agent_checkout(job_id: str, data: CheckoutRequest):
    # 1. Get the check-in time to calculate total duration
    job = supabase.table("cleaning_jobs").select("*").eq("id", job_id).single().execute()
    
    if not job.data:
        raise HTTPException(status_code=404, detail="Job not found.")

    check_out_time = datetime.now(timezone.utc)
    check_in_time = datetime.fromisoformat(job.data['check_in_time'].replace('Z', '+00:00'))
    duration_mins = (check_out_time - check_in_time).total_seconds() / 60

    # 2. AI Performance Evaluation (Mock Logic)
    # In a real app, you'd send `data.notes` to an LLM here.
    ai_score = 100
    if "broken" in data.notes.lower() or "damage" in data.notes.lower():
        ai_score = 85  # Flagging maintenance is good, but indicates an issue
    
    ai_summary = f"Cleaning completed in {int(duration_mins)} mins. Notes: {data.notes}"

    # 3. Update Supabase
    update = supabase.table("cleaning_jobs").update({
        "status": "completed",
        "check_out_time": check_out_time.isoformat(),
        "ai_performance_score": ai_score,
        "summary_report": ai_summary
    }).eq("id", job_id).execute()

    return {
        "status": "Success",
        "duration": duration_mins,
        "ai_report": ai_summary
    }
    
