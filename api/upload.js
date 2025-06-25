// api/upload.js - Node.js Business Card Scanner for Vercel
// This replaces the Python version and does exactly the same thing
import { OpenAI } from 'openai';
import fetch from 'node-fetch';

export default async function handler(req, res) {
    // Enable CORS
    res.setHeader('Access-Control-Allow-Origin', '*');
    res.setHeader('Access-Control-Allow-Methods', 'GET, POST, OPTIONS');
    res.setHeader('Access-Control-Allow-Headers', 'Content-Type, Authorization');

    // Handle CORS preflight
    if (req.method === 'OPTIONS') {
        return res.status(200).end();
    }

    // Only allow POST requests
    if (req.method !== 'POST') {
        return res.status(405).json({ error: 'Method not allowed' });
    }

    try {
        // Get image data from request
        let imageData = null;
        let imageBase64 = null;

        if (req.body && req.body.image) {
            // Handle base64 image data
            const imageStr = req.body.image;
            if (imageStr.startsWith('data:image')) {
                imageBase64 = imageStr.split(',')[1];
            } else {
                imageBase64 = imageStr;
            }
        } else {
            return res.status(400).json({ error: 'No image data provided' });
        }

        // Validate OpenAI API key
        const openaiApiKey = process.env.OPENAI_API_KEY;
        if (!openaiApiKey) {
            return res.status(500).json({ error: 'OpenAI API key not configured' });
        }

        // Initialize OpenAI client
        const openai = new OpenAI({
            apiKey: openaiApiKey,
        });

        const prompt = `
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
        `;

        // Call OpenAI GPT-4o Vision
        const response = await openai.chat.completions.create({
            model: 'gpt-4o',
            messages: [
                {
                    role: 'user',
                    content: [
                        {
                            type: 'text',
                            text: prompt
                        },
                        {
                            type: 'image_url',
                            image_url: {
                                url: `data:image/jpeg;base64,${imageBase64}`,
                                detail: 'high'
                            }
                        }
                    ]
                }
            ],
            max_tokens: 1000,
            temperature: 0.1
        });

        let extractedText = response.choices[0].message.content;

        // Parse JSON from AI response
        let extractedData;
        try {
            // Clean the response - remove markdown code blocks if present
            if (extractedText.includes('```json')) {
                extractedText = extractedText.split('```json')[1].split('```')[0];
            } else if (extractedText.includes('```')) {
                extractedText = extractedText.split('```')[1].split('```')[0];
            }
            
            extractedData = JSON.parse(extractedText.trim());
        } catch (parseError) {
            // Fallback: create empty structure
            extractedData = {
                full_name: null,
                first_name: null,
                last_name: null,
                email: null,
                handphone_number: null,
                company_name: null,
                position: null,
                address: null,
                city: null,
                country: null,
                website: null,
                social_media: null,
                company_description: null
            };
        }

        // Add timestamp
        extractedData.timestamp = new Date().toISOString();

        // Data validation and cleaning
        if (extractedData.email && !extractedData.email.includes('@')) {
            extractedData.email = null;
        }

        if (extractedData.handphone_number) {
            // Clean phone number OCR errors
            let phone = String(extractedData.handphone_number);
            phone = phone.replace(/O/g, '0').replace(/l/g, '1').replace(/I/g, '1');
            extractedData.handphone_number = phone;
        }

        // Handle name parsing
        if (extractedData.full_name && !extractedData.first_name) {
            const nameParts = extractedData.full_name.split(' ');
            if (nameParts.length >= 2) {
                extractedData.first_name = nameParts[0];
                extractedData.last_name = nameParts.slice(1).join(' ');
            } else {
                extractedData.first_name = extractedData.full_name;
            }
        }

        // Send to Make.com webhook
        const webhookUrl = process.env.MAKE_WEBHOOK_URL;
        if (webhookUrl) {
            try {
                await fetch(webhookUrl, {
                    method: 'POST',
                    headers: {
                        'Content-Type': 'application/json'
                    },
                    body: JSON.stringify(extractedData)
                });
                console.log('Webhook sent successfully');
            } catch (webhookError) {
                console.error('Webhook error:', webhookError);
            }
        }

        // Return success response
        return res.status(200).json({
            success: true,
            data: extractedData
        });

    } catch (error) {
        console.error('Processing error:', error);
        return res.status(500).json({
            error: 'Processing failed',
            details: error.message
        });
    }
}
