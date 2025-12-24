import os
import re
import sys
import time
import json
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
# NEED FIXING: currently does not work as intended
# I think we should just split this into multipl variables instead, and keep the cls static (not touching the cls'ed text)
# def update_cls_text(comp, tool_name, new_text):
#     tool = comp.FindTool(tool_name)
#     if not tool:
#         print(f"Warning: Tool '{tool_name}' not found.")
#         return

#     matches = re.finditer(r"(\d+\.?\d*)(pts\*?)", new_text)
    
#     lua_entries = []
    
#     for match in matches:
#         n_start, n_end = match.start(1), match.end(1) - 1
#         u_start, u_end = match.start(2), match.end(2) - 1
        
#         lua_entries.append(f"{{ 102, {n_start}, {n_end}, Value = 0.094 }}")
#         lua_entries.append(f"{{ 102, {u_start}, {u_end}, Value = 0.067 }}")
#         lua_entries.append(f"{{ 1100, {u_start}, {u_end}, Value = 0.937 }}")

#     styling_array_str = "{" + ",".join(lua_entries) + "}"
#     sanitized_text = new_text.replace("\n", "\\n")
#     lua_script = f'''
#         obj = comp:FindTool("{tool_name}")
#         if obj then
#             obj.StyledText:Disconnect()
#             obj.StyledText = StyledText {{
#                 Array = {styling_array_str},
#                 Value = "{sanitized_text}"
#             }}
#         end
#         '''
    
#     comp.Execute(lua_script)

# ================== ROUTES ==================
@app.post("/render")
def render(body: dict, x_api_key: str = Header(None)):
    auth(x_api_key)

    project = connect_project(body)
    timeline = ensure_timeline(project, body)

    items = timeline.GetItemListInTrack("video", 1)
    if not items:
        raise HTTPException(400, "no_clips_on_v1")

    item = items[0]

    # Find way to make this insta-load the project comp, without having to import every time
    # ---------- FUSION COMP IMPORT ----------
    comp_path = body.get("comp_path")
    if comp_path:
        fusion_comp = item.ImportFusionComp(comp_path)
        if not fusion_comp:
            raise HTTPException(500, "fusion_comp_import_failed")

    # ---------- VARIABLES ----------
    if "text_desc" in body:
        t = fusion_comp.FindTool("VAR_TextMediaDesc")
        if t:
            t["StyledText"] = str(body["text_desc"])

    if "text_rw" in body:
        t_rw = fusion_comp.FindTool("VAR_RW")
        if t_rw:
            t_rw["StyledText"] = str(body["text_rw"])

    if "text_slick" in body:
        t_front = fusion_comp.FindTool("VAR_Text1B")
        if t_front:
            t_front["StyledText"] = str(body["text_slick"])
        t_back = fusion_comp.FindTool("VAR_Text1")
        if t_back:
            t_back["StyledText"] = str(body["text_slick"])

    if "text_trade" in body:
        t_trade = fusion_comp.FindTool("VAR_Text2B")
        if t_trade:
            t_trade["StyledText"] = str(body["text_trade"])
        t_trade = fusion_comp.FindTool("VAR_Text2")
        if t_trade:
            t_trade["StyledText"] = str(body["text_trade"])

    if "text_tagline" in body:
        t_tagline = fusion_comp.FindTool("VAR_TextTaglineB")
        if t_tagline:
            t_tagline["StyledText"] = str(body["text_tagline"])
        t_tagline = fusion_comp.FindTool("VAR_TextTagline")
        if t_tagline:
            t_tagline["StyledText"] = str(body["text_tagline"])
    
    if "text_button" in body:
        t_button = fusion_comp.FindTool("VAR_TextButton")
        if t_button:
            t_button["StyledText"] = str(body["text_button"])
    
    if "text_end" in body:
        t_end = fusion_comp.FindTool("VAR_TextEnd")
        if t_end:
            t_end["StyledText"] = str(body["text_end"])

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

        # Try to relink for other media (e.g. logo, phone, and even font)
        media_item = find_media(root, "Bg_Media_4K.mp4")
        if not media_item:
            raise HTTPException(500, "media_pool_item_not_found")

        if not mp.RelinkClips([media_item], "C:/resolve_presets"):
            raise HTTPException(500, "media_relink_failed")

    # ---------- RENDER ----------
    project.LoadRenderPreset("test-sanity-preset")
    render_settings = {
        "SelectAllFrames": True,
        "TargetDir": body.get("output_dir", "C:/resolve_renders"),
        "CustomName": body.get("text_output", project.GetName()),
        "ExportVideo": True,
        "ExportAudio": True
    }

    if not project.SetRenderSettings(render_settings):
        raise HTTPException(500, "failed_to_apply_render_settings")

    project.SetRenderSettings({"FilenameMode": 1})
    project.SetCurrentTimeline(timeline)

    project.DeleteAllRenderJobs()
    job_id = project.AddRenderJob()
    project.StartRendering([job_id])

    return {
        "status": "render_started",
        "project": project.GetName(),
        "job_id": job_id
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