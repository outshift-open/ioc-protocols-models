from __future__ import annotations

from typing import Any, Dict


class LLMClient:
    def complete_json(self, _task: str, _payload: Dict[str, Any]) -> Dict[str, Any]:
        raise NotImplementedError()
