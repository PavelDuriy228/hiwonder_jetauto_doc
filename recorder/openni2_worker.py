#!/usr/bin/env python3
"""OpenNI2 camera capture worker — runs as a subprocess.

Writes frames to stdout: 4-byte LE uint32 (JPEG size) + JPEG bytes, repeated.
Running isolated from the main process so any OpenNI2 segfault stays contained.
"""

import struct
import sys

import cv2
import numpy as np

# Orbbec/OpenNI2 .so location on Jetson Ubuntu 18.04
# Try the ROS-installed path first; fall back to system /usr/lib
import os as _os
_OPENNI2_LIB = (
    "/opt/ros/melodic/lib/astra_camera"
    if _os.path.isdir("/opt/ros/melodic/lib/astra_camera")
    else "/usr/lib"
)
_PRIMESENSE  = "/usr/local/lib/python3.6/dist-packages"

if _PRIMESENSE not in sys.path:
    sys.path.insert(0, _PRIMESENSE)

from primesense import openni2  # type: ignore

HDR          = struct.Struct("<I")
JPEG_QUALITY = 85
FRAME_H      = 480
FRAME_W      = 640


def main():
    # type: () -> None
    openni2.initialize(_OPENNI2_LIB)
    dev = openni2.Device.open_any()

    stream = dev.create_color_stream()
    stream.start()

    out = sys.stdout.buffer
    while True:
        frame_obj = stream.read_frame()
        buf = frame_obj.get_buffer_as_uint8()
        img_rgb = np.frombuffer(buf, dtype=np.uint8).reshape(FRAME_H, FRAME_W, 3)
        img_bgr = cv2.cvtColor(img_rgb, cv2.COLOR_RGB2BGR)

        ok, jpeg = cv2.imencode(".jpg", img_bgr, [cv2.IMWRITE_JPEG_QUALITY, JPEG_QUALITY])
        if not ok:
            continue

        data = jpeg.tobytes()
        out.write(HDR.pack(len(data)))
        out.write(data)
        out.flush()


if __name__ == "__main__":
    main()
