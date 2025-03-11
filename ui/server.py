from messaging_manager.libs.database_models import DraftResponse, UnifiedMessageFormat, ServiceMetadata
from sqlmodel import create_engine, Session, SQLModel, select
from fastapi.responses import FileResponse
from fastapi import FastAPI, Body
from pydantic import BaseModel
import uvicorn
import os

app = FastAPI()

web_dir = os.path.join(os.path.dirname(__file__), "web")

class ApproveRequest(BaseModel):
    response: str

@app.get("/media/{path:path}")
async def serve_media_file(path: str):
    return FileResponse("media/" + path)

@app.get("/draft_responses")
async def get_draft_responses():
    engine = create_engine("sqlite:///messages.db")
    with Session(engine) as session:
        draft_responses = session.exec(select(DraftResponse).where(DraftResponse.status == "pending")).all()
        return draft_responses


@app.post("/draft_responses/{draft_response_id}/approve")
async def approve_draft_response(draft_response_id: str, request: ApproveRequest):
    engine = create_engine("sqlite:///messages.db")
    with Session(engine) as session:
        draft_response = session.exec(select(DraftResponse).where(DraftResponse.draft_response_id == draft_response_id)).first()
        if draft_response:
            draft_response.status = "approved"
            draft_response.response = request.response
            session.add(draft_response)
            session.commit()
            return {"message": "Draft response approved", "success": True}
        return {"message": "Draft response not found", "success": False}
    
@app.post("/draft_responses/{draft_response_id}/ignore")
async def ignore_draft_response(draft_response_id: str):
    engine = create_engine("sqlite:///messages.db")
    with Session(engine) as session:
        draft_response = session.exec(select(DraftResponse).where(DraftResponse.draft_response_id == draft_response_id)).first()
        if draft_response:
            draft_response.status = "ignored"
            session.add(draft_response)
            session.commit()
            return {"message": "Draft response ignored", "success": True}
        return {"message": "Draft response not found", "success": False}

# serve files from the static web directory
@app.get("/")
async def serve_static_folder():
    return FileResponse(os.path.join(web_dir, "index.html"))

@app.get("/{path:path}")
async def serve_static_file(path: str):
    return FileResponse(os.path.join(web_dir, path))


# start the server to with cors on localhost:8000
if __name__ == "__main__":
    uvicorn.run(app, host="0.0.0.0", port=8000)