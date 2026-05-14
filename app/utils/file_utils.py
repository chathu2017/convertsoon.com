"""
File Utilities
"""

def get_file_extension(filename: str) -> str:
    """Get lowercase file extension"""
    return filename.rsplit('.', 1)[-1].lower() if '.' in filename else ''

def validate_file_type(ext: str, allowed: set) -> bool:
    """Check if extension is allowed"""
    return ext.lower() in allowed

def get_conversion_options(input_ext: str, output_fmt: str) -> dict:
    """Get default conversion options"""
    return {
        "dpi": 300,
        "quality": 85,
        "compression": "default",
        "background_color": "#FFFFFF"
    }
