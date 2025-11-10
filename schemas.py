"""
Database Schemas

Define your MongoDB collection schemas here using Pydantic models.
These schemas are used for data validation in your application.

Each Pydantic model represents a collection in your database.
Model name is converted to lowercase for the collection name:
- User -> "user" collection
- Chat -> "chat" collection
- Message -> "message" collection
"""

from pydantic import BaseModel, Field
from typing import Optional, List
from datetime import datetime

class User(BaseModel):
    """
    Users collection schema
    Collection name: "user" (lowercase of class name)
    """
    username: str = Field(..., description="Unique username used to log in")
    display_name: str = Field(..., description="Name shown in conversations")
    avatar: Optional[str] = Field(None, description="Avatar image URL")
    status: Optional[str] = Field("Hey there! I am using Vibe Chat.", description="Status message")
    online: bool = Field(False, description="Is the user currently online")
    last_seen: Optional[datetime] = Field(None, description="Last time the user was seen online")

class Chat(BaseModel):
    """
    Chats collection schema
    Collection name: "chat"
    """
    participants: List[str] = Field(..., description="Array of user ids (as strings)")
    last_message_preview: Optional[str] = Field(None, description="Preview of the latest message")

class Message(BaseModel):
    """
    Messages collection schema
    Collection name: "message"
    """
    chat_id: str = Field(..., description="ID of the chat this message belongs to")
    sender_id: str = Field(..., description="User ID of the sender")
    content: str = Field(..., description="Message text content or caption")
    kind: str = Field("text", description="Message kind: text | image | audio")
    media_url: Optional[str] = Field(None, description="Optional media URL for image/audio messages")
    seen: bool = Field(False, description="Whether the message has been seen by recipients")
