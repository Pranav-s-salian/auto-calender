import logging
import schedule
import time
import threading
from datetime import datetime, timedelta
import pytz
from telegram import Update, InlineKeyboardButton, InlineKeyboardMarkup
from telegram.ext import Application, CommandHandler, MessageHandler, filters, ContextTypes, CallbackQueryHandler
import asyncio
import os
import json
from io import BytesIO

from text_extraction import TextExtractor
from llm import TimetableProcessor
from embeddings import TimetableEmbeddingStore, TimetableQueryProcessor


logging.basicConfig(
    format='%(asctime)s - %(name)s - %(levelname)s - %(message)s',
    level=logging.INFO
)
logger = logging.getLogger(__name__)

class TimetableBot:
    def __init__(self, telegram_token: str, llama_api_key: str, groq_api_key: str):
        
        self.telegram_token = telegram_token
        self.groq_api_key = groq_api_key
        
        # Initialize classes
        self.text_extractor = TextExtractor(llama_api_key)
        self.timetable_processor = TimetableProcessor(groq_api_key)
        self.embedding_store = TimetableEmbeddingStore()
        self.query_processor = TimetableQueryProcessor(groq_api_key, self.embedding_store)
        
        ## sytoring teh user things for details
        self.user_states = {}  
        self.user_reminders = {}  
        self.user_timetables = {} 
        
        ##indian time zone
        self.timezone = pytz.timezone('Asia/Kolkata')
        
        
        self.app = None
        

        self.scheduler_loop = None
    
    def get_current_time(self):
        return datetime.now(self.timezone)
    
    def get_tomorrow_date(self):
        return self.get_current_time() + timedelta(days=1)
    
    async def start(self, update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
        user_id = update.effective_user.id
        
        welcome_message = """
**Welcome to Callendernigga!**

**Available Commands:**
/upload - Upload your timetable image
/settime - Set reminder time
/schedule - View your timetable
/tomorrow - Get tomorrow's classes
/delete - Delete all data and start fresh
/help - Get help

Ready to begin!
        """
        
        await update.message.reply_text(welcome_message, parse_mode='Markdown')
        self.user_states[user_id] = "started"
    
    async def help_command(self, update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
        """Send help information."""
        help_text = """
**Commands:**
/upload - Upload timetable image
/settime - Set reminder time (format: "8:30 PM" or "20:30")
/schedule - View your timetable
/tomorrow - Get tomorrow's schedule
/delete - Delete all data and start fresh

**Usage:**
1 Upload your timetable image
2️Set your reminder time (in IST - Indian Standard Time)
3️Ask questions about your schedule naturally

**Time Zone:** All times are in IST (Asia/Kolkata)
        """
        await update.message.reply_text(help_text, parse_mode='Markdown')
    
    async def upload_command(self, update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
        """Handle upload command."""
        user_id = update.effective_user.id
        self.user_states[user_id] = "waiting_for_image"
        
        message = """
📸 **Upload Your Timetable Image of your class**

make sure taht it is clean and tidy
Send as a photo, dont send other things!!
        """
        
        await update.message.reply_text(message, parse_mode='Markdown')
    
    async def handle_photo(self, update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
        
        user_id = update.effective_user.id
        
        if self.user_states.get(user_id) != "waiting_for_image":
            await update.message.reply_text("Please use /upload command first to upload your timetable image.")
            return
        
        await update.message.reply_text("Image received! Extracting your image")
        
        try:
           
            photo = update.message.photo[-1]
            
            
            photo_file = await context.bot.get_file(photo.file_id)
            photo_bytes = BytesIO()
            await photo_file.download_to_memory(photo_bytes)
            photo_bytes = photo_bytes.getvalue()
            
            
            await update.message.reply_text("🔍 Extracting ")
            extracted_text = self.text_extractor.extract_from_telegram_photo(photo_bytes)
            
            if not extracted_text:
                await update.message.reply_text("Sorry, I couldn't extract text from the image. Please try with a clearer image.")
                return
            
            # Process with LLM
            await update.message.reply_text("Structuring your timetable...")
            structured_data = self.timetable_processor.process_timetable(extracted_text)
            
            if not structured_data:
                await update.message.reply_text("Sorry, I couldn't process your timetable. Please try with a clearer image.")
                return
            
            # Store in embedding database
            await update.message.reply_text("just few seconds to goo, Something is cooking ")
            self.embedding_store.clear_timetable()  # Clear previous data
            self.embedding_store.create_embeddings(structured_data)
            
            
            self.user_timetables[user_id] = structured_data
            
            # Format and send confirmation
            formatted_schedule = self.timetable_processor.format_for_display(structured_data)
            
            success_message = "**Timetable stored successfully!** \n\n"
            success_message += "Here's your processed schedule:\n\n"
            success_message += formatted_schedule
            success_message += "\n\n**Next step:** Use /settime to set your daily reminder time!"
            
            await update.message.reply_text(success_message, parse_mode='Markdown')
            
            self.user_states[user_id] = "timetable_stored"
            
        except Exception as e:
            logger.error(f"Error processing photo: {str(e)}")
            await update.message.reply_text("An error occurred while processing your image. Please try again.")
    
    async def settime_command(self, update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
        """Handle set time command."""
        user_id = update.effective_user.id
        
        if user_id not in self.user_timetables:
            await update.message.reply_text("Please upload your timetable first using /upload command.")
            return
        
        self.user_states[user_id] = "waiting_for_time"
        
        current_time = self.get_current_time().strftime('%I:%M %p IST')
        
        message = f"""
 **Set Your Daily Reminder Time**

Please send me the time when you want to receive daily notifications.
do this else you will forget your time table

**Examples:** 8:30 PM, 9:00 AM, 20:30

**Time Zone:** IST (Asia/Kolkata)
**Current Time:** {current_time}

Just type the time and send it! 
        """
        
        await update.message.reply_text(message, parse_mode='Markdown')
    
    async def handle_time_setting(self, update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
        """Handle time setting from user."""
        user_id = update.effective_user.id
        time_text = update.message.text.strip()
        
        try:
            # Parse time
            reminder_time = self.parse_time(time_text)
            
            if not reminder_time:
                await update.message.reply_text("Invalid time format. Please use formats like '8:30 PM', '8:30 AM', or '20:30'")
                return
            
            # Store reminder time
            self.user_reminders[user_id] = reminder_time
            
            # Schedule reminder
            self.schedule_daily_reminder(user_id, reminder_time)
            
            success_message = f"**Reminder time set successfully!** ⏰\n\n"
            success_message += f"You'll receive daily reminders at **{time_text} IST**.\n\n"
            success_message += f"**Setup Complete!** Your timetable assistant is ready!"
            
            await update.message.reply_text(success_message, parse_mode='Markdown')
            
            self.user_states[user_id] = "fully_setup"
            
        except Exception as e:
            logger.error(f"Error setting time: {str(e)}")
            await update.message.reply_text(" An error occurred while setting your reminder time. Please try again.")
    
    def parse_time(self, time_str: str) -> str:
        """Parse time string to standard format."""
        time_str = time_str.upper().strip()
        
        try:
            # Handle AM/PM format
            if 'AM' in time_str or 'PM' in time_str:
                # Remove IST if present
                time_str = time_str.replace(' IST', '').replace('IST', '').strip()
                time_obj = datetime.strptime(time_str, '%I:%M %p')
                return time_obj.strftime('%H:%M')
            else:
                # Handle 24-hour format
                if ':' in time_str:
                    time_obj = datetime.strptime(time_str, '%H:%M')
                    return time_obj.strftime('%H:%M')
        except:
            pass
        
        return None
    
    async def schedule_command(self, update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
        """Show current timetable."""
        user_id = update.effective_user.id
        
        if user_id not in self.user_timetables:
            await update.message.reply_text("No timetable found. Please upload your timetable first using /upload command.")
            return
        
        timetable_data = self.user_timetables[user_id]
        formatted_schedule = self.timetable_processor.format_for_display(timetable_data)
        
        message = " **Your Current Timetable**\n\n" + formatted_schedule
        await update.message.reply_text(message, parse_mode='Markdown')
    
    async def tomorrow_command(self, update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
        """Get tomorrow's schedule."""
        user_id = update.effective_user.id
        
        if user_id not in self.user_timetables:
            await update.message.reply_text("No timetable found. Please upload your timetable first using /upload command.")
            return
        
        tomorrow_schedule = self.get_tomorrow_schedule(user_id)
        await update.message.reply_text(tomorrow_schedule, parse_mode='Markdown')
    
    async def delete_command(self, update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
        """Delete all user data with confirmation."""
        user_id = update.effective_user.id
        
        # Check if user has any data
        has_timetable = user_id in self.user_timetables
        has_reminder = user_id in self.user_reminders
        
        if not has_timetable and not has_reminder:
            await update.message.reply_text("No data found to delete. You can start fresh with /upload!")
            return
        
        # Create confirmation buttons
        keyboard = [
            [
                InlineKeyboardButton("Yes, Delete Everything", callback_data=f"confirm_delete_{user_id}"),
                InlineKeyboardButton("Cancel", callback_data=f"cancel_delete_{user_id}")
            ]
        ]
        reply_markup = InlineKeyboardMarkup(keyboard)
        
        # Show what will be deleted
        delete_items = []
        if has_timetable:
            delete_items.append("Your stored timetable")
        if has_reminder:
            delete_items.append("Your daily reminder settings")
        
        items_text = "\n• ".join(delete_items)
        
        confirmation_message = f"""
 **Confirm Data Deletion** 

This will permanently delete:
• {items_text}

 **This action cannot be undone!**

Are you sure you want to proceed?
        """
        
        await update.message.reply_text(
            confirmation_message,
            parse_mode='Markdown',
            reply_markup=reply_markup
        )
    
    async def handle_delete_callback(self, update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
        """Handle delete confirmation callback."""
        query = update.callback_query
        await query.answer()
        
        callback_data = query.data
        user_id = int(callback_data.split('_')[-1])
        
        # Verify user
        if query.from_user.id != user_id:
            await query.edit_message_text("You can only delete your own data.")
            return
        
        if callback_data.startswith("confirm_delete_"):
            # Perform complete deletion
            deleted_items = []
            
            # Clear user timetable
            if user_id in self.user_timetables:
                del self.user_timetables[user_id]
                deleted_items.append("Timetable data")
            
            # Clear user reminders
            if user_id in self.user_reminders:
                del self.user_reminders[user_id]
                deleted_items.append(" Reminder settings")
                # Clear scheduled reminders
                schedule.clear(f'user_{user_id}')
            
            # Clear user state
            if user_id in self.user_states:
                del self.user_states[user_id]
            
            # Clear embedding store (this affects all users - you might want to make this user-specific)
            self.embedding_store.clear_timetable()
            
            items_text = "\n• ".join(deleted_items) if deleted_items else "No data found"
            
            success_message = f"""
**Data Deleted Successfully!** 

Deleted items:
• {items_text}

**You can now start fresh!**
Use /upload to add a new timetable.
            """
            
            await query.edit_message_text(success_message, parse_mode='Markdown')
            
        elif callback_data.startswith("cancel_delete_"):
            await query.edit_message_text(" **Deletion cancelled.** Your data is safe! 🔒")
    
    async def clear_command(self, update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
        """Clear stored timetable data (kept for backward compatibility)."""
        await self.delete_command(update, context)
    
    async def handle_text_message(self, update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
        """Handle general text messages and queries."""
        user_id = update.effective_user.id
        message_text = update.message.text
        
        # Check if waiting for time input
        if self.user_states.get(user_id) == "waiting_for_time":
            await self.handle_time_setting(update, context)
            return
        
        # Check if user has timetable stored
        if user_id not in self.user_timetables:
            await update.message.reply_text(
                "I don't have your timetable yet. Please use /upload to upload your timetable image first! 📸"
            )
            return
        
        # Process as query
        await update.message.reply_text("wiat wait brooo, iam looking into your timetablu")
        
        try:
            response = self.query_processor.process_query(message_text)
            await update.message.reply_text(response, parse_mode='Markdown')
        except Exception as e:
            logger.error(f"Error processing query: {str(e)}")
            await update.message.reply_text("Sorry, I couldn't process your query. Please try again.")
    
    def get_tomorrow_schedule(self, user_id: int) -> str:
        """Get formatted schedule for tomorrow."""
        tomorrow = self.get_tomorrow_date()
        tomorrow_day = tomorrow.strftime('%A')  # Full day name
        
        if user_id not in self.user_timetables:
            return "No timetable found."
        
        timetable_data = self.user_timetables[user_id]
        
        if tomorrow_day not in timetable_data:
            return f"**Tomorrow ({tomorrow_day})**\n\n🎉 No classes scheduled! Enjoy your free day!"
        
        day_schedule = timetable_data[tomorrow_day]
        
        if not day_schedule:
            return f" **Tomorrow ({tomorrow_day})** \n\n No classes scheduled! Enjoy your free day!"
        
        message = f"**Tomorrow's Schedule ({tomorrow_day})** \n\n"
        
        for period in day_schedule:
            time = period.get('time', 'N/A')
            subject = period.get('subject', 'N/A')
            full_name = period.get('full_name', '')
            period_type = period.get('type', '')
            
            message += f" **{time}** - {subject}"
            if full_name:
                message += f"\n    {full_name}"
            if period_type:
                message += f" [{period_type}]"
            message += "\n\n"
        
        message += " Don't forget to bring your materials! Good luck! "
        
        return message
    
    def schedule_daily_reminder(self, user_id: int, reminder_time: str) -> None:
        """Schedule daily reminder for user."""
        def send_reminder():
            # Create a new event loop for this thread if one doesn't exist
            if self.scheduler_loop is None or self.scheduler_loop.is_closed():
                self.scheduler_loop = asyncio.new_event_loop()
                asyncio.set_event_loop(self.scheduler_loop)
            
            # Schedule the coroutine in the event loop
            self.scheduler_loop.run_until_complete(self.send_daily_reminder(user_id))
        
        # Clear existing schedule for this user if any
        schedule.clear(f'user_{user_id}')
        
        # Schedule new reminder
        schedule.every().day.at(reminder_time).do(send_reminder).tag(f'user_{user_id}')
        
        logger.info(f"Scheduled daily reminder for user {user_id} at {reminder_time} IST")
    
    async def send_daily_reminder(self, user_id: int) -> None:
        """Send daily reminder to user."""
        try:
            tomorrow_schedule = self.get_tomorrow_schedule(user_id)
            current_time = self.get_current_time().strftime('%I:%M %p IST')
            reminder_message = f"**Daily Reminder** \n\n{tomorrow_schedule}\n\n Sent at: {current_time}"
            
            await self.app.bot.send_message(
                chat_id=user_id,
                text=reminder_message,
                parse_mode='Markdown'
            )
            
            logger.info(f"Reminder sent to user {user_id} at {current_time}")
            
        except Exception as e:
            logger.error(f"Error sending reminder to user {user_id}: {str(e)}")
    
    def run_scheduler(self) -> None:
        """Run the scheduler in a separate thread."""
        logger.info("Scheduler thread started")
        while True:
            try:
                schedule.run_pending()
                time.sleep(60)  # Check every minute
            except Exception as e:
                logger.error(f"Scheduler error: {str(e)}")
                time.sleep(60)  # Continue after error
    
    async def error_handler(self, update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
        """Log errors and notify user."""
        logger.error(f'Update {update} caused error {context.error}')
        
        if update.effective_message:
            await update.effective_message.reply_text(
                "Sorry, something went wrong. Please try again or contact support."
            )
    
    def run(self) -> None:
        """Start the bot."""
        # Create application
        self.app = Application.builder().token(self.telegram_token).build()
        
        # Add handlers
        self.app.add_handler(CommandHandler("start", self.start))
        self.app.add_handler(CommandHandler("help", self.help_command))
        self.app.add_handler(CommandHandler("upload", self.upload_command))
        self.app.add_handler(CommandHandler("settime", self.settime_command))
        self.app.add_handler(CommandHandler("schedule", self.schedule_command))
        self.app.add_handler(CommandHandler("tomorrow", self.tomorrow_command))
        self.app.add_handler(CommandHandler("delete", self.delete_command))
        self.app.add_handler(CommandHandler("reset", self.delete_command))  # Alias for delete
        self.app.add_handler(CommandHandler("clear", self.clear_command))
        
        # Callback query handler for delete confirmations
        self.app.add_handler(CallbackQueryHandler(self.handle_delete_callback))
        
        # Photo handler
        self.app.add_handler(MessageHandler(filters.PHOTO, self.handle_photo))
        
        # Text message handler
        self.app.add_handler(MessageHandler(filters.TEXT & ~filters.COMMAND, self.handle_text_message))
        
        # Error handler
        self.app.add_error_handler(self.error_handler)
        
        # Start scheduler in separate thread
        scheduler_thread = threading.Thread(target=self.run_scheduler, daemon=True)
        scheduler_thread.start()
        
        # Start the bot
        logger.info("Starting Timetable Bot...")
        print("Timetable Bot is running!")
        print(f" Timezone: Asia/Kolkata (IST)")
        print(f" Current time: {self.get_current_time().strftime('%Y-%m-%d %I:%M:%S %p IST')}")
        print("Send /start to begin using the bot")
        
        # Start polling
        self.app.run_polling(drop_pending_updates=True)

import os

def main():
    """Main function to run the bot."""
    # Load environment variables
    try:
        from dotenv import load_dotenv
        load_dotenv()
    except ImportError:
        print("python-dotenv not found. Using system environment variables.")
    
    # Read from environment
    TELEGRAM_TOKEN = os.getenv("TELEGRAM_BOT_TOKEN")
    LLAMA_API_KEY = os.getenv("LLAMA_CLOUD_API_KEY")
    GROQ_API_KEY = os.getenv("GROQ_API_KEY")
    
    # Validate API keys
    missing_keys = []
    if not TELEGRAM_TOKEN:
        missing_keys.append("TELEGRAM_BOT_TOKEN")
    if not LLAMA_API_KEY:
        missing_keys.append("LLAMA_CLOUD_API_KEY")
    if not GROQ_API_KEY:
        missing_keys.append("GROQ_API_KEY")
    
    
    
    if missing_keys:
        print("Error: Missing required API keys in environment variables:")
        for key in missing_keys:
            print(f"   - {key}")
        print("\n💡 Create a .env file with your API keys or set them as environment variables")
        return
    
    # Test components before starting
    print("🧪 Testing components...")
    try:
        # Test pytz
        import pytz
        tz = pytz.timezone('Asia/Kolkata')
        current_time = datetime.now(tz)
        print(f"✅ Timezone support working - Current IST: {current_time.strftime('%Y-%m-%d %I:%M:%S %p')}")
        
        # Test ChromaDB
        import chromadb
        client = chromadb.Client()
        test_collection = client.create_collection("test")
        client.delete_collection("test")
        print(" ChromaDB working")
        
        # Test Telegram
        from telegram.ext import Application
        Application.builder().token("test").build()
        print("Telegram library working")
        
    except Exception as e:
        print(f"Component test failed: {str(e)}")
        print("Run 'python test_components.py' for detailed diagnostics")
        return
    
    # Create and run bot
    print(" Starting Timetable Bot...")
    
    try:
        bot = TimetableBot(
            telegram_token=TELEGRAM_TOKEN,
            llama_api_key=LLAMA_API_KEY,
            groq_api_key=GROQ_API_KEY
        )
        bot.run()
    except KeyboardInterrupt:
        print("\n Bot stopped by user")
    except Exception as e:
        print(f"Error running bot: {str(e)}")
        print("Try running 'python test_components.py' to diagnose issues")

if __name__ == '__main__':
    main()