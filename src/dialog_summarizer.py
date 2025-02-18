import os
import sys
import json
import asyncio
import threading
import time
from datetime import datetime
from pathlib import Path
from openai import AsyncOpenAI
from watchdog.observers import Observer
from watchdog.events import FileSystemEventHandler

# Add parent directory to path for imports
sys.path.insert(0, str(Path(__file__).parent.parent))

__all__ = ['DialogSummarizer', 'DialogObserver']

class DialogSummarizer:
    """Handles summarization of dialog text using OpenAI."""
    
    def __init__(self, output_dir):
        """Initialize the dialog summarizer."""
        # Set up paths
        self.output_dir = Path(output_dir)
        self.captured_text_file = self.output_dir / 'captured_text.txt'
        self.dialogs_dir = self.output_dir / 'dialogs'
        self.prompts_dir = self.output_dir / 'summarize'
        
        # Create directories
        self.dialogs_dir.mkdir(exist_ok=True)
        self.prompts_dir.mkdir(exist_ok=True)
        
        # Clear all files in prompts directory
        for file in self.prompts_dir.glob("*"):
            try:
                file.unlink()
            except Exception as e:
                print(f"[DIALOG] Failed to delete {file}: {e}")
                
        # Initialize OpenAI client
        self.api_key = os.getenv('OPENAI_API_KEY')
        if not self.api_key:
            raise ValueError("OPENAI_API_KEY environment variable not set")
        self.client = AsyncOpenAI(api_key=self.api_key)
        
        # Load prompt template
        prompt_path = Path(__file__).parent / "prompts" / "summarize_dialog.txt"
        if not prompt_path.exists():
            raise FileNotFoundError(f"Prompt file not found: {prompt_path}")
        with open(prompt_path) as f:
            self.prompt_template = f.read()
            
        # Initialize state
        self.current_text = ''
        self.summarization_in_progress = False
        self.last_summary_time = datetime.now()
        self.text_changed_during_summarization = False
        self.lock = asyncio.Lock()
        
    async def get_previous_dialogs(self, max_files=20):
        """Get the most recent dialog files from both unplayed and played directories."""
        if not self.dialogs_dir.exists():
            return []
            
        try:
            # Get list of all dialog files (both unplayed and played)
            dialog_files = sorted(list(self.dialogs_dir.glob('dialog_*.txt')) + 
                               list((self.dialogs_dir / "played").glob('dialog_*.txt')))
            
            # Get the most recent files
            recent_files = dialog_files[-max_files:] if dialog_files else []
            
            # Read the content of each file
            dialogs = []
            for file in recent_files:
                try:
                    with open(file, 'r') as f:
                        content = f.read().strip()
                        if content:
                            # Add each line of content
                            for line in content.split('\n'):
                                if line.strip():
                                    dialogs.append(line.strip())
                                
                except Exception as e:
                    print(f"[DIALOG] Error reading dialog file {file}: {e}")
                    
            return dialogs
            
        except Exception as e:
            print(f"[DIALOG] Error getting previous dialogs: {e}")
            return []
            
    async def summarize_text(self, text):
        """Summarize dialog text and save to a new file."""
        try:
            if not text:
                return []
                
            # Get previous dialogs
            previous_dialogs = await self.get_previous_dialogs()
            print(f"\n[DIALOG] Previous dialogs ({len(previous_dialogs)}):")
            for i, dialog in enumerate(previous_dialogs):
                print(f"\nDialog {i+1}:\n{dialog}")
            
            # Format prompt with previous dialogs and captured text
            prompt = self.prompt_template.replace(
                "PREVIOUS_DIALOGS",
                "\n".join(previous_dialogs) if previous_dialogs else "No previous dialogs"
            ).replace(
                "CAPTURED_TEXT",
                text
            )
            
            print(f"\n[DIALOG] Sending prompt to OpenAI:")
            print(prompt)
            
            # Save prompt to file
            timestamp = datetime.now().strftime("%Y%m%d_%H%M%S")
            prompt_file = self.prompts_dir / f"prompt_{timestamp}.txt"
            with open(prompt_file, 'w') as f:
                f.write(prompt)
            
            # Call OpenAI API
            response = await self.client.chat.completions.create(
                model="gpt-4o",
                response_format={"type": "json_object"},
                messages=[
                    {"role": "user", "content": prompt}
                ],
                max_tokens=300,
                temperature=0.7
            )
            
            # Parse response
            if response.choices and response.choices[0].message:
                content = response.choices[0].message.content.strip()
                print(f"\n[DIALOG] Raw response:\n{content}\n")
                
                try:
                    # Parse JSON response
                    parsed = json.loads(content)
                    
                    # Save response to file
                    response_file = self.prompts_dir / f"response_{timestamp}.txt"
                    with open(response_file, 'w') as f:
                        f.write(json.dumps(parsed, indent=2))
                    
                    if isinstance(parsed, dict) and 'dialog' in parsed:
                        dialog_lines = parsed['dialog']
                        if isinstance(dialog_lines, list) and dialog_lines:
                            # Create timestamped filename
                            dialog_timestamp = datetime.now().strftime("%Y%m%d_%H%M%S")
                            counter = 1
                            while True:
                                filename = f"dialog_{dialog_timestamp}_{counter:03d}.txt"
                                filepath = self.dialogs_dir / filename
                                if not filepath.exists():
                                    break
                                counter += 1
                                
                            # Write dialog lines to file
                            with open(filepath, 'w') as f:
                                for line in dialog_lines:
                                    f.write(f"{line}\n")
                                    
                            print(f"[DIALOG] Saved dialog to {filename}")
                            return dialog_lines  # Return the list of dialog lines
                            
                except json.JSONDecodeError as e:
                    print(f"[DIALOG] Failed to parse JSON response: {e}")
                    return []
                    
            print("[DIALOG] No valid dialog lines found in response")
            return []
            
        except Exception as e:
            print(f"[DIALOG] Error summarizing dialog: {str(e)}")
            return []
            
    async def process_captured_text(self):
        """Process newly captured text."""
        try:
            # Check if summarization is already in progress
            if self.summarization_in_progress:
                print("[DIALOG] Summarization already in progress, skipping")
                return
                
            # Read current text
            if not self.captured_text_file.exists():
                return
                
            with open(self.captured_text_file, 'r') as f:
                current_text = f.read().strip()
                
            if not current_text or current_text == self.current_text:
                return
                
            # Strip timestamps from the captured text
            cleaned_text = []
            for line in current_text.split('\n'):
                line = line.strip()
                if line:
                    # Skip empty lines and timestamp-only lines
                    if line == '' or line.startswith('###'):
                        continue
                    # Remove timestamp if present (multiple formats)
                    if line.startswith('[') and ']' in line:
                        line = line.split(']', 1)[1].strip()
                    cleaned_text.append(line)
            
            cleaned_text = '\n'.join(cleaned_text)
            
            # Update state and set flag
            self.summarization_in_progress = True
            try:
                # Process the cleaned text
                self.current_text = current_text
                await self.summarize_text(cleaned_text)
            finally:
                self.summarization_in_progress = False
                
        except Exception as e:
            print(f"[DIALOG] Error processing captured text: {e}")
            self.summarization_in_progress = False
            
    def start(self):
        """Start monitoring for text changes."""
        try:
            # Create asyncio event loop
            loop = asyncio.new_event_loop()
            asyncio.set_event_loop(loop)
            
            # Run the monitor
            while True:
                try:
                    loop.run_until_complete(self.process_captured_text())
                    time.sleep(1)  # Check every second
                except Exception as e:
                    print(f"Error in monitor loop: {e}")
                    time.sleep(5)  # Wait longer on error
                    
        except Exception as e:
            print(f"Error starting monitor: {e}")
            
class DialogObserver:
    """Observes dialog text file for changes."""
    
    def __init__(self, output_dir):
        """Initialize the dialog observer."""
        self.output_dir = output_dir
        self.summarizer = DialogSummarizer(output_dir)
        self.thread = None
        
    def start(self):
        """Start the dialog observer in a separate thread."""
        if not self.thread:
            self.thread = threading.Thread(target=self.summarizer.start)
            self.thread.daemon = True
            self.thread.start()
            
def start_dialog_summarizer(output_dir):
    """Start the dialog summarizer and observer."""
    try:
        # Create observer
        observer = DialogObserver(output_dir)
        
        # Start observer
        observer.start()
        
        return observer
        
    except Exception as e:
        print(f"Error starting dialog summarizer: {e}")
        return None
