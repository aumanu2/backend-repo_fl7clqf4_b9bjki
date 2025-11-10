import os
from fastapi import FastAPI, HTTPException
from fastapi.middleware.cors import CORSMiddleware
from pydantic import BaseModel
from typing import List, Optional
from bson import ObjectId

from database import db, create_document, get_documents
from schemas import User as UserSchema, Chat as ChatSchema, Message as MessageSchema

app = FastAPI(title="Vibe Chat API")

app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)

class CreateUserRequest(BaseModel):
    username: str
    display_name: str
    avatar: Optional[str] = None

class CreateChatRequest(BaseModel):
    participant_usernames: List[str]

class SendMessageRequest(BaseModel):
    chat_id: str
    sender_username: str
    content: str

@app.get("/")
def read_root():
    return {"message": "Vibe Chat API is running"}

@app.get("/test")
def test_database():
    response = {
        "backend": "✅ Running",
        "database": "❌ Not Available",
        "database_url": None,
        "database_name": None,
        "connection_status": "Not Connected",
        "collections": []
    }

    try:
        if db is not None:
            response["database"] = "✅ Available"
            response["database_url"] = "✅ Set" if os.getenv("DATABASE_URL") else "❌ Not Set"
            response["database_name"] = db.name if hasattr(db, 'name') else "✅ Connected"
            response["connection_status"] = "Connected"
            try:
                collections = db.list_collection_names()
                response["collections"] = collections[:10]
                response["database"] = "✅ Connected & Working"
            except Exception as e:
                response["database"] = f"⚠️  Connected but Error: {str(e)[:50]}"
        else:
            response["database"] = "⚠️  Available but not initialized"
    except Exception as e:
        response["database"] = f"❌ Error: {str(e)[:50]}"

    return response

# Helper to get user by username

def _get_user_by_username(username: str):
    u = db["user"].find_one({"username": username})
    return u

@app.post("/api/users", response_model=dict)
async def create_user(payload: CreateUserRequest):
    existing = _get_user_by_username(payload.username)
    if existing:
        # return existing user id
        return {"user_id": str(existing.get("_id"))}

    user = UserSchema(
        username=payload.username,
        display_name=payload.display_name,
        avatar=payload.avatar,
    )
    user_id = create_document("user", user)
    return {"user_id": user_id}

@app.get("/api/users", response_model=List[dict])
async def list_users():
    users = get_documents("user")
    # convert _id
    for u in users:
        u["_id"] = str(u["_id"]) if "_id" in u else None
    return users

@app.post("/api/chats", response_model=dict)
async def create_chat(payload: CreateChatRequest):
    if len(payload.participant_usernames) < 2:
        raise HTTPException(status_code=400, detail="At least two participants required")

    # fetch user ids
    user_ids = []
    for username in payload.participant_usernames:
        u = _get_user_by_username(username)
        if not u:
            raise HTTPException(status_code=404, detail=f"User {username} not found")
        user_ids.append(str(u["_id"]))

    chat = ChatSchema(participants=user_ids, last_message_preview=None)
    chat_id = create_document("chat", chat)
    return {"chat_id": chat_id}

@app.get("/api/chats", response_model=List[dict])
async def list_chats(username: Optional[str] = None):
    filt = {}
    if username:
        u = _get_user_by_username(username)
        if not u:
            raise HTTPException(status_code=404, detail=f"User {username} not found")
        filt = {"participants": {"$in": [str(u["_id"]) ]}}
    chats = get_documents("chat", filt)
    for c in chats:
        c["_id"] = str(c["_id"]) if "_id" in c else None
    return chats

@app.post("/api/messages", response_model=dict)
async def send_message(payload: SendMessageRequest):
    # ensure chat exists
    try:
        chat_oid = ObjectId(payload.chat_id)
    except Exception:
        raise HTTPException(status_code=400, detail="Invalid chat_id")

    chat = db["chat"].find_one({"_id": chat_oid})
    if not chat:
        raise HTTPException(status_code=404, detail="Chat not found")

    sender = _get_user_by_username(payload.sender_username)
    if not sender:
        raise HTTPException(status_code=404, detail="Sender not found")

    msg = MessageSchema(chat_id=payload.chat_id, sender_id=str(sender["_id"]), content=payload.content, seen=False)
    msg_id = create_document("message", msg)

    # update last message preview
    db["chat"].update_one({"_id": chat_oid}, {"$set": {"last_message_preview": payload.content}})

    return {"message_id": msg_id}

@app.get("/api/messages", response_model=List[dict])
async def list_messages(chat_id: str):
    try:
        chat_oid = ObjectId(chat_id)
    except Exception:
        raise HTTPException(status_code=400, detail="Invalid chat_id")

    msgs = get_documents("message", {"chat_id": chat_id})
    for m in msgs:
        m["_id"] = str(m["_id"]) if "_id" in m else None
    return msgs

if __name__ == "__main__":
    import uvicorn
    port = int(os.getenv("PORT", 8000))
    uvicorn.run(app, host="0.0.0.0", port=port)
