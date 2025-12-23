# main.py
import uvicorn # type: ignore
from Gateway import app

HOST = "0.0.0.0"
PORT = 5080

if __name__ == "__main__":
    uvicorn.run(app, host=HOST, port=PORT)