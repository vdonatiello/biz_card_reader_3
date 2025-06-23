import json
import base64
import requests
import os
from http.server import BaseHTTPRequestHandler

class handler(BaseHTTPRequestHandler):
    def do_POST(self):
        # Set CORS headers
        self.send_response(200)
        self.send_header('Content-type', 'application/json')
        self.send_header('Access-Control-Allow-Origin', '*')
        self.send_header('Access-Control-Allow-Methods', 'POST, OPTIONS')
        self.send_header('Access-Control-Allow-Headers', 'Content-Type')
        self.end_headers()
        
        try:
            # Read the request body
            content_length = int(self.headers['Content-Length'])
            post_data = self.rfile.read(content_length)
            data = json.loads(post_data.decode('utf-8'))
            
            # Get the base64 image
            image_base64 = data.get('image')
            if not image_base64:
                raise ValueError("No image provided")
            
            # Process with GPT-4 Vision
            extracted_data = extract_business_card_data(image_base64)
            
            # Send to Make.com webhook
            webhook_response = send_to_make_webhook(extracted_data)
            
            # Return success response
            response = {
                "success": True,
                "extracted_data": extracted_data,
                "webhook_sent": webhook_response
            }
            
        except Exception as e:
            response = {
                "success": False,
                "error": str(e)
            }
        
        self.wfile.write(json.dumps(response).encode('utf-8'))
    
    def do_OPTIONS(self):
        # Handle preflight requests
        self.send_response(200)
        self.send_header('Access-Control-Allow-Origin', '*')
        self.send_header('Access-Control-Allow-Methods', 'POST, OPTIONS')
        self.send_header('Access-Control-Allow-Headers', 'Content-Type')
        self.end_headers()

def extract_business_card_data(image_base64):
    """Extract structured data from business card using GPT-4 Vision"""
    
    # Your OpenAI API key (set this as environment variable in Vercel)
    api_key = os.environ.get('OPENAI_API_KEY')
    if not api_key:
        raise ValueError("OpenAI API key not configured")
    
    headers = {
        "Content-Type": "application/json",
        "Authorization": f"Bearer {api_key}"
    }
    
    payload = {
        "model": "gpt-4-vision-preview",
        "messages": [
            {
                "role": "user",
                "content": [
                    {
                        "type": "text",
                        "text": """Please extract the following information from this business card image and return it as a JSON object:

{
  "name": "Full name of the person",
  "title": "Job title/position",
  "company": "Company name",
  "email": "Email address",
  "phone": "Phone number",
  "website": "Website URL",
  "address": "Full address",
  "linkedin": "LinkedIn profile if visible",
  "other_info": "Any other relevant information"
}

If any field is not visible or available, use null for that field. Only return the JSON object, no additional text."""
                    },
                    {
                        "type": "image_url",
                        "image_url": {
                            "url": f"data:image/jpeg;base64,{image_base64}"
                        }
                    }
                ]
            }
        ],
        "max_tokens": 500
    }
    
    response = requests.post("https://api.openai.com/v1/chat/completions", 
                           headers=headers, json=payload)
    
    if response.status_code != 200:
        raise Exception(f"OpenAI API error: {response.text}")
    
    result = response.json()
    
    # Extract the JSON from GPT-4's response
    content = result['choices'][0]['message']['content']
    
    try:
        # Parse the JSON response from GPT-4
        extracted_data = json.loads(content)
        return extracted_data
    except json.JSONDecodeError:
        # If GPT-4 didn't return valid JSON, create a structured response
        return {
            "name": None,
            "title": None,
            "company": None,
            "email": None,
            "phone": None,
            "website": None,
            "address": None,
            "linkedin": None,
            "other_info": content,
            "raw_response": content
        }

def send_to_make_webhook(data):
    """Send extracted data to Make.com webhook"""
    
    # Your Make.com webhook URL (set this as environment variable)
    webhook_url = os.environ.get('MAKE_WEBHOOK_URL')
    if not webhook_url:
        return {"error": "Make.com webhook URL not configured"}
    
    try:
        response = requests.post(webhook_url, json=data, timeout=10)
        return {
            "status_code": response.status_code,
            "success": response.status_code == 200,
            "response": response.text[:200]  # First 200 chars of response
        }
    except Exception as e:
        return {"error": f"Webhook failed: {str(e)}"}
