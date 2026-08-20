import pandas as pd
from fastapi import FastAPI
from fastapi.exceptions import HTTPException
from pydantic import BaseModel

app = FastAPI()


class File(BaseModel):
    filename: str
    hashed_content: str


class FileBatch(BaseModel):
    files: list[File]


@app.post("/v1/")
def process(file_batch: FileBatch):
    try:
        print(file_batch)
        return {"received": file_batch}
    except Exception as e:
        return type(e)
