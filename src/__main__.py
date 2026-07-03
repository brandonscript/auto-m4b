# update path
import sys
from pathlib import Path

sys.path.append(str(Path(__file__).parent.parent))

from src.auto_m4b import app

if __name__ == "__main__":
    app()
