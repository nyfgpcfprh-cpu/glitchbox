#!/usr/bin/env python3
import zipfile
import os
from pathlib import Path

source_dir = Path("/Users/poop/dev/media-server/GlitchBox/GlitchBox_Roku_Fixed/Archive2")
output_zip = Path("/Users/poop/dev/media-server/GlitchBox/GlitchBox_Roku_NavFixed.zip")

# Remove old zip if exists
if output_zip.exists():
    output_zip.unlink()

# Create new zip
with zipfile.ZipFile(output_zip, 'w', zipfile.ZIP_DEFLATED) as zipf:
    for file_path in source_dir.rglob('*'):
        if file_path.is_file() and '.DS_Store' not in str(file_path):
            arcname = file_path.relative_to(source_dir)
            zipf.write(file_path, arcname)

print(f"Created: {output_zip}")
print("File size:", output_zip.stat().st_size, "bytes")
