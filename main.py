import os
import logging
import requests
from fastapi import FastAPI, Request, HTTPException
from google import genai
from google.genai import types

# הגדרת לוגים
logging.basicConfig(level=logging.INFO)
logger = logging.getLogger(__name__)

app = FastAPI()

# מפתח Gemini API
GEMINI_API_KEY = os.getenv("GEMINI_API_KEY")
client = genai.Client(api_key=GEMINI_API_KEY)

# הגדרות Green API (יש להגדיר ב-Render Environment Variables)
GREEN_API_INSTANCE_ID = os.getenv("GREEN_API_INSTANCE_ID") # למשל: 7133123456
GREEN_API_TOKEN = os.getenv("GREEN_API_TOKEN")             # המפתח מ-Green API

GREEN_API_BASE_URL = f"https://api.green-api.com/waInstance{GREEN_API_INSTANCE_ID}"

# מחירון עבודה בלבד (Labor Only)
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
    """שליחת הודעת טקסט בחזרה ללקוח דרך Green API"""
    url = f"{GREEN_API_BASE_URL}/sendMessage/{GREEN_API_TOKEN}"
    payload = {
        "chatId": chat_id,
        "message": text
    }
    headers = {"Content-Type": "application/json"}
    response = requests.post(url, json=payload, headers=headers)
    logger.info(f"Green API Response Status: {response.status_code}")

@app.post("/webhook")
async def whatsapp_webhook(request: Request):
    try:
        data = await request.json()
        logger.info(f"Incoming Webhook Payload: {data}")

        # סינון אירועים שלא קשורים להודעה נכנסת
        type_webhook = data.get("typeWebhook")
        if type_webhook != "incomingMessageReceived":
            return {"status": "ignored"}

        message_data = data.get("messageData", {})
        sender_data = data.get("senderData", {})
        chat_id = sender_data.get("chatId")

        if not chat_id:
            return {"status": "no_chat_id"}

        contents = [SYSTEM_PROMPT]

        # 1. טיפול בתמונות נכנסות
        type_message = message_data.get("typeMessage")
        if type_message in ["imageMessage", "fileMessage"]:
            file_data = message_data.get("fileMessageData", {})
            download_url = file_data.get("downloadUrl")
            caption = file_data.get("caption", "")

            if download_url:
                img_res = requests.get(download_url)
                if img_res.status_code == 200:
                    image_part = types.Part.from_bytes(
                        data=img_res.content,
                        mime_type=img_res.headers.get("Content-Type", "image/jpeg")
                    )
                    contents.append(image_part)
            
            if caption:
                contents.append(caption)

        # 2. טיפול בהודעת טקסט רגילה
        elif type_message == "textMessage":
            text_data = message_data.get("textMessageData", {})
            text_body = text_data.get("textMessage", "")
            if text_body:
                contents.append(text_body)

        else:
            # סוג הודעה לא נתמך (למשל הודעה קולית / מיקום)
            send_green_api_message(chat_id, "שלום! כרגע אני יודע לקבל הודעות טקסט ותמונות בלבד. נשמח שתתאר את התקלה או שתשלח תמונה.")
            return {"status": "unsupported_media"}

        # 3. פנייה למודל Gemini 3.1-Flash-Lite
        response = client.models.generate_content(
            model="gemini-3.1-flash-lite",
            contents=contents
        )
        reply_text = response.text

        # 4. שליחת התשובה בחזרה ללקוח
        send_green_api_message(chat_id, reply_text)

        return {"status": "success"}

    except Exception as e:
        logger.error(f"Error processing webhook: {str(e)}", exc_info=True)
        return {"status": "error", "message": str(e)}

@app.get("/")
def health_check():
    return {"status": "Handy Plus Green API Bot is running!"}
