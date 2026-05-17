"""Mock NIM server — OpenAI-compatible API for testing without a real model."""

import time
import uuid
from fastapi import FastAPI
from pydantic import BaseModel
from typing import Any

app = FastAPI()

class ChatRequest(BaseModel):
    model: str = "mock-model"
    messages: list[dict[str, Any]] = []
    max_tokens: int = 256
    temperature: float = 0.7
    stream: bool = False

@app.get("/v1/health/ready")
async def health():
    return {"status": "ready"}

@app.get("/v1/models")
async def models():
    return {"object": "list", "data": [{"id": "mock-model", "object": "model"}]}

@app.post("/v1/chat/completions")
async def chat(req: ChatRequest):
    # Simulate ~100ms inference latency
    prompt = req.messages[-1]["content"] if req.messages else ""
    completion = f"Mock response to: {prompt[:50]}"
    return {
        "id": f"chatcmpl-{uuid.uuid4().hex[:8]}",
        "object": "chat.completion",
        "created": int(time.time()),
        "model": req.model,
        "choices": [{
            "index": 0,
            "message": {"role": "assistant", "content": completion},
            "finish_reason": "stop",
        }],
        "usage": {
            "prompt_tokens": len(prompt.split()),
            "completion_tokens": len(completion.split()),
            "total_tokens": len(prompt.split()) + len(completion.split()),
        },
    }

if __name__ == "__main__":
    import uvicorn
    uvicorn.run(app, host="0.0.0.0", port=8000)
