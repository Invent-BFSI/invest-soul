import os, json, uuid, math, tempfile
from typing import List, Optional, Dict, Any
from fastapi import FastAPI, HTTPException, UploadFile, File, Form, Depends, Request
from fastapi.middleware.cors import CORSMiddleware
from starlette.responses import JSONResponse, HTMLResponse, Response

from pydantic import BaseModel
from openai import AzureOpenAI
import requests
import azure.cognitiveservices.speech as speechsdk

from app.prompts import INNOVIYA_SYSTEM_PROMPT
from app.db import init_db, SessionLocal, SessionState, MessageLog, Portfolio
from app.market_search import search_top5, curated_four

# ---------- ENV ----------
AZURE_OPENAI_ENDPOINT    = os.getenv("AZURE_OPENAI_ENDPOINT")
AZURE_OPENAI_API_KEY     = os.getenv("AZURE_OPENAI_API_KEY")
AZURE_OPENAI_API_VERSION = os.getenv("AZURE_OPENAI_API_VERSION", "2024-10-01-preview")
AZURE_OPENAI_DEPLOYMENT  = os.getenv("AZURE_OPENAI_DEPLOYMENT")  # chat deployment

SPEECH_KEY    = os.getenv("SPEECH_KEY")
SPEECH_REGION = os.getenv("SPEECH_REGION", "eastus2")  # Browser token region

ALLOWED_ORIGINS = os.getenv("ALLOWED_ORIGINS", "http://localhost:5173,http://localhost:3000")

app = FastAPI(title="invest-soul (Innoviya) API", version="1.0.0")
app.add_middleware(
    CORSMiddleware,
    allow_origins=[o.strip() for o in ALLOWED_ORIGINS.split(",") if o.strip()],
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)

@app.on_event("startup")
def startup():
    init_db()

# ---------- Helpers ----------
def aoai_client() -> AzureOpenAI:
    # Azure endpoint pattern with OpenAI SDK is the recommended approach for Azure OpenAI. [4](https://learn.microsoft.com/en-us/samples/azure/azure-sdk-for-python/openai-samples/)
    if not (AZURE_OPENAI_ENDPOINT and AZURE_OPENAI_API_KEY and AZURE_OPENAI_DEPLOYMENT):
        raise HTTPException(500, "Azure OpenAI is not configured.")
    return AzureOpenAI(api_key=AZURE_OPENAI_API_KEY, api_version=AZURE_OPENAI_API_VERSION, azure_endpoint=AZURE_OPENAI_ENDPOINT)

def ensure_session(session_id: Optional[str]) -> str:
    sid = session_id or uuid.uuid4().hex
    db = SessionLocal()
    try:
        s = db.get(SessionState, sid)
        if not s:
            s = SessionState(sessionId=sid)
            db.add(s); db.commit()
        return sid
    finally:
        db.close()

def save_message(session_id: str, role: str, content: str):
    db = SessionLocal()
    try:
        db.add(MessageLog(sessionId=session_id, role=role, content=content)); db.commit()
    finally:
        db.close()

def infer_country_currency(city: str) -> tuple[str, str]:
    # Lightweight heuristic; extend via Azure Maps/AI Search if needed.
    city_l = (city or "").lower()
    if any(k in city_l for k in ["mumbai","delhi","bangalore","bengaluru","hyderabad","chennai","pune","kolkata"]):
        return "India", "₹"
    if any(k in city_l for k in ["new york","san francisco","austin","seattle","chicago","los angeles"]):
        return "United States", "$"
    if any(k in city_l for k in ["london","manchester"]):
        return "United Kingdom", "£"
    if any(k in city_l for k in ["paris","lyon","berlin","madrid","rome"]):
        return "European Union", "€"
    return "United States", "$"

def calc_allocation(risk: str, liabilities: float, period_years: int, net_surplus: float):
    risk_l = (risk or "").lower()
    # Asset allocation
    if risk_l.startswith("aggr"):
        equity_pct, savings_pct = 85, 15
    elif risk_l.startswith("mod"):
        equity_pct, savings_pct = 60, 40
    else:
        equity_pct, savings_pct = 30, 70
    funds_equity = round(net_surplus * (equity_pct/100.0), 2)
    funds_saving = round(net_surplus - funds_equity, 2)

    # Equity split defaults
    ds, mf, debt = 50, 30, 20

    # Overrides
    low_liab = (liabilities or 0) <= (0.2 * net_surplus if net_surplus>0 else 0)
    med_liab = (liabilities or 0) > (0.2 * net_surplus) and (liabilities or 0) <= (0.5 * net_surplus)
    if risk_l.startswith("aggr") and low_liab:
        ds, mf, debt = 70, 20, 10
    elif risk_l.startswith("mod") or med_liab:
        ds, mf, debt = 50, 30, 20
    if risk_l.startswith("cons") or (period_years or 0) < 2:
        ds, mf, debt = 30, 40, 30

    return {
        "equity_pct": equity_pct, "savings_pct": savings_pct,
        "funds_equity": funds_equity, "funds_saving": funds_saving,
        "eq_split": {"direct_stocks": ds, "mutual_funds": mf, "debt": debt}
    }

