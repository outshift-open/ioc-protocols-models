from enum import Enum
from typing import Union
from pydantic import BaseModel
from ioc_l9.epistemic_state import EpistemicState

class RepresentationStateType(str, Enum):
    EPISTEMIC = "epistemic"

class RepresentationState(BaseModel):
    """
    RepresentationState model
    """
    type: RepresentationStateType = RepresentationStateType.EPISTEMIC
    state: Union[dict, EpistemicState] ## TODO we can make it more specific based on the type of representation state