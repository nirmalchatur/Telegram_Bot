import os
import logging
import time
from datetime import datetime
from telebot import TeleBot, types
import google.generativeai as genai
from pymongo import MongoClient
from PIL import Image
from io import BytesIO
from dotenv import load_dotenv
from serpapi import GoogleSearch
import sys
from PyPDF2 import PdfReader
from serpapi import GoogleSearch

# Load environment variables
load_dotenv()

# Setup logging
logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s - %(levelname)s - %(message)s"
)

# Validate environment variables
BOT_TOKEN = os.getenv("TELEGRAM_BOT_TOKEN")
GEMINI_API_KEY = os.getenv("GEMINI_API_KEY")
MONGO_URI = os.getenv("MONGO_URI")
SERP_API_KEY = os.getenv("SERP_API_KEY")

if not all([BOT_TOKEN, GEMINI_API_KEY, MONGO_URI, SERP_API_KEY]):
    logging.error("Missing required environment variables")
    exit(1)

# Initialize components
bot = TeleBot(BOT_TOKEN)
genai.configure(api_key=GEMINI_API_KEY)
model = genai.GenerativeModel('gemini-1.5-flash')

# Database connection
try:
    mongo_client = MongoClient(MONGO_URI)
    mongo_client.server_info()
    db = mongo_client['telegram_bot']
    users_collection = db['users']
    sentiments_collection = db['sentiments']
except Exception as e:
    logging.error(f"Database connection failed: {e}")
    exit(1)

# ========================
# CORE FUNCTIONS
# ========================

@bot.message_handler(commands=['start'])
def handle_start(message):
    chat_id = message.chat.id
    user = users_collection.find_one({"chat_id": chat_id})
    
    if not user:
        users_collection.insert_one({
            "chat_id": chat_id,
            "first_name": message.from_user.first_name,
            "username": message.from_user.username,
            "phone_number": None,
            "created_at": datetime.now()
        })
        bot.send_message(chat_id, "👋 Welcome! Please share your phone number to continue.")
        request_phone_number(message)
    else:
        show_main_menu(message)

def show_main_menu(message):
    markup = types.ReplyKeyboardMarkup(resize_keyboard=True)
    markup.row("📷 Image Analysis", "🌐 Web Search")
    markup.row("📊 Sentiment Report", "👤 My Profile")
    markup.row("💬 Chat with Gemini", "🛑 Stop Bot")
    bot.send_message(
        message.chat.id,
        "🔧 Main Menu - Select an option:",
        reply_markup=markup
    )


# ========================
# MENU HANDLERS
# ========================

@bot.message_handler(func=lambda msg: msg.text in [
    "📷 Image Analysis", "🌐 Web Search",
    "📊 Sentiment Report", "👤 My Profile",
    "💬 Chat with Gemini", "🛑 Stop Bot"
])
def handle_menu_selection(message):
    chat_id = message.chat.id
    try:
        if message.text == "📷 Image Analysis":
            bot.send_message(chat_id, "📤 Please send an image for analysis")
            
        elif message.text == "🌐 Web Search":
            msg = bot.send_message(chat_id, "🔍 What would you like to search for?")
            bot.register_next_step_handler(msg, process_web_search)
            
        elif message.text == "📊 Sentiment Report":
            generate_sentiment_report(message)
            
        elif message.text == "👤 My Profile":
            show_user_profile(message)
        
        elif message.text == "💬 Chat with Gemini":
            msg = bot.send_message(chat_id, "🤖 Ask anything to Gemini AI:")
            bot.register_next_step_handler(msg, chat_with_gemini)
            
        elif message.text == "🛑 Stop Bot":
            stop_bot(message)
            
    except Exception as e:
        logging.error(f"Menu handler error: {e}")
        bot.send_message(chat_id, "⚠️ Error processing your request")
# ========================
# CHAT WITH GEMINI
# ========================

def chat_with_gemini(message):
    chat_id = message.chat.id
    user_input = message.text.strip()

    if not user_input:
        bot.send_message(chat_id, "❌ Please enter a valid query.")
        return
    
    try:
        bot.send_message(chat_id, "🤖 Thinking...")

        response = model.generate_content(user_input)
        bot.send_message(chat_id, f"💡 Gemini says:\n{response.text}")

    except Exception as e:
        logging.error(f"Gemini chat error: {e}")
        bot.send_message(chat_id, "⚠️ Failed to fetch a response from Gemini.")