def format_currency(amount: float, symbol: str) -> str:
    return f"{symbol}{amount:,.2f}"

# ---------- Models ----------
class ChatMessage(BaseModel):
    role: str
    content: str

class ChatRequest(BaseModel):
    messages: List[ChatMessage]
    temperature: float = 0.3
    max_tokens: int = 800
    sessionId: Optional[str] = None

class ChatResponse(BaseModel):
    content: str
    sessionId: str
    finish_reason: Optional[str] = None

# ---------- Routes ----------
@app.get("/", tags=["meta"])
def root():
    return {"message": "Innoviya API (invest-soul)"}

@app.get("/health", tags=["meta"])
def health():
    return {
        "status": "healthy",
        "deps": {
            "aoai": bool(AZURE_OPENAI_ENDPOINT and AZURE_OPENAI_API_KEY and AZURE_OPENAI_DEPLOYMENT),
            "speech": bool(SPEECH_KEY and SPEECH_REGION),
            "sql": True,
            "search": bool(os.getenv("AZURE_SEARCH_ENDPOINT"))
        }
    }
@app.get("/healthy")
def health_check():
    return { "status":"healthy"}

# Speech token for browser STT/Avatar
@app.get("/speech/token", tags=["speech"])
def speech_token():
    if not (SPEECH_KEY and SPEECH_REGION):
        raise HTTPException(500, "SPEECH_KEY and SPEECH_REGION must be set.")
    url = f"https://{SPEECH_REGION}.api.cognitive.microsoft.com/sts/v1.0/issueToken"
    r = requests.post(url, headers={"Ocp-Apim-Subscription-Key": SPEECH_KEY, "Content-Length": "0"}, timeout=10)
    if r.status_code != 200:
        raise HTTPException(r.status_code, f"Failed to issue token: {r.text}")
    # Tokens last ~10 minutes; browser should renew. [1](https://learn.microsoft.com/en-us/azure/ai-services/speech-service/)[2](https://docs.azure.cn/en-us/ai-services/speech-service/troubleshooting)
    return {"token": r.text, "region": SPEECH_REGION, "expiresInSeconds": 600}

# Avatar TURN/ICE relay token for WebRTC (Real-time Avatar)
@app.get("/api/avatar/relay-token", tags=["speech"])
def avatar_relay_token():
    if not (SPEECH_KEY and SPEECH_REGION):
        raise HTTPException(status_code=500, detail="SPEECH_KEY and SPEECH_REGION must be set.")

    url = f"https://{SPEECH_REGION}.tts.speech.microsoft.com/cognitiveservices/avatar/relay/token/v1"
    try:
        r = requests.get(url, headers={"Ocp-Apim-Subscription-Key": SPEECH_KEY}, timeout=15)
    except requests.RequestException as e:
        # Network or timeout error contacting the Speech service
        raise HTTPException(status_code=500, detail=str(e))

    # If the upstream returns an error, mirror the body and status
    if r.status_code >= 400:
        return Response(
            content=r.text,
            status_code=r.status_code,
            media_type=r.headers.get("content-type", "text/plain")
        )

    # On success, proxy the JSON through (contains urls, username, credential, ttl)
    return r.json()
    
# Market: top stocks via Azure AI Search with curated fallback
@app.get("/market/top-stocks", tags=["market"])
def market_top_stocks(sector: str):
    search = search_top5(sector)  # Azure AI Search client usage. [6](https://learn.microsoft.com/en-us/python/api/azure-search-documents/azure.search.documents.searchclient?view=azure-python)[8](https://learn.microsoft.com/en-us/python/api/overview/azure/search-documents-readme?view=azure-python)
    if search:
        return {"sector": sector, "top5": search}
    # fallback: curated 4 (used along with Cognizant in final split)
    return {"sector": sector, "top5": [{"symbol": s} for s in curated_four(sector)[:5]]}

# Core chat with Azure OpenAI (+ tool: UpdatePortfolioTool)
@app.post("/chat", response_model=ChatResponse, tags=["ai"])
def chat(req: ChatRequest):
    session_id = ensure_session(req.sessionId)
    save_message(session_id, "user", json.dumps([m.model_dump() for m in req.messages]))

    # Handle '#fetch-top-stocks:' control message (model trigger)
    if req.messages and req.messages[-1].content.strip().startswith("#fetch-top-stocks:"):
        sector = req.messages[-1].content.split(":",1)[1].strip()
        payload = market_top_stocks(sector)
        return ChatResponse(content=json.dumps({"marketTopStocks": payload["top5"]}), sessionId=session_id, finish_reason="tool")

    client = aoai_client()

    # Define tool (function) for DB update; Azure OpenAI supports tools/function-calling. 
    tools = [{
        "type": "function",
        "function": {
            "name": "UpdatePortfolioTool",
            "description": "Persist portfolio to corporate DB (Azure SQL) and return status.",
            "parameters": {
                "type": "object",
                "properties": {
                    "userName": {"type":"string"},
                    "userEmail": {"type":"string"},
                    "region": {"type":"string"},
                    "monthlyInflow": {"type":"number"},
                    "monthlyOutflow": {"type":"number"},
                    "totalDebt": {"type":"number"},
                    "riskAppetite": {"type":"string"},
                    "preferredSector": {"type":"string"},
                    "investmentAmount": {"type":"number"},
                    "investmentPeriod": {"type":"number"},
                    "futureGoals": {"type":"string"},
                    "assetAllocation": {"type":"string"},
                    "equityRecommendation": {"type":"string"},
                    "alternateEquities": {"type":"string"},
                    "debtRecommendation": {"type":"string"},
                    "portfolioSummary": {"type":"string"}
                },
                "required": ["userName","region","monthlyInflow","monthlyOutflow","totalDebt",
                             "riskAppetite","preferredSector","investmentAmount","investmentPeriod",
                             "futureGoals","assetAllocation","equityRecommendation",
                             "alternateEquities","debtRecommendation","portfolioSummary"]
            }
        }
    }]

    # Prepend system prompt
    messages = [{"role": "system", "content": INNOVIYA_SYSTEM_PROMPT}]
    messages.extend([m.model_dump() for m in req.messages])

    # First call: allow tool calling
    resp = client.chat.completions.create(
        model=AZURE_OPENAI_DEPLOYMENT,
        messages=messages,
        temperature=req.temperature,
        max_tokens=req.max_tokens,
        tools=tools
    )
    choice = resp.choices[0]

    # If model requests tool call, execute it then respond
    if getattr(choice.message, "tool_calls", None):
        for call in choice.message.tool_calls:
            if call.function.name == "UpdatePortfolioTool":
                args = json.loads(call.function.arguments or "{}")
                db = SessionLocal()
                try:
                    db.add(Portfolio(
                        sessionId=session_id,
                        userName=args.get("userName",""),
                        userEmail=args.get("userEmail",""),
                        region=args.get("region",""),
                        monthlyInflow=float(args.get("monthlyInflow",0)),
                        monthlyOutflow=float(args.get("monthlyOutflow",0)),
                        totalDebt=float(args.get("totalDebt",0)),
                        riskAppetite=args.get("riskAppetite",""),
                        preferredSector=args.get("preferredSector",""),
                        investmentAmount=float(args.get("investmentAmount",0)),
                        investmentPeriod=int(args.get("investmentPeriod",0)),
                        futureGoals=args.get("futureGoals",""),
                        assetAllocation=args.get("assetAllocation",""),
                        equityRecommendation=args.get("equityRecommendation",""),
                        alternateEquities=args.get("alternateEquities",""),
                        debtRecommendation=args.get("debtRecommendation",""),
                        portfolioSummary=args.get("portfolioSummary","")
                    )); db.commit()
                    tool_result = {"status":"success","message":"Portfolio updated"}
                except Exception as e:
                    db.rollback(); tool_result = {"status":"error","message":str(e)}
                finally:
                    db.close()

                # Send tool result back to model
                tool_messages = messages + [
                    {"role":"assistant","content":choice.message.content or "", "tool_calls":[call.model_dump()]},
                    {"role":"tool","tool_call_id":call.id,"name":"UpdatePortfolioTool","content":json.dumps(tool_result)}
                ]
                resp2 = client.chat.completions.create(
                    model=AZURE_OPENAI_DEPLOYMENT,
                    messages=tool_messages,
                    temperature=req.temperature,
                    max_tokens=400
                )
                final = resp2.choices[0].message.content
                save_message(session_id, "assistant", final)
                return ChatResponse(content=final, sessionId=session_id, finish_reason=resp2.choices[0].finish_reason)

    # Normal response
    final = choice.message.content
    save_message(session_id, "assistant", final)
    return ChatResponse(content=final, sessionId=session_id, finish_reason=choice.finish_reason)

# Optional: server-side STT file transcription (browser uses SDK directly)
@app.post("/stt", tags=["speech"])
async def stt(file: UploadFile = File(...), language: str = Form("en-US")):
    if not SPEECH_KEY or not SPEECH_REGION:
        raise HTTPException(500, "SPEECH_KEY and SPEECH_REGION must be set.")
    with tempfile.NamedTemporaryFile(delete=False, suffix=f"_{file.filename}") as tmp:
        tmp.write(await file.read()); tmp_path = tmp.name
    try:
        speech_config = speechsdk.SpeechConfig(subscription=SPEECH_KEY, region=SPEECH_REGION)
        speech_config.speech_recognition_language = language
        audio_config = speechsdk.audio.AudioConfig(filename=tmp_path)
        recognizer = speechsdk.SpeechRecognizer(speech_config, audio_config)
        result = recognizer.recognize_once_async().get()
        if result.reason == speechsdk.ResultReason.RecognizedSpeech:
            return {"text": result.text, "language": language}
        elif result.reason == speechsdk.ResultReason.NoMatch:
            return JSONResponse({"error": "No speech recognized."}, status_code=422)
        else:
            raise HTTPException(500, f"STT failed: {result.cancellation_details}")
    finally:
        try: os.unlink(tmp_path)
        except: pass
