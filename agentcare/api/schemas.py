from pydantic import BaseModel
from typing import Optional


class ManagerActionRequest(BaseModel):
    action_type: str
    target_type: str
    target_id: int
    comment: Optional[str] = None