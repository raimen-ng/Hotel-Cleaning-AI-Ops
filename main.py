import google.generativeai as genai
import json
import os
from fastapi import FastAPI, HTTPException
from pydantic import BaseModel
from supabase import create_client, Client
from datetime import datetime, timezone

app = FastAPI()

# 1. Setup
URL = os.environ.get("SUPABASE_URL")
KEY = os.environ.get("SUPABASE_ANON_KEY")
supabase: Client = create_client(URL, KEY)

# Configure Gemini
genai.configure(api_key=os.environ.get("GEMINI_API_KEY"))
model = genai.GenerativeModel('gemini-1.5-flash')

class CheckoutRequest(BaseModel):
    notes: str
    photo_url: str = None

@app.post("/checkout/{job_id}")
async def agent_checkout(job_id: str, data: CheckoutRequest):
    # Fetch job data
    job = supabase.table("cleaning_jobs").select("*").eq("id", job_id).single().execute()
    if not job.data:
        raise HTTPException(status_code=404, detail="Job not found.")

    # 2. Gemini AI Evaluation
    # We ask Gemini to act as a manager and return JSON
    prompt = f"""
    Analyze this hotel cleaning report and provide a performance score (0-100) 
    and a 1-sentence summary.
    
    Report: "{data.notes}"
    
    Return the response strictly as a JSON object with keys: "score" and "summary".
    """

    response = model.generate_content(prompt)
    
    # Clean the response text (Gemini sometimes adds markdown backticks)
    json_text = response.text.replace('```json', '').replace('```', '').strip()
    analysis = json.loads(json_text)

    # 3. Update Supabase
    update = supabase.table("cleaning_jobs").update({
        "status": "completed",
        "check_out_time": datetime.now(timezone.utc).isoformat(),
        "ai_performance_score": analysis['score'],
        "summary_report": analysis['summary']
    }).eq("id", job_id).execute()

    return {
        "status": "Success",
        "ai_analysis": analysis
    }
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
    
