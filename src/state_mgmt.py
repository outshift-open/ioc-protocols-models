# Copyright 2026 Cisco Systems, Inc. and its affiliates
#
# SPDX-License-Identifier: Apache-2.0

"""
State management models for tracking work across teams, tasks, and conversations.

Hierarchy:
  Team
  └── TaskWork        (one or more tasks assigned to team members)
      └── Episode     (one or more conversation episodes per task)
          └── Message (one or more messages per episode)
"""

from pydantic import BaseModel


class Message(BaseModel):
    """
    A single message within a conversation episode.
    """
    content: str   # the text or structured content of the message


class Episode(BaseModel):
    """
    A discrete conversation or interaction sequence tied to a task.
    An episode groups the messages exchanged during one focused interaction
    (e.g. one round of clarification, one tool invocation cycle).
    """
    id: str                  # unique episode identifier
    messages: list[Message]  # ordered sequence of messages in this episode


class TaskWork(BaseModel):
    """
    A unit of work assigned to a team member, tracked through one or more episodes.
    Status lifecycle example: "pending" → "in_progress" → "completed" | "blocked"
    """
    id: str                    # unique task identifier
    assigned_to: str           # name or ID of the agent/human responsible
    task_description: str      # human-readable description of what needs to be done
    status: str                # current task status: "pending" | "in_progress" | "completed" | "blocked"
    episodes: list[Episode]    # conversation episodes associated with this task


class Team(BaseModel):
    """
    A group of agents and/or humans collaborating on a shared set of tasks.
    """
    id: str                    # unique team identifier
    team_members: list[str]    # IDs or names of agents/humans on this team
    tasks: list[TaskWork]      # all tasks assigned within this team


if __name__ == "__main__":
    # Example usage
    message1 = Message(content="Hello, how can I assist you?")
    episode1 = Episode(id="episode1", messages=[message1])
    task_work1 = TaskWork(id="task1", assigned_to="Alice", task_description="Assist with customer inquiry", status="In Progress", episodes=[episode1])
    team1 = Team(id="team1", team_members=["Alice", "Bob"], tasks=[task_work1])

    print(team1.model_dump_json(indent=4))