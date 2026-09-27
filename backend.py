"""
CodeWise - Intelligent Code Mentor AI
Backend server with RAG capabilities powered by Ollama

Entry point kept for `python backend.py`; the implementation lives in the codewise package.
"""

import logging

from codewise.app import create_app
from codewise.config import Config

logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)s %(name)s: %(message)s")

config = Config()
app = create_app(config)

if __name__ == '__main__':
    # Debug mode enables the Werkzeug debugger (remote code execution if exposed);
    # it is off unless CODEWISE_DEBUG=1.
    app.run(debug=config.debug, host=config.host, port=config.port, threaded=True)
