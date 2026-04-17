from fastapi import APIRouter

from app.core.prompt_profiles import PROFILE_DEFINITIONS

router = APIRouter(tags=["prompt-profiles"])


@router.get("/prompt-profiles")
def list_prompt_profiles() -> dict:
    return {"items": PROFILE_DEFINITIONS}

