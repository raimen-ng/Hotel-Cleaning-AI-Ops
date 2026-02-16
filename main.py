from fastapi import FastAPI, HTTPException
from supabase import create_client, Client
from datetime import datetime, timezone
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

