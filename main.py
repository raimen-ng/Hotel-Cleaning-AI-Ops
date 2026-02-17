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

@app.get("/")
async def root():
    return {"status": "online", "method": "REST API (No SDK)"}

@app.post("/checkin/{job_id}")
async def agent_checkin(job_id: str, hotel_qr: str):
    # (Existing check-in logic remains the same)
    response = supabase.table("cleaning_jobs").select("*, hotels(qr_code_secret)").eq("id", job_id).single().execute()
    if not response.data or response.data['hotels']['qr_code_secret'] != hotel_qr:
        raise HTTPException(status_code=403, detail="Invalid QR or Job")
    
    supabase.table("cleaning_jobs").update({
        "check_in_time": datetime.now(timezone.utc).isoformat(),
        "status": "on-site"
    }).eq("id", job_id).execute()
    return {"message": "Checked in"}

@app.post("/checkout/{job_id}")
async def agent_checkout(job_id: str, data: CheckoutRequest):
    # Use v1beta and correct the URL to the latest model
    gemini_url = f"https://generativelanguage.googleapis.com/v1beta/models/gemini-3-flash:generateContent?key={GEMINI_KEY}"
    
    # PAYLOAD FIX: Changed to camelCase for REST compatibility
    payload = {
        "contents": [{
            "parts": [{
                "text": f"Analyze cleaning report: '{data.notes}'. Return JSON with keys: 'score' (0-100), 'summary' (1 sentence), 'maintenance_needed' (boolean)."
            }]
        }],
        "generationConfig": {
            "responseMimeType": "application/json",
        }
    }

    async with httpx.AsyncClient() as client:
        try:
            response = await client.post(gemini_url, json=payload, timeout=30.0)
            
            if response.status_code != 200:
                return {
                    "status": "error", 
                    "debug_info": f"Google API returned {response.status_code}: {response.text}"
                }

            result = response.json()
            ai_text = result['candidates'][0]['content']['parts'][0]['text']
            analysis = json.loads(ai_text)
            
        except Exception as e:
            raise HTTPException(status_code=500, detail=f"Internal logic error: {str(e)}")

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
