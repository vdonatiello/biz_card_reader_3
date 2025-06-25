import json
import os
import base64
import requests
from PIL import Image
from io import BytesIO
from openai import OpenAI
from datetime import datetime

def handler(request):
    """
    Vercel serverless function handler for business card processing
    """
    # Handle CORS preflight
    if request.method == 'OPTIONS':
        return {
            'statusCode': 200,
            'headers': {
                'Access-Control-Allow-Origin': '*',
                'Access-Control-Allow-Methods': 'POST, OPTIONS',
                'Access-Control-Allow-Headers': 'Content-Type',
            },
            'body': ''
        }
    
    # Only allow POST requests
    if request.method != 'POST':
        return {
            'statusCode': 405,
            'headers': {
                'Access-Control-Allow-Origin': '*',
                'Content-Type': 'application/json',
            },
            'body': json.dumps({'error': 'Method not allowed - use POST'})
        }
    
    try:
        # Get environment variables
        openai_api_key = os.environ.get('OPENAI_API_KEY')
        webhook_url = os.environ.get('MAKE_WEBHOOK_URL')
        
        if not openai_api_key:
            return {
                'statusCode': 500,
                'headers': {
                    'Access-Control-Allow-Origin': '*',
                    'Content-Type': 'application/json',
                },
                'body': json.dumps({'error': 'OpenAI API key not configured'})
            }
        
        if not webhook_url:
            return {
                'statusCode': 500,
                'headers': {
                    'Access-Control-Allow-Origin': '*',
                    'Content-Type': 'application/json',
                },
                'body': json.dumps({'error': 'Make.com webhook URL not configured'})
            }
        
        # Initialize OpenAI client
        client = OpenAI(api_key=openai_api_key)
        
        # Get image data from request
        image_data = None
        
        # Try to get image from form data
        if hasattr(request, 'files') and 'image' in request.files:
            image_file = request.files['image']
            image_data = image_file.read()
        # Try to get from JSON body
        elif hasattr(request, 'json') and request.json:
            if 'image' in request.json:
                # Base64 encoded image
                try:
                    image_data = base64.b64decode(request.json['image'])
                except Exception as e:
                    return {
                        'statusCode': 400,
                        'headers': {
                            'Access-Control-Allow-Origin': '*',
                            'Content-Type': 'application/json',
                        },
                        'body': json.dumps({'error': f'Invalid base64 image data: {str(e)}'})
                    }
        # Try to get from body
        elif hasattr(request, 'body'):
            try:
                body_data = json.loads(request.body) if isinstance(request.body, str) else request.body
                if isinstance(body_data, dict) and 'image' in body_data:
                    image_data = base64.b64decode(body_data['image'])
            except Exception as e:
                pass
        
        if not image_data:
            return {
                'statusCode': 400,
                'headers': {
                    'Access-Control-Allow-Origin': '*',
                    'Content-Type': 'application/json',
                },
                'body': json.dumps({'error': 'No image data provided'})
            }
        
        # Process and compress image if needed
        try:
            image = Image.open(BytesIO(image_data))
            
            # Compress if image is too large
            if len(image_data) > 5 * 1024 * 1024:  # 5MB
                image.thumbnail((1920, 1920), Image.Resampling.LANCZOS)
                buffer = BytesIO()
                image.save(buffer, format='JPEG', quality=85)
                image_data = buffer.getvalue()
            
            # Convert to base64 for OpenAI API
            image_b64 = base64.b64encode(image_data).decode('utf-8')
            
        except Exception as e:
            return {
                'statusCode': 400,
                'headers': {
                    'Access-Control-Allow-Origin': '*',
                    'Content-Type': 'application/json',
                },
                'body': json.dumps({'error': f'Invalid image format: {str(e)}'})
            }
        
        # Enhanced business card extraction prompt
        prompt = """
        You are an expert OCR system specialized in business cards. Extract ALL visible information from this business card image and return it as a JSON object with these exact fields:

        {
            "timestamp": "current timestamp in YYYY-MM-DD HH:MM:SS format",
            "full_name": "complete name as written on card",
            "first_name": "first name only",
            "last_name": "last name only",
            "email": "email address",
            "handphone_number": "phone number with original formatting",
            "company_name": "company or organization name",
            "position": "job title or position",
            "address": "complete address",
            "city": "city name",
            "country": "country name",
            "website": "website URL",
            "social_media": "social media handles or profiles",
            "company_description": "company tagline or description"
        }

        IMPORTANT RULES:
        - Use empty string "" for any field that is not visible or available
        - For names: Handle both Western (First Last) and Asian naming conventions appropriately
        - For phone numbers: Preserve original formatting, fix common OCR errors (O→0, l→1, I→1)
        - For emails: Ensure @ symbol is correct, validate email format
        - For websites: Include http/https prefix if missing
        - For addresses: Extract full address, then separate city/country when possible
        - Return ONLY valid JSON, no additional text
        - Be extremely accurate with text recognition
        """
        
        # Call GPT-4o Vision API
        response = client.chat.completions.create(
            model="gpt-4o",
            messages=[
                {
                    "role": "user",
                    "content": [
                        {"type": "text", "text": prompt},
                        {
                            "type": "image_url",
                            "image_url": {
                                "url": f"data:image/jpeg;base64,{image_b64}",
                                "detail": "high"
                            }
                        }
                    ]
                }
            ],
            max_tokens=1000,
            temperature=0.1
        )
        
        # Extract and parse the response
        extracted_text = response.choices[0].message.content.strip()
        
        try:
            # Parse as JSON
            extracted_data = json.loads(extracted_text)
        except json.JSONDecodeError:
            # Try to find JSON in the response
            import re
            json_match = re.search(r'\{.*\}', extracted_text, re.DOTALL)
            if json_match:
                try:
                    extracted_data = json.loads(json_match.group())
                except json.JSONDecodeError:
                    return {
                        'statusCode': 500,
                        'headers': {
                            'Access-Control-Allow-Origin': '*',
                            'Content-Type': 'application/json',
                        },
                        'body': json.dumps({
                            'error': 'Failed to parse AI response as JSON',
                            'raw_response': extracted_text
                        })
                    }
            else:
                return {
                    'statusCode': 500,
                    'headers': {
                        'Access-Control-Allow-Origin': '*',
                        'Content-Type': 'application/json',
                    },
                    'body': json.dumps({
                        'error': 'No JSON found in AI response',
                        'raw_response': extracted_text
                    })
                }
        
        # Add timestamp if missing
        if not extracted_data.get('timestamp'):
            extracted_data['timestamp'] = datetime.now().strftime('%Y-%m-%d %H:%M:%S')
        
        # Data validation and cleaning
        # Clean email
        if extracted_data.get('email') and '@' not in extracted_data['email']:
            extracted_data['email'] = ""
        
        # Clean phone number OCR errors
        if extracted_data.get('handphone_number'):
            phone = extracted_data['handphone_number']
            phone = phone.replace('O', '0').replace('l', '1').replace('I', '1')
            extracted_data['handphone_number'] = phone
        
        # Fix website URL
        if extracted_data.get('website') and extracted_data['website']:
            website = extracted_data['website']
            if not website.startswith(('http://', 'https://')):
                extracted_data['website'] = 'https://' + website
        
        # Send to Make.com webhook
        try:
            webhook_response = requests.post(
                webhook_url, 
                json=extracted_data, 
                timeout=30,
                headers={'Content-Type': 'application/json'}
            )
            
            if webhook_response.status_code not in [200, 201]:
                return {
                    'statusCode': 500,
                    'headers': {
                        'Access-Control-Allow-Origin': '*',
                        'Content-Type': 'application/json',
                    },
                    'body': json.dumps({
                        'error': 'Failed to save to Google Sheet',
                        'webhook_status': webhook_response.status_code,
                        'webhook_response': webhook_response.text,
                        'extracted_data': extracted_data
                    })
                }
        
        except requests.exceptions.RequestException as e:
            return {
                'statusCode': 500,
                'headers': {
                    'Access-Control-Allow-Origin': '*',
                    'Content-Type': 'application/json',
                },
                'body': json.dumps({
                    'error': f'Webhook request failed: {str(e)}',
                    'extracted_data': extracted_data
                })
            }
        
        # Success response
        return {
            'statusCode': 200,
            'headers': {
                'Access-Control-Allow-Origin': '*',
                'Content-Type': 'application/json',
            },
            'body': json.dumps({
                'success': True,
                'extracted_data': extracted_data,
                'message': 'Business card processed and saved successfully'
            })
        }
        
    except Exception as e:
        # Generic error handler
        return {
            'statusCode': 500,
            'headers': {
                'Access-Control-Allow-Origin': '*',
                'Content-Type': 'application/json',
            },
            'body': json.dumps({
                'error': f'Server error: {str(e)}',
                'message': 'An unexpected error occurred during processing'
            })
        }
