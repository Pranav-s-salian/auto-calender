from langchain_groq import ChatGroq
from langchain.schema import HumanMessage, SystemMessage
import json
from typing import Dict, List
import os

class TimetableProcessor:
    def __init__(self, groq_api_key: str):
       
        self.llm = ChatGroq(
            groq_api_key=groq_api_key,
            model_name="llama-3.3-70b-versatile",  # or "llama2-70b-4096"
            temperature=0.1
        )
    
    def structure_timetable(self, extracted_text: str) -> str:
        
        system_prompt = """You are a timetable processing assistant. Your task is to analyze the extracted text from a college timetable image and structure it into a clean, organized format.

Instructions:
1. Extract the weekly schedule for Monday to Saturday
2. Identify time slots and corresponding subjects/labs
3. Include subject codes, full names, and lab details
4. Format the output as a JSON structure with days as keys
5. For each day, list the time periods and subjects
6. Include break times if mentioned
7. Only include Monday to Saturday (ignore Sunday)

Expected JSON format:
{
    "Monday": [
        {
            "time": "9:00-9:55",
            "subject": "DSA",
            "full_name": "Data Structures and Algorithms",
            "type": "Theory",
            "room": "NC34"
        }
    ],
    "Tuesday": [...],
    ...
}

If you cannot clearly identify a schedule, return an empty JSON object {}."""

        human_prompt = f"""Please analyze this extracted timetable text and structure it according to the format specified:

{extracted_text}

Focus on Monday to Saturday only. Extract time slots, subjects, labs, and any room information available."""

        try:
            messages = [
                SystemMessage(content=system_prompt),
                HumanMessage(content=human_prompt)
            ]
            
            response = self.llm(messages)
            return response.content
        
        except Exception as e:
            print(f"Error processing with LLM: {str(e)}")
            return "{}"
    
    def validate_and_clean_json(self, llm_response: str) -> Dict:
        
        try:
            # Try to extract JSON from response
            json_start = llm_response.find('{')
            json_end = llm_response.rfind('}') + 1
            
            if json_start != -1 and json_end > json_start:
                json_str = llm_response[json_start:json_end]
                timetable_data = json.loads(json_str)
                return timetable_data
            else:
                return {}
        
        except json.JSONDecodeError as e:
            print(f"JSON parsing error: {str(e)}")
            return {}
        except Exception as e:
            print(f"Error validating JSON: {str(e)}")
            return {}
    
    def process_timetable(self, extracted_text: str) -> Dict:
        """
        Complete pipeline to process extracted text into structured timetable
        
        Args:
            extracted_text (str): Raw extracted text from image
            
        Returns:
            Dict: Structured timetable data
        """
        # Get structured response from LLM
        llm_response = self.structure_timetable(extracted_text)
        
        # Validate and clean the JSON
        structured_data = self.validate_and_clean_json(llm_response)
        
        return structured_data
    
    def format_for_display(self, timetable_data: Dict) -> str:
        """
        Format timetable data for display in Telegram messages
        
        Args:
            timetable_data (Dict): Structured timetable data
            
        Returns:
            str: Formatted string for display
        """
        if not timetable_data:
            return "No timetable data available."
        
        formatted_text = " **Your Weekly Timetable** \n\n"
        
        days_order = ["Monday", "Tuesday", "Wednesday", "Thursday", "Friday", "Saturday"]
        
        for day in days_order:
            if day in timetable_data:
                formatted_text += f"**{day.upper()}**\n"
                
                if not timetable_data[day]:
                    formatted_text += "No classes scheduled\n\n"
                    continue
                
                for period in timetable_data[day]:
                    time = period.get('time', 'N/A')
                    subject = period.get('subject', 'N/A')
                    full_name = period.get('full_name', '')
                    period_type = period.get('type', '')
                    
                    formatted_text += f" {time} - {subject}"
                    if full_name:
                        formatted_text += f" ({full_name})"
                    if period_type:
                        formatted_text += f" [{period_type}]"
                    formatted_text += "\n"
                
                formatted_text += "\n"
        
        return formatted_text