# ========================
# WEB SEARCH FUNCTIONALITY
# ========================

def process_web_search(message):
    chat_id = message.chat.id
    try:
        query = message.text.strip()
        if not query:
            bot.send_message(chat_id, "❌ Search cancelled")
            return
            
        bot.send_message(chat_id, "🔎 Searching the web...")
        
        params = {
            "q": query,
            "api_key": SERP_API_KEY,
            "engine": "google",
        }
        
        search = GoogleSearch(params)
        results = search.get_dict().get('organic_results', [])[:3]
        
        if results:
            response = "\n".join(
                [f"{i+1}. [{res['title']}]({res['link']})" 
                 for i, res in enumerate(results)]
            )
            bot.send_message(chat_id, f"🌐 Top Results for '{query}':\n{response}", 
                           parse_mode="Markdown")
        else:
            bot.send_message(chat_id, "❌ No results found")
            
    except Exception as e:
        logging.error(f"Search error: {e}")
        bot.send_message(chat_id, "⚠️ Search failed. Please try again")

# ========================
# IMAGE PROCESSING
# ========================
# ... (keep all previous imports and setup unchanged)

# ========================
# PDF PROCESSING
# ========================

@bot.message_handler(content_types=['document'])
def handle_pdf(message):
    chat_id = message.chat.id
    try:
        if message.document.mime_type != 'application/pdf':
            bot.send_message(chat_id, "⚠️ Please send a PDF file")
            return

        # Send processing message
        processing_msg = bot.send_message(chat_id, "📄 Processing PDF...")

        # Download PDF file
        file_info = bot.get_file(message.document.file_id)
        file_data = bot.download_file(file_info.file_path)
        
        # Save to temporary file
        pdf_path = f"temp_{chat_id}.pdf"
        with open(pdf_path, 'wb') as f:
            f.write(file_data)

        # Extract text from PDF
        text = extract_text_from_pdf(pdf_path)
        
        if not text:
            bot.send_message(chat_id, "❌ No text found in PDF")
            return

        # Classify content using Gemini
        classification = classify_pdf_content(text)
        bot.send_message(chat_id, f"📑 PDF Analysis:\n{classification}")

    except Exception as e:
        logging.error(f"PDF error: {str(e)}")
        bot.send_message(chat_id, "⚠️ Error processing PDF")
    finally:
        try:
            os.remove(pdf_path)  # Cleanup temp file
            bot.delete_message(chat_id, processing_msg.message_id)
        except:
            pass

def extract_text_from_pdf(pdf_path):
    try:
        reader = PdfReader(pdf_path)
        text = ""
        for page in reader.pages:
            page_text = page.extract_text()
            if page_text:
                text += page_text + "\n"
        return text.strip()
    except Exception as e:
        logging.error(f"PDF extraction error: {e}")
        return ""

def classify_pdf_content(text):
    try:
        prompt = f"""Analyze this document and provide:
        1. Document type (report, article, etc.)
        2. Main topic
        3. Key points (3-5 bullet points)
        4. Overall sentiment
        
        Document content: {text[:10000]}"""  # Limit to first 10k characters
        
        response = model.generate_content(prompt)
        return response.text
    except Exception as e:
        logging.error(f"Classification error: {e}")
        return "⚠️ Failed to analyze document content"

# ... (keep all other existing functions unchanged)
@bot.message_handler(content_types=['photo'])
def handle_image(message):
    chat_id = message.chat.id
    try:
        processing_msg = bot.send_message(chat_id, "🖼️ Analyzing image...")
        
        file_info = bot.get_file(message.photo[-1].file_id)
        image_data = bot.download_file(file_info.file_path)
        img = Image.open(BytesIO(image_data))
        
        response = model.generate_content(["Describe this image in detail", img])
        response.resolve()
        
        bot.send_message(chat_id, f"📸 Image Analysis:\n{response.text}")
        bot.send_message(chat_id, "💡 Ask follow-up questions about the image")
        
    except Exception as e:
        bot.send_message(chat_id, f"⚠️ Error: {str(e)}")
    finally:
        try:
            bot.delete_message(chat_id, processing_msg.message_id)
        except:
            pass

# ========================
# SENTIMENT ANALYSIS
# ========================

