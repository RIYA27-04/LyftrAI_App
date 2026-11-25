import os, json, time, hashlib
from datetime import datetime, timezone
from typing import Optional
from fastapi import FastAPI, HTTPException, Header
from fastapi.middleware.cors import CORSMiddleware
from pydantic import BaseModel, Field
from sqlalchemy import create_engine, Column, Integer, String, Text
from sqlalchemy.orm import declarative_base, sessionmaker
import litellm
from litellm import completion

DATABASE_URL=os.getenv("DATABASE_URL","sqlite:////data/app.db")
if DATABASE_URL.startswith("sqlite:///"):
    db_path=DATABASE_URL.replace("sqlite:///","",1)
    if db_path and db_path != ":memory:":
        os.makedirs(os.path.dirname(db_path) or ".", exist_ok=True)
engine=create_engine(DATABASE_URL, connect_args={"check_same_thread":False} if DATABASE_URL.startswith("sqlite") else {})
SessionLocal=sessionmaker(bind=engine)
Base=declarative_base()
class Message(Base):
    __tablename__="messages"
    id=Column(Integer,primary_key=True,autoincrement=True)
    session_id=Column(String,nullable=False,index=True)
    role=Column(String,nullable=False)
    content=Column(Text,nullable=False)
    metadata_json=Column(Text,nullable=True)
    created_at=Column(String,nullable=False)
class Cache(Base):
    __tablename__="response_cache"
    cache_key=Column(String,primary_key=True)
    reply=Column(Text,nullable=False)
    model=Column(String,nullable=False)
    input_tokens=Column(Integer,nullable=False)
    output_tokens=Column(Integer,nullable=False)
Base.metadata.create_all(engine)

keys=[k.strip() for k in os.getenv("LLM_API_KEYS","").split(",") if k.strip()]
MODEL=os.getenv("LLM_MODEL","gemini/gemini-2.0-flash")
DEFAULT_SYSTEM=os.getenv("DEFAULT_SYSTEM_PROMPT","You are a helpful, concise assistant.")
app=FastAPI(title="LyftrAI Chat API")
origins=[o.strip() for o in os.getenv("ALLOWED_ORIGINS","*").split(",") if o.strip()]
app.add_middleware(CORSMiddleware,allow_origins=origins or ["*"],allow_credentials=False,allow_methods=["*"],allow_headers=["*"])
litellm.cache = litellm.Cache(type="local")

class ChatRequest(BaseModel):
    session_id:str=Field(min_length=1,max_length=128)
    message:str=Field(min_length=1,max_length=4000)
    system_prompt:Optional[str]=None

def token_estimate(text):
    return max(1,len(text)//4)
def get_cache(db,key):
    return db.query(Cache).filter(Cache.cache_key==key).first()
@app.get("/health")
def health():
    db=SessionLocal()
    try:
        db.execute(__import__('sqlalchemy').text("SELECT 1"))
    finally: db.close()
    return {"status":"ok","keys_configured":len(keys),"cache_enabled":True}
@app.post("/chat")
def chat(req:ChatRequest, x_simulate_failure:Optional[str]=Header(default=None)):
    message=req.message.strip()
    if not req.session_id.strip() or not message:
        raise HTTPException(422,detail="session_id and message are required")
    db=SessionLocal()
    try:
        history=db.query(Message).filter(Message.session_id==req.session_id).order_by(Message.id.asc()).all()
        system=req.system_prompt.strip() if req.system_prompt and req.system_prompt.strip() else DEFAULT_SYSTEM
        messages=[{"role":"system","content":system}]+[{"role":m.role,"content":m.content} for m in history]+[{"role":"user","content":message}]
        cache_key=hashlib.sha256(json.dumps({"model":MODEL,"messages":messages},sort_keys=True).encode()).hexdigest()
        cached=get_cache(db,cache_key)
        if cached:
            metadata={"resolution_source":"LLM_CACHE","model":cached.model,"latency_ms":1,"input_tokens":cached.input_tokens,"output_tokens":cached.output_tokens,"key_id":None,"fallback_attempts":0}
            db.add(Message(session_id=req.session_id,role="user",content=message,metadata_json=None,created_at=datetime.now(timezone.utc).isoformat()))
            db.add(Message(session_id=req.session_id,role="assistant",content=cached.reply,metadata_json=json.dumps(metadata),created_at=datetime.now(timezone.utc).isoformat()))
            db.commit()
            return {"session_id":req.session_id,"reply":cached.reply,"metadata":metadata}
        sim={}
        if os.getenv("ENABLE_FAILURE_SIMULATION","false").lower()=="true" and x_simulate_failure:
            for part in x_simulate_failure.split(","):
                if "=" in part:
                    k,v=part.strip().split("=",1); sim[k.strip()]=v.strip()
        if not keys:
            raise HTTPException(503,detail="all providers unavailable")
        start=time.perf_counter(); answer=None; used=None; failures=0
        for i,key in enumerate(keys):
            key_id=f"key_{i+1}"
            if sim.get("*") or sim.get(key_id):
                failures+=1
                continue
            try:
                response=completion(model=MODEL,messages=messages,api_key=key)
                answer=response.choices[0].message.content or ""
                used=key_id
                usage=response.usage
                in_tokens=int(getattr(usage,"prompt_tokens",0) or token_estimate(json.dumps(messages)))
                out_tokens=int(getattr(usage,"completion_tokens",0) or token_estimate(answer))
                break
            except Exception:
                failures+=1
        latency=int((time.perf_counter()-start)*1000)
        if answer is None:
            raise HTTPException(503,detail="all providers unavailable")
        metadata={"resolution_source":"LIVE_INFERENCE","model":MODEL,"latency_ms":latency,"input_tokens":in_tokens,"output_tokens":out_tokens,"key_id":used,"fallback_attempts":failures}
        db.add(Message(session_id=req.session_id,role="user",content=message,metadata_json=None,created_at=datetime.now(timezone.utc).isoformat()))
        db.add(Message(session_id=req.session_id,role="assistant",content=answer,metadata_json=json.dumps(metadata),created_at=datetime.now(timezone.utc).isoformat()))
        db.add(Cache(cache_key=cache_key,reply=answer,model=MODEL,input_tokens=in_tokens,output_tokens=out_tokens))
        db.commit()
        return {"session_id":req.session_id,"reply":answer,"metadata":metadata}
    finally: db.close()
@app.get("/sessions/{session_id}/messages")
def get_messages(session_id:str):
    db=SessionLocal()
    try:
        records=db.query(Message).filter(Message.session_id==session_id).order_by(Message.id.asc()).all()
        if not records: raise HTTPException(404,detail="session not found")
        result=[]
        for m in records:
            row={"role":m.role,"content":m.content}
            if m.role=="assistant" and m.metadata_json:
                row["metadata"]=json.loads(m.metadata_json)
            result.append(row)
        return {"session_id":session_id,"messages":result}
    finally: db.close()
