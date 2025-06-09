import asyncio
import websockets
import json
import base64
import pyaudio
import wave
import tempfile
import os
import time
import threading
import queue
from pathlib import Path
import logging

class MuseTalkStreamingClient:
    """
    Client for connecting to MuseTalk Streaming Server.
    Captures audio from microphone and receives generated videos.
    """
    
    def __init__(self, server_url="ws://localhost:8765"):
        self.server_url = server_url
        self.websocket = None
        self.client_id = None
        self.avatar_id = None
        self.is_connected = False
        self.is_recording = False
        
        # Audio settings
        self.audio_format = pyaudio.paInt16
        self.channels = 1
        self.sample_rate = 16000
        self.chunk_size = 1024
        self.chunk_duration = 2.0  # seconds
        
        # Queues
        self.audio_queue = queue.Queue()
        self.video_queue = queue.Queue()
        
        # Setup logging
        logging.basicConfig(level=logging.INFO)
        self.logger = logging.getLogger(__name__)
        
        # PyAudio instance
        self.audio = pyaudio.PyAudio()
        self.stream = None
    
    async def connect(self):
        """Connect to the streaming server"""
        try:
            self.websocket = await websockets.connect(
                self.server_url,
                max_size=50 * 1024 * 1024,  # 50MB max message size
                ping_interval=20,
                ping_timeout=10
            )
            self.is_connected = True
            self.logger.info(f"Connected to server: {self.server_url}")
            
            # Start message handler
            asyncio.create_task(self.handle_messages())
            
        except Exception as e:
            self.logger.error(f"Failed to connect to server: {e}")
            raise
    
    async def disconnect(self):
        """Disconnect from the server"""
        try:
            self.is_connected = False
            if self.websocket:
                await self.websocket.close()
            self.logger.info("Disconnected from server")
        except Exception as e:
            self.logger.error(f"Error disconnecting: {e}")
    
    async def handle_messages(self):
        """Handle incoming messages from server"""
        try:
            async for message in self.websocket:
                data = json.loads(message)
                message_type = data.get('type')
                
                if message_type == 'connection_established':
                    self.client_id = data.get('client_id')
                    self.logger.info(f"Connection established. Client ID: {self.client_id}")
                
                elif message_type == 'avatar_initialization_started':
                    self.logger.info("Avatar initialization started...")
                
                elif message_type == 'avatar_initialized':
                    self.avatar_id = data.get('avatar_id')
                    self.logger.info(f"Avatar initialized successfully. Avatar ID: {self.avatar_id}")
                
                elif message_type == 'audio_received':
                    self.logger.debug("Audio chunk received by server")
                
                elif message_type == 'video_chunk':
                    video_data = data.get('video_data')
                    timestamp = data.get('timestamp')
                    self.video_queue.put((video_data, timestamp))
                    self.logger.info(f"Received video chunk at {timestamp}")
                
                elif message_type == 'status':
                    self.logger.info(f"Status: {data}")
                
                elif message_type == 'error':
                    self.logger.error(f"Server error: {data.get('message')}")
                
                else:
                    self.logger.warning(f"Unknown message type: {message_type}")
                    
        except websockets.exceptions.ConnectionClosed:
            self.logger.info("Connection closed by server")
            self.is_connected = False
        except Exception as e:
            self.logger.error(f"Error handling messages: {e}")
            self.is_connected = False
    
    async def initialize_avatar(self, avatar_video_path=None, avatar_video_data=None, version="v15"):
        """Initialize avatar on the server"""
        if not self.is_connected:
            raise Exception("Not connected to server")
        
        message = {
            'type': 'initialize_avatar',
            'version': version
        }
        
        if avatar_video_path:
            if not os.path.exists(avatar_video_path):
                raise FileNotFoundError(f"Avatar video not found: {avatar_video_path}")
            
            # Read and encode video file
            with open(avatar_video_path, 'rb') as f:
                video_data = f.read()
            message['avatar_video_data'] = base64.b64encode(video_data).decode('utf-8')
        
        elif avatar_video_data:
            message['avatar_video_data'] = avatar_video_data
        
        else:
            raise ValueError("Either avatar_video_path or avatar_video_data must be provided")
        
        await self.websocket.send(json.dumps(message))
        self.logger.info("Avatar initialization request sent")
    
    def start_audio_recording(self):
        """Start recording audio from microphone"""
        if self.is_recording:
            self.logger.warning("Already recording")
            return
        
        try:
            self.stream = self.audio.open(
                format=self.audio_format,
                channels=self.channels,
                rate=self.sample_rate,
                input=True,
                frames_per_buffer=self.chunk_size
            )
            
            self.is_recording = True
            self.logger.info("Started audio recording")
            
            # Start recording thread
            threading.Thread(target=self._record_audio, daemon=True).start()
            
        except Exception as e:
            self.logger.error(f"Failed to start audio recording: {e}")
            raise
    
    def stop_audio_recording(self):
        """Stop recording audio"""
        self.is_recording = False
        
        if self.stream:
            self.stream.stop_stream()
            self.stream.close()
            self.stream = None
        
        self.logger.info("Stopped audio recording")
    
    def _record_audio(self):
        """Record audio in chunks and add to queue"""
        frames_per_chunk = int(self.sample_rate * self.chunk_duration)
        
        while self.is_recording:
            try:
                frames = []
                for _ in range(0, frames_per_chunk, self.chunk_size):
                    if not self.is_recording:
                        break
                    data = self.stream.read(self.chunk_size, exception_on_overflow=False)
                    frames.append(data)
                
                if frames:
                    # Combine frames into single audio chunk
                    audio_data = b''.join(frames)
                    self.audio_queue.put(audio_data)
                    
            except Exception as e:
                self.logger.error(f"Error recording audio: {e}")
                break
    
    async def process_audio_queue(self):
        """Process audio chunks from queue and send to server"""
        while self.is_connected:
            try:
                if not self.audio_queue.empty():
                    audio_data = self.audio_queue.get()
                    
                    # Encode audio data
                    audio_base64 = base64.b64encode(audio_data).decode('utf-8')
                    
                    # Send to server
                    message = {
                        'type': 'audio_chunk',
                        'audio_data': audio_base64
                    }
                    
                    await self.websocket.send(json.dumps(message))
                    self.logger.debug("Sent audio chunk to server")
                
                await asyncio.sleep(0.1)  # Small delay to prevent busy waiting
                
            except Exception as e:
                self.logger.error(f"Error processing audio queue: {e}")
                break
    
    def get_next_video(self):
        """Get the next generated video from queue"""
        try:
            return self.video_queue.get_nowait()
        except queue.Empty:
            return None
    
    def save_video(self, video_data, output_path):
        """Save video data to file"""
        try:
            video_bytes = base64.b64decode(video_data)
            with open(output_path, 'wb') as f:
                f.write(video_bytes)
            self.logger.info(f"Video saved to: {output_path}")
            return True
        except Exception as e:
            self.logger.error(f"Error saving video: {e}")
            return False
    
    async def get_status(self):
        """Get status from server"""
        if not self.is_connected:
            return None
        
        message = {'type': 'get_status'}
        await self.websocket.send(json.dumps(message))
    
    def cleanup(self):
        """Clean up resources"""
        self.stop_audio_recording()
        self.audio.terminate()

# Example usage and testing
async def main():
    client = MuseTalkStreamingClient()
    
    try:
        # Connect to server
        await client.connect()
        
        # Wait for connection
        await asyncio.sleep(1)
        
        # Initialize avatar (use default video from MuseTalk project)
        await client.initialize_avatar(avatar_video_path="data/video/yongen.mp4")
        
        # Wait for avatar initialization
        await asyncio.sleep(10)  # Avatar initialization takes time
        
        # Start audio recording
        client.start_audio_recording()
        
        # Start processing audio queue
        audio_task = asyncio.create_task(client.process_audio_queue())
        
        # Monitor for generated videos
        video_count = 0
        start_time = time.time()
        
        print("Recording audio and generating videos. Press Ctrl+C to stop...")
        
        while True:
            # Check for new videos
            video_result = client.get_next_video()
            if video_result:
                video_data, timestamp = video_result
                video_count += 1
                
                # Save video
                output_path = f"generated_video_{video_count}_{int(timestamp)}.mp4"
                if client.save_video(video_data, output_path):
                    print(f"Generated video #{video_count}: {output_path}")
            
            # Get status every 10 seconds
            if int(time.time() - start_time) % 10 == 0:
                await client.get_status()
            
            await asyncio.sleep(0.5)
    
    except KeyboardInterrupt:
        print("\nStopping client...")
    
    except Exception as e:
        print(f"Client error: {e}")
    
    finally:
        # Cleanup
        client.cleanup()
        await client.disconnect()

if __name__ == "__main__":
    # Check if PyAudio is available
    try:
        import pyaudio
    except ImportError:
        print("PyAudio is required for audio recording. Install it with: pip install pyaudio")
        exit(1)
    
    # Run the client
    asyncio.run(main())