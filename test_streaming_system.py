#!/usr/bin/env python3
"""
Test script for MuseTalk Streaming System
This script tests all components of the streaming system to ensure everything works correctly.
"""

import os
import sys
import time
import tempfile
import subprocess
import requests
import json
import asyncio
import websockets
import base64
import logging
from pathlib import Path

# Setup logging
logging.basicConfig(level=logging.INFO, format='%(asctime)s - %(levelname)s - %(message)s')
logger = logging.getLogger(__name__)

class StreamingSystemTester:
    """Test suite for the MuseTalk streaming system"""
    
    def __init__(self):
        self.test_results = {}
        self.api_server_url = "http://localhost:5000"
        self.websocket_url = "ws://localhost:8765"
        
        # Test files (using MuseTalk's default test data)
        self.test_video = "data/video/yongen.mp4"
        self.test_audio = "data/audio/yongen.wav"
        
        logger.info("MuseTalk Streaming System Tester initialized")
    
    def run_all_tests(self):
        """Run all tests in sequence"""
        logger.info("Starting comprehensive test suite...")
        
        # Test 1: Basic wrapper functionality
        self.test_wrapper_basic()
        
        # Test 2: API server functionality
        self.test_api_server()
        
        # Test 3: WebSocket server functionality
        asyncio.run(self.test_websocket_server())
        
        # Print results
        self.print_test_results()
        
        return all(self.test_results.values())
    
    def test_wrapper_basic(self):
        """Test basic wrapper functionality"""
        logger.info("Testing MuseTalkWrapper basic functionality...")
        
        try:
            from musetalk_wrapper import MuseTalkWrapper
            
            # Check if test files exist
            if not os.path.exists(self.test_video):
                logger.error(f"Test video not found: {self.test_video}")
                self.test_results['wrapper_basic'] = False
                return
            
            if not os.path.exists(self.test_audio):
                logger.error(f"Test audio not found: {self.test_audio}")
                self.test_results['wrapper_basic'] = False
                return
            
            # Initialize wrapper
            wrapper = MuseTalkWrapper(
                avatar_video_path=self.test_video,
                musetalk_project_path=".",
                version="v15"
            )
            
            logger.info("Wrapper initialized successfully")
            
            # Test video generation
            logger.info("Testing video generation...")
            video_path = wrapper.generate_video_from_audio(self.test_audio, "test_output")
            
            if video_path and os.path.exists(video_path):
                logger.info(f"Video generated successfully: {video_path}")
                file_size = os.path.getsize(video_path)
                logger.info(f"Generated video size: {file_size} bytes")
                
                if file_size > 1000:  # Basic sanity check
                    self.test_results['wrapper_basic'] = True
                    logger.info("✓ Wrapper basic test PASSED")
                else:
                    self.test_results['wrapper_basic'] = False
                    logger.error("✗ Generated video file too small")
            else:
                self.test_results['wrapper_basic'] = False
                logger.error("✗ Video generation failed")
            
            # Cleanup
            wrapper.cleanup()
            
        except Exception as e:
            logger.error(f"✗ Wrapper basic test FAILED: {e}")
            self.test_results['wrapper_basic'] = False
    
    def test_api_server(self):
        """Test API server functionality"""
        logger.info("Testing API Server functionality...")
        
        try:
            # Check if server is running
            try:
                response = requests.get(f"{self.api_server_url}/health", timeout=5)
                if response.status_code != 200:
                    logger.warning("API server not running, attempting to start...")
                    self.start_api_server()
                    time.sleep(5)  # Wait for server to start
            except requests.exceptions.ConnectionError:
                logger.warning("API server not running, attempting to start...")
                self.start_api_server()
                time.sleep(5)  # Wait for server to start
            
            # Test health endpoint
            response = requests.get(f"{self.api_server_url}/health", timeout=10)
            if response.status_code == 200:
                logger.info("✓ Health endpoint working")
            else:
                raise Exception(f"Health endpoint failed: {response.status_code}")
            
            # Test avatar initialization
            if not os.path.exists(self.test_video):
                raise Exception(f"Test video not found: {self.test_video}")
            
            with open(self.test_video, 'rb') as f:
                files = {'avatar_video': f}
                data = {'avatar_id': 'test_avatar_api', 'version': 'v15'}
                response = requests.post(f"{self.api_server_url}/initialize_avatar", 
                                       files=files, data=data, timeout=60)
            
            if response.status_code == 200:
                result = response.json()
                if result.get('status') == 'success':
                    logger.info("✓ Avatar initialization working")
                else:
                    raise Exception(f"Avatar initialization failed: {result}")
            else:
                raise Exception(f"Avatar initialization request failed: {response.status_code}")
            
            # Test video generation
            if not os.path.exists(self.test_audio):
                raise Exception(f"Test audio not found: {self.test_audio}")
            
            with open(self.test_audio, 'rb') as f:
                files = {'audio_file': f}
                data = {'avatar_id': 'test_avatar_api', 'output_name': 'api_test_output'}
                response = requests.post(f"{self.api_server_url}/generate_video",
                                       files=files, data=data, timeout=120)
            
            if response.status_code == 200:
                # Save the video to verify
                test_output_path = "api_test_output.mp4"
                with open(test_output_path, 'wb') as f:
                    f.write(response.content)
                
                file_size = os.path.getsize(test_output_path)
                logger.info(f"✓ Video generation working (size: {file_size} bytes)")
                
                # Cleanup
                os.unlink(test_output_path)
                
                self.test_results['api_server'] = True
                logger.info("✓ API Server test PASSED")
            else:
                raise Exception(f"Video generation request failed: {response.status_code}")
        
        except Exception as e:
            logger.error(f"✗ API Server test FAILED: {e}")
            self.test_results['api_server'] = False
    
    async def test_websocket_server(self):
        """Test WebSocket server functionality"""
        logger.info("Testing WebSocket Server functionality...")
        
        try:
            # Check if WebSocket server is running
            try:
                websocket = await websockets.connect(self.websocket_url, timeout=5)
                await websocket.close()
            except Exception:
                logger.warning("WebSocket server not running, attempting to start...")
                self.start_websocket_server()
                await asyncio.sleep(5)  # Wait for server to start
            
            # Connect to WebSocket server
            async with websockets.connect(self.websocket_url, timeout=10) as websocket:
                logger.info("✓ WebSocket connection established")
                
                # Wait for connection message
                message = await websocket.recv()
                data = json.loads(message)
                
                if data.get('type') == 'connection_established':
                    client_id = data.get('client_id')
                    logger.info(f"✓ Connection established with client ID: {client_id}")
                else:
                    raise Exception(f"Unexpected connection message: {data}")
                
                # Test avatar initialization
                if not os.path.exists(self.test_video):
                    raise Exception(f"Test video not found: {self.test_video}")
                
                with open(self.test_video, 'rb') as f:
                    video_data = base64.b64encode(f.read()).decode()
                
                init_message = {
                    'type': 'initialize_avatar',
                    'avatar_video_data': video_data,
                    'version': 'v15'
                }
                
                await websocket.send(json.dumps(init_message))
                logger.info("Avatar initialization request sent")
                
                # Wait for initialization response (this may take time)
                timeout_count = 0
                max_timeout = 60  # 60 seconds timeout
                
                while timeout_count < max_timeout:
                    try:
                        message = await asyncio.wait_for(websocket.recv(), timeout=1.0)
                        data = json.loads(message)
                        
                        if data.get('type') == 'avatar_initialized':
                            logger.info("✓ Avatar initialization completed")
                            break
                        elif data.get('type') == 'error':
                            raise Exception(f"Avatar initialization error: {data.get('message')}")
                        else:
                            logger.info(f"Received: {data.get('type', 'unknown')}")
                    
                    except asyncio.TimeoutError:
                        timeout_count += 1
                        if timeout_count % 10 == 0:
                            logger.info(f"Waiting for avatar initialization... ({timeout_count}s)")
                
                if timeout_count >= max_timeout:
                    raise Exception("Avatar initialization timed out")
                
                # Test audio processing
                if not os.path.exists(self.test_audio):
                    raise Exception(f"Test audio not found: {self.test_audio}")
                
                with open(self.test_audio, 'rb') as f:
                    audio_data = base64.b64encode(f.read()).decode()
                
                audio_message = {
                    'type': 'audio_chunk',
                    'audio_data': audio_data
                }
                
                await websocket.send(json.dumps(audio_message))
                logger.info("Audio chunk sent")
                
                # Wait for video response
                timeout_count = 0
                max_timeout = 120  # 2 minutes timeout for video generation
                
                while timeout_count < max_timeout:
                    try:
                        message = await asyncio.wait_for(websocket.recv(), timeout=1.0)
                        data = json.loads(message)
                        
                        if data.get('type') == 'video_chunk':
                            video_data = data.get('video_data')
                            if video_data:
                                # Save video to verify
                                video_bytes = base64.b64decode(video_data)
                                test_output_path = "websocket_test_output.mp4"
                                
                                with open(test_output_path, 'wb') as f:
                                    f.write(video_bytes)
                                
                                file_size = os.path.getsize(test_output_path)
                                logger.info(f"✓ Video generation working (size: {file_size} bytes)")
                                
                                # Cleanup
                                os.unlink(test_output_path)
                                
                                self.test_results['websocket_server'] = True
                                logger.info("✓ WebSocket Server test PASSED")
                                return
                            else:
                                raise Exception("Received empty video data")
                        
                        elif data.get('type') == 'error':
                            raise Exception(f"Video generation error: {data.get('message')}")
                        
                        else:
                            logger.info(f"Received: {data.get('type', 'unknown')}")
                    
                    except asyncio.TimeoutError:
                        timeout_count += 1
                        if timeout_count % 30 == 0:
                            logger.info(f"Waiting for video generation... ({timeout_count}s)")
                
                if timeout_count >= max_timeout:
                    raise Exception("Video generation timed out")
        
        except Exception as e:
            logger.error(f"✗ WebSocket Server test FAILED: {e}")
            self.test_results['websocket_server'] = False
    
    def start_api_server(self):
        """Start API server in background"""
        try:
            logger.info("Starting API server...")
            subprocess.Popen([sys.executable, "api_server.py"], 
                           stdout=subprocess.DEVNULL, 
                           stderr=subprocess.DEVNULL)
        except Exception as e:
            logger.error(f"Failed to start API server: {e}")
    
    def start_websocket_server(self):
        """Start WebSocket server in background"""
        try:
            logger.info("Starting WebSocket server...")
            subprocess.Popen([sys.executable, "streaming_server.py"], 
                           stdout=subprocess.DEVNULL, 
                           stderr=subprocess.DEVNULL)
        except Exception as e:
            logger.error(f"Failed to start WebSocket server: {e}")
    
    def print_test_results(self):
        """Print comprehensive test results"""
        logger.info("\n" + "="*60)
        logger.info("TEST RESULTS SUMMARY")
        logger.info("="*60)
        
        total_tests = len(self.test_results)
        passed_tests = sum(1 for result in self.test_results.values() if result)
        
        for test_name, result in self.test_results.items():
            status = "✓ PASSED" if result else "✗ FAILED"
            logger.info(f"{test_name.replace('_', ' ').title()}: {status}")
        
        logger.info("-"*60)
        logger.info(f"Total Tests: {total_tests}")
        logger.info(f"Passed: {passed_tests}")
        logger.info(f"Failed: {total_tests - passed_tests}")
        logger.info(f"Success Rate: {(passed_tests/total_tests)*100:.1f}%")
        
        if passed_tests == total_tests:
            logger.info("🎉 ALL TESTS PASSED! The streaming system is working correctly.")
        else:
            logger.warning("⚠️  Some tests failed. Check the logs above for details.")
        
        logger.info("="*60)

def main():
    """Main test function"""
    print("MuseTalk Streaming System Test Suite")
    print("="*50)
    
    # Check prerequisites
    if not os.path.exists("musetalk_wrapper.py"):
        print("❌ musetalk_wrapper.py not found. Run this script from the streaming system directory.")
        return False
    
    if not os.path.exists("data/video/yongen.mp4"):
        print("❌ Test video not found. Make sure you're in the MuseTalk project directory.")
        print("   Expected: data/video/yongen.mp4")
        return False
    
    if not os.path.exists("data/audio/yongen.wav"):
        print("❌ Test audio not found. Make sure you're in the MuseTalk project directory.")
        print("   Expected: data/audio/yongen.wav")
        return False
    
    # Run tests
    tester = StreamingSystemTester()
    success = tester.run_all_tests()
    
    return success

if __name__ == "__main__":
    try:
        success = main()
        sys.exit(0 if success else 1)
    except KeyboardInterrupt:
        print("\n\nTest interrupted by user.")
        sys.exit(1)
    except Exception as e:
        print(f"\n\nUnexpected error: {e}")
        sys.exit(1)