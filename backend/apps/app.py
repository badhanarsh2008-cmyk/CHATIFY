from pathlib import Path

from fastapi import FastAPI,Request
from fastapi.responses import HTMLResponse
from fastapi.staticfiles import StaticFiles
from fastapi.templating import Jinja2Templates

PROJECT_DIR = Path(__file__).resolve().parents[2]
FRONTEND_DIR = PROJECT_DIR / "frontend"
TEMPLATES_DIR = FRONTEND_DIR / "templates"

app = FastAPI(title="Chatify")

app.mount(
    "/CHATIFY/frontend",
    StaticFiles(directory=FRONTEND_DIR),
    name="frontend",
)
templates = Jinja2Templates(directory=str(TEMPLATES_DIR))

@app.get("/", response_class=HTMLResponse)
async def landing_page(request : Request):
    return templates.TemplateResponse(
        request=request,
        name="landing_page.html",
        context={},
    )

@app.get("/register", response_class=HTMLResponse)
@app.get("/signup", response_class=HTMLResponse, include_in_schema=False)
async def signup(request : Request):
    return templates.TemplateResponse(
        request=request,
        name="signup.html",
        context={},
    )


@app.get("/login", response_class=HTMLResponse)
@app.get("/signin", response_class=HTMLResponse, include_in_schema=False)
async def signin(request: Request):
    return templates.TemplateResponse(
        request=request,
        name="signin.html",
        context={},
    )

