# L9 Message Cache

A thread-safe, conversation and episode-aware cache for L9 protocol messages.

## Design

The cache organizes messages by **conversation** and **episode**:

- **Conversation**: All messages that share the same root (a message with `parents = []`)
- **Episode**: A logical phase within or across conversations (explicit field in L9 header)

Messages are linked through their `parents` field, forming a directed acyclic graph (DAG).

### Features:

- **Thread-safe**: All operations protected by reentrant lock (RLock)
- **Dual indexing**: Query by conversation OR episode
- **Timestamp tracking**: Find recent messages, evict by age
- **Cross-episode conversations**: One conversation can span multiple episodes
- **Episode spanning conversations**: One episode can appear in multiple conversations

## Usage

### Basic operations

```python
from SSTP.examples.cache import L9MessageCache

cache = L9MessageCache()

# Add messages (timestamp is optional, defaults to now)
cache.add(msg1)
cache.add(msg2)
cache.add(msg3)

# Get a single message
msg = cache.get("msg_id")

# Get entire conversation
conversation = cache.get_conversation("msg_id")

# Get last N messages from the same conversation
recent = cache.get_last_n("msg_id", n=5)
```

### Episode queries

```python
# Get all messages in an episode
episode_msgs = cache.get_episode("ep1")

# Get messages in a specific episode within a conversation
msgs = cache.get_episode_in_conversation("msg_id", "ep2")

# Get last N messages in an episode (by timestamp)
recent_in_episode = cache.get_last_n_in_episode("ep1", n=3)

# List all episodes
for ep in cache.list_episodes():
    print(f"Episode {ep['episode_id']}:")
    print(f"  Messages: {ep['message_count']}")
    print(f"  Conversations: {ep['conversation_count']}")
    print(f"  Last activity: {ep['last_activity']}")
```

### List all conversations

```python
for conv in cache.list_conversations():
    print(f"Conversation {conv['root_id']}:")
    print(f"  Messages: {conv['message_count']}")
    print(f"  Episodes: {conv['episodes']}")
    print(f"  Started: {conv['started']}")
    print(f"  Last activity: {conv['last_activity']}")
```

### Eviction

```python
from datetime import datetime, timedelta

# Remove specific conversation
cache.evict_conversation(root_id="msg1")

# Remove specific episode
cache.evict_episode(episode_id="ep1")

# Remove old conversations (returns count of evicted conversations)
cutoff = datetime.now() - timedelta(hours=1)
evicted_count = cache.evict_old_conversations(cutoff)

# Clear everything
cache.clear()
```

## Example

```python
from ai.outshift.data_model import L9, L9Header, Message, Kind, L9Payload, Actor, ParticipantSet
from SSTP.examples.cache import L9MessageCache

cache = L9MessageCache()

# Conversation 1: Alice ↔ Bob
msg1 = L9(
    header=L9Header(
        protocol="SSTP",
        subprotocol="SAB",
        version="1.0",
        kind=Kind.intent,
        subkind="",
        message=Message(id="msg1", parents=[], episode="ep1"),
        participants=ParticipantSet(actors=[Actor(id="alice", role="buyer")], groups={}),
    ),
    payload=L9Payload(type="text", data={"content": "Need supplies"})
)

msg2 = L9(
    header=L9Header(
        protocol="SSTP",
        subprotocol="SAB",
        version="1.0",
        kind=Kind.response,
        subkind="",
        message=Message(id="msg2", parents=["msg1"], episode="ep1"),
        participants=ParticipantSet(
            actors=[Actor(id="alice", role="buyer"), Actor(id="bob", role="seller")],
            groups={}
        ),
    ),
    payload=L9Payload(type="text", data={"content": "What do you need?"})
)

msg3 = L9(
    header=L9Header(
        protocol="SSTP",
        subprotocol="SAB",
        version="1.0",
        kind=Kind.intent,
        subkind="",
        message=Message(id="msg3", parents=["msg2"], episode="ep2"),  # New episode!
        participants=ParticipantSet(
            actors=[Actor(id="alice", role="buyer"), Actor(id="bob", role="seller")],
            groups={}
        ),
    ),
    payload=L9Payload(type="text", data={"content": "100 units of steel"})
)

# Add messages
cache.add(msg1)
cache.add(msg2)
cache.add(msg3)

# Get entire conversation (returns all 3 messages)
conversation = cache.get_conversation("msg3")
print(f"Conversation has {len(conversation)} messages")

# Get last 2 messages
recent = cache.get_last_n("msg3", 2)
print(f"Last 2: {[m.header.message.id for m in recent]}")  # ['msg2', 'msg3']
```

## Implementation details

### Data structures

```python
_lock: RLock                                    # Thread safety lock
_messages: Dict[str, L9]                        # msg_id → message object
_timestamps: Dict[str, datetime]                # msg_id → insertion timestamp
_conversations: Dict[str, List[str]]            # root_id → [msg_ids in order]
_msg_to_root: Dict[str, str]                    # msg_id → root_id (cache)
_episodes: Dict[str, Set[str]]                  # episode_id → set of msg_ids
_episode_to_conv: Dict[str, Set[str]]           # episode_id → set of root_ids
```

### Thread safety

All public methods acquire a reentrant lock (`RLock`), making the cache safe for concurrent access from multiple threads. The lock is reentrant to allow internal method calls without deadlock.

### Root finding

The cache walks up the parent chain to find the root:

```
msg3.parents = ["msg2"]
  → msg2.parents = ["msg1"]
    → msg1.parents = []  ← This is the root!
```

All three messages belong to the same conversation (root = `msg1`), even though `msg3` is in a different episode.

### Conversation separation

Messages belong to **different conversations** if they have **different roots**:

```
Conversation 1 (root=msg1): msg1 → msg2 → msg3
Conversation 2 (root=msg10): msg10 → msg11
```

Querying `cache.get_conversation("msg2")` returns only `[msg1, msg2, msg3]`, never mixing in messages from conversation 2.

### Episode spanning

Episodes can span conversations, and conversations can span episodes:

```
Episode ep1:
  - msg1 (conv1, ep1)
  - msg2 (conv1, ep1)
  - msg10 (conv2, ep1)  # Different conversation, same episode

Episode ep2:
  - msg3 (conv1, ep2)  # Same conversation, new episode
```

This allows querying:
- "All messages in episode ep1" → returns msg1, msg2, msg10 (cross-conversation)
- "All messages in episode ep1 within conv1" → returns msg1, msg2 only

## Limitations

1. **Only follows first parent**: If a message has multiple parents, only `parents[0]` is used for root finding
2. **No participant indexing**: Can't query "show me all messages from agent Alice"
3. **No content search**: Can't search by SIEP concepts or payload data
4. **In-memory only**: No persistence, data lost on restart
5. **No size limits**: Cache grows forever without manual eviction
