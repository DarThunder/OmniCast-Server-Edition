from contextlib import asynccontextmanager
import mimetypes
import os
from fastapi import FastAPI, HTTPException, Request, BackgroundTasks
from fastapi.responses import FileResponse
from fastapi.responses import StreamingResponse
from fastapi.responses import Response
from src.helpers.utils import get_video_file, get_thumbnail_file, get_all_videos
from src.helpers.fetcher import download_video
from src.helpers.shrieker import omni_shrieker
import aiofiles
import asyncio

@asynccontextmanager
async def lifespan(app: FastAPI):
    omni_shrieker.start()
    yield
    omni_shrieker.stop()

app = FastAPI(lifespan=lifespan)

@app.get("/health")
def live():
    return {"message": "Hola pim"}

@app.get("/videos")
def list_videos():
    return {"videos": get_all_videos()}

@app.get("/thumbnail/{hash}")
def get_thumbnail_route(hash: str):
    thumb_path = get_thumbnail_file(hash)
    if not thumb_path:
        raise HTTPException(status_code=404, detail="Miniatura no encontrada")
    return FileResponse(thumb_path)

@app.get("/video/{hash}")
async def get_video_route(hash: str, request: Request):
    video_path = get_video_file(hash)
    if not video_path:
        raise HTTPException(status_code=404, detail="Video no encontrado")
    
    file_size = os.path.getsize(video_path)
    range_header = request.headers.get("Range")
    
    mime_type, _ = mimetypes.guess_type(video_path)
    mime_type = mime_type or "video/mp4"
    
    if range_header and range_header.startswith("bytes="):
        range_val = range_header.replace("bytes=", "").strip()
        
        if range_val.startswith("-"):
            suffix_len = int(range_val[1:])
            start = max(0, file_size - suffix_len)
            end = file_size - 1
        else:
            start_str, end_str = range_val.split("-", 1)
            start = int(start_str)
            end = int(end_str) if end_str else file_size - 1
            
        end = min(end, file_size - 1)
        
        if start >= file_size or start > end:
            return Response(
                status_code=416,
                headers={"Content-Range": f"bytes */{file_size}"}
            )
            
        chunk_size = end - start + 1
        
        async def stream_partial():
            async with aiofiles.open(video_path, "rb") as f:
                await f.seek(start)
                remaining = chunk_size
                while remaining > 0:
                    if await request.is_disconnected():
                        break
                    chunk = await f.read(256 * 1024)
                    if not chunk:
                        break
                    remaining -= len(chunk)
                    yield chunk
                    
        return StreamingResponse(
            stream_partial(),
            status_code=206,
            media_type=mime_type,
            headers={
                "Content-Range": f"bytes {start}-{end}/{file_size}",
                "Accept-Ranges": "bytes",
                "Content-Length": str(chunk_size),
                "Connection": "keep-alive",  
                "Cache-Control": "no-store",
            }
        )

    async def stream_full():
            async with aiofiles.open(video_path, "rb") as f:
                while chunk := await f.read(1024 * 1024):
                    if await request.is_disconnected():
                        break
                    yield chunk
                
    return StreamingResponse(
        stream_full(),
        media_type=mime_type,
        headers={
            "Accept-Ranges": "bytes",
            "Content-Length": str(file_size),
        }
    )

@app.post("/videos")
def set_video_route(url: str, background_tasks: BackgroundTasks):
    background_tasks.add_task(download_video, url)
    return {"Message": "¡Descarga iniciada en segundo plano! Estará lista pronto."}

@app.get("/debug/tasks")
async def debug_tasks():
    tasks = asyncio.all_tasks()
    return {
        "total": len(tasks),
        "tasks": [str(t) for t in tasks]
    }