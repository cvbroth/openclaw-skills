"""Single operator entry; Python 3.11+ stdlib on host, engines stay in the separate Docker worker."""
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]/"src"))
from nas_filetools.cli import main  # noqa: E402

if __name__ == "__main__":
    main()
