from typing import Dict, List, Optional, Set
from datetime import datetime
from threading import RLock
from ai.outshift.data_model import L9


class L9MessageCache:
    """Thread-safe cache for L9 messages organized by conversation and episode."""

    def __init__(self):
        self._lock = RLock()  # Reentrant lock for thread safety
        self._messages: Dict[str, L9] = {}  # msg_id → message
        self._timestamps: Dict[str, datetime] = {}  # msg_id → timestamp
        self._conversations: Dict[str, List[str]] = {}  # root_id → [msg_ids]
        self._msg_to_root: Dict[str, str] = {}  # msg_id → root_id
        self._episodes: Dict[str, Set[str]] = {}  # episode_id → set of msg_ids
        self._episode_to_conv: Dict[str, Set[str]] = {}  # episode_id → set of root_ids

    def add(self, msg: L9, timestamp: Optional[datetime] = None):
        """Add a message to the cache."""
        with self._lock:
            msg_id = msg.header.message.id
            episode_id = msg.header.message.episode

            # Store message
            self._messages[msg_id] = msg
            self._timestamps[msg_id] = timestamp or datetime.now()

            # Find root (walk up parents until we hit a message with no parents)
            root_id = self._find_root(msg)
            self._msg_to_root[msg_id] = root_id

            # Add to conversation
            if root_id not in self._conversations:
                self._conversations[root_id] = []
            self._conversations[root_id].append(msg_id)

            # Index by episode
            if episode_id not in self._episodes:
                self._episodes[episode_id] = set()
            self._episodes[episode_id].add(msg_id)

            # Track which conversations an episode belongs to
            if episode_id not in self._episode_to_conv:
                self._episode_to_conv[episode_id] = set()
            self._episode_to_conv[episode_id].add(root_id)

    def get(self, msg_id: str) -> Optional[L9]:
        """Get a single message."""
        with self._lock:
            return self._messages.get(msg_id)

    def get_conversation(self, msg_id: str) -> List[L9]:
        """Get all messages in the same conversation."""
        with self._lock:
            root_id = self._msg_to_root.get(msg_id)
            if not root_id:
                return []

            msg_ids = self._conversations.get(root_id, [])
            return [self._messages[mid] for mid in msg_ids if mid in self._messages]

    def get_last_n(self, msg_id: str, n: int) -> List[L9]:
        """Get last N messages from the same conversation."""
        with self._lock:
            root_id = self._msg_to_root.get(msg_id)
            if not root_id:
                return []

            msg_ids = self._conversations.get(root_id, [])[-n:]
            return [self._messages[mid] for mid in msg_ids if mid in self._messages]

    def get_episode(self, episode_id: str) -> List[L9]:
        """Get all messages in a specific episode."""
        with self._lock:
            msg_ids = self._episodes.get(episode_id, set())
            return [self._messages[mid] for mid in msg_ids if mid in self._messages]

    def get_episode_in_conversation(self, msg_id: str, episode_id: str) -> List[L9]:
        """Get messages in a specific episode within the same conversation."""
        with self._lock:
            root_id = self._msg_to_root.get(msg_id)
            if not root_id:
                return []

            # Get all messages in this episode
            episode_msg_ids = self._episodes.get(episode_id, set())

            # Filter to only those in the same conversation
            conv_msg_ids = set(self._conversations.get(root_id, []))
            filtered_ids = episode_msg_ids & conv_msg_ids

            return [self._messages[mid] for mid in filtered_ids if mid in self._messages]

    def get_last_n_in_episode(self, episode_id: str, n: int) -> List[L9]:
        """Get last N messages in a specific episode by timestamp."""
        with self._lock:
            msg_ids = self._episodes.get(episode_id, set())
            if not msg_ids:
                return []

            # Sort by timestamp
            sorted_ids = sorted(
                msg_ids,
                key=lambda mid: self._timestamps.get(mid, datetime.min)
            )

            return [self._messages[mid] for mid in sorted_ids[-n:] if mid in self._messages]

    def list_episodes(self) -> List[Dict]:
        """List all episodes with basic info."""
        with self._lock:
            result = []
            for episode_id, msg_ids in self._episodes.items():
                valid_ids = [mid for mid in msg_ids if mid in self._messages]
                if not valid_ids:
                    continue

                timestamps = [self._timestamps[mid] for mid in valid_ids if mid in self._timestamps]
                conv_roots = self._episode_to_conv.get(episode_id, set())

                result.append({
                    "episode_id": episode_id,
                    "message_count": len(valid_ids),
                    "conversation_count": len(conv_roots),
                    "started": min(timestamps) if timestamps else None,
                    "last_activity": max(timestamps) if timestamps else None,
                })

            return result

    def list_conversations(self) -> List[Dict]:
        """List all conversations with basic info."""
        with self._lock:
            result = []
            for root_id, msg_ids in self._conversations.items():
                valid_ids = [mid for mid in msg_ids if mid in self._messages]
                if not valid_ids:
                    continue

                timestamps = [self._timestamps[mid] for mid in valid_ids if mid in self._timestamps]

                # Get episodes in this conversation
                episodes = set()
                for mid in valid_ids:
                    msg = self._messages.get(mid)
                    if msg:
                        episodes.add(msg.header.message.episode)

                result.append({
                    "root_id": root_id,
                    "message_count": len(valid_ids),
                    "episode_count": len(episodes),
                    "episodes": list(episodes),
                    "started": min(timestamps) if timestamps else None,
                    "last_activity": max(timestamps) if timestamps else None,
                })

            return result

    def evict_conversation(self, root_id: str):
        """Remove entire conversation."""
        with self._lock:
            msg_ids = self._conversations.pop(root_id, [])
            for msg_id in msg_ids:
                msg = self._messages.get(msg_id)
                if msg:
                    episode_id = msg.header.message.episode

                    # Clean up episode index
                    if episode_id in self._episodes:
                        self._episodes[episode_id].discard(msg_id)
                        if not self._episodes[episode_id]:
                            self._episodes.pop(episode_id)

                    # Clean up episode-to-conversation mapping
                    if episode_id in self._episode_to_conv:
                        self._episode_to_conv[episode_id].discard(root_id)
                        if not self._episode_to_conv[episode_id]:
                            self._episode_to_conv.pop(episode_id)

                self._messages.pop(msg_id, None)
                self._timestamps.pop(msg_id, None)
                self._msg_to_root.pop(msg_id, None)

    def evict_episode(self, episode_id: str):
        """Remove all messages in a specific episode."""
        with self._lock:
            msg_ids = self._episodes.pop(episode_id, set())
            for msg_id in msg_ids:
                root_id = self._msg_to_root.get(msg_id)

                # Remove from conversation
                if root_id and root_id in self._conversations:
                    try:
                        self._conversations[root_id].remove(msg_id)
                        if not self._conversations[root_id]:
                            self._conversations.pop(root_id)
                    except ValueError:
                        pass

                self._messages.pop(msg_id, None)
                self._timestamps.pop(msg_id, None)
                self._msg_to_root.pop(msg_id, None)

            # Clean up episode-to-conversation mapping
            self._episode_to_conv.pop(episode_id, None)

    def evict_old_conversations(self, cutoff: datetime) -> int:
        """Remove conversations with no activity since cutoff."""
        with self._lock:
            to_evict = []
            for root_id, msg_ids in self._conversations.items():
                timestamps = [self._timestamps.get(mid) for mid in msg_ids if mid in self._timestamps]
                if timestamps and max(timestamps) < cutoff:
                    to_evict.append(root_id)

            for root_id in to_evict:
                self.evict_conversation(root_id)

            return len(to_evict)

    def _find_root(self, msg: L9) -> str:
        """Find root by walking up parent chain."""
        msg_id = msg.header.message.id

        # Already cached?
        if msg_id in self._msg_to_root:
            return self._msg_to_root[msg_id]

        # No parents = this is root
        if not msg.header.message.parents:
            return msg_id

        # Walk up first parent
        parent_id = msg.header.message.parents[0]
        parent_msg = self._messages.get(parent_id)

        if not parent_msg:
            return msg_id  # Parent missing, treat as root

        return self._find_root(parent_msg)

    def clear(self):
        """Clear everything."""
        with self._lock:
            self._messages.clear()
            self._timestamps.clear()
            self._conversations.clear()
            self._msg_to_root.clear()
            self._episodes.clear()
            self._episode_to_conv.clear()
