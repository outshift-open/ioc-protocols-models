from pydantic import BaseModel

class Message(BaseModel):
    """
    Message model
    """
    content: str

class Episode(BaseModel):
    """
    Episode model
    """
    id: str
    messages: list[Message]

class Conversation(BaseModel):
    """
    Conversation model
    """
    id: str
    episodes: list[Episode]