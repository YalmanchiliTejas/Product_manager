"""Projects router — full CRUD for project records."""

from fastapi import APIRouter, HTTPException

from backend.db.supabase_client import get_supabase
from backend.schemas.models import ProjectCreate, ProjectResponse, ProjectUpdate

router = APIRouter(prefix="/api/projects", tags=["projects"])


@router.get(
    "",
    response_model=list[ProjectResponse],
    summary="List all projects (optionally filtered by user_id)",
)
def list_projects(user_id: str | None = None) -> list[ProjectResponse]:
    db = get_supabase()
    q = db.table("projects").select("*").order("created_at", desc=True)
    if user_id:
        q = q.eq("user_id", user_id)
    result = q.execute()
    return result.data or []


@router.post(
    "",
    response_model=ProjectResponse,
    status_code=201,
    summary="Create a new project",
)
def create_project(body: ProjectCreate) -> ProjectResponse:
    db = get_supabase()
    try:
        result = (
            db.table("projects")
            .insert(
                {
                    "user_id": body.user_id,
                    "name": body.name,
                    "description": body.description,
                }
            )
            .execute()
        )
    except Exception as exc:
        raise HTTPException(status_code=500, detail=str(exc)) from exc
    return result.data[0]


@router.get(
    "/{project_id}",
    response_model=ProjectResponse,
    summary="Get a single project by ID",
)
def get_project(project_id: str) -> ProjectResponse:
    db = get_supabase()
    result = db.table("projects").select("*").eq("id", project_id).execute()
    if not result.data:
        raise HTTPException(status_code=404, detail="Project not found")
    return result.data[0]


@router.patch(
    "/{project_id}",
    response_model=ProjectResponse,
    summary="Update a project's name or description",
)
def update_project(project_id: str, body: ProjectUpdate) -> ProjectResponse:
    updates = body.model_dump(exclude_none=True)
    if not updates:
        raise HTTPException(status_code=400, detail="No fields provided to update")
    db = get_supabase()
    result = db.table("projects").update(updates).eq("id", project_id).execute()
    if not result.data:
        raise HTTPException(status_code=404, detail="Project not found")
    return result.data[0]


@router.delete(
    "/{project_id}",
    status_code=204,
    summary="Delete a project and all its cascading data",
)
def delete_project(project_id: str) -> None:
    db = get_supabase()
    db.table("projects").delete().eq("id", project_id).execute()
