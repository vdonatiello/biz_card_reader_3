import json
import base64
import requests
import os
from datetime import datetime
from http.server import BaseHTTPRequestHandler
import io
from PIL import Image
import cgi

class handler(BaseHTTPRequestHandler):
    def do_OPTIONS(self):
        """Handle CORS preflight requests"""
        self.send_response(200)
        self.send_header('Access-Control-Allow-Origin', '*')
        self.send_header('Access-Control-Allow-Methods', 'POST, OPTIONS')
        self.send_header('Access-Control-Allow-Headers', 'Content-Type')
        self.end_headers()

    def do_POST(self):
        try:
            print("=== Processing business card upload ===")
            
            # CORS headers
            self.send_header('Access-Control-Allow-Origin', '*')
            self.send_header('Access-Control-Allow-Methods', 'POST, OPTIONS')
            self.send_header('Access-Control-Allow-Headers', 'Content-Type')
            
            # Parse multipart form data
            content_type = self.headers.get('Content-Type', '')
            if not content_type.startswith('multipart/form-data'):
                raise ValueError("Expected multipart/form-data")
            
            # Get form data
            form = cgi.FieldStorage(
                fp=self.rfile,
                headers=self.headers,
                environ={'REQUEST_METHOD': 'POST'}
            )
            
            # Extract images and processing mode
            front_image = None
            back_image = None
            processing_mode = "single"  # default
            
            if "image" in form:
                front_image = form["image"].file.read()
                print(f"Front image received: {len(front_image)} bytes")
            
            if "back_image" in form:
                back_image = form["back_image"].file.read()
                processing_mode = "double"
                print(f"Back image received: {len(back_image)} bytes")
            
            if "processing_mode" in form:
                processing_mode = form["processing_mode"].value
                print(f"Processing mode: {processing_mode}")
            
            if not front_image:
                raise ValueError("No image provided")
            
            # Process front side (always required)
            print("Processing front side...")
            front_data = self.process_business_card_image(front_image, "front")
            
            # Process back side if provided
            back_data = {}
            if back_image and processing_mode == "double":
                print("Processing back side...")
                back_data = self.process_business_card_image(back_image, "back")
            
            # Merge data from both sides
            final_data = self.merge_card_data(front_data, back_data)
            
            # Add timestamp
            final_data["timestamp"] = datetime.now().strftime("%Y-%m-%d %H:%M:%S")
            
            print(f"Final extracted data: {json.dumps(final_data, indent=2)}")
            
            # Send to webhook
            webhook_response = self.send_to_webhook(final_data)
            
            # Return success response
            self.send_response(200)
            self.send_header('Content-Type', 'application/json')
            self.end_headers()
            
            response_data = {
                "success": True,
                "message": "Business card processed successfully",
                "extracted_data": final_data,
                "processing_mode": processing_mode,
                "webhook_status": webhook_response
            }
            
            self.wfile.write(json.dumps(response_data).encode())
            print("=== Processing completed successfully ===")
            
        except Exception as e:
            print(f"Error processing business card: {str(e)}")
            self.send_response(500)
            self.send_header('Content-Type', 'application/json')
            self.send_header('Access-Control-Allow-Origin', '*')
            self.end_headers()
            
            error_response = {
                "success": False,
                "error": str(e),
                "message": "Failed to process business card"
            }
            
            self.wfile.write(json.dumps(error_response).encode())

    def process_business_card_image(self, image_data, side="front"):
        """Process a single business card image and extract data"""
        try:
            # Load and process image
            image = Image.open(io.BytesIO(image_data))
            print(f"Original image size: {image.size}, mode: {image.mode}")
            
            # Convert RGBA to RGB if needed
            if image.mode in ('RGBA', 'LA'):
                background = Image.new('RGB', image.size, (255, 255, 255))
                if image.mode == 'RGBA':
                    background.paste(image, mask=image.split()[-1])
                else:
                    background.paste(image)
                image = background
            
            # Resize if too large (OpenAI has size limits)
            max_size = 2048
            if image.width > max_size or image.height > max_size:
                image.thumbnail((max_size, max_size), Image.Resampling.LANCZOS)
                print(f"Resized image to: {image.size}")
            
            # Convert to base64
            buffer = io.BytesIO()
            image.save(buffer, format='JPEG', quality=85)
            base64_image = base64.b64encode(buffer.getvalue()).decode()
            
            # Prepare OpenAI API request
            openai_api_key = os.environ.get('OPENAI_API_KEY')
            if not openai_api_key:
                raise ValueError("OpenAI API key not configured")
            
            # Enhanced prompt based on card side
            if side == "front":
                extraction_prompt = """
                Extract business card information from this front side image. Return ONLY a JSON object with these exact fields:
                {
                    "full_name": "person's complete name",
                    "first_name": "first name only", 
                    "last_name": "last name only",
                    "email": "email address",
                    "handphone_number": "phone number with country code if visible",
                    "company_name": "company or organization name",
                    "position": "job title or position",
                    "address": "complete address",
                    "city": "city name",
                    "country": "country name", 
                    "website": "website URL"
                }
                
                Important guidelines:
                - Handle both Western and Asian naming conventions
                - Preserve international phone number formatting
                - Validate email format (must contain @)
                - Extract website URL if present
                - If information is not clearly visible, use empty string ""
                - Clean common OCR errors: O→0, l→1, I→1 in phone/email
                """
            else:  # back side
                extraction_prompt = """
                Extract additional business card information from this back side image. Look for:
                - Additional contact information
                - Social media handles
                - QR codes or website URLs
                - Secondary addresses
                - Additional phone numbers
                - Company descriptions or services
                
                Return ONLY a JSON object with these fields (use empty string if not found):
                {
                    "additional_email": "secondary email if present",
                    "additional_phone": "secondary phone number",
                    "social_media": "social media handles or URLs",
                    "additional_website": "additional website URLs",
                    "company_description": "company services or description",
                    "additional_address": "secondary address if different",
                    "additional_info": "any other relevant information"
                }
                """
            
            # Call OpenAI API
            headers = {
                "Authorization": f"Bearer {openai_api_key}",
                "Content-Type": "application/json"
            }
            
            payload = {
                "model": "gpt-4o",
                "messages": [
                    {
                        "role": "user",
                        "content": [
                            {
                                "type": "text",
                                "text": extraction_prompt
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
                ],
                "max_tokens": 1000,
                "temperature": 0.1
            }
            
            print(f"Calling OpenAI API for {side} side...")
            response = requests.post(
                "https://api.openai.com/v1/chat/completions",
                headers=headers,
                json=payload,
                timeout=30
            )
            
            if response.status_code != 200:
                print(f"OpenAI API error: {response.status_code} - {response.text}")
                raise ValueError(f"OpenAI API error: {response.status_code}")
            
            # Parse response
            result = response.json()
            extracted_text = result['choices'][0]['message']['content']
            print(f"OpenAI response for {side}: {extracted_text}")
            
            # Parse JSON from response
            try:
                # Clean the response - sometimes GPT includes extra text
                if extracted_text.strip().startswith('{'):
                    json_start = extracted_text.find('{')
                    json_end = extracted_text.rfind('}') + 1
                    json_text = extracted_text[json_start:json_end]
                else:
                    # Look for JSON block
                    import re
                    json_match = re.search(r'\{.*\}', extracted_text, re.DOTALL)
                    if json_match:
                        json_text = json_match.group()
                    else:
                        raise ValueError("No JSON found in OpenAI response")
                
                extracted_data = json.loads(json_text)
                print(f"Successfully parsed {side} side data: {extracted_data}")
                return extracted_data
                
            except json.JSONDecodeError as e:
                print(f"JSON parsing error for {side}: {e}")
                print(f"Raw response: {extracted_text}")
                raise ValueError(f"Failed to parse extracted data from {side} side")
                
        except Exception as e:
            print(f"Error processing {side} side image: {str(e)}")
            raise

    def merge_card_data(self, front_data, back_data):
        """Merge data from front and back sides of business card"""
        # Start with front side data as base
        merged_data = front_data.copy()
        
        # Add back side data if available
        if back_data:
            # Merge additional contact info
            if back_data.get("additional_email") and not merged_data.get("email"):
                merged_data["email"] = back_data["additional_email"]
            
            if back_data.get("additional_phone") and not merged_data.get("handphone_number"):
                merged_data["handphone_number"] = back_data["additional_phone"]
            
            if back_data.get("additional_website") and not merged_data.get("website"):
                merged_data["website"] = back_data["additional_website"]
            
            # Add new fields from back side
            merged_data["social_media"] = back_data.get("social_media", "")
            merged_data["company_description"] = back_data.get("company_description", "")
            merged_data["additional_info"] = back_data.get("additional_info", "")
            
            # Note that back side was processed
            merged_data["back_side_processed"] = True
        else:
            merged_data["back_side_processed"] = False
        
        return merged_data

    def send_to_webhook(self, data):
        """Send extracted data to Make.com webhook"""
        try:
            webhook_url = os.environ.get('MAKE_WEBHOOK_URL')
            if not webhook_url:
                raise ValueError("Webhook URL not configured")
            
            print(f"Sending data to webhook: {webhook_url}")
            
            response = requests.post(
                webhook_url,
                json=data,
                headers={'Content-Type': 'application/json'},
                timeout=10
            )
            
            print(f"Webhook response: {response.status_code}")
            
            if response.status_code == 200:
                return {"status": "success", "message": "Data sent to Google Sheets"}
            else:
                print(f"Webhook error: {response.text}")
                return {"status": "error", "message": f"Webhook failed: {response.status_code}"}
                
        except Exception as e:
            print(f"Webhook error: {str(e)}")
            return {"status": "error", "message": f"Webhook failed: {str(e)}"}
