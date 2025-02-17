from typing import List
import time
import json
from pathlib import Path
import os

class ChatMonitor:
    def __init__(self, output_dir: str = None):
        self.seen_messages = set()  # Store message hashes
        self.recent_messages = []   # Keep track of recent messages for context
        self.max_recent = 10        # Maximum number of recent messages to keep
        
        # Setup output directory and file
        if output_dir:
            self.output_dir = Path(output_dir)
        else:
            self.output_dir = Path(__file__).parent.parent / "output"
            
        self.output_dir.mkdir(exist_ok=True)
        self.captured_text_file = self.output_dir / "captured_text.txt"
        
        # Create file if it doesn't exist
        if not self.captured_text_file.exists():
            self.captured_text_file.touch()
        
    def _normalize_message(self, text: str) -> str:
        """Normalize message text to help with deduplication."""
        # Remove extra whitespace and make lowercase
        text = ' '.join(text.lower().split())
        # Remove punctuation except periods
        text = ''.join(c for c in text if c.isalnum() or c.isspace() or c == '.')
        return text
        
    def _is_duplicate(self, text: str) -> bool:
        """Check if a message is a duplicate using normalized text."""
        normalized = self._normalize_message(text)
        
        # Check exact duplicates
        if normalized in self.seen_messages:
            return True
            
        # Check for near duplicates in recent messages
        for recent in self.recent_messages:
            if self._is_similar(normalized, self._normalize_message(recent)):
                return True
                
        return False
        
    def _is_similar(self, text1: str, text2: str) -> bool:
        """Check if two normalized messages are very similar."""
        # If one is a substring of the other
        if text1 in text2 or text2 in text1:
            return True
            
        # Split into words and check overlap
        words1 = set(text1.split())
        words2 = set(text2.split())
        overlap = len(words1.intersection(words2))
        total = len(words1.union(words2))
        
        # If more than 80% of words are the same
        if total > 0 and overlap / total > 0.8:
            return True
            
        return False
        
    def process_text(self, new_text: str) -> str:
        """Process new text from the OCR, removing duplicates."""
        if new_text == "NO_NEW_MESSAGES":
            return ""
            
        # Clean up the text
        new_text = new_text.strip()
        if not new_text:
            return ""
            
        # Don't deduplicate timestamp headers
        if new_text.startswith("### "):
            try:
                with open(self.captured_text_file, 'a') as f:
                    f.write(f"{new_text}\n")
            except Exception as e:
                print(f"Error writing to captured text file: {str(e)}")
            return new_text
            
        # Check for duplicates
        if self._is_duplicate(new_text):
            return ""
            
        # Add to seen messages and recent messages
        normalized = self._normalize_message(new_text)
        self.seen_messages.add(normalized)
        
        self.recent_messages.append(new_text)
        if len(self.recent_messages) > self.max_recent:
            self.recent_messages.pop(0)
            
        # Log the message
        try:
            with open(self.captured_text_file, 'a') as f:
                f.write(f"{new_text}\n")
        except Exception as e:
            print(f"Error writing to captured text file: {str(e)}")
            
        return new_text
            
    def get_context(self) -> dict:
        """Get context for the OpenAI prompt."""
        return {
            "RECENT_TEXT": " ".join(self.recent_messages)  # Last recent messages
        }

    def clear_history(self):
        """Clear message history."""
        self.seen_messages.clear()
        self.recent_messages.clear()
        
        # Create a backup of the current log file if it exists
        if self.captured_text_file.exists() and self.captured_text_file.stat().st_size > 0:
            timestamp = time.strftime('%Y%m%d_%H%M%S')
            backup_file = self.output_dir / f"captured_text_backup_{timestamp}.txt"
            os.rename(self.captured_text_file, backup_file)
            
        # Create a new empty log file
        self.captured_text_file.touch()

    def get_log_file_path(self) -> Path:
        """Return the path to the current log file."""
        return self.captured_text_file

    def get_recent_text(self) -> str:
        """Get recent text from captured text file."""
        try:
            if self.captured_text_file.exists():
                with open(self.captured_text_file, 'r') as f:
                    # Get last 50 lines
                    lines = f.readlines()[-50:]
                    return ''.join(lines).strip()
            return ""
        except Exception as e:
            print(f"Error reading recent text: {str(e)}")
            return ""
            
    def get_prompt_with_context(self, prompt_template: str) -> str:
        """Get the prompt template with recent chat context."""
        try:
            # Get recent text
            recent_text = self.get_recent_text()
            
            # Find the position between the backticks
            start = prompt_template.find("``` recent text")
            end = prompt_template.find("```", start + 14)  # Start after first ```
            
            if start != -1 and end != -1:
                # Replace everything between the backticks
                before = prompt_template[:start + 14]  # Include "``` recent text"
                after = prompt_template[end:]  # Include closing ```
                prompt = before + "\n\n" + recent_text + "\n\n" + after
            else:
                # Fallback: just replace the placeholder
                prompt = prompt_template.replace("RECENT_TEXT", recent_text)
            
            return prompt
            
        except Exception as e:
            print(f"Error getting chat context: {str(e)}")
            return prompt_template
            
    def clean_json_response(self, response: str) -> str:
        """Clean JSON response from OpenAI."""
        # Remove markdown code blocks if present
        response = response.strip()
        if response.startswith("```json"):
            response = response[7:]
        if response.startswith("```"):
            response = response[3:]
        if response.endswith("```"):
            response = response[:-3]
            
        return response.strip()
            
    def process_response(self, response: str) -> str:
        """Process the OpenAI response."""
        if not response:
            return None
            
        try:
            # Clean and parse JSON response
            json_str = self.clean_json_response(response)
            data = json.loads(json_str)
            
            # Get text array
            text_lines = data.get('text', [])
            
            # Skip if no new text
            if not text_lines:
                return None
                
            # Join lines and append to file
            new_text = "\n".join(text_lines)
            if new_text:
                try:
                    with open(self.captured_text_file, 'a') as f:
                        f.write(new_text + "\n")
                except Exception as e:
                    print(f"Error writing to captured text file: {str(e)}")
                    
            return new_text
            
        except json.JSONDecodeError as e:
            print(f"Error parsing JSON response: {str(e)}")
            print(f"Raw response: {response}")
            return None
        except Exception as e:
            print(f"Error processing response: {str(e)}")
            return None
