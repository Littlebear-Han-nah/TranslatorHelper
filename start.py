"""Start the same server used in Docker, without silently installing dependencies."""
import os
import sys
from pathlib import Path
os.chdir(Path(__file__).resolve().parent)
os.execv(sys.executable, [sys.executable, '-m', 'uvicorn', 'backend.app.main:app', '--host', '127.0.0.1', '--port', os.getenv('PORT', '8010')])
