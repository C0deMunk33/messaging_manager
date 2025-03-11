from messaging_manager.libs.database_models import DraftResponse, UnifiedMessageFormat, ServiceMetadata
from sqlmodel import create_engine, Session, SQLModel, select
from fastapi.responses import FileResponse
from fastapi import FastAPI, Body
from pydantic import BaseModel
import uvicorn
import os
import asyncio
import threading
from messaging_manager.run import get_loop_manager, run_continuous_loop, LoopManager

app = FastAPI()

web_dir = os.path.join(os.path.dirname(__file__), "web")
loop_manager = get_loop_manager()

# Start the background processing loop
def start_background_loop():
    loop = asyncio.new_event_loop()
    asyncio.set_event_loop(loop)
    loop.run_until_complete(run_continuous_loop(interval_seconds=300))

# Start the background thread when the server starts
background_thread = threading.Thread(target=start_background_loop, daemon=True)
background_thread.start()

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
    # Send the response through the appropriate service
    result = await loop_manager.send_approved_response(draft_response_id, request.response)
    
    if result["success"]:
        return {"message": "Draft response approved and sent", "success": True}
    else:
        return {"message": result["message"], "success": False}
    
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

# Add endpoint to manually trigger message processing
@app.post("/process_messages")
async def process_messages():
    try:
        await loop_manager.pull_latest_messages()
        await loop_manager.process_messages()
        return {"message": "Messages processed successfully", "success": True}
    except Exception as e:
        return {"message": f"Error processing messages: {str(e)}", "success": False}

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