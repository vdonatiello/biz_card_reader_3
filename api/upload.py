import base64
import json
import os
from datetime import datetime
import requests
from PIL import Image
import io
from http.server import BaseHTTPRequestHandler
from urllib.parse import parse_qs
import cgi

class handler(BaseHTTPRequestHandler):
    def do_OPTIONS(self):
        # Handle CORS preflight
        self.send_response(200)
        self.send_header('Access-Control-Allow-Origin', '*')
        self.send_header('Access-Control-Allow-Methods', 'GET, POST, OPTIONS')
        self.send_header('Access-Control-Allow-Headers', 'Content-Type, Authorization')
        self.end_headers()
        return

    def do_GET(self):
        # Return 405 for GET requests
        self.send_response(405)
        self.send_header('Access-Control-Allow-Origin', '*')
        self.send_header('Content-Type', 'application/json')
        self.end_headers()
        response = json.dumps({'error': 'Method not allowed'})
        self.wfile.write(response.encode())
        return

    def do_POST(self):
        try:
            # Get content length
            content_length = int(self.headers.get('Content-Length', 0))
            
            # Read the request body
            post_data = self.rfile.read(content_length)
            
            # Parse multipart form data
            content_type = self.headers.get('Content-Type', '')
            
            if 'multipart/form-data' in content_type:
                # Handle multipart form data (file upload)
                boundary = content_type.split('boundary=')[1].encode()
                
                # Simple multipart parsing - look for image data
                parts = post_data.split(b'--' + boundary)
                image_data = None
                
                for part in parts:
                    if b'Content-Type: image' in part or b'name="image"' in part:
                        # Extract image data after double CRLF
                        if b'\r\n\r\n' in part:
                            image_data = part.split(b'\r\n\r\n', 1)[1]
                            # Remove trailing boundary markers
                            if image_data.endswith(b'\r\n'):
                                image_data = image_data[:-2]
                            break
                
                if not image_data:
                    self.send_error_response(400, 'No image file found in upload')
                    return
                    
            elif 'application/json' in content_type:
                # Handle JSON data with base64 image
                try:
                    json_data = json.loads(post_data.decode())
                    if 'image' in json_data:
                        image_data_str = json_data['image']
                        if image_data_str.startswith('data:image'):
                            image_data = base64.b64decode(image_data_str.split(',')[1])
                        else:
                            image_data = base64.b64decode(image_data_str)
                    else:
                        self.send_error_response(400, 'No image data in JSON')
                        return
                except Exception as e:
                    self.send_error_response(400, f'Invalid JSON data: {str(e)}')
                    return
            else:
                self.send_error_response(400, 'Unsupported content type')
                return

            # Process the image
            result = self.process_business_card(image_data)
            
            # Send successful response
            self.send_response(200)
            self.send_header('Access-Control-Allow-Origin', '*')
            self.send_header('Content-Type', 'application/json')
            self.end_headers()
            
            response = json.dumps(result)
            self.wfile.write(response.encode())
            
        except Exception as e:
            print(f"Handler error: {e}")
            self.send_error_response(500, f'Processing failed: {str(e)}')

    def send_error_response(self, status_code, error_message):
        self.send_response(status_code)
        self.send_header('Access-Control-Allow-Origin', '*')
        self.send_header('Content-Type', 'application/json')
        self.end_headers()
        
        response = json.dumps({'error': error_message})
        self.wfile.write(response.encode())

    def process_business_card(self, image_data):
        try:
            # Compress image if needed
            try:
                img = Image.open(io.BytesIO(image_data))
                if img.mode != 'RGB':
                    img = img.convert('RGB')
                
                # Compress if image is too large
                if len(image_data) > 5 * 1024 * 1024:  # 5MB
                    output = io.BytesIO()
                    img.save(output, format='JPEG', quality=85, optimize=True)
                    image_data = output.getvalue()
            except Exception as e:
                print(f"Image processing error: {e}")
            
            # Convert to base64
            image_base64 = base64.b64encode(image_data).decode('utf-8')
            
            # Call OpenAI GPT-4o Vision
            openai_api_key = os.environ.get('OPENAI_API_KEY')
            if not openai_api_key:
                raise Exception('OpenAI API key not configured')
            
            headers = {
                'Authorization': f'Bearer {openai_api_key}',
                'Content-Type': 'application/json'
            }
            
            prompt = """
            Extract the following information from this business card image. Be very careful with OCR accuracy.
            
            Please return ONLY a JSON object with these exact fields (use null for missing information):
            {
                "full_name": "Complete name as shown",
                "first_name": "First name only",
                "last_name": "Last name only", 
                "email": "Email address",
                "handphone_number": "Phone number (preserve international format)",
                "company_name": "Company name",
                "position": "Job title/position",
                "address": "Full address",
                "city": "City name",
                "country": "Country",
                "website": "Website URL",
                "social_media": "Social media handles",
                "company_description": "Brief company description if available"
            }
            
            Important OCR corrections:
            - Fix common OCR errors: O→0, l→1, I→1 in phone numbers
            - Ensure email has @ symbol
            - Handle both Western (First Last) and Asian naming conventions
            - If only one name visible, put it in full_name and first_name
            """
            
            data = {
                'model': 'gpt-4o',
                'messages': [
                    {
                        'role': 'user',
                        'content': [
                            {
                                'type': 'text',
                                'text': prompt
                            },
                            {
                                'type': 'image_url',
                                'image_url': {
                                    'url': f'data:image/jpeg;base64,{image_base64}',
                                    'detail': 'high'
                                }
                            }
                        ]
                    }
                ],
                'max_tokens': 1000,
                'temperature': 0.1
            }
            
            response = requests.post(
                'https://api.openai.com/v1/chat/completions',
                headers=headers,
                json=data,
                timeout=30
            )
            
            if response.status_code != 200:
                raise Exception(f'OpenAI API error: {response.status_code} - {response.text}')
            
            ai_response = response.json()
            extracted_text = ai_response['choices'][0]['message']['content']
            
            # Parse JSON from AI response
            try:
                # Clean the response - remove markdown code blocks if present
                if '```json' in extracted_text:
                    extracted_text = extracted_text.split('```json')[1].split('```')[0]
                elif '```' in extracted_text:
                    extracted_text = extracted_text.split('```')[1].split('```')[0]
                
                extracted_data = json.loads(extracted_text.strip())
            except json.JSONDecodeError:
                # Fallback: try to extract data manually
                extracted_data = {
                    'full_name': None,
                    'first_name': None,
                    'last_name': None,
                    'email': None,
                    'handphone_number': None,
                    'company_name': None,
                    'position': None,
                    'address': None,
                    'city': None,
                    'country': None,
                    'website': None,
                    'social_media': None,
                    'company_description': None
                }
            
            # Add timestamp
            extracted_data['timestamp'] = datetime.now().strftime('%Y-%m-%d %H:%M:%S')
            
            # Data validation and cleaning
            if extracted_data.get('email') and '@' not in str(extracted_data['email']):
                extracted_data['email'] = None
                
            if extracted_data.get('handphone_number'):
                # Clean phone number OCR errors
                phone = str(extracted_data['handphone_number'])
                phone = phone.replace('O', '0').replace('l', '1').replace('I', '1')
                extracted_data['handphone_number'] = phone
            
            # Handle name parsing
            if extracted_data.get('full_name') and not extracted_data.get('first_name'):
                name_parts = extracted_data['full_name'].split()
                if len(name_parts) >= 2:
                    extracted_data['first_name'] = name_parts[0]
                    extracted_data['last_name'] = ' '.join(name_parts[1:])
                else:
                    extracted_data['first_name'] = extracted_data['full_name']
            
            # Send to Make.com webhook
            webhook_url = os.environ.get('MAKE_WEBHOOK_URL')
            if webhook_url:
                try:
                    webhook_response = requests.post(
                        webhook_url,
                        json=extracted_data,
                        timeout=10
                    )
                    print(f"Webhook response: {webhook_response.status_code}")
                except Exception as e:
                    print(f"Webhook error: {e}")
            
            return {
                'success': True,
                'data': extracted_data
            }
            
        except Exception as e:
            print(f"Processing error: {e}")
            raise e
