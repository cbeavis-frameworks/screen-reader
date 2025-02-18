import os
import asyncio
import queue
import threading
import shutil
import subprocess
from pathlib import Path
from typing import Optional, Tuple, Set
from elevenlabs import stream
from elevenlabs.client import ElevenLabs
from dotenv import load_dotenv
from datetime import datetime
import time

class TTSStreamer:
    def __init__(self, voice_name: Optional[str] = None):
        """Initialize the TTS streamer with ElevenLabs integration.
        
        Args:
            voice_name: Name of the ElevenLabs voice to use. If None, uses the first available voice.
        """
        # Load environment variables
        load_dotenv()
        api_key = os.getenv("ELEVENLABS_API_KEY")
        if not api_key:
            raise ValueError("ELEVENLABS_API_KEY not found in environment variables")
        
        # Initialize ElevenLabs client
        self.client = ElevenLabs(api_key=api_key)
        
        # Initialize voice
        voices_response = self.client.voices.get_all()
        self.available_voices = voices_response.voices
        
        if not self.available_voices:
            raise ValueError("No voices available in your ElevenLabs account")
            
        if voice_name:
            self.voice = next((v for v in self.available_voices if v.name == voice_name), None)
            if not self.voice:
                raise ValueError(f"Voice '{voice_name}' not found")
        else:
            self.voice = self.available_voices[0]
            
        # Initialize queue and state
        self.dialog_queue = asyncio.Queue()
        self.is_speaking = False
        self.should_stop = False
        self.processed_files = set()  # Track processed files
        self.original_mic_volume = None
        
        # Set up debug log file
        self.base_dir = Path(__file__).parent.parent
        self.debug_log_file = self.base_dir / "output" / "debug.log"
        
        # Start the processing loop
        self.loop = asyncio.new_event_loop()
        self.thread = threading.Thread(target=self._run_event_loop, daemon=True)
        self.thread.start()

    def _log_message(self, message: str):
        """Log a message to the debug log file."""
        try:
            # Get timestamp
            timestamp = datetime.now().strftime("%Y-%m-%d %H:%M:%S")
            
            # Format message
            log_entry = f"[{timestamp}] [TTS] {message}\n"
            
            # Write to file
            with open(self.debug_log_file, 'a') as f:
                f.write(log_entry)
                
        except Exception as e:
            print(f"Error logging message: {str(e)}")

    def _toggle_voice_control(self, enable: bool):
        """Toggle macOS Voice Control listening state using AXUIElement.
        
        Args:
            enable: True to start listening, False to stop listening
        """
        try:
            script = '''
            tell application "System Events"
                set frontmost of process "ControlCenter" to true
                tell process "ControlCenter"
                    -- Find the Voice Control menu item by cycling through all menu items
                    repeat with i from 1 to count of menu bar items of menu bar 1
                        set currentItem to menu bar item i of menu bar 1
                        try
                            -- Try to get the description of the menu item
                            set itemDesc to description of currentItem
                            if itemDesc contains "Voice Control" then
                                -- Found the Voice Control menu item
                                click currentItem
                                delay 0.5
                                -- Click the appropriate menu item
                                click menu item "''' + ('Start' if enable else 'Stop') + ''' Listening" of menu 1 of currentItem
                                return true
                            end if
                        end try
                    end repeat
                end tell
            end tell
            '''
            
            result = subprocess.run(['osascript', '-e', script], capture_output=True, text=True)
            status = "started" if enable else "stopped"
            self._log_message(f"Voice Control {status} listening command (exit code: {result.returncode})")
            if result.stderr:
                self._log_message(f"Voice Control {status} error: {result.stderr}")
            else:
                self._log_message(f"Voice Control successfully {status} listening")
        except Exception as e:
            self._log_message(f"Error controlling Voice Control: {e}")

    def _get_mic_volume(self) -> int:
        """Get the current microphone input volume.
        
        Returns:
            Current microphone volume (0-100) or None if error
        """
        try:
            script = '''
            tell application "System Events"
                get input volume of (get volume settings)
            end tell
            '''
            result = subprocess.run(['osascript', '-e', script], capture_output=True, text=True)
            if result.returncode == 0:
                return int(result.stdout.strip())
        except Exception as e:
            self._log_message(f"Error getting microphone volume: {e}")
        return None

    def _mute_microphone(self):
        """Mute the microphone by setting input volume to 0.
        First saves the current volume if not already saved."""
        try:
            # Only save the original volume if we haven't already
            if self.original_mic_volume is None:
                self.original_mic_volume = self._get_mic_volume()
                if self.original_mic_volume is None:
                    self.original_mic_volume = 50  # Default fallback value
                self._log_message(f"Saved original microphone volume: {self.original_mic_volume}")
            
            # Set input volume to 0
            script = '''
            tell application "System Events"
                set volume input volume 0
            end tell
            '''
            result = subprocess.run(['osascript', '-e', script], capture_output=True, text=True)
            if result.returncode == 0:
                self._log_message("Microphone muted")
            else:
                self._log_message(f"Error muting microphone: {result.stderr}")
        except Exception as e:
            self._log_message(f"Error muting microphone: {e}")

    def _restore_microphone(self):
        """Restore the microphone to its original volume."""
        try:
            if self.original_mic_volume is not None:
                script = f'''
                tell application "System Events"
                    set volume input volume {self.original_mic_volume}
                end tell
                '''
                result = subprocess.run(['osascript', '-e', script], capture_output=True, text=True)
                if result.returncode == 0:
                    self._log_message(f"Restored microphone volume to {self.original_mic_volume}")
                else:
                    self._log_message(f"Error restoring microphone: {result.stderr}")
        except Exception as e:
            self._log_message(f"Error restoring microphone: {e}")

    def _run_event_loop(self):
        """Run the async event loop in a separate thread."""
        asyncio.set_event_loop(self.loop)
        self.loop.run_until_complete(self._process_queue())

    async def _process_queue(self):
        """Process the dialog queue and stream audio."""
        while not self.should_stop:
            try:
                if not self.is_speaking:
                    # Get the next dialog from the queue
                    dialog_text, dialog_file = await self.dialog_queue.get()
                    
                    # Skip if already processed
                    if str(dialog_file) in self.processed_files:
                        self.dialog_queue.task_done()
                        continue
                        
                    self.is_speaking = True
                    # Disable Voice Control before playing
                    self._log_message("Starting audio playback, disabling Voice Control...")
                    self._toggle_voice_control(False)
                    
                    try:
                        # Mute microphone before TTS playback
                        self._mute_microphone()
                        
                        # Generate audio stream using the selected voice
                        audio_stream = self.client.text_to_speech.convert_as_stream(
                            text=dialog_text,
                            voice_id=self.voice.voice_id,
                            model_id="eleven_multilingual_v2",
                            output_format="mp3_44100_128",
                            optimize_streaming_latency=2  # Strong latency optimizations
                        )
                        
                        # Stream the audio in real-time
                        stream(audio_stream)
                        
                        # Add to processed set before moving
                        self.processed_files.add(str(dialog_file))
                        
                        # Move the file to played directory after successful playback
                        played_path = dialog_file.parent / "played" / dialog_file.name
                        if dialog_file.exists():  # Check if file still exists
                            shutil.move(str(dialog_file), str(played_path))
                        
                    except Exception as e:
                        self._log_message(f"Error streaming audio: {e}")
                    finally:
                        # Always restore microphone after TTS playback, even if there was an error
                        self._restore_microphone()
                        # Re-enable Voice Control after playing
                        self._log_message("Audio playback finished, re-enabling Voice Control...")
                        self._toggle_voice_control(True)
                        self.is_speaking = False
                        self.dialog_queue.task_done()
                        
                else:
                    # If currently speaking, wait a bit before checking again
                    await asyncio.sleep(0.1)
                    
            except asyncio.CancelledError:
                break
            except Exception as e:
                self._log_message(f"Error in queue processing: {e}")
                await asyncio.sleep(1)  # Wait before retrying

    def add_dialog(self, text: str, dialog_file: Path):
        """Add a new dialog to the queue for TTS processing.
        
        Args:
            text: The text to convert to speech
            dialog_file: Path to the dialog file being processed
        """
        # Only add if not already processed
        if str(dialog_file) not in self.processed_files:
            asyncio.run_coroutine_threadsafe(
                self.dialog_queue.put((text, dialog_file)),
                self.loop
            )

    def get_available_voices(self) -> list:
        """Get list of available ElevenLabs voices.
        
        Returns:
            List of available voices
        """
        return self.available_voices

    def change_voice(self, voice_name: str):
        """Change the current voice.
        
        Args:
            voice_name: Name of the voice to switch to
        
        Raises:
            ValueError: If the voice name is not found
        """
        new_voice = next((v for v in self.available_voices if v.name == voice_name), None)
        if not new_voice:
            raise ValueError(f"Voice '{voice_name}' not found")
        self.voice = new_voice

    def stop(self):
        """Stop the TTS streamer and cleanup resources."""
        self.should_stop = True
        if self.loop:
            self.loop.stop()
        if self.thread:
            self.thread.join(timeout=1.0)
