import os
import json
from datetime import datetime
from pathlib import Path
from openai import OpenAI
from watchdog.observers import Observer
from watchdog.events import FileSystemEventHandler

class DialogSummarizer:
    """Handles summarization of dialog text using OpenAI."""
    
    def __init__(self, temp_dir):
        """Initialize the dialog summarizer."""
        # Set up paths
        self.temp_dir = Path(temp_dir)
        self.captured_text_file = self.temp_dir / 'captured_text.txt'
        self.summaries_dir = self.temp_dir / 'summaries'
        self.summaries_dir.mkdir(exist_ok=True)
        
        # Initialize OpenAI client
        self.client = OpenAI()
        
        # Initialize state
        self.current_text = ''
        self.last_summary_time = datetime.now()
        
    def summarize_text(self, text):
        """Summarize the given text using OpenAI."""
        try:
            # Skip if text is too short
            if len(text.strip()) < 50:
                return None
                
            # Get previous summaries
            previous_dialogs = []
            if self.summaries_dir.exists():
                for summary_file in sorted(self.summaries_dir.glob('summary_*.txt')):
                    with open(summary_file) as f:
                        data = json.load(f)
                        if 'summary' in data:
                            previous_dialogs.append(data['summary'])
                            
            # Read prompt template
            prompt_file = Path(__file__).parent / 'prompts' / 'summarize_dialog.txt'
            with open(prompt_file) as f:
                prompt_template = f.read()
                
            # Format prompt
            prompt = prompt_template.replace('CAPTURED_TEXT', text)
            prompt = prompt.replace('PREVIOUS_DIALOGS', '\n'.join(previous_dialogs))
            
            # Call OpenAI API
            response = self.client.chat.completions.create(
                model="gpt-4",
                messages=[
                    {"role": "user", "content": prompt}
                ],
                max_tokens=200,
                temperature=0.7
            )
            
            # Parse response as JSON
            response_text = response.choices[0].message.content.strip()
            response_data = json.loads(response_text)
            
            # Get new dialog lines
            new_dialogs = response_data.get('dialog', [])
            if not new_dialogs:
                return None
                
            # Save summary
            timestamp = datetime.now().strftime('%Y%m%d_%H%M%S')
            summary_file = self.summaries_dir / f'summary_{timestamp}.txt'
            
            with open(summary_file, 'w') as f:
                json.dump({
                    'timestamp': timestamp,
                    'original_text': text,
                    'summary': '\n'.join(new_dialogs)
                }, f, indent=2)
                
            return '\n'.join(new_dialogs)
            
        except Exception as e:
            print(f"Error summarizing text: {e}")
            return None
            
    def process_captured_text(self):
        """Process newly captured text."""
        try:
            # Read current text
            if not self.captured_text_file.exists():
                return
                
            text = self.captured_text_file.read_text().strip()
            
            # Skip if no new text
            if text == self.current_text:
                return
                
            # Update current text
            self.current_text = text
            
            # Summarize text
            summary = self.summarize_text(text)
            if summary:
                print(f"Generated summary: {summary}")
                
        except Exception as e:
            print(f"Error processing captured text: {e}")
            
class DialogFileHandler(FileSystemEventHandler):
    """Handles file system events for dialog text file."""
    
    def __init__(self, summarizer):
        """Initialize the file handler."""
        self.summarizer = summarizer
        
    def on_modified(self, event):
        """Handle file modification events."""
        if event.src_path == str(self.summarizer.captured_text_file):
            self.summarizer.process_captured_text()
            
class DialogObserver:
    """Observes dialog text file for changes."""
    
    def __init__(self, temp_dir):
        """Initialize the dialog observer."""
        self.summarizer = DialogSummarizer(temp_dir)
        self.event_handler = DialogFileHandler(self.summarizer)
        self.observer = Observer()
        
    def start(self):
        """Start observing the dialog text file."""
        self.observer.schedule(
            self.event_handler,
            str(self.summarizer.temp_dir),
            recursive=False
        )
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
