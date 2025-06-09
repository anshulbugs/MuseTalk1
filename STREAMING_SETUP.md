# MuseTalk Streaming System Setup Guide

This guide explains how to set up and use the MuseTalk streaming system that interfaces with the existing MuseTalk project without making any modifications to the original codebase.

## Overview

The streaming system consists of several components:

1. **MuseTalkWrapper** (`musetalk_wrapper.py`) - Interfaces with original MuseTalk scripts
2. **Streaming Server** (`streaming_server.py`) - WebSocket-based real-time streaming
3. **API Server** (`api_server.py`) - HTTP REST API for video generation
4. **Streaming Client** (`streaming_client.py`) - Example client for testing

## Prerequisites

1. **MuseTalk Project Setup**: Ensure the original MuseTalk project is properly installed and working
2. **Python 3.10+**: Required for compatibility
3. **CUDA GPU**: Recommended for real-time performance
4. **FFmpeg**: Required for audio/video processing

## Installation

### 1. Install MuseTalk Dependencies

First, ensure the original MuseTalk project is set up:

```bash
# Navigate to MuseTalk project directory
cd /path/to/MuseTalk

# Install MuseTalk dependencies (if not already done)
conda create -n MuseTalk python==3.10
conda activate MuseTalk
pip install torch==2.0.1 torchvision==0.15.2 torchaudio==2.0.2 --index-url https://download.pytorch.org/whl/cu118
pip install -r requirements.txt

# Install MMLab packages
pip install --no-cache-dir -U openmim
mim install mmengine
mim install "mmcv==2.0.1"
mim install "mmdet==3.1.0"
mim install "mmpose==1.1.0"

# Download model weights
./download_weights.sh  # Linux
# OR
download_weights.bat   # Windows
```

### 2. Install Streaming Dependencies

```bash
# Install additional streaming dependencies
pip install -r streaming_requirements.txt
```

### 3. Verify Setup

Test that the original MuseTalk works:

```bash
# Test basic inference
python -m scripts.inference \
  --inference_config configs/inference/test.yaml \
  --version v15 \
  --unet_model_path models/musetalkV15/unet.pth \
  --unet_config models/musetalkV15/musetalk.json
```

## Usage

### Option 1: HTTP API Server (Recommended for Web Applications)

#### Start the API Server

```bash
python api_server.py
```

The server will start on `http://localhost:5000`

#### API Endpoints

1. **Health Check**
   ```bash
   curl http://localhost:5000/health
   ```

2. **Initialize Avatar**
   ```bash
   curl -X POST \
     -F "avatar_video=@path/to/avatar/video.mp4" \
     -F "avatar_id=my_avatar" \
     -F "version=v15" \
     http://localhost:5000/initialize_avatar
   ```

3. **Generate Video**
   ```bash
   curl -X POST \
     -F "avatar_id=my_avatar" \
     -F "audio_file=@path/to/audio.wav" \
     -F "output_name=my_output" \
     http://localhost:5000/generate_video \
     --output generated_video.mp4
   ```

4. **List Avatars**
   ```bash
   curl http://localhost:5000/list_avatars
   ```

5. **Get Status**
   ```bash
   curl http://localhost:5000/status
   ```

#### Example Python Client for API

```python
import requests

# Initialize avatar
with open('avatar_video.mp4', 'rb') as f:
    response = requests.post('http://localhost:5000/initialize_avatar', 
                           files={'avatar_video': f},
                           data={'avatar_id': 'test_avatar', 'version': 'v15'})
print(response.json())

# Generate video
with open('audio.wav', 'rb') as f:
    response = requests.post('http://localhost:5000/generate_video',
                           files={'audio_file': f},
                           data={'avatar_id': 'test_avatar'})
    
    if response.status_code == 200:
        with open('output.mp4', 'wb') as out_f:
            out_f.write(response.content)
        print("Video generated successfully!")
```

### Option 2: WebSocket Streaming Server (Real-time Applications)

#### Start the Streaming Server

```bash
python streaming_server.py
```

The server will start on `ws://localhost:8765`

#### Use the Example Client

```bash
# Make sure you have a microphone connected
python streaming_client.py
```

The client will:
1. Connect to the streaming server
2. Initialize an avatar using the default video
3. Start recording audio from your microphone
4. Send audio chunks to the server
5. Receive and save generated videos

#### Custom WebSocket Client

```python
import asyncio
import websockets
import json
import base64

async def streaming_client():
    uri = "ws://localhost:8765"
    
    async with websockets.connect(uri) as websocket:
        # Initialize avatar
        with open('avatar_video.mp4', 'rb') as f:
            video_data = base64.b64encode(f.read()).decode()
        
        init_message = {
            'type': 'initialize_avatar',
            'avatar_video_data': video_data,
            'version': 'v15'
        }
        await websocket.send(json.dumps(init_message))
        
        # Wait for initialization
        response = await websocket.recv()
        print(json.loads(response))
        
        # Send audio chunk
        with open('audio.wav', 'rb') as f:
            audio_data = base64.b64encode(f.read()).decode()
        
        audio_message = {
            'type': 'audio_chunk',
            'audio_data': audio_data
        }
        await websocket.send(json.dumps(audio_message))
        
        # Receive video
        response = await websocket.recv()
        data = json.loads(response)
        
        if data['type'] == 'video_chunk':
            video_bytes = base64.b64decode(data['video_data'])
            with open('output.mp4', 'wb') as f:
                f.write(video_bytes)
            print("Video received and saved!")

asyncio.run(streaming_client())
```

### Option 3: Direct Wrapper Usage

For simple integration without servers:

```python
from musetalk_wrapper import MuseTalkWrapper

# Initialize wrapper
wrapper = MuseTalkWrapper(
    avatar_video_path="path/to/avatar/video.mp4",
    musetalk_project_path=".",  # Path to MuseTalk project
    version="v15"
)

# Generate single video
video_path = wrapper.generate_video_from_audio("audio.wav")
if video_path:
    print(f"Generated video: {video_path}")

# Generate multiple videos
audio_files = ["audio1.wav", "audio2.wav", "audio3.wav"]
video_paths = wrapper.generate_video_batch(audio_files)
print(f"Generated videos: {video_paths}")

# Cleanup
wrapper.cleanup()
```

## Configuration

### Audio Settings

For the streaming client, you can modify audio settings:

```python
# In streaming_client.py
self.sample_rate = 16000  # Audio sample rate
self.channels = 1         # Mono audio
self.chunk_duration = 2.0 # Seconds per audio chunk
```

### Performance Tuning

1. **Batch Size**: Adjust batch size in wrapper initialization
   ```python
   # In musetalk_wrapper.py, modify the batch_size parameter
   cmd.extend(["--batch_size", "4"])  # Smaller for lower latency
   ```

2. **GPU Memory**: Use float16 for better performance
   ```bash
   # Add to inference commands
   --use_float16
   ```

3. **Concurrent Processing**: Adjust thread counts based on your system

## Troubleshooting

### Common Issues

1. **"Avatar video not found"**
   - Ensure the video file path is correct and accessible
   - Check file permissions

2. **"MuseTalk project not found"**
   - Verify the `musetalk_project_path` parameter
   - Ensure all MuseTalk dependencies are installed

3. **"Failed to initialize avatar"**
   - Check GPU memory availability
   - Verify model weights are downloaded
   - Check MuseTalk project setup

4. **Audio recording issues**
   - Install PyAudio: `pip install pyaudio`
   - Check microphone permissions
   - Verify audio device availability

5. **WebSocket connection issues**
   - Check firewall settings
   - Verify server is running
   - Check port availability

### Performance Issues

1. **Slow video generation**
   - Use GPU acceleration
   - Enable float16 mode
   - Reduce batch size for lower latency
   - Use smaller audio chunks

2. **High memory usage**
   - Reduce batch size
   - Clean up temporary files regularly
   - Use avatar preparation for repeated use

### Debugging

Enable detailed logging:

```python
import logging
logging.basicConfig(level=logging.DEBUG)
```

Check server logs for detailed error messages.

## Integration Examples

### Web Application Integration

```javascript
// JavaScript example for web integration
const formData = new FormData();
formData.append('avatar_video', avatarVideoFile);
formData.append('avatar_id', 'web_avatar');

// Initialize avatar
fetch('http://localhost:5000/initialize_avatar', {
    method: 'POST',
    body: formData
}).then(response => response.json())
  .then(data => console.log(data));

// Generate video
const audioFormData = new FormData();
audioFormData.append('avatar_id', 'web_avatar');
audioFormData.append('audio_file', audioFile);

fetch('http://localhost:5000/generate_video', {
    method: 'POST',
    body: audioFormData
}).then(response => response.blob())
  .then(blob => {
    const videoUrl = URL.createObjectURL(blob);
    document.getElementById('videoPlayer').src = videoUrl;
  });
```

### Mobile App Integration

Use the HTTP API endpoints with your mobile app's HTTP client library.

### Real-time Chat Integration

Use the WebSocket server for real-time conversational applications.

## Production Deployment

### Docker Deployment

Create a `Dockerfile`:

```dockerfile
FROM nvidia/cuda:11.8-devel-ubuntu20.04

# Install Python and dependencies
RUN apt-get update && apt-get install -y python3 python3-pip ffmpeg

# Copy MuseTalk project
COPY . /app/MuseTalk
WORKDIR /app/MuseTalk

# Install dependencies
RUN pip install -r requirements.txt
RUN pip install -r streaming_requirements.txt

# Download models (you may want to include these in the image)
RUN ./download_weights.sh

# Expose ports
EXPOSE 5000 8765

# Start servers
CMD ["python", "api_server.py"]
```

### Load Balancing

For high-traffic applications:
1. Run multiple server instances
2. Use a load balancer (nginx, HAProxy)
3. Implement avatar caching
4. Use Redis for session management

### Monitoring

Monitor key metrics:
- GPU memory usage
- Processing latency
- Queue sizes
- Error rates

## Security Considerations

1. **File Upload Validation**: Validate uploaded files
2. **Rate Limiting**: Implement rate limiting for API endpoints
3. **Authentication**: Add authentication for production use
4. **HTTPS**: Use HTTPS in production
5. **Input Sanitization**: Sanitize all user inputs

## Support

For issues related to:
- **Original MuseTalk**: Check the MuseTalk repository
- **Streaming System**: Check logs and troubleshooting section
- **Performance**: Review configuration and hardware requirements

## License

This streaming system is provided as-is and follows the same license terms as the original MuseTalk project.