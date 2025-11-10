import os
from fastapi import FastAPI, HTTPException, UploadFile, File, Form, WebSocket, WebSocketDisconnect
from fastapi.middleware.cors import CORSMiddleware
from pydantic import BaseModel
from typing import List, Optional
from bson import ObjectId
from datetime import datetime, timezone

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

class UpdateStatusRequest(BaseModel):
    status: Optional[str] = None

class CreateChatRequest(BaseModel):
    participant_usernames: List[str]

class SendMessageRequest(BaseModel):
    chat_id: str
    sender_username: str
    content: str
    kind: Optional[str] = "text"  # text | image | audio
    media_url: Optional[str] = None

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
    now = datetime.now(timezone.utc)
    if existing:
        # set online
        db["user"].update_one({"_id": existing["_id"]}, {"$set": {"online": True, "last_seen": now, "display_name": payload.display_name, "avatar": payload.avatar}})
        return {"user_id": str(existing.get("_id"))}

    user = UserSchema(
        username=payload.username,
        display_name=payload.display_name,
        avatar=payload.avatar,
        online=True,
        last_seen=now,
    )
    user_id = create_document("user", user)
    return {"user_id": user_id}

@app.post("/api/users/status", response_model=dict)
async def update_status(payload: UpdateStatusRequest, username: str):
    u = _get_user_by_username(username)
    if not u:
        raise HTTPException(status_code=404, detail="User not found")
    update = {"last_seen": datetime.now(timezone.utc)}
    if payload.status is not None:
        update["status"] = payload.status
    db["user"].update_one({"_id": u["_id"]}, {"$set": update})
    return {"ok": True}

@app.post("/api/users/online", response_model=dict)
async def set_online(username: str, online: bool = True):
    u = _get_user_by_username(username)
    if not u:
        raise HTTPException(status_code=404, detail="User not found")
    db["user"].update_one({"_id": u["_id"]}, {"$set": {"online": online, "last_seen": datetime.now(timezone.utc)}})
    return {"ok": True}

@app.get("/api/users", response_model=List[dict])
async def list_users(q: Optional[str] = None):
    filt = {}
    if q:
        filt = {"$or": [
            {"username": {"$regex": q, "$options": "i"}},
            {"display_name": {"$regex": q, "$options": "i"}},
        ]}
    users = get_documents("user", filt)
    for u in users:
        u["_id"] = str(u["_id"]) if "_id" in u else None
        if isinstance(u.get("last_seen"), datetime):
            u["last_seen"] = u["last_seen"].isoformat()
    return users

@app.get("/api/users/profile", response_model=dict)
async def get_profile(username: str):
    u = _get_user_by_username(username)
    if not u:
        raise HTTPException(status_code=404, detail="User not found")
    u["_id"] = str(u["_id"]) if "_id" in u else None
    if isinstance(u.get("last_seen"), datetime):
        u["last_seen"] = u["last_seen"].isoformat()
    return u

@app.get("/api/users/by_ids", response_model=List[dict])
async def users_by_ids(ids: str):
    try:
        oid_list = [ObjectId(x) for x in ids.split(",") if x]
    except Exception:
        raise HTTPException(status_code=400, detail="Invalid ids")
    docs = list(db["user"].find({"_id": {"$in": oid_list}}))
    for u in docs:
        u["_id"] = str(u["_id"]) if "_id" in u else None
        if isinstance(u.get("last_seen"), datetime):
            u["last_seen"] = u["last_seen"].isoformat()
    return docs

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

# Realtime broadcasting helpers (SSE + WebSocket)
from fastapi import Request
from fastapi.responses import StreamingResponse
import asyncio

sse_subscribers = set()

async def sse_event_generator(request: Request):
    queue = asyncio.Queue()
    sse_subscribers.add(queue)
    try:
        while True:
            if await request.is_disconnected():
                break
            try:
                event = await asyncio.wait_for(queue.get(), timeout=15)
                yield f"data: {event}\n\n"
            except asyncio.TimeoutError:
                yield ": keep-alive\n\n"
    finally:
        sse_subscribers.discard(queue)

@app.get("/api/stream")
async def stream(request: Request):
    return StreamingResponse(sse_event_generator(request), media_type="text/event-stream")

class ConnectionManager:
    def __init__(self):
        self.active: List[WebSocket] = []
    async def connect(self, websocket: WebSocket):
        await websocket.accept()
        self.active.append(websocket)
    def disconnect(self, websocket: WebSocket):
        if websocket in self.active:
            self.active.remove(websocket)
    async def broadcast(self, message: str):
        for ws in list(self.active):
            try:
                await ws.send_text(message)
            except Exception:
                self.disconnect(ws)

ws_manager = ConnectionManager()

@app.websocket("/ws")
async def websocket_endpoint(websocket: WebSocket):
    await ws_manager.connect(websocket)
    try:
        while True:
            # Keep connection alive; ignore incoming messages for now
            await websocket.receive_text()
    except WebSocketDisconnect:
        ws_manager.disconnect(websocket)
    except Exception:
        ws_manager.disconnect(websocket)

async def publish_event(event: str):
    # SSE
    for q in list(sse_subscribers):
        try:
            q.put_nowait(event)
        except Exception:
            pass
    # WebSocket
    await ws_manager.broadcast(event)

@app.post("/api/messages", response_model=dict)
async def send_message(payload: SendMessageRequest):
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

    kind = payload.kind or "text"
    msg = MessageSchema(chat_id=payload.chat_id, sender_id=str(sender["_id"]), content=payload.content or "", kind=kind, media_url=payload.media_url, seen=False)
    msg_id = create_document("message", msg)

    preview = payload.content or ("📷 Immagine" if kind == "image" else "🎙️ Audio" if kind == "audio" else "Messaggio")
    db["chat"].update_one({"_id": chat_oid}, {"$set": {"last_message_preview": preview}})

    # notify
    import json
    await publish_event(json.dumps({"type": "new_message", "chat_id": payload.chat_id, "message_id": msg_id, "preview": preview}))

    return {"message_id": msg_id}

@app.post("/api/messages/upload", response_model=dict)
async def upload_media(chat_id: str = Form(...), sender_username: str = Form(...), kind: str = Form(...), file: UploadFile = File(...)):
    try:
        chat_oid = ObjectId(chat_id)
    except Exception:
        raise HTTPException(status_code=400, detail="Invalid chat_id")

    chat = db["chat"].find_one({"_id": chat_oid})
    if not chat:
        raise HTTPException(status_code=404, detail="Chat not found")

    sender = _get_user_by_username(sender_username)
    if not sender:
        raise HTTPException(status_code=404, detail="Sender not found")

    content = await file.read()
    doc = {
        "filename": file.filename,
        "content_type": file.content_type,
        "size": len(content),
        "bytes": content,
        "created_at": datetime.now(timezone.utc)
    }
    media_id = db["media"].insert_one(doc).inserted_id
    media_url = f"/api/media/{str(media_id)}"

    msg = MessageSchema(chat_id=chat_id, sender_id=str(sender["_id"]), content="", kind=kind, media_url=media_url, seen=False)
    msg_id = create_document("message", msg)

    preview = "📷 Immagine" if kind == "image" else "🎙️ Audio"
    db["chat"].update_one({"_id": chat_oid}, {"$set": {"last_message_preview": preview}})

    import json
    await publish_event(json.dumps({"type": "new_message", "chat_id": chat_id, "message_id": msg_id, "preview": preview}))

    return {"message_id": msg_id, "media_url": media_url}

@app.get("/api/media/{media_id}")
async def get_media(media_id: str):
    try:
        oid = ObjectId(media_id)
    except Exception:
        raise HTTPException(status_code=400, detail="Invalid media id")
    doc = db["media"].find_one({"_id": oid})
    if not doc:
        raise HTTPException(status_code=404, detail="Not found")
    from fastapi.responses import Response
    return Response(content=doc["bytes"], media_type=doc.get("content_type") or "application/octet-stream")

@app.get("/api/messages", response_model=List[dict])
async def list_messages(chat_id: str):
    try:
        _ = ObjectId(chat_id)
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
