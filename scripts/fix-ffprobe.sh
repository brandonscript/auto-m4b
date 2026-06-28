#!/bin/bash
# Check if poetry is installed and that we're running in a poetry/venv
current_venv=$(poetry env info --path)
if [ -z "$current_venv" ]; then
    echo "Not running in a poetry/venv, running pip directly..."
    bin_root=".venv/bin/python"
    site_packages=".venv/lib/python3.12/site-packages"
    $bin_root -m pip uninstall ffmpeg-python python-ffmpeg -y && $bin_root -m pip install ffmpeg-python --target $site_packages
else
    echo "Running in a poetry/venv, running via poetry..."
    poetry run pip uninstall ffmpeg-python python-ffmpeg -y && poetry run pip install ffmpeg-python
fi
