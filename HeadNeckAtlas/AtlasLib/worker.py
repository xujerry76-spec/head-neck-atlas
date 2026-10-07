"""Invoked with PythonSlicer; never imports or mutates a live MRML scene."""
import sys
from pathlib import Path
sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
from AtlasLib.inference import run_worker

if __name__ == '__main__':
    sys.exit(run_worker(sys.argv[1]))
