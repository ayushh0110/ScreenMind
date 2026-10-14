"""Bookmark routes — toggle and list bookmarks."""

from fastapi import APIRouter, Query

from screenmind.api.dependencies import db
from screenmind.api.serializers import add_display_fields

router = APIRouter(prefix="/api", tags=["bookmarks"])


@router.put("/activities/{activity_id}/bookmark")
async def toggle_bookmark(activity_id: int):
    """Toggle bookmark status."""
    new_state = db.toggle_bookmark(activity_id)
    return {"bookmarked": new_state, "activity_id": activity_id}


@router.get("/bookmarks")
async def get_bookmarks(limit: int = Query(default=50, ge=1, le=200)):
    bookmarks = db.get_bookmarks(limit=limit)
    for b in bookmarks:
        add_display_fields(b)
    return {"bookmarks": bookmarks}
