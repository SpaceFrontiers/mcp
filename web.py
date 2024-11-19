from fastapi import FastAPI
from mcp_server import mcp

app = FastAPI()
app.mount("/", mcp.sse_app())
