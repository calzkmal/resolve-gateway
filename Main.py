# main.py
import uvicorn # type: ignore
from Gateway import app

if __name__ == "__main__":
    uvicorn.run(app, host="0.0.0.0", port=5080)