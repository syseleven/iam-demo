import os
import shelve
from contextlib import asynccontextmanager
from datetime import datetime
from types import SimpleNamespace
from uuid import uuid4

import httpx
from dotenv import load_dotenv
from fastapi import Depends, FastAPI, Header, HTTPException
from pydantic import UUID4, BaseModel, Field
from typing_extensions import Annotated

ctx = None


@asynccontextmanager
async def lifespan(app: FastAPI):
    global ctx
    load_dotenv(verbose=True)
    ctx = SimpleNamespace(db=shelve.open("app"), store_id=os.getenv("OPENFGA_STORE_ID"))
    if not ctx.store_id:
        raise RuntimeError("OPENFGA_STORE_ID is not set")
    yield
    ctx.db.close()


app = FastAPI(lifespan=lifespan)


class SecretCreate(BaseModel):
    name: str = Field(None)
    value: str = Field(None)


class Secret(SecretCreate):
    id: UUID4 = Field(default_factory=uuid4)
    created_at: datetime = Field(default_factory=datetime.now)
    updated_at: datetime = Field(default_factory=datetime.now)


async def authenticate(user: Annotated[str, Header()] = None) -> str:
    if not user:
        raise HTTPException(status_code=401, detail="Unauthorized")
    return user


authed_id = Annotated[str, Depends(authenticate)]


@app.get("/me")
async def get_me(user: authed_id):
    return {"user": user}


@app.get("/projects/{project_id}/secrets")
async def get_secrets(user: authed_id, project_id: str):
    # Authorize request
    if not httpx.post(
        f"http://localhost:8080/stores/{ctx.store_id}/check",
        json={
            "tuple_key": {
                "user": f"user:{user}",
                "relation": "reader",
                "object": f"project:{project_id}",
            }
        },
    ).json()["allowed"]:
        raise HTTPException(status_code=403, detail="Forbidden")

    # Return secrets
    secrets = ctx.db.get(project_id, [])
    return secrets


@app.post("/projects/{project_id}/secret")
async def set_secret(user: authed_id, project_id: str, secret: SecretCreate):
    # Authorize request
    if not httpx.post(
        f"http://localhost:8080/stores/{ctx.store_id}/check",
        json={
            "tuple_key": {
                "user": f"user:{user}",
                "relation": "writer",
                "object": f"project:{project_id}",
            }
        },
    ).json()["allowed"]:
        raise HTTPException(status_code=403, detail="Forbidden")

    # Set secret
    secrets = ctx.db.get(project_id, [])
    secrets.append(Secret(**secret.model_dump()))
    ctx.db[project_id] = secrets
    return {"status": "success"}
