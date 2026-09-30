from fastapi import FastAPI, HTTPException, Request
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import JSONResponse
from pydantic import BaseModel

from agentcare.api.routes import router
from agentcare.auth import authenticate, is_valid_token


class LoginRequest(BaseModel):
    username: str
    password: str


app = FastAPI(
    title="AgentCare AI API",
    description="Hospital Operations Monitoring and Decision Support API",
    version="1.0.0",
)


# ============================================================
# CORS
# ============================================================

app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)


# ============================================================
# ROUTES
# ============================================================

app.include_router(router)


@app.post("/api/auth/login")
def login(request: LoginRequest):
    token = authenticate(request.username, request.password)
    if token is None:
        raise HTTPException(status_code=401, detail="Invalid username or password")
    return {"access_token": token, "token_type": "bearer"}


@app.middleware("http")
async def require_dashboard_login(request: Request, call_next):
    # Let CORS preflight requests through untouched — they carry no
    # Authorization header by design, and must reach CORSMiddleware to
    # get a valid preflight response. Blocking them here (with a 401 that
    # has no CORS headers) causes the browser to reject every real
    # request that follows as a CORS failure, even with a valid token.
    if request.method == "OPTIONS":
        return await call_next(request)

    if request.url.path.startswith("/api/") and request.url.path != "/api/auth/login":
        authorization = request.headers.get("Authorization", "")
        scheme, _, token = authorization.partition(" ")
        if scheme.lower() != "bearer" or not is_valid_token(token):
            return JSONResponse(
                status_code=401,
                content={"detail": "Authentication required"},
            )
    return await call_next(request)


# ============================================================
# HEALTH CHECK
# ============================================================

@app.get("/")
def root():
    return {
        "system": "AgentCare AI",
        "status": "RUNNING",
        "message": "Backend API is working"
    }


@app.get("/health")
def health():
    return {
        "status": "healthy"
    }