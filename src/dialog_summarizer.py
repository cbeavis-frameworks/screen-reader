import os
import sys
import json
import asyncio
from datetime import datetime
from pathlib import Path
from openai import OpenAI
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
        self.dialogs_dir.mkdir(exist_ok=True)
        
        # Initialize OpenAI client
        self.client = OpenAI()
        
        # Initialize state
        self.current_text = ''
        self.last_summary_time = datetime.now()
        self.summarization_in_progress = False
        self.text_changed_during_summarization = False
        self.lock = asyncio.Lock()
        
    async def summarize_text(self, text):
        """Summarize the given text using OpenAI."""
        try:
            # Skip if text is too short
            if len(text.strip()) < 50:
                return None
                
            # Get previous dialogs
            previous_dialogs = []
            if self.dialogs_dir.exists():
                for dialog_file in sorted(self.dialogs_dir.glob('dialog_*.txt')):
                    with open(dialog_file) as f:
                        previous_dialogs.append(f.read().strip())
                            
            # Read prompt template
            prompt_file = Path(__file__).parent / 'prompts' / 'summarize_dialog.txt'
            with open(prompt_file) as f:
                prompt_template = f.read()
                
            # Format prompt
            prompt = prompt_template.replace('CAPTURED_TEXT', text)
            prompt = prompt.replace('PREVIOUS_DIALOGS', '\n'.join(previous_dialogs[-5:]))  # Only use last 5 dialogs
            
            print(f"\n[DIALOG] Previous dialogs ({len(previous_dialogs)}):")
            for i, dialog in enumerate(previous_dialogs):
                print(f"\nDialog {i+1}:\n{dialog}")
            
            print(f"\n[DIALOG] Sending prompt to OpenAI:")
            print(prompt)
            
            # Call OpenAI API
            response = self.client.chat.completions.create(
                model="gpt-4o",
                response_format={"type": "json_object"},
                messages=[
                    {"role": "user", "content": prompt}
                ],
                max_tokens=300,
                temperature=0.5
            )
            
            # Parse response as JSON
            response_text = response.choices[0].message.content.strip()
            try:
                response_data = json.loads(response_text)
            except json.JSONDecodeError:
                print(f"Error parsing OpenAI response as JSON: {response_text}")
                return None
            
            print(f"\n[DIALOG] Raw response:\n{response_text}\n")
            
            # Get new dialog lines
            new_dialogs = response_data.get('dialog', [])
            if not new_dialogs:
                return None
                
            # Save each dialog line to a timestamped file
            timestamp = datetime.now().strftime('%Y%m%d_%H%M%S')
            for i, dialog in enumerate(new_dialogs):
                dialog_file = self.dialogs_dir / f'dialog_{timestamp}_{i:03d}.txt'
                with open(dialog_file, 'w') as f:
                    f.write(dialog)
                
            print(f"[DIALOG] Saved dialog to {dialog_file.name}")
            return new_dialogs
            
        except Exception as e:
            print(f"Error summarizing text: {e}")
            return None
            
    async def process_captured_text(self):
        """Process newly captured text."""
        try:
            async with self.lock:
                # Check if summarization is already in progress
                if self.summarization_in_progress:
                    self.text_changed_during_summarization = True
                    return
                
                # Read current text
                if not self.captured_text_file.exists():
                    return
                    
                text = self.captured_text_file.read_text().strip()
                
                # Skip if no new text
                if text == self.current_text:
                    return
                
                # Update current text and mark summarization as in progress
                self.current_text = text
                self.summarization_in_progress = True
                
            try:
                # Process text
                dialogs = await self.summarize_text(text)
                if dialogs:
                    print(f"New dialogs extracted: {len(dialogs)}")
                    
            finally:
                async with self.lock:
                    self.summarization_in_progress = False
                    
                    # If text changed during summarization, process it again
                    if self.text_changed_during_summarization:
                        self.text_changed_during_summarization = False
                        await self.process_captured_text()
                    
        except Exception as e:
            print(f"Error processing captured text: {e}")
            async with self.lock:
                self.summarization_in_progress = False
                
class DialogFileHandler(FileSystemEventHandler):
    """Handles file system events for dialog text file."""
    
    def __init__(self, summarizer):
        """Initialize the file handler."""
        super().__init__()
        self.summarizer = summarizer
        self.loop = asyncio.get_event_loop()
        
    def on_modified(self, event):
        """Handle file modification events."""
        if event.src_path == str(self.summarizer.captured_text_file):
            self.loop.create_task(self.summarizer.process_captured_text())
            
    def on_created(self, event):
        """Handle file creation events."""
        if event.src_path == str(self.summarizer.captured_text_file):
            self.loop.create_task(self.summarizer.process_captured_text())
            
class DialogObserver:
    """Observes dialog text file for changes."""
    
    def __init__(self, output_dir):
        """Initialize the dialog observer."""
        self.summarizer = DialogSummarizer(output_dir)
        self.event_handler = DialogFileHandler(self.summarizer)
        self.observer = Observer()
        
    def start(self):
        """Start observing the dialog text file."""
        # Watch the directory containing the captured text file
        watch_dir = str(self.summarizer.captured_text_file.parent)
        self.observer.schedule(self.event_handler, watch_dir, recursive=False)
        self.observer.start()
        
    def stop(self):
        """Stop observing the dialog text file."""
        self.observer.stop()
        self.observer.join()

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