@bot.message_handler(func=lambda msg: True)
def analyze_sentiment(message):
    chat_id = message.chat.id
    text = message.text.strip()
    
    if not text or text.startswith('/'):
        return
    
    try:
        prompt = f"""Classify sentiment as Positive, Neutral, or Negative:
        Message: {text}"""
        
        response = model.generate_content(prompt)
        sentiment = response.text.strip().lower()
        
        sentiments_collection.insert_one({
            "chat_id": chat_id,
            "message": text,
            "sentiment": sentiment,
            "timestamp": datetime.now()
        })
        
        if "positive" in sentiment:
            bot.send_message(chat_id, "😊 Positive vibes detected!")
        elif "negative" in sentiment:
            bot.send_message(chat_id, "😟 Negative sentiment noted")
        else:
            bot.send_message(chat_id, "🤔 Neutral message recorded")
            
    except Exception as e:
        logging.error(f"Sentiment error: {e}")

def generate_sentiment_report(message):
    chat_id = message.chat.id
    try:
        records = list(sentiments_collection.find(
            {"chat_id": chat_id},
            sort=[("timestamp", -1)],
            limit=10
        ))
        
        if not records:
            bot.send_message(chat_id, "📊 Start chatting to generate insights!")
            return
            
        positive = sum(1 for r in records if 'positive' in r['sentiment'])
        neutral = sum(1 for r in records if 'neutral' in r['sentiment'])
        negative = sum(1 for r in records if 'negative' in r['sentiment'])
        total = len(records)
        
        report = f"""
📈 Emotional Analysis (Last {total} messages):
✅ Positive: {positive} ({positive/total:.0%})
🔄 Neutral: {neutral} ({neutral/total:.0%})
❌ Negative: {negative} ({negative/total:.0%})

💡 Mood Pattern: {"😊 Mostly Positive" if positive > negative else 
                 "😟 Needs Support" if negative > positive else 
                 "⚖️ Balanced Emotions"}
        """
        bot.send_message(chat_id, report)
        
    except Exception as e:
        logging.error(f"Report error: {e}")
        bot.send_message(chat_id, "⚠️ Failed to generate report")

# ========================
# USER MANAGEMENT
# ========================

def show_user_profile(message):
    chat_id = message.chat.id
    try:
        user = users_collection.find_one({"chat_id": chat_id})
        if user:
            response = (
                "👤 User Profile:\n"
                f"├ Name: {user.get('first_name', 'N/A')}\n"
                f"├ Username: @{user.get('username', 'N/A')}\n"
                f"└ Phone: {user.get('phone_number', 'Not provided')}"
            )
            bot.send_message(chat_id, response)
        else:
            bot.send_message(chat_id, "❌ Profile not found")
    except Exception as e:
        logging.error(f"Profile error: {e}")
        bot.send_message(chat_id, "⚠️ Failed to load profile")

def request_phone_number(message):
    markup = types.ReplyKeyboardMarkup(
        one_time_keyboard=True,
        resize_keyboard=True
    )
    button = types.KeyboardButton("📱 Share Phone Number", request_contact=True)
    markup.add(button)
    bot.send_message(
        message.chat.id,
        "🔐 Please share your phone number:",
        reply_markup=markup
    )

@bot.message_handler(content_types=['contact'])
def save_phone_number(message):
    chat_id = message.chat.id
    try:
        if message.contact:
            users_collection.update_one(
                {"chat_id": chat_id},
                {"$set": {"phone_number": message.contact.phone_number}}
            )
            bot.send_message(chat_id, "✅ Phone number saved!")
            show_main_menu(message)
    except Exception as e:
        logging.error(f"Phone save error: {e}")
        bot.send_message(chat_id, "⚠️ Failed to save contact")

# ========================
# SYSTEM CONTROLS
# ========================

def stop_bot(message):
    chat_id = message.chat.id
    bot.send_message(chat_id, "🛑 Session ended. Use /start to begin again!")
    logging.info(f"Bot stopped by {chat_id}")
    bot.stop_polling()
    sys.exit(0)

# ========================
# MAIN EXECUTION
# ========================

if __name__ == "__main__":
    logging.info("Starting bot...")
    while True:
        try:
            bot.polling(non_stop=True, interval=2)
        except Exception as e:
            logging.error(f"Polling error: {e}")
            time.sleep(5)