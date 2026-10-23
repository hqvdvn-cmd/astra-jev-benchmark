"""Deterministic shared visual input for every candidate; no external media or API."""
from __future__ import annotations
import math
import subprocess
from pathlib import Path
from PIL import Image, ImageDraw, ImageFilter

target = Path(__file__).resolve().parents[1] / 'tasks/react-site-001/starter/public/orbit-loop.mp4'
target.parent.mkdir(parents=True, exist_ok=True)
width, height, fps, seconds = 960, 540, 24, 6
process = subprocess.Popen(['ffmpeg', '-hide_banner', '-loglevel', 'error', '-y', '-f', 'rawvideo', '-pix_fmt', 'rgb24', '-s', f'{width}x{height}', '-r', str(fps), '-i', '-', '-an', '-c:v', 'libx264', '-preset', 'fast', '-crf', '22', '-pix_fmt', 'yuv420p', '-movflags', '+faststart', str(target)], stdin=subprocess.PIPE)
for frame in range(fps * seconds):
    phase = frame / (fps * seconds) * math.tau
    image = Image.new('RGB', (width, height), (8, 12, 19))
    glow = Image.new('RGB', (width, height))
    draw = ImageDraw.Draw(glow)
    for index in range(9):
        radius = 60 + index * 23
        x = width / 2 + math.cos(phase + index * .22) * 32
        y = height / 2 + math.sin(phase + index * .22) * 22
        draw.ellipse((x-radius, y-radius*.43, x+radius, y+radius*.43), outline=(50+index*9, 110+index*8, 130+index*10), width=3)
    glow = glow.filter(ImageFilter.GaussianBlur(15))
    image = Image.blend(image, glow, .65)
    draw = ImageDraw.Draw(image)
    for index in range(9):
        radius = 60 + index * 23
        x = width / 2 + math.cos(phase + index * .22) * 32
        y = height / 2 + math.sin(phase + index * .22) * 22
        draw.ellipse((x-radius, y-radius*.43, x+radius, y+radius*.43), outline=(85+index*12, 135+index*9, 165+index*8), width=1)
        px, py = x + math.cos(phase*2 + index)*radius, y + math.sin(phase*2 + index)*radius*.43
        draw.ellipse((px-3, py-3, px+3, py+3), fill=(235, 248, 255))
    process.stdin.write(image.tobytes())
process.stdin.close()
if process.wait() != 0:
    raise SystemExit('Video generation failed')
print('SHARED_VIDEO_CREATED', target.name, target.stat().st_size)
