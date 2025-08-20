import chromadb
from sentence_transformers import SentenceTransformer
import json
from typing import Dict, List, Optional
from datetime import datetime
import uuid

class TimetableEmbeddingStore:
    def __init__(self, persist_directory: str = "./chroma_db"):
        """
        Initialize ChromaDB for storing timetable embeddings
        
        Args:
            persist_directory (str): Directory to persist the database
        """
        # Initialize ChromaDB client with persistence
        try:
            self.client = chromadb.PersistentClient(path=persist_directory)
        except Exception as e:
            print(f"Warning: ChromaDB persistence issue: {e}")
            # Fallback to in-memory client
            self.client = chromadb.Client()
        
        # Initialize sentence transformer for embeddings
        self.embedding_model = SentenceTransformer('all-MiniLM-L6-v2')
        
        # Get or create collection
        try:
            self.collection = self.client.get_or_create_collection(
                name="timetable_data",
                metadata={"description": "Student timetable information"}
            )
        except Exception as e:
            print(f"Error creating collection: {e}")
            # Delete and recreate if exists
            try:
                self.client.delete_collection(name="timetable_data")
            except:
                pass
            self.collection = self.client.create_collection(
                name="timetable_data",
                metadata={"description": "Student timetable information"}
            )
    
    def create_embeddings(self, timetable_data: Dict) -> None:
        """
        Create and store embeddings for timetable data
        
        Args:
            timetable_data (Dict): Structured timetable data
        """
        documents = []
        metadatas = []
        ids = []
        
        # Process each day and create documents
        for day, periods in timetable_data.items():
            if not periods:  # Skip empty days
                continue
            
            for period in periods:
                # Create a document text for embedding
                doc_text = f"Day: {day}, Time: {period.get('time', '')}, "
                doc_text += f"Subject: {period.get('subject', '')}, "
                doc_text += f"Full Name: {period.get('full_name', '')}, "
                doc_text += f"Type: {period.get('type', '')}"
                
                documents.append(doc_text)
                
                # Create metadata
                metadata = {
                    "day": day,
                    "time": period.get('time', ''),
                    "subject": period.get('subject', ''),
                    "full_name": period.get('full_name', ''),
                    "type": period.get('type', ''),
                    "room": period.get('room', ''),
                    "timestamp": datetime.now().isoformat()
                }
                metadatas.append(metadata)
                
                # Generate unique ID
                ids.append(str(uuid.uuid4()))
        
        if documents:
            # Generate embeddings
            embeddings = self.embedding_model.encode(documents).tolist()
            
            # Store in ChromaDB
            self.collection.add(
                embeddings=embeddings,
                documents=documents,
                metadatas=metadatas,
                ids=ids
            )
            
            print(f"Successfully stored {len(documents)} timetable entries")
        else:
            print("No valid timetable data to store")
    
    def query_timetable(self, query: str, n_results: int = 10) -> List[Dict]:
        """
        Query the timetable database
        
        Args:
            query (str): Query string (e.g., "tomorrow classes", "Monday schedule")
            n_results (int): Number of results to return
            
        Returns:
            List[Dict]: Query results with metadata
        """
        try:
            # Generate embedding for query
            query_embedding = self.embedding_model.encode([query]).tolist()[0]
            
            # Query ChromaDB
            results = self.collection.query(
                query_embeddings=[query_embedding],
                n_results=n_results
            )
            
            # Format results
            formatted_results = []
            if results['documents']:
                for i in range(len(results['documents'][0])):
                    result = {
                        'document': results['documents'][0][i],
                        'metadata': results['metadatas'][0][i],
                        'distance': results['distances'][0][i] if results['distances'] else None
                    }
                    formatted_results.append(result)
            
            return formatted_results
        
        except Exception as e:
            print(f"Error querying timetable: {str(e)}")
            return []
    
    def get_day_schedule(self, day: str) -> List[Dict]:
        """
        Get all classes for a specific day
        
        Args:
            day (str): Day of the week (e.g., "Monday", "Tuesday")
            
        Returns:
            List[Dict]: All classes for the specified day
        """
        try:
            # Query using where filter for specific day
            results = self.collection.get(
                where={"day": day}
            )
            
            # Format results
            formatted_results = []
            if results['documents']:
                for i in range(len(results['documents'])):
                    result = {
                        'document': results['documents'][i],
                        'metadata': results['metadatas'][i]
                    }
                    formatted_results.append(result)
            
            return formatted_results
        
        except Exception as e:
            print(f"Error getting day schedule: {str(e)}")
            return []
    
    def clear_timetable(self) -> None:
        """
        Clear all timetable data from the database
        """
        try:
            # Delete the collection
            self.client.delete_collection(name="timetable_data")
            
            # Recreate empty collection
            self.collection = self.client.get_or_create_collection(
                name="timetable_data",
                metadata={"description": "Student timetable information"}
            )
            
            print("Timetable data cleared successfully")
        
        except Exception as e:
            print(f"Error clearing timetable: {str(e)}")
    
    def get_collection_count(self) -> int:
        """
        Get total number of stored entries
        
        Returns:
            int: Number of entries in the database
        """
        try:
            return self.collection.count()
        except Exception as e:
            print(f"Error getting collection count: {str(e)}")
            return 0

class TimetableQueryProcessor:
    def __init__(self, groq_api_key: str, embedding_store: TimetableEmbeddingStore):
        """
        Initialize query processor with LLM and embedding store
        
        Args:
            groq_api_key (str): Groq API key
            embedding_store (TimetableEmbeddingStore): Embedding store instance
        """
        from langchain_groq import ChatGroq
        from langchain.schema import HumanMessage, SystemMessage
        
        self.llm = ChatGroq(
            groq_api_key=groq_api_key,
            model_name="llama-3.3-70b-versatile",
            temperature=0.1
        )
        self.embedding_store = embedding_store
    
    def process_query(self, query: str) -> str:
        """
        Process user query and return formatted response
        
        Args:
            query (str): User query about timetable
            
        Returns:
            str: Formatted response
        """
        # Query the embedding store
        results = self.embedding_store.query_timetable(query, n_results=5)
        
        if not results:
            return "No relevant timetable information found for your query."
        
        # Format context for LLM
        context = "Timetable Information:\n"
        for result in results:
            metadata = result['metadata']
            context += f"- {metadata['day']} {metadata['time']}: {metadata['subject']}"
            if metadata['full_name']:
                context += f" ({metadata['full_name']})"
            if metadata['type']:
                context += f" [{metadata['type']}]"
            context += "\n"
        
        # Create prompt for LLM
        system_prompt = """You are a helpful timetable assistant. Based on the provided timetable information, answer the user's query in a clear and organized manner. Format your response with appropriate emojis and structure."""
        
        human_prompt = f"""User Query: {query}

{context}

Please provide a clear, organized response to the user's query based on the timetable information above."""
        
        try:
            from langchain.schema import HumanMessage, SystemMessage
            
            messages = [
                SystemMessage(content=system_prompt),
                HumanMessage(content=human_prompt)
            ]
            
            response = self.llm(messages)
            return response.content
        
        except Exception as e:
            print(f"Error processing query: {str(e)}")
            return "Sorry, I couldn't process your query at the moment."

