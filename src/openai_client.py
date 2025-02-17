import os
import sys
import base64
import json
from pathlib import Path
from openai import OpenAI, AsyncOpenAI

# Add parent directory to path for imports
sys.path.insert(0, str(Path(__file__).parent.parent))

class OpenAIClient:
    def __init__(self):
        """Initialize the OpenAI client."""
        # Get API key from environment
        self.api_key = os.getenv('OPENAI_API_KEY')
        if not self.api_key:
            raise ValueError("OPENAI_API_KEY environment variable not set")
            
        # Create sync and async clients
        self.client = OpenAI(api_key=self.api_key)
        self.async_client = AsyncOpenAI(api_key=self.api_key)
        
        # Set up paths
        self.base_dir = Path(__file__).parent.parent
        self.output_dir = self.base_dir / "output"
        self.captured_text_file = self.output_dir / "captured_text.txt"
        
        # Load prompt template
        prompt_path = Path(__file__).parent / "prompts" / "analyze_image.txt"
        if not prompt_path.exists():
            raise FileNotFoundError(f"Prompt file not found: {prompt_path}")
            
        with open(prompt_path) as f:
            self.prompt_template = f.read()
        print(f"[OPENAI] Loaded prompt template:\n{self.prompt_template}\n")
            
    def get_recent_text(self, max_lines=50):
        """Get the most recent text from the captured text file."""
        if not self.captured_text_file.exists():
            return ""
            
        try:
            with open(self.captured_text_file, 'r') as f:
                lines = f.readlines()
                # Get last max_lines lines
                recent_lines = lines[-max_lines:] if lines else []
                return ''.join(recent_lines).strip()
        except Exception as e:
            print(f"[OPENAI] Error reading recent text: {e}")
            return ""
            
    async def analyze_image(self, image_data):
        """Analyze an image using OpenAI's Vision API."""
        try:
            # Convert image to base64
            base64_image = base64.b64encode(image_data).decode('utf-8')
            
            # Get recent text
            recent_text = self.get_recent_text()
            print(f"\n[OPENAI] Recent text:\n{recent_text}\n")
            
            # Format prompt with recent text
            prompt = self.prompt_template.replace("RECENT_TEXT", recent_text)
            
            # Format the messages
            messages = [
                {
                    "role": "user",
                    "content": [
                        {
                            "type": "text",
                            "text": prompt
                        },
                        {
                            "type": "image_url",
                            "image_url": {
                                "url": f"data:image/jpeg;base64,{base64_image}"
                            }
                        }
                    ]
                }
            ]
            
            # Print the text content being sent (excluding the base64 image)
            print("\n[OPENAI] Sending message to Vision API:")
            print("Text content:", messages[0]["content"][0]["text"])
            print("Image: <base64_encoded_image_data>")
            
            # Call OpenAI API
            print("[OPENAI] Calling Vision API")
            response = await self.async_client.chat.completions.create(
                model="gpt-4o-mini",
                response_format={"type": "json_object"},
                messages=messages,
                max_tokens=500,
                temperature=0.5
            )
            
            # Parse response
            if response.choices and response.choices[0].message:
                content = response.choices[0].message.content.strip()
                print(f"\n[OPENAI] Raw response:\n{content}\n")
                try:
                    # Parse the JSON response
                    parsed = json.loads(content)
                    if isinstance(parsed, dict) and 'text' in parsed:
                        text_lines = parsed['text']
                        if isinstance(text_lines, list):
                            print(f"[OPENAI] Found {len(text_lines)} lines of text")
                            return text_lines
                        else:
                            print("[OPENAI] Text field is not a list")
                            return None
                    else:
                        print("[OPENAI] Response missing text field")
                        return None
                except json.JSONDecodeError as e:
                    print(f"[OPENAI] Failed to parse JSON response: {e}")
                    return None
            else:
                print("[OPENAI] Empty response received")
                return None
                
        except Exception as e:
            print(f"[OPENAI] Error analyzing image: {str(e)}")
            return None
