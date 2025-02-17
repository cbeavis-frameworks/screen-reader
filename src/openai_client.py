import os
import json
from pathlib import Path
import aiohttp
import base64
import openai

class OpenAIClient:
    def __init__(self):
        """Initialize OpenAI client."""
        # Get API key from environment
        self.api_key = os.getenv('OPENAI_API_KEY')
        if not self.api_key:
            print("[ERROR] OPENAI_API_KEY not found in environment")
            raise ValueError("OPENAI_API_KEY environment variable not set")
            
        # Configure OpenAI
        openai.api_key = self.api_key
        
        # Load prompt template
        prompt_path = Path(__file__).parent / "prompts" / "analyze_image.txt"
        if not prompt_path.exists():
            print(f"[ERROR] Prompt file not found: {prompt_path}")
            raise FileNotFoundError(f"Prompt file not found: {prompt_path}")
            
        with open(prompt_path, 'r') as f:
            self.prompt_template = f.read().strip()
            
    async def analyze_image(self, image_data: bytes) -> str:
        """Analyze image using OpenAI vision model."""
        try:
            print("[OPENAI] Starting image analysis")
            
            # Convert image to base64
            base64_image = base64.b64encode(image_data).decode('utf-8')
            
            # Get recent text from captured_text file
            recent_text = ""
            captured_text_file = Path(__file__).parent.parent / "output" / "captured_text.txt"
            if captured_text_file.exists():
                with open(captured_text_file, 'r', encoding='utf-8') as f:
                    recent_text = f.read().strip()
            
            # Replace placeholder in prompt
            prompt = self.prompt_template.replace("RECENT_TEXT", recent_text)
            print(f"[OPENAI] Using prompt:\n{prompt}\n")
            
            # Create message with image
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
                                "url": f"data:image/jpeg;base64,{base64_image}",
                                "detail": "high"
                            }
                        }
                    ]
                }
            ]
            
            # Call OpenAI API
            print("[OPENAI] Calling Vision API")
            async with openai.AsyncOpenAI() as client:
                response = await client.chat.completions.create(
                    model="gpt-4o-mini",
                    response_format={"type": "json_object"},
                    messages=messages,
                    temperature=0.5,
                    max_tokens=500
                )
            
            # Extract and return text
            if response and hasattr(response, 'choices') and response.choices:
                result = response.choices[0].message.content.strip()
                print(f"[OPENAI] Raw response content: {result}")
                
                try:
                    parsed_json = json.loads(result)
                    print(f"[OPENAI] Parsed JSON: {parsed_json}")
                    return parsed_json
                except json.JSONDecodeError as e:
                    print(f"[ERROR] Failed to parse OpenAI response as JSON: {str(e)}")
                    print(f"[ERROR] Raw response: {result}")
                    return None
            else:
                print(f"[ERROR] No content in OpenAI response. Response: {response}")
                return None
                
        except Exception as e:
            print(f"[ERROR] OpenAI API error: {str(e)}")
            return None

    async def summarize_text(self, prompt: str) -> str:
        """Summarize text using OpenAI's API."""
        try:
            # Prepare request payload
            payload = {
                "model": "gpt-4o",
                "response_format": { "type": "json_object" },
                "messages": [
                    {
                        "role": "user",
                        "content": prompt
                    }
                ],
                "max_tokens": 500,
                "temperature": 0.5
            }
            
            print(f"\nSummarizer using prompt:\n{prompt}\n")
            
            # Prepare headers
            headers = {
                "Content-Type": "application/json",
                "Authorization": f"Bearer {self.api_key}"
            }
            
            # Make request
            async with aiohttp.ClientSession() as session:
                async with session.post(
                    "https://api.openai.com/v1/chat/completions",
                    headers=headers,
                    json=payload
                ) as response:
                    
                    if response.status == 200:
                        result = await response.json()
                        return result['choices'][0]['message']['content']
                    else:
                        error_text = await response.text()
                        print(f"OpenAI API error: {error_text}")
                        return None
                        
        except openai.APIError as e:
            print(f"[ERROR] OpenAI API Error: {str(e)}")
        except openai.APIConnectionError as e:
            print(f"[ERROR] OpenAI Connection Error: {str(e)}")
        except openai.APITimeoutError as e:
            print(f"[ERROR] OpenAI Timeout Error: {str(e)}")
        except openai.AuthenticationError as e:
            print(f"[ERROR] OpenAI Authentication Error: {str(e)}")
        except openai.BadRequestError as e:
            print(f"[ERROR] OpenAI Bad Request Error: {str(e)}")
        except openai.ConflictError as e:
            print(f"[ERROR] OpenAI Conflict Error: {str(e)}")
        except openai.InternalServerError as e:
            print(f"[ERROR] OpenAI Server Error: {str(e)}")
        except openai.NotFoundError as e:
            print(f"[ERROR] OpenAI Not Found Error: {str(e)}")
        except openai.PermissionDeniedError as e:
            print(f"[ERROR] OpenAI Permission Error: {str(e)}")
        except openai.RateLimitError as e:
            print(f"[ERROR] OpenAI Rate Limit Error: {str(e)}")
        except Exception as e:
            print(f"[ERROR] Unexpected error in summarize_text: {str(e)}")
            print(f"Error type: {type(e)}")
            import traceback
            print(f"Traceback: {traceback.format_exc()}")
            
        return None
