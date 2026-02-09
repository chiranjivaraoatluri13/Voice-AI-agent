# =========================
# FILE: agent/realtime_screen.py
# =========================
"""
Real-time screen capture without screenshot delays.
Uses scrcpy for low-latency video streaming.
"""

import subprocess
import cv2
import numpy as np
import threading
import time
from typing import Optional
from pathlib import Path


class RealtimeScreenCapture:
    """
    Captures Android screen in real-time using scrcpy.
    No screenshot delays - continuous video stream.
    """
    
    def __init__(self, fps: int = 15):
        self.fps = fps
        self.stream_process = None
        self.current_frame = None
        self.running = False
        self.frame_count = 0
        
        # Temp storage
        self.temp_dir = Path("temp_frames")
        self.temp_dir.mkdir(exist_ok=True)
    
    def start(self):
        """Start real-time screen capture"""
        
        print(f"🎥 Starting screen capture at {self.fps} FPS...")
        
        # Check if scrcpy is available
        try:
            subprocess.run(['scrcpy', '--version'], 
                         capture_output=True, check=True)
        except:
            print("❌ scrcpy not found!")
            print("   Install: https://github.com/Genymobile/scrcpy")
            return False
        
        # Start scrcpy stream
        self.stream_process = subprocess.Popen([
            'scrcpy',
            '--no-display',           # Don't show window
            '--no-audio',             # No audio needed
            '--max-fps', str(self.fps),
            '--video-codec=h264',
            '--video-bit-rate=2M',
            '--record', '-'           # Output to stdout
        ], stdout=subprocess.PIPE, stderr=subprocess.DEVNULL)
        
        # Start processing thread
        self.running = True
        threading.Thread(target=self._capture_loop, daemon=True).start()
        
        # Wait for first frame
        for _ in range(50):
            if self.current_frame is not None:
                print("✅ Screen capture ready!")
                return True
            time.sleep(0.1)
        
        print("⚠️ No frames received")
        return False
    
    def _capture_loop(self):
        """Capture frames continuously"""
        
        cap = cv2.VideoCapture(self.stream_process.stdout.fileno())
        
        while self.running:
            ret, frame = cap.read()
            if not ret:
                time.sleep(0.01)
                continue
            
            self.current_frame = frame
            self.frame_count += 1
        
        cap.release()
    
    def get_current_frame(self) -> Optional[np.ndarray]:
        """Get latest frame (no delay!)"""
        return self.current_frame
    
    def save_current_frame(self, filename: str = None) -> str:
        """Save current frame to disk for processing"""
        
        if self.current_frame is None:
            return None
        
        if filename is None:
            filename = f"frame_{int(time.time()*1000)}.png"
        
        filepath = self.temp_dir / filename
        cv2.imwrite(str(filepath), self.current_frame)
        
        return str(filepath)
    
    def stop(self):
        """Stop capture"""
        self.running = False
        if self.stream_process:
            self.stream_process.terminate()
        
        print(f"⏹️  Stopped. Captured {self.frame_count} frames")