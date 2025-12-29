import os
import re
import sys
import time
import json
import uuid
import shutil
from dotenv import load_dotenv
import DaVinciResolveScript as dvr

from fastapi import FastAPI, Header, HTTPException # pyright: ignore[reportMissingImports]
import uvicorn # pyright: ignore[reportMissingImports]

from BucketHandler import download_media, upload_file 

# ================== INIT ==================
load_dotenv()

HOST = "0.0.0.0"
PORT = 5080
API_KEY = os.getenv("API_KEY")

if not API_KEY:
    raise RuntimeError("API_KEY not found in environment")

app = FastAPI(title="Resolve HTTP Gateway")

# ================== AUTH ==================
def auth(x_api_key: str | None):
    if x_api_key != API_KEY:
        raise HTTPException(401, "unauthorized")

# ================== RESOLVE HELPERS ==================
def connect_project(body: dict):
    resolve = dvr.scriptapp("Resolve")
    if not resolve:
        raise HTTPException(400, "resolve_not_running")

    resolve.OpenPage("deliver")
    pm = resolve.GetProjectManager()

    project_name = body.get("project_name")
    project = pm.LoadProject(project_name) if project_name else pm.GetCurrentProject()

    if not project:
        raise HTTPException(400, "project_not_found")

    return project

def ensure_timeline(project, body: dict):
    timeline = project.GetCurrentTimeline()
    if timeline:
        return timeline

    timeline_name = body.get("timeline_name")
    if timeline_name:
        timeline = project.GetTimelineByName(timeline_name)
        if not timeline:
            raise HTTPException(400, "timeline_not_found")
        project.SetCurrentTimeline(timeline)
        return timeline

    timelines = project.GetTimelineList()
    if not timelines:
        raise HTTPException(400, "no_timelines_in_project")

    project.SetCurrentTimeline(timelines[0])
    return timelines[0]

# apply dynamic character level styling for trade text
# NEED MORE WORK: text_end has not yet been implemented
def build_trailing_cls_array(text: str) -> str:
    txt = text.rstrip()
    length = len(txt)

    if length < 8:
        raise ValueError("text_trade must be at least 8 characters")

    s1, e1 = length - 8, length - 5
    s2, e2 = length - 4, length - 1

    return (
        f"{{ 102, {s1}, {e1}, Value = 0.094 }},\n"
        f"{{ 102, {s2}, {e2}, Value = 0.067 }},\n"
        f"{{ 1100, {s2}, {e2}, Value = 0.937 }}"
    )

def lua_string(text: str) -> str:
    # Safe for Fusion/Lua
    return "[[" + text.replace("]]", "] ]") + "]]"

def make_temp_comp(base_comp_path: str, body: dict) -> str:
    job_id = uuid.uuid4().hex
    tmp_dir = os.path.join(os.path.dirname(base_comp_path), "tmp")
    os.makedirs(tmp_dir, exist_ok=True)

    tmp_comp_path = os.path.join(tmp_dir, f"trade_{job_id}.comp")
    shutil.copyfile(base_comp_path, tmp_comp_path)

    with open(tmp_comp_path, "r", encoding="utf-8") as f:
        comp_text = f.read()

    if "text_trade" in body:
        trade_text = body["text_trade"].rstrip()
        cls_array = build_trailing_cls_array(trade_text)

        comp_text = comp_text.replace("__TRADE_TEXT__", lua_string(trade_text))
        comp_text = comp_text.replace("__CLS_ARRAY__", cls_array)

    with open(tmp_comp_path, "w", encoding="utf-8") as f:
        f.write(comp_text)

    return tmp_comp_path

def apply_fusion_variables(fusion_comp, body: dict, project):
    # ---------- TEXT VARIABLES ----------
    def set_text(tool_name, key):
        if key in body:
            t = fusion_comp.FindTool(tool_name)
            if t:
                t["StyledText"] = str(body[key])

    set_text("VAR_TextMediaDesc", "text_desc")
    set_text("VAR_RW", "text_rw")

    if "text_slick" in body:
        for name in ("VAR_Text1B", "VAR_Text1"):
            t = fusion_comp.FindTool(name)
            if t:
                t["StyledText"] = str(body["text_slick"])

    if "text_tagline" in body:
        for name in ("VAR_TextTaglineB", "VAR_TextTagline"):
            t = fusion_comp.FindTool(name)
            if t:
                t["StyledText"] = str(body["text_tagline"])

    if "text_button" in body:
        set_text("VAR_TextButton", "text_button")

    if "text_end" in body:
        set_text("VAR_TextEnd", "text_end")

    # ---------- MEDIA ----------
    if "media_url" in body:
        download_media(body["media_url"])

        mp = project.GetMediaPool()
        root = mp.GetRootFolder()

        def find_media(folder, name):
            for clip in folder.GetClipList():
                if clip.GetName() == name:
                    return clip
            for sub in folder.GetSubFolderList():
                found = find_media(sub, name)
                if found:
                    return found
            return None

        media_item = find_media(root, "Bg_Media_4K.mp4")
        if not media_item:
            raise HTTPException(500, "media_pool_item_not_found")

        if not mp.RelinkClips([media_item], "C:/resolve_presets"):
            raise HTTPException(500, "media_relink_failed")

def start_render(project, timeline, body: dict):
    project.LoadRenderPreset("test-sanity-preset")

    render_settings = {
        "SelectAllFrames": True,
        "TargetDir": body.get("output_dir", "C:/resolve_renders"),
        "CustomName": body.get("text_output", project.GetName()),
        "ExportVideo": True,
        "ExportAudio": True,
        "FilenameMode": 1,
    }

    if not project.SetRenderSettings(render_settings):
        raise HTTPException(500, "failed_to_apply_render_settings")

    project.SetCurrentTimeline(timeline)

    project.DeleteAllRenderJobs()
    job_id = project.AddRenderJob()
    project.StartRendering([job_id])

    return job_id

# ================== ROUTES ==================
@app.post("/render")
def render(body: dict, x_api_key: str = Header(None)):
    auth(x_api_key)

    resolve = dvr.scriptapp("Resolve")
    if not resolve:
        raise HTTPException(400, "resolve_not_running")

    project = connect_project(body)
    timeline = ensure_timeline(project, body)

    items = timeline.GetItemListInTrack("video", 1)
    item = items[0] if items else None
    if not items:
        raise HTTPException(400, "no_clips_on_v1")

    base_comp = body.get("comp_path")
    if not base_comp or not os.path.isfile(base_comp):
        raise HTTPException(400, "invalid_comp_path")

    resolve.OpenPage("fusion")
    time.sleep(0.5)

    tmp_comp = make_temp_comp(base_comp, body)
    if not os.path.isfile(tmp_comp):
        raise HTTPException(500, "temp_comp_missing")

    fusion_comp = item.ImportFusionComp(tmp_comp)
    if not fusion_comp:
        raise HTTPException(500, "fusion_comp_import_failed")

    apply_fusion_variables(fusion_comp, body, project)
    job_id = start_render(project, timeline, body)

    return {
        "status": "render_started",
        "project": project.GetName(),
        "job_id": job_id,
        "temp_comp": tmp_comp
    }

@app.post("/render/status")
def render_status(body: dict, x_api_key: str = Header(None)):
    auth(x_api_key)

    project = connect_project(body)
    job_id = body.get("job_id")

    response = {
        "rendering": project.IsRenderingInProgress()
    }

    if job_id:
        status = project.GetRenderJobStatus(job_id)
        if not status:
            raise HTTPException(404, "job_not_found")
        response["job"] = status

    return response

@app.post("/render/upload")
def render_upload(body: dict, x_api_key: str = Header(None)):
    auth(x_api_key)

    output_dir = body.get("output_dir", "C:/resolve_renders")
    output_name = body.get("text_output")

    if not output_name:
        raise HTTPException(status_code=400, detail="output_name_required")

    drive_folder_id = os.getenv("GDRIVE_RENDER_FOLDER_ID")
    service_account_json = os.getenv("GOOGLE_SERVICE_ACCOUNT_JSON")

    if not drive_folder_id or not service_account_json:
        raise HTTPException(
            status_code=500,
            detail="gdrive_env_not_configured"
        )

    filepath = os.path.join(output_dir, f"{output_name}.mp4")
    if not os.path.exists(filepath):
        raise HTTPException(status_code=404, detail="rendered_file_not_found")

    try:
        result = upload_file(
            file_path=filepath,
            drive_folder_id=drive_folder_id
        )
    except Exception as e:
        raise HTTPException(status_code=500, detail=f"upload_failed: {str(e)}")

    return {
        "status": "upload_successful",
        "file_id": result["id"],
        "file_name": result["name"],
        "drive_url": f"https://drive.google.com/file/d/{result['id']}/view"
    }

# ================== ENTRY ==================
if __name__ == "__main__":
    uvicorn.run("Gateway:app", host=HOST, port=PORT)