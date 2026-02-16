from fastapi import FastAPI, HTTPException
from supabase import create_client, Client
from datetime import datetime
import os

app = FastAPI()

# These credentials you get for free from Supabase
URL = "https://dnfpggnwpnoortcpwlrt.supabase.co"
KEY = "eyJhbGciOiJIUzI1NiIsInR5cCI6IkpXVCJ9.eyJpc3MiOiJzdXBhYmFzZSIsInJlZiI6ImRuZnBnZ253cG5vb3J0Y3B3bHJ0Iiwicm9sZSI6ImFub24iLCJpYXQiOjE3NzExNzk2MDUsImV4cCI6MjA4Njc1NTYwNX0.ptNufLKJWiB7wFTI6afq5CsHDD9BXTTRMEiI5knA6Ds"
supabase: Client = create_client(URL, KEY)

@app.post("/checkin/{job_id}")
async def agent_checkin(job_id: str, agent_id: str, hotel_qr: str):
    # 1. Verify the QR Code matches the Hotel
    job = supabase.table("cleaning_jobs").select("*, hotels(qr_code_secret)").eq("id", job_id).single().execute()
    
    if job.data['hotels']['qr_code_secret'] != hotel_qr:
        raise HTTPException(status_code=403, detail="Invalid QR Code for this location.")

    # 2. Calculate Punctuality
    check_in_time = datetime.now()
    scheduled_time = datetime.fromisoformat(job.data['scheduled_start'])
    delay = (check_in_time - scheduled_time).total_seconds() / 60

    # 3. Apply the "Stick" (Penalty Logic)
    base_pay = float(job.data['base_pay'])
    final_payout = base_pay

    if delay > 20:
        final_payout = base_pay * 0.75  # 25% Penalty
    elif delay > 10:
        final_payout = base_pay * 0.90  # 10% Penalty
    
    # 4. Update Database
    update = supabase.table("cleaning_jobs").update({
        "check_in_time": check_in_time.isoformat(),
        "final_payout": final_payout,
        "status": "on-site" if delay <= 3 else "LATE"
    }).eq("id", job_id).execute()

    return {"message": "Check-in successful", "payout_locked": final_payout}
