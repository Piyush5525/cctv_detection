"""EXPERIMENTAL action detectors (fall, violence, snatch) for the v2 event pipeline. See engine.py."""
from api.services.action_detectors.base import ActionDetector, ActionResult, PersonPose, PoseFrame  # noqa: F401
from api.services.action_detectors.engine import ACTION_NAMES, ActionEngine, build_detectors, model_lock  # noqa: F401

# detector name -> (incident category value, label shown to the operator)
CATEGORY_OF = {"fall": "fall", "violence": "assault", "snatch": "snatching"}
DISPLAY_OF = {"fall": "Fall", "violence": "Violence", "snatch": "Snatch"}
EXPERIMENTAL_CATEGORIES = frozenset(CATEGORY_OF.values())
