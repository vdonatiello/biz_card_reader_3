import json
from flask import Request, jsonify

def handler(request: Request):
    request_json = request.get_json()
    image_data = request_json.get("image")
    if not image_data:
        return jsonify({"error": "Missing image"}), 400

    # Simulated response
    extracted_data = {
        "name": "John Doe",
        "email": "john@example.com",
        "phone": "+123456789",
        "company": "Example Inc.",
        "title": "Marketing Director"
    }
    return jsonify(extracted_data)
