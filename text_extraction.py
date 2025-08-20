import base64
from io import BytesIO
from PIL import Image
import requests
from llama_parse import LlamaParse
import os
from typing import Optional

class TextExtractor:
    def __init__(self, llama_cloud_api_key: str):
        
        self.parser = LlamaParse(
            api_key=llama_cloud_api_key,
            result_type="text",  # "markdown" and "text" are available
            verbose=True,
        )
    
    def extract_from_image(self, image_path: str) -> str:
       
        try:
            # Parse the document
            documents = self.parser.load_data(image_path)
            
            # Combine all extracted text
            extracted_text = ""
            for doc in documents:
                extracted_text += doc.text + "\n"
            
            return extracted_text.strip()
        
        except Exception as e:
            print(f"Error extracting text: {str(e)}")
            return ""
    
    def extract_from_telegram_photo(self, photo_bytes: bytes) -> str:
        
        try:
            # Save bytes to temporary file
            temp_path = "temp_timetable.jpg"
            
            # Convert bytes to image and save
            image = Image.open(BytesIO(photo_bytes))
            image.save(temp_path)
            
            # Extract text
            extracted_text = self.extract_from_image(temp_path)
            
            # Clean up temp file
            if os.path.exists(temp_path):
                os.remove(temp_path)
            
            return extracted_text
        
        except Exception as e:
            print(f"Error processing Telegram photo: {str(e)}")
            return ""
    
    def preprocess_text(self, text: str) -> str:
        
        # Basic cleaning
        lines = text.split('\n')
        cleaned_lines = []
        
        for line in lines:
            line = line.strip()
            if line and len(line) > 2:  # Filter out very short lines
                cleaned_lines.append(line)
        
        return '\n'.join(cleaned_lines)

