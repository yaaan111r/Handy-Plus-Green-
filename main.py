import os
import logging
import requests
from fastapi import FastAPI, Request
from google import genai
from google.genai import types

# הגדרת לוגים להתחקות אחר אירועים ב-Render
logging.basicConfig(level=logging.INFO)
logger = logging.getLogger(__name__)

app = FastAPI()

# 1. טעינת משתני סביבה
GEMINI_API_KEY = os.getenv("GEMINI_API_KEY")
GREEN_API_INSTANCE_ID = os.getenv("GREEN_API_INSTANCE_ID") # למשל: 710722732656
GREEN_API_TOKEN = os.getenv("GREEN_API_TOKEN")             # ה-Token מ-Green API

# בדיקת מפתח Gemini באופן בטוח למניעת קריסת השרת בהעלאה
if not GEMINI_API_KEY:
    logger.error("CRITICAL: GEMINI_API_KEY is missing in Environment Variables!")
    client = None
else:
    client = genai.Client(api_key=GEMINI_API_KEY)

GREEN_API_BASE_URL = f"https://api.green-api.com/waInstance{GREEN_API_INSTANCE_ID}" if GREEN_API_INSTANCE_ID else ""

# 2. מחירון עבודה בלבד (Labor Only) עבור Handy Plus
PRICE_LIST = """
1. התקנת גוף תאורה צמוד תקרה/קיר: 180-250 ש"ח
2. החלפת שקע/מתג חשמל יחיד: 150-200 ש"ח
3. התקנת מאוורר תקרה: 300-450 ש"ח
4. תליית טלוויזיה על זרוע/מתלה (עד 65 אינץ'): 250-350 ש"ח
5. תליית מדף / תמונה / מראה: 120-180 ש"ח
6. הרכבת ארון מאיקאה (2 דלתות): 300-450 ש"ח
7. החלפת סיפון בכיור: 180-250 ש"ח
8. החלפת ברז כיור/מטבח: 220-300 ש"ח
9. תיקון נזילה קלה / החלפת גומייה: 150-200 ש"ח
10. התקנת מנעול / צילינדר בדלת: 200-300 ש"ח
"""

SYSTEM_PROMPT = f"""
אתה נציג שירות ואבחון אוטומטי של חברת "הנדי פלוס" (Handy Plus) המציעה שירותי הנדימן ותיקונים לבית.
תפקידך לאבחן את התקלה או ההתקנה הנדרשת ולספק הצעת מחיר מדויקת עבור **עבודה בלבד (Labor Only)**.

המחירון המלא של הלקוח:
{PRICE_LIST}

כללים מחייבים לתשובה:
1. **אם התקבלה תמונה:** נתח אותה תחילה. שאל את המשתמש שאלת אישור קצרה, למשל: "מזיהוי התמונה נראה שמדובר ב-[שם השירות], האם נדרש [תיאור הפעולה]?"
2. **אם המשתמש מאשר או מפרט בטקסט:** התאם את השירות למחירון, קובע את טווח המחיר, וציין בפירוש שהמחיר הינו עבור עבודה בלבד ואינו כולל חלפים/ציוד.
3. **שירותים שאינם במחירון (כגון תיקון מזגנים/מוצרי חשמל כבדים):** ציין באדיבות שהשירות אינו מבוצע על ידך.
4. שמור על שפה מקצועית, קצרה, אדיבה ומהירה.
"""

def send_green_api_message(chat_id: str, text: str):
    """שליחת הודעת טקסט בחזרה ללקוח דרך Green API עם timeout בטוח"""
    if not GREEN_API_INSTANCE_ID or not GREEN_API_TOKEN:
        logger.error("Green API Instance ID or Token missing. Cannot send message.")
        return

    url = f"{GREEN_API_BASE_URL}/sendMessage/{GREEN_API_TOKEN}"
    payload = {
        "chatId": chat_id,
        "message": text
    }
    headers = {"Content-Type": "application/json"}
    
    try:
        response = requests.post(url, json=payload, headers=headers, timeout=10)
        logger.info(f"Green API Response Status: {response.status_code}")
    except requests.exceptions.RequestException as e:
        logger.error(f"Failed to send message via Green API: {e}")

# בדיקת תקינות ראשונית של Webhook (עבור מנגנון האימות של Green API)
@app.get("/webhook")
def verify_webhook():
    return {"status": "Webhook endpoint is active"}

# קבלת הודעות נכנסות מ-Green API
@app.post("/webhook")
async def whatsapp_webhook(request: Request):
    try:
        data = await request.json()
        logger.info(f"Incoming Webhook Payload: {data}")

        # סינון אירועים שאינם הודעה נכנסת מלקוח
        type_webhook = data.get("typeWebhook")
        if type_webhook != "incomingMessageReceived":
            return {"status": "ignored"}

        message_data = data.get("messageData", {})
        sender_data = data.get("senderData", {})
        chat_id = sender_data.get("chatId")

        if not chat_id:
            return {"status": "no_chat_id"}

        # בדיקה שתשתיות ה-AI תקינות
        if not client:
            logger.error("Gemini client is not initialized.")
            send_green_api_message(chat_id, "מצטערים, המערכת בתחזוקה קלה כרגע. אנא נסה שוב מאוחר יותר.")
            return {"status": "error", "message": "Gemini API key missing"}

        contents = [SYSTEM_PROMPT]
        type_message = message_data.get("typeMessage")

        # 1. טיפול בתמונות נכנסות
        if type_message in ["imageMessage", "fileMessage"]:
            file_data = message_data.get("fileMessageData", {})
            download_url = file_data.get("downloadUrl")
            caption = file_data.get("caption", "")

            if download_url:
                try:
                    img_res = requests.get(download_url, timeout=15)
                    if img_res.status_code == 200:
                        image_part = types.Part.from_bytes(
                            data=img_res.content,
                            mime_type=img_res.headers.get("Content-Type", "image/jpeg")
                        )
                        contents.append(image_part)
                except requests.exceptions.RequestException as e:
                    logger.error(f"Failed to download image: {e}")

            if caption:
                contents.append(caption)

        # 2. טיפול בהודעת טקסט רגילה
        elif type_message == "textMessage":
            text_data = message_data.get("textMessageData", {})
            text_body = text_data.get("textMessage", "")
            if text_body:
                contents.append(text_body)

        else:
            # מענה להודעות לא נתמכות (קוליות, מיקום וכו')
            send_green_api_message(
                chat_id, 
                "שלום! כרגע אני יודע לקבל הודעות טקסט ותמונות בלבד. נשמח שתתאר את התקלה או שתשלח תמונה."
            )
            return {"status": "unsupported_media"}

        # 3. פנייה ל-Gemini 3.1-Flash-Lite
        response = client.models.generate_content(
            model="gemini-3.1-flash-lite",
            contents=contents
        )
        reply_text = response.text

        # 4. שליחת התשובה ללקוח ב-WhatsApp
        send_green_api_message(chat_id, reply_text)

        return {"status": "success"}

    except Exception as e:
        logger.error(f"Error processing webhook: {str(e)}", exc_info=True)
        return {"status": "error", "message": str(e)}

@app.get("/")
def health_check():
    return {"status": "Handy Plus Green API Bot is up and running!"}
