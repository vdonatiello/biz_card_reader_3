import json
import base64
import requests
import os
from datetime import datetime
from http.server import BaseHTTPRequestHandler
import io
from PIL import Image

class handler(BaseHTTPRequestHandler):
    def do_POST(self):
        try:
            # Get content length and read the request body
            content_length = int(self.headers['Content-Length'])
            post_data = self.rfile.read(content_length)
            
            # Handle multipart form data (image upload)
            if 'multipart/form-data' in self.headers.get('Content-Type', ''):
                # Extract image from multipart data
                image_data = self.extract_image_from_multipart(post_data)
                if not image_data:
                    self.send_error_response("No image found in request")
                    return
            else:
                self.send_error_response("Invalid content type")
                return

            # Convert image to base64 for GPT-4 Vision
            base64_image = base64.b64encode(image_data).decode('utf-8')
            
            # Extract business card data using GPT-4 Vision
            extracted_data = self.extract_business_card_data(base64_image)
            
            if not extracted_data:
                self.send_error_response("Failed to extract data from business card")
                return

            # Send data to Make.com webhook
            webhook_success = self.send_to_webhook(extracted_data)
            
            if webhook_success:
                self.send_success_response(extracted_data)
            else:
                self.send_error_response("Failed to save data to Google Sheets")
                
        except Exception as e:
            print(f"Error processing request: {str(e)}")
            self.send_error_response(f"Server error: {str(e)}")

    def do_OPTIONS(self):
        # Handle CORS preflight requests
        self.send_response(200)
        self.send_header('Access-Control-Allow-Origin', '*')
        self.send_header('Access-Control-Allow-Methods', 'POST, OPTIONS')
        self.send_header('Access-Control-Allow-Headers', 'Content-Type')
        self.end_headers()

    def extract_image_from_multipart(self, post_data):
        """Extract image data from multipart form data"""
        try:
            # Simple multipart parsing - look for image data
            boundary_start = post_data.find(b'\r\n\r\n')
            if boundary_start == -1:
                return None
                
            # Find the start of actual image data
            image_start = boundary_start + 4
            
            # Find the end boundary
            boundary_end = post_data.find(b'\r\n--', image_start)
            if boundary_end == -1:
                boundary_end = len(post_data)
                
            image_data = post_data[image_start:boundary_end]
            
            # Validate it's actually image data
            if len(image_data) < 100:  # Too small to be a real image
                return None
                
            return image_data
            
        except Exception as e:
            print(f"Error extracting image: {str(e)}")
            return None

    def extract_business_card_data(self, base64_image):
        """Use GPT-4 Vision to extract structured data from business card"""
        try:
            api_key = os.environ.get('OPENAI_API_KEY')
            if not api_key:
                print("OpenAI API key not found")
                return None

            headers = {
                "Content-Type": "application/json",
                "Authorization": f"Bearer {api_key}"
            }

            prompt = """
            You are an expert OCR system specialized in business card data extraction. 
            
            Analyze this business card image and extract information into a JSON object with these exact fields:
            - full_name: Complete name as written on card (preserve original format and order)
            - first_name: First/given name only
            - last_name: Last/family name only  
            - email: Email address (validate format)
            - handphone_number: Phone/mobile number (preserve original formatting including country codes)
            - job_title: Job title or position (complete title as shown)
            - company_name: Company name (full official name)
            - company_website: Website URL (add https:// if missing)
            - city: City from address (just city name)
            - country: Country from address (just country name)

            IMPORTANT INSTRUCTIONS:
            1. For names: Handle both Western (first last) and Asian (family given) name orders correctly
            2. If only one name visible, put it in first_name, leave last_name empty
            3. For Asian names, respect cultural naming conventions 
            4. Extract phone numbers exactly as shown (including +country codes, spaces, dashes)
            5. For addresses: separate city and country, ignore street address
            6. If any field not found or unclear, use empty string ""
            7. Validate email format - must contain @ and valid domain
            8. For websites: add https:// prefix if missing, ensure valid format

            Return ONLY a valid JSON object, no explanations or additional text.
            """

            payload = {
                "model": "gpt-4o",  # Using latest GPT-4o which has better vision capabilities
                "messages": [
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
                                    "detail": "high"  # High detail for better OCR accuracy
                                }
                            }
                        ]
                    }
                ],
                "max_tokens": 500,
                "temperature": 0.1  # Lower temperature for more consistent extraction
            }

            response = requests.post(
                "https://api.openai.com/v1/chat/completions",
                headers=headers,
                json=payload,
                timeout=30
            )

            if response.status_code == 200:
                result = response.json()
                content = result['choices'][0]['message']['content'].strip()
                
                # Try to parse the JSON response
                try:
                    extracted_data = json.loads(content)
                    
                    # Add timestamp
                    extracted_data['timestamp'] = datetime.now().isoformat() + 'Z'
                    
                    # Validate and clean data
                    extracted_data = self.validate_and_clean_data(extracted_data)
                    
                    return extracted_data
                    
                except json.JSONDecodeError:
                    print(f"Failed to parse GPT response as JSON: {content}")
                    return None
            else:
                print(f"OpenAI API error: {response.status_code} - {response.text}")
                return None

        except Exception as e:
            print(f"Error in GPT-4 Vision extraction: {str(e)}")
            return None

    def validate_and_clean_data(self, data):
        """Validate and clean the extracted data with improved logic"""
        required_fields = [
            'timestamp', 'full_name', 'first_name', 'last_name', 'email',
            'handphone_number', 'job_title', 'company_name', 'company_website',
            'city', 'country'
        ]
        
        # Ensure all required fields exist
        for field in required_fields:
            if field not in data:
                data[field] = ""
        
        # Clean and validate email
        if data['email']:
            email = data['email'].strip()
            if '@' not in email or '.' not in email.split('@')[-1]:
                data['email'] = ""  # Invalid email
            else:
                data['email'] = email.lower()
        
        # Clean website URL
        if data['company_website']:
            website = data['company_website'].strip()
            if website and not website.startswith(('http://', 'https://')):
                data['company_website'] = 'https://' + website
            # Validate basic URL format
            if website and '.' not in website:
                data['company_website'] = ""
        
        # Improved name parsing - handle Asian and Western names
        if data['full_name'] and not (data['first_name'] and data['last_name']):
            full_name = data['full_name'].strip()
            names = full_name.split()
            
            if len(names) == 1:
                # Single name - put in first_name
                data['first_name'] = names[0]
                data['last_name'] = ""
            elif len(names) >= 2:
                # For Western names: First Middle... Last
                # For Asian names: Family Given (GPT-4o should handle this correctly)
                # Let's trust GPT-4o's cultural understanding, but provide fallback
                if not data['first_name']:
                    data['first_name'] = names[0]
                if not data['last_name']:
                    data['last_name'] = ' '.join(names[1:])
        
        # Clean phone number - preserve formatting but remove obvious errors
        if data['handphone_number']:
            phone = data['handphone_number'].strip()
            # Remove common OCR errors but preserve international formatting
            phone = phone.replace('O', '0').replace('l', '1').replace('I', '1')
            data['handphone_number'] = phone
        
        # Clean text fields
        text_fields = ['job_title', 'company_name', 'city', 'country']
        for field in text_fields:
            if data[field]:
                data[field] = data[field].strip()
        
        return data

    def send_to_webhook(self, data):
        """Send extracted data to Make.com webhook"""
        try:
            webhook_url = os.environ.get('MAKE_WEBHOOK_URL')
            if not webhook_url:
                webhook_url = "https://hook.eu2.make.com/oz6cgrhqg8bctxvqhscaws053nery1mp"
            
            headers = {
                'Content-Type': 'application/json'
            }
            
            response = requests.post(
                webhook_url,
                json=data,
                headers=headers,
                timeout=15
            )
            
            if response.status_code in [200, 201, 204]:
                print(f"Webhook success: {response.status_code}")
                return True
            else:
                print(f"Webhook error: {response.status_code} - {response.text}")
                return False
                
        except Exception as e:
            print(f"Error sending to webhook: {str(e)}")
            return False

    def send_success_response(self, data):
        """Send success response to frontend"""
        self.send_response(200)
        self.send_header('Content-Type', 'application/json')
        self.send_header('Access-Control-Allow-Origin', '*')
        self.end_headers()
        
        response_data = {
            'success': True,
            'message': 'Business card processed successfully',
            'data': data
        }
        
        self.wfile.write(json.dumps(response_data).encode())

    def send_error_response(self, message):
        """Send error response to frontend"""
        self.send_response(400)
        self.send_header('Content-Type', 'application/json')
        self.send_header('Access-Control-Allow-Origin', '*')
        self.end_headers()
        
        response_data = {
            'success': False,
            'message': message
        }
        
        self.wfile.write(json.dumps(response_data).encode())
