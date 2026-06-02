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


class TaskWork(BaseModel):
    """
    TaskWork model
    """
    id: str
    assigned_to: str
    task_description: str
    status: str
    conversations: list[Conversation]


class Team(BaseModel):
    """
    Team model
    """
    id: str
    team_members: list[str]
    tasks: list[TaskWork]



if __name__ == "__main__":
    # Example usage
    message1 = Message(content="Hello, how can I assist you?")
    episode1 = Episode(id="episode1", messages=[message1])
    conversation1 = Conversation(id="conversation1", episodes=[episode1])
    task_work1 = TaskWork(id="task1", assigned_to="Alice", task_description="Assist with customer inquiry", status="In Progress", conversations=[conversation1])
    team1 = Team(id="team1", team_members=["Alice", "Bob"], tasks=[task_work1])
    
    print(team1.model_dump_json(indent=4))