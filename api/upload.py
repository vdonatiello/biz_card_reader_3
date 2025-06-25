def handler(request):
    import json
    
    # Simple test response
    return {
        'statusCode': 200,
        'headers': {
            'Content-Type': 'application/json',
            'Access-Control-Allow-Origin': '*'
        },
        'body': json.dumps({
            'message': 'Python function is working!',
            'method': getattr(request, 'method', 'unknown'),
            'success': True
        })
    }
