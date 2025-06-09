import asyncio
import websockets
import json
import base64
import tempfile
import os
import time
import threading
import queue
import logging
from pathlib import Path
import wave
import io
from musetalk_wrapper import MuseTalkWrapper

class MuseTalkStreamingServer:
    """
    WebSocket-based streaming server that processes audio chunks and returns video streams.
    Uses the MuseTalkWrapper to interface with the original MuseTalk project without modifications.
    """
    
    def __init__(self, host="localhost", port=8765):
        self.host = host
        self.port = port
        self.clients = {}
        self.avatars = {}
        
        # Setup logging
        logging.basicConfig(level=logging.INFO)
        self.logger = logging.getLogger(__name__)
        
        self.logger.info(f"MuseTalk Streaming Server initialized on {host}:{port}")
    
    async def register_client(self, websocket, path):
        """Handle new client connections"""
        client_id = f"client_{int(time.time() * 1000)}"
        self.clients[client_id] = {
            'websocket': websocket,
            'avatar_id': None,
            'audio_queue': queue.Queue(),
            'processing': False
        }
        
        self.logger.info(f"Client {client_id} connected")
        
        try:
            await websocket.send(json.dumps({
                'type': 'connection_established',
                'client_id': client_id,
                'message': 'Connected to MuseTalk Streaming Server'
            }))
            
            async for message in websocket:
                await self.handle_message(client_id, message)
                
        except websockets.exceptions.ConnectionClosed:
            self.logger.info(f"Client {client_id} disconnected")
        except Exception as e:
            self.logger.error(f"Error handling client {client_id}: {e}")
        finally:
            await self.cleanup_client(client_id)
    
    async def handle_message(self, client_id, message):
        """Handle incoming messages from clients"""
        try:
            data = json.loads(message)
            message_type = data.get('type')
            
            if message_type == 'initialize_avatar':
                await self.handle_initialize_avatar(client_id, data)
            
            elif message_type == 'audio_chunk':
                await self.handle_audio_chunk(client_id, data)
            
            elif message_type == 'get_status':
                await self.handle_get_status(client_id)
            
            else:
                await self.send_error(client_id, f"Unknown message type: {message_type}")
                
        except json.JSONDecodeError:
            await self.send_error(client_id, "Invalid JSON message")
        except Exception as e:
            await self.send_error(client_id, f"Error processing message: {e}")
    
    async def handle_initialize_avatar(self, client_id, data):
        """Initialize avatar for a client"""
        try:
            avatar_video_data = data.get('avatar_video_data')
            avatar_video_path = data.get('avatar_video_path')
            version = data.get('version', 'v15')
            
            if not avatar_video_data and not avatar_video_path:
                await self.send_error(client_id, "Either avatar_video_data or avatar_video_path must be provided")
                return
            
            # If video data is provided, save it to a temporary file
            if avatar_video_data:
                video_data = base64.b64decode(avatar_video_data)
                temp_video = tempfile.NamedTemporaryFile(suffix='.mp4', delete=False)
                temp_video.write(video_data)
                temp_video.close()
                avatar_video_path = temp_video.name
            
            # Validate video path
            if not os.path.exists(avatar_video_path):
                await self.send_error(client_id, f"Avatar video not found: {avatar_video_path}")
                return
            
            # Create avatar wrapper
            avatar_id = f"avatar_{client_id}_{int(time.time())}"
            
            await self.send_message(client_id, {
                'type': 'avatar_initialization_started',
                'avatar_id': avatar_id,
                'message': 'Initializing avatar, this may take a few moments...'
            })
            
            # Initialize avatar in a separate thread to avoid blocking
            def initialize_avatar():
                try:
                    wrapper = MuseTalkWrapper(
                        avatar_video_path=avatar_video_path,
                        musetalk_project_path=".",
                        version=version
                    )
                    
                    # Prepare avatar for real-time inference
                    success = wrapper.prepare_avatar_realtime()
                    
                    if success:
                        self.avatars[avatar_id] = wrapper
                        self.clients[client_id]['avatar_id'] = avatar_id
                        
                        # Send success message
                        asyncio.create_task(self.send_message(client_id, {
                            'type': 'avatar_initialized',
                            'avatar_id': avatar_id,
                            'message': 'Avatar initialized successfully. Ready to process audio.'
                        }))
                    else:
                        asyncio.create_task(self.send_error(client_id, "Failed to initialize avatar"))
                        
                except Exception as e:
                    asyncio.create_task(self.send_error(client_id, f"Avatar initialization error: {e}"))
            
            # Start initialization in background
            threading.Thread(target=initialize_avatar, daemon=True).start()
            
        except Exception as e:
            await self.send_error(client_id, f"Error initializing avatar: {e}")
    
    async def handle_audio_chunk(self, client_id, data):
        """Handle incoming audio chunk"""
        try:
            if client_id not in self.clients:
                await self.send_error(client_id, "Client not found")
                return
            
            avatar_id = self.clients[client_id]['avatar_id']
            if not avatar_id or avatar_id not in self.avatars:
                await self.send_error(client_id, "Avatar not initialized")
                return
            
            audio_data = data.get('audio_data')
            if not audio_data:
                await self.send_error(client_id, "No audio data provided")
                return
            
            # Decode audio data
            audio_bytes = base64.b64decode(audio_data)
            
            # Add to processing queue
            self.clients[client_id]['audio_queue'].put(audio_bytes)
            
            # Start processing if not already processing
            if not self.clients[client_id]['processing']:
                self.clients[client_id]['processing'] = True
                threading.Thread(
                    target=self.process_audio_queue,
                    args=(client_id, avatar_id),
                    daemon=True
                ).start()
            
            await self.send_message(client_id, {
                'type': 'audio_received',
                'message': 'Audio chunk received and queued for processing'
            })
            
        except Exception as e:
            await self.send_error(client_id, f"Error handling audio chunk: {e}")
    
    def process_audio_queue(self, client_id, avatar_id):
        """Process audio chunks in queue"""
        try:
            wrapper = self.avatars[avatar_id]
            audio_queue = self.clients[client_id]['audio_queue']
            
            while not audio_queue.empty():
                try:
                    audio_bytes = audio_queue.get(timeout=1)
                    
                    # Save audio to temporary file
                    temp_audio = tempfile.NamedTemporaryFile(suffix='.wav', delete=False)
                    
                    # Convert raw audio bytes to WAV format
                    self.save_audio_as_wav(audio_bytes, temp_audio.name)
                    
                    # Generate video
                    output_name = f"stream_{client_id}_{int(time.time() * 1000)}"
                    video_path = wrapper.generate_video_from_audio(temp_audio.name, output_name)
                    
                    if video_path and os.path.exists(video_path):
                        # Read generated video
                        with open(video_path, 'rb') as f:
                            video_data = f.read()
                        
                        # Encode video as base64
                        video_base64 = base64.b64encode(video_data).decode('utf-8')
                        
                        # Send video to client
                        asyncio.create_task(self.send_message(client_id, {
                            'type': 'video_chunk',
                            'video_data': video_base64,
                            'timestamp': time.time()
                        }))
                        
                        # Clean up generated video
                        os.unlink(video_path)
                    else:
                        asyncio.create_task(self.send_error(client_id, "Failed to generate video"))
                    
                    # Clean up temporary audio
                    os.unlink(temp_audio.name)
                    
                except queue.Empty:
                    break
                except Exception as e:
                    self.logger.error(f"Error processing audio for client {client_id}: {e}")
                    asyncio.create_task(self.send_error(client_id, f"Audio processing error: {e}"))
            
        except Exception as e:
            self.logger.error(f"Error in audio processing thread for client {client_id}: {e}")
        finally:
            if client_id in self.clients:
                self.clients[client_id]['processing'] = False
    
    def save_audio_as_wav(self, audio_bytes, output_path, sample_rate=16000, channels=1, sample_width=2):
        """Save raw audio bytes as WAV file"""
        try:
            with wave.open(output_path, 'wb') as wav_file:
                wav_file.setnchannels(channels)
                wav_file.setsampwidth(sample_width)
                wav_file.setframerate(sample_rate)
                wav_file.writeframes(audio_bytes)
        except Exception as e:
            self.logger.error(f"Error saving audio as WAV: {e}")
            raise
    
    async def handle_get_status(self, client_id):
        """Get status information for client"""
        try:
            if client_id not in self.clients:
                await self.send_error(client_id, "Client not found")
                return
            
            client_info = self.clients[client_id]
            avatar_id = client_info['avatar_id']
            
            status = {
                'type': 'status',
                'client_id': client_id,
                'avatar_initialized': avatar_id is not None,
                'avatar_id': avatar_id,
                'queue_size': client_info['audio_queue'].qsize(),
                'processing': client_info['processing']
            }
            
            await self.send_message(client_id, status)
            
        except Exception as e:
            await self.send_error(client_id, f"Error getting status: {e}")
    
    async def send_message(self, client_id, message):
        """Send message to specific client"""
        try:
            if client_id in self.clients:
                websocket = self.clients[client_id]['websocket']
                await websocket.send(json.dumps(message))
        except Exception as e:
            self.logger.error(f"Error sending message to client {client_id}: {e}")
    
    async def send_error(self, client_id, error_message):
        """Send error message to client"""
        await self.send_message(client_id, {
            'type': 'error',
            'message': error_message
        })
    
    async def cleanup_client(self, client_id):
        """Clean up client resources"""
        try:
            if client_id in self.clients:
                avatar_id = self.clients[client_id]['avatar_id']
                
                # Clean up avatar if it exists
                if avatar_id and avatar_id in self.avatars:
                    self.avatars[avatar_id].cleanup()
                    del self.avatars[avatar_id]
                
                # Remove client
                del self.clients[client_id]
                
                self.logger.info(f"Cleaned up resources for client {client_id}")
                
        except Exception as e:
            self.logger.error(f"Error cleaning up client {client_id}: {e}")
    
    def start_server(self):
        """Start the WebSocket server"""
        self.logger.info(f"Starting MuseTalk Streaming Server on {self.host}:{self.port}")
        
        start_server = websockets.serve(
            self.register_client,
            self.host,
            self.port,
            max_size=50 * 1024 * 1024,  # 50MB max message size for video data
            ping_interval=20,
            ping_timeout=10
        )
        
        asyncio.get_event_loop().run_until_complete(start_server)
        self.logger.info("Server started successfully")
        asyncio.get_event_loop().run_forever()

if __name__ == "__main__":
    # Create and start the server
    server = MuseTalkStreamingServer(host="0.0.0.0", port=8765)
    
    try:
        server.start_server()
    except KeyboardInterrupt:
        print("\nServer stopped by user")
    except Exception as e:
        print(f"Server error: {e}")