import time
from dataclasses import dataclass, field
from enum import Enum, auto
from typing import Any, Dict

class EventType(Enum):
    BUZZ = auto()
    TTS_STOPPED = auto()
    SPEECH_RECOGNIZED = auto()
    KEYWORD_DETECTED = auto()
    EVALUATION_COMPLETE = auto()
    STATE_CHANGED = auto()
    SCORE_UPDATED = auto()
    TIMEOUT = auto()
    UPDATE_SCORE = auto()
    BUZZ_EVALUATED = auto()
    PENALTY_APPLIED = auto()
    BLURT_DETECTED = auto()
    QUESTION_STARTED = auto()
    BONUS_STARTED = auto()
    BONUS_ANSWER_LOCKED = auto()
    TOSSUP_RESULT = auto()
    BONUS_RESULT = auto()
    
    # --- ADDED TO FIX TRACEBACK ---
    READING_DONE = auto() 

@dataclass
class Event:
    type: EventType | str # Allow string types for dynamic frontend events
    timestamp: float = field(default_factory=time.time)
    payload: Dict[str, Any] = field(default_factory=dict)