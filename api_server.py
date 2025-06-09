from flask import Flask, request, jsonify, send_file
from flask_cors import CORS
import tempfile
import os
import time
import base64
import threading
import queue
import logging
from werkzeug.utils import secure_filename
from musetalk_wrapper import MuseTalkWrapper

app = Flask(__name__)
CORS(app)  # Enable CORS for web clients

# Configure logging
logging.basicConfig(level=logging.INFO)
logger = logging.getLogger(__name__)

# Global storage for avatars and processing queues
avatars = {}
processing_queues = {}

class APIServer:
    """
    HTTP API Server for MuseTalk streaming.
    Provides REST endpoints for avatar initialization and video generation.
    """
    
    def __init__(self):
        self.upload_folder = tempfile.mkdtemp(prefix="musetalk_api_uploads_")
        self.output_folder = tempfile.mkdtemp(prefix="musetalk_api_outputs_")
        
        # Ensure folders exist
        os.makedirs(self.upload_folder, exist_ok=True)
        os.makedirs(self.output_folder, exist_ok=True)
        
        logger.info(f"API Server initialized")
        logger.info(f"Upload folder: {self.upload_folder}")
        logger.info(f"Output folder: {self.output_folder}")

api_server = APIServer()

@app.route('/health', methods=['GET'])
def health_check():
    """Health check endpoint"""
    return jsonify({
        'status': 'healthy',
        'message': 'MuseTalk API Server is running',
        'timestamp': time.time()
    })

@app.route('/initialize_avatar', methods=['POST'])
def initialize_avatar():
    """
    Initialize an avatar for video generation.
    
    Expected form data:
    - avatar_video: Video file (multipart/form-data)
    - avatar_id: Optional avatar identifier
    - version: Optional MuseTalk version (v1 or v15, default: v15)
    
    Returns:
    - JSON response with avatar_id and status
    """
    try:
        # Check if video file is provided
        if 'avatar_video' not in request.files:
            return jsonify({'error': 'No avatar video file provided'}), 400
        
        video_file = request.files['avatar_video']
        if video_file.filename == '':
            return jsonify({'error': 'No video file selected'}), 400
        
        # Get optional parameters
        avatar_id = request.form.get('avatar_id', f'avatar_{int(time.time())}')
        version = request.form.get('version', 'v15')
        
        if version not in ['v1', 'v15']:
            return jsonify({'error': 'Invalid version. Must be v1 or v15'}), 400
        
        # Save uploaded video
        filename = secure_filename(video_file.filename)
        video_path = os.path.join(api_server.upload_folder, f"{avatar_id}_{filename}")
        video_file.save(video_path)
        
        logger.info(f"Initializing avatar {avatar_id} with video: {video_path}")
        
        # Initialize avatar wrapper
        wrapper = MuseTalkWrapper(
            avatar_video_path=video_path,
            musetalk_project_path=".",
            version=version
        )
        
        # Prepare avatar (this may take some time)
        success = wrapper.prepare_avatar_realtime()
        
        if success:
            avatars[avatar_id] = wrapper
            processing_queues[avatar_id] = queue.Queue()
            
            logger.info(f"Avatar {avatar_id} initialized successfully")
            
            return jsonify({
                'status': 'success',
                'avatar_id': avatar_id,
                'message': 'Avatar initialized successfully',
                'version': version
            })
        else:
            return jsonify({
                'status': 'error',
                'message': 'Failed to initialize avatar'
            }), 500
    
    except Exception as e:
        logger.error(f"Error initializing avatar: {e}")
        return jsonify({
            'status': 'error',
            'message': f'Avatar initialization failed: {str(e)}'
        }), 500

@app.route('/generate_video', methods=['POST'])
def generate_video():
    """
    Generate video from audio for a specific avatar.
    
    Expected form data:
    - avatar_id: Avatar identifier
    - audio_file: Audio file (multipart/form-data)
    - output_name: Optional output filename
    
    Returns:
    - Generated video file
    """
    try:
        # Check required parameters
        avatar_id = request.form.get('avatar_id')
        if not avatar_id:
            return jsonify({'error': 'avatar_id is required'}), 400
        
        if avatar_id not in avatars:
            return jsonify({'error': f'Avatar {avatar_id} not found. Initialize avatar first.'}), 404
        
        # Check if audio file is provided
        if 'audio_file' not in request.files:
            return jsonify({'error': 'No audio file provided'}), 400
        
        audio_file = request.files['audio_file']
        if audio_file.filename == '':
            return jsonify({'error': 'No audio file selected'}), 400
        
        # Get optional parameters
        output_name = request.form.get('output_name', f'output_{int(time.time())}')
        
        # Save uploaded audio
        audio_filename = secure_filename(audio_file.filename)
        audio_path = os.path.join(api_server.upload_folder, f"{avatar_id}_{audio_filename}")
        audio_file.save(audio_path)
        
        logger.info(f"Generating video for avatar {avatar_id} with audio: {audio_path}")
        
        # Generate video
        wrapper = avatars[avatar_id]
        video_path = wrapper.generate_video_from_audio(audio_path, output_name)
        
        if video_path and os.path.exists(video_path):
            # Copy video to output folder
            output_video_path = os.path.join(api_server.output_folder, f"{output_name}.mp4")
            import shutil
            shutil.copy2(video_path, output_video_path)
            
            logger.info(f"Video generated successfully: {output_video_path}")
            
            # Clean up temporary audio file
            os.unlink(audio_path)
            
            # Return the generated video
            return send_file(
                output_video_path,
                as_attachment=True,
                download_name=f"{output_name}.mp4",
                mimetype='video/mp4'
            )
        else:
            # Clean up temporary audio file
            if os.path.exists(audio_path):
                os.unlink(audio_path)
            
            return jsonify({
                'status': 'error',
                'message': 'Failed to generate video'
            }), 500
    
    except Exception as e:
        logger.error(f"Error generating video: {e}")
        return jsonify({
            'status': 'error',
            'message': f'Video generation failed: {str(e)}'
        }), 500

@app.route('/generate_video_batch', methods=['POST'])
def generate_video_batch():
    """
    Generate multiple videos from multiple audio files for a specific avatar.
    
    Expected form data:
    - avatar_id: Avatar identifier
    - audio_files: Multiple audio files (multipart/form-data)
    
    Returns:
    - ZIP file containing all generated videos
    """
    try:
        # Check required parameters
        avatar_id = request.form.get('avatar_id')
        if not avatar_id:
            return jsonify({'error': 'avatar_id is required'}), 400
        
        if avatar_id not in avatars:
            return jsonify({'error': f'Avatar {avatar_id} not found. Initialize avatar first.'}), 404
        
        # Check if audio files are provided
        audio_files = request.files.getlist('audio_files')
        if not audio_files:
            return jsonify({'error': 'No audio files provided'}), 400
        
        logger.info(f"Generating {len(audio_files)} videos for avatar {avatar_id}")
        
        # Save all audio files
        audio_paths = []
        output_names = []
        
        for i, audio_file in enumerate(audio_files):
            if audio_file.filename == '':
                continue
            
            audio_filename = secure_filename(audio_file.filename)
            audio_path = os.path.join(api_server.upload_folder, f"{avatar_id}_batch_{i}_{audio_filename}")
            audio_file.save(audio_path)
            audio_paths.append(audio_path)
            
            output_name = f"batch_output_{i}_{int(time.time())}"
            output_names.append(output_name)
        
        if not audio_paths:
            return jsonify({'error': 'No valid audio files provided'}), 400
        
        # Generate videos in batch
        wrapper = avatars[avatar_id]
        video_paths = wrapper.generate_video_batch(audio_paths, output_names)
        
        # Create ZIP file with generated videos
        import zipfile
        zip_path = os.path.join(api_server.output_folder, f"batch_{avatar_id}_{int(time.time())}.zip")
        
        with zipfile.ZipFile(zip_path, 'w') as zip_file:
            for i, video_path in enumerate(video_paths):
                if video_path and os.path.exists(video_path):
                    zip_file.write(video_path, f"{output_names[i]}.mp4")
        
        # Clean up temporary audio files
        for audio_path in audio_paths:
            if os.path.exists(audio_path):
                os.unlink(audio_path)
        
        logger.info(f"Batch generation completed: {zip_path}")
        
        # Return the ZIP file
        return send_file(
            zip_path,
            as_attachment=True,
            download_name=f"batch_videos_{avatar_id}.zip",
            mimetype='application/zip'
        )
    
    except Exception as e:
        logger.error(f"Error in batch generation: {e}")
        return jsonify({
            'status': 'error',
            'message': f'Batch generation failed: {str(e)}'
        }), 500

@app.route('/list_avatars', methods=['GET'])
def list_avatars():
    """List all initialized avatars"""
    try:
        avatar_list = []
        for avatar_id, wrapper in avatars.items():
            avatar_list.append({
                'avatar_id': avatar_id,
                'version': wrapper.version,
                'video_path': wrapper.avatar_video_path
            })
        
        return jsonify({
            'status': 'success',
            'avatars': avatar_list,
            'count': len(avatar_list)
        })
    
    except Exception as e:
        logger.error(f"Error listing avatars: {e}")
        return jsonify({
            'status': 'error',
            'message': f'Failed to list avatars: {str(e)}'
        }), 500

@app.route('/delete_avatar', methods=['DELETE'])
def delete_avatar():
    """Delete an avatar and clean up resources"""
    try:
        avatar_id = request.json.get('avatar_id') if request.is_json else request.form.get('avatar_id')
        
        if not avatar_id:
            return jsonify({'error': 'avatar_id is required'}), 400
        
        if avatar_id not in avatars:
            return jsonify({'error': f'Avatar {avatar_id} not found'}), 404
        
        # Clean up avatar resources
        wrapper = avatars[avatar_id]
        wrapper.cleanup()
        
        # Remove from storage
        del avatars[avatar_id]
        if avatar_id in processing_queues:
            del processing_queues[avatar_id]
        
        logger.info(f"Avatar {avatar_id} deleted successfully")
        
        return jsonify({
            'status': 'success',
            'message': f'Avatar {avatar_id} deleted successfully'
        })
    
    except Exception as e:
        logger.error(f"Error deleting avatar: {e}")
        return jsonify({
            'status': 'error',
            'message': f'Failed to delete avatar: {str(e)}'
        }), 500

@app.route('/status', methods=['GET'])
def get_status():
    """Get server status and statistics"""
    try:
        return jsonify({
            'status': 'running',
            'avatars_count': len(avatars),
            'avatar_ids': list(avatars.keys()),
            'upload_folder': api_server.upload_folder,
            'output_folder': api_server.output_folder,
            'timestamp': time.time()
        })
    
    except Exception as e:
        logger.error(f"Error getting status: {e}")
        return jsonify({
            'status': 'error',
            'message': f'Failed to get status: {str(e)}'
        }), 500

if __name__ == '__main__':
    # Run the Flask app
    logger.info("Starting MuseTalk API Server...")
    app.run(
        host='0.0.0.0',
        port=5000,
        debug=False,
        threaded=True
    )