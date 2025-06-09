import subprocess
import tempfile
import os
import time
import shutil
import json
import yaml
from pathlib import Path
import logging

class MuseTalkWrapper:
    """
    Wrapper class that interfaces with existing MuseTalk scripts without any modifications.
    Uses subprocess calls to execute the original inference scripts.
    """
    
    def __init__(self, avatar_video_path, musetalk_project_path=".", version="v15"):
        self.avatar_video_path = os.path.abspath(avatar_video_path)
        self.musetalk_project_path = os.path.abspath(musetalk_project_path)
        self.version = version
        self.temp_dir = tempfile.mkdtemp(prefix="musetalk_wrapper_")
        self.avatar_prepared = False
        self.avatar_id = f"avatar_{int(time.time())}"
        
        # Setup logging
        logging.basicConfig(level=logging.INFO)
        self.logger = logging.getLogger(__name__)
        
        # Validate paths
        if not os.path.exists(self.avatar_video_path):
            raise FileNotFoundError(f"Avatar video not found: {self.avatar_video_path}")
        
        if not os.path.exists(os.path.join(self.musetalk_project_path, "scripts", "inference.py")):
            raise FileNotFoundError(f"MuseTalk project not found at: {self.musetalk_project_path}")
        
        self.logger.info(f"MuseTalk Wrapper initialized with avatar: {self.avatar_video_path}")
    
    def prepare_avatar_realtime(self):
        """
        Prepare avatar for real-time inference using the existing realtime_inference.py script.
        This creates all necessary cached data for fast inference.
        """
        if self.avatar_prepared:
            return True
        
        try:
            # Create dummy audio file for preparation
            dummy_audio_path = os.path.join(self.temp_dir, "dummy.wav")
            self._create_dummy_audio(dummy_audio_path)
            
            # Create configuration file for realtime preparation
            config_content = {
                self.avatar_id: {
                    "preparation": True,
                    "video_path": self.avatar_video_path,
                    "bbox_shift": 0 if self.version == "v15" else 0,
                    "audio_clips": {
                        "dummy": dummy_audio_path
                    }
                }
            }
            
            config_path = os.path.join(self.temp_dir, "realtime_config.yaml")
            with open(config_path, 'w') as f:
                yaml.dump(config_content, f)
            
            # Prepare command for realtime inference
            cmd = [
                "python", "-m", "scripts.realtime_inference",
                "--inference_config", config_path,
                "--version", self.version,
                "--result_dir", self.temp_dir,
                "--batch_size", "8"
            ]
            
            if self.version == "v15":
                cmd.extend([
                    "--unet_model_path", "models/musetalkV15/unet.pth",
                    "--unet_config", "models/musetalkV15/musetalk.json"
                ])
            else:
                cmd.extend([
                    "--unet_model_path", "models/musetalk/pytorch_model.bin",
                    "--unet_config", "models/musetalk/musetalk.json"
                ])
            
            self.logger.info("Preparing avatar for real-time inference...")
            
            # Execute preparation
            result = subprocess.run(
                cmd,
                cwd=self.musetalk_project_path,
                capture_output=True,
                text=True,
                timeout=300  # 5 minute timeout
            )
            
            if result.returncode == 0:
                self.avatar_prepared = True
                self.logger.info("Avatar preparation completed successfully")
                return True
            else:
                self.logger.error(f"Avatar preparation failed: {result.stderr}")
                return False
                
        except subprocess.TimeoutExpired:
            self.logger.error("Avatar preparation timed out")
            return False
        except Exception as e:
            self.logger.error(f"Error during avatar preparation: {e}")
            return False
    
    def generate_video_from_audio(self, audio_path, output_name=None):
        """
        Generate video from audio using the existing inference.py script.
        
        Args:
            audio_path (str): Path to the audio file
            output_name (str): Optional output name, auto-generated if None
            
        Returns:
            str: Path to generated video file, None if failed
        """
        if not os.path.exists(audio_path):
            self.logger.error(f"Audio file not found: {audio_path}")
            return None
        
        if output_name is None:
            output_name = f"output_{int(time.time() * 1000)}"
        
        try:
            # Create configuration file for this inference
            task_config = {
                "task_0": {
                    "video_path": self.avatar_video_path,
                    "audio_path": os.path.abspath(audio_path),
                    "result_name": f"{output_name}.mp4"
                }
            }
            
            if self.version == "v1":
                task_config["task_0"]["bbox_shift"] = 0
            
            config_path = os.path.join(self.temp_dir, f"inference_config_{output_name}.yaml")
            with open(config_path, 'w') as f:
                yaml.dump(task_config, f)
            
            # Prepare command
            result_dir = os.path.join(self.temp_dir, "results")
            os.makedirs(result_dir, exist_ok=True)
            
            cmd = [
                "python", "-m", "scripts.inference",
                "--inference_config", config_path,
                "--version", self.version,
                "--result_dir", result_dir,
                "--batch_size", "8"
            ]
            
            if self.version == "v15":
                cmd.extend([
                    "--unet_model_path", "models/musetalkV15/unet.pth",
                    "--unet_config", "models/musetalkV15/musetalk.json"
                ])
            else:
                cmd.extend([
                    "--unet_model_path", "models/musetalk/pytorch_model.bin",
                    "--unet_config", "models/musetalk/musetalk.json"
                ])
            
            self.logger.info(f"Generating video for audio: {audio_path}")
            
            # Execute inference
            result = subprocess.run(
                cmd,
                cwd=self.musetalk_project_path,
                capture_output=True,
                text=True,
                timeout=120  # 2 minute timeout per inference
            )
            
            if result.returncode == 0:
                # Find generated video
                video_path = os.path.join(result_dir, self.version, f"{output_name}.mp4")
                if os.path.exists(video_path):
                    self.logger.info(f"Video generated successfully: {video_path}")
                    return video_path
                else:
                    self.logger.error(f"Generated video not found at expected path: {video_path}")
                    return None
            else:
                self.logger.error(f"Video generation failed: {result.stderr}")
                return None
                
        except subprocess.TimeoutExpired:
            self.logger.error("Video generation timed out")
            return None
        except Exception as e:
            self.logger.error(f"Error during video generation: {e}")
            return None
    
    def generate_video_batch(self, audio_paths, output_names=None):
        """
        Generate multiple videos from multiple audio files in batch.
        
        Args:
            audio_paths (list): List of audio file paths
            output_names (list): Optional list of output names
            
        Returns:
            list: List of generated video paths
        """
        if output_names is None:
            output_names = [f"batch_output_{i}_{int(time.time())}" for i in range(len(audio_paths))]
        
        if len(audio_paths) != len(output_names):
            raise ValueError("Number of audio paths must match number of output names")
        
        # Create batch configuration
        batch_config = {}
        for i, (audio_path, output_name) in enumerate(zip(audio_paths, output_names)):
            task_key = f"task_{i}"
            batch_config[task_key] = {
                "video_path": self.avatar_video_path,
                "audio_path": os.path.abspath(audio_path),
                "result_name": f"{output_name}.mp4"
            }
            
            if self.version == "v1":
                batch_config[task_key]["bbox_shift"] = 0
        
        config_path = os.path.join(self.temp_dir, f"batch_config_{int(time.time())}.yaml")
        with open(config_path, 'w') as f:
            yaml.dump(batch_config, f)
        
        # Execute batch inference
        result_dir = os.path.join(self.temp_dir, "batch_results")
        os.makedirs(result_dir, exist_ok=True)
        
        cmd = [
            "python", "-m", "scripts.inference",
            "--inference_config", config_path,
            "--version", self.version,
            "--result_dir", result_dir,
            "--batch_size", "8"
        ]
        
        if self.version == "v15":
            cmd.extend([
                "--unet_model_path", "models/musetalkV15/unet.pth",
                "--unet_config", "models/musetalkV15/musetalk.json"
            ])
        else:
            cmd.extend([
                "--unet_model_path", "models/musetalk/pytorch_model.bin",
                "--unet_config", "models/musetalk/musetalk.json"
            ])
        
        try:
            self.logger.info(f"Generating {len(audio_paths)} videos in batch")
            
            result = subprocess.run(
                cmd,
                cwd=self.musetalk_project_path,
                capture_output=True,
                text=True,
                timeout=300  # 5 minute timeout for batch
            )
            
            if result.returncode == 0:
                # Collect generated videos
                generated_videos = []
                for output_name in output_names:
                    video_path = os.path.join(result_dir, self.version, f"{output_name}.mp4")
                    if os.path.exists(video_path):
                        generated_videos.append(video_path)
                    else:
                        generated_videos.append(None)
                
                self.logger.info(f"Batch generation completed. {len([v for v in generated_videos if v])} videos generated successfully")
                return generated_videos
            else:
                self.logger.error(f"Batch generation failed: {result.stderr}")
                return [None] * len(audio_paths)
                
        except subprocess.TimeoutExpired:
            self.logger.error("Batch generation timed out")
            return [None] * len(audio_paths)
        except Exception as e:
            self.logger.error(f"Error during batch generation: {e}")
            return [None] * len(audio_paths)
    
    def _create_dummy_audio(self, output_path, duration=1.0):
        """Create a dummy audio file for preparation"""
        try:
            cmd = [
                "ffmpeg", "-f", "lavfi", "-i", f"sine=frequency=1000:duration={duration}",
                "-ar", "16000", "-ac", "1", "-y", output_path
            ]
            
            result = subprocess.run(cmd, capture_output=True, text=True)
            if result.returncode != 0:
                self.logger.error(f"Failed to create dummy audio: {result.stderr}")
                return False
            return True
            
        except Exception as e:
            self.logger.error(f"Error creating dummy audio: {e}")
            return False
    
    def cleanup(self):
        """Clean up temporary files"""
        try:
            if os.path.exists(self.temp_dir):
                shutil.rmtree(self.temp_dir)
                self.logger.info("Temporary files cleaned up")
        except Exception as e:
            self.logger.error(f"Error during cleanup: {e}")
    
    def __del__(self):
        """Destructor to ensure cleanup"""
        self.cleanup()

# Example usage and testing
if __name__ == "__main__":
    # Test the wrapper
    wrapper = MuseTalkWrapper(
        avatar_video_path="data/video/yongen.mp4",
        musetalk_project_path=".",
        version="v15"
    )
    
    # Test single video generation
    video_path = wrapper.generate_video_from_audio("data/audio/yongen.wav")
    if video_path:
        print(f"Generated video: {video_path}")
    else:
        print("Failed to generate video")
    
    # Cleanup
    wrapper.cleanup()