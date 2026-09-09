import os
import logging
import requests
from fastapi import FastAPI, Request
from google import genai
from google.genai import types

logging.basicConfig(level=logging.INFO)
logger = logging.getLogger(__name__)

app = FastAPI()

# 1. טעינת משתני סביבה
GEMINI_API_KEY = os.getenv("GEMINI_API_KEY")
GREEN_API_INSTANCE_ID = os.getenv("GREEN_API_INSTANCE_ID") # 710722732656
GREEN_API_TOKEN = os.getenv("GREEN_API_TOKEN")

if not GEMINI_API_KEY:
    logger.error("CRITICAL: GEMINI_API_KEY is missing in Environment Variables!")
    client = None
else:
    client = genai.Client(api_key=GEMINI_API_KEY)

GREEN_API_BASE_URL = f"https://7107.api.greenapi.com/waInstance{GREEN_API_INSTANCE_ID}" if GREEN_API_INSTANCE_ID else ""

# ניהול זיכרון שיחות בזיכרון השרת (לפי chatId)
chat_sessions = {}

PRICE_LIST = """
מחירים לעבודה בלבד (ללא חומרים):
אינסטלציה:
- פתיחת סתימה קלה בכיור/אמבטיה/מקלחון: 180-300 ₪
- פתיחת סתימה מורכבת/צנרת ראשית: 450-700 ₪
- החלפת סיפון: 250-400 ₪
- החלפת ברז (פרח/נשלף/קיר): 280-450 ₪
- תיקון/החלפת מנגנון ניאגרה גלויה: 180-350 ₪
- תיקון/החלפת מנגנון ניאגרה סמויה: 250-380 ₪
- החלפת גומיות/אטמים: 180-250 ₪
- תיקון נזילה גלויה: 180-350 ₪
- החלפת ראש דוש/צינור: 180-280 ₪
- החלפת/התקנת ברז ניל: 180-280 ₪

חשמל ותאורה:
- התקנת גוף תאורה צמוד תקרה/קיר: 230-400 ₪
- התקנת נברשת מורכבת: 280-480 ₪
- התקנת מאוורר תקרה: 250-380 ₪
- החלפת מפסק לתריס חשמלי: 300-450 ₪

הנדימן ותלייה:
- תליית טלוויזיה: 180-280 ₪
- תליית מדפים/זרוע מיקרוגל: 180-250 ₪
- תליית תמונות/מראות: 150-280 ₪
- תליית וילון: 150-280 ₪
- אביזרי אמבטיה: 150-280 ₪

הרכבת רהיטים:
- ארון 2 דלתות: 350-550 ₪ | ארון 3-4 דלתות/הזזה: 450-750 ₪
- שידה/קומודה/שולחן/כוורת: 280-550 ₪
- מיטה: 350-650 ₪
- כיוון צירים/מסילות: 120-250 ₪

דלתות:
- כיוון דלת/החלפת ידית: 180-250 ₪

איננו מבצעים: החלפת אסלות/מונובלוק, נקודות מים חדשות, תיקון מזגנים.
"""

SYSTEM_PROMPT = f"""
אתה בוט וואטסאפ מהיר, ממוקד וקצר של 'הנדי פלוס'.
מטרתך: לאסוף פרטים במינימום הודעות ולתת הצעת מחיר.

חוקי ברזל נוקשים:
1. הודעה קצרה בלבד! מקסימום 1-2 משפטים.
2. תברך "שלום" רק בהודעה הראשונה בשיחה. לאחר מכן - אל תגיד "שלום" יותר לעולם, אלא אם אמרו שלום כלפייך!
3. **ניתוח תמונות ואישור מהמשתמש:**
   - ברגע שמתקבלת תמונה, נתח אותה מיד.
   - שאל את הלקוח בדיוק בנוסח הבא: "אני רואה בתמונה [תיאור הבעיה]. האם נדרש לבצע [תיאור השירות המבוקש המדויק מהמחירון]?"
4. **זרימת השיחה:**
   - אם המשתמש מאשר (תשובה חיובית כמו "כן", "נכון", "בדיוק"): התקדם מיד לשלב של שאלת כתובת מדויקת ודחיפות.
   - אם המשתמש משיב בשלילה (או אומר שלא לזה התכוון): פנה בצורה נעימה ובקש ממנו לחדד מה הטיפול הדרוש.
5. **עבודות שאיננו מבצעים** (כמו תיקון מזגן, החלפת אסלה, נקודת מים): ענה מיד: "אנחנו לא מבצעים עבודה זו, לבירורים ניתן לחייג 055-9821845".
6. **מתן הצעת מחיר:** לאחר אישור השירות והגדרת הכתובת/הדחיפות - תן מחיר משוער מהמחירון (חובה לרשום שזה עבור עבודה בלבד) + הפניה למספר 055-9821845.

מחירון:
{PRICE_LIST}
"""

def get_or_create_chat(user_id: str):
    """ניהול זיכרון שיחה מול Gemini לכל משתמש בנפרד"""
    if user_id not in chat_sessions:
        chat_sessions[user_id] = client.chats.create(
            model='gemini-3.1-flash-lite',
            config=types.GenerateContentConfig(
                system_instruction=SYSTEM_PROMPT
            )
        )
    return chat_sessions[user_id]

def send_green_api_message(chat_id: str, text: str):
    """שליחת הודעת טקסט דרך Green API"""
    if not GREEN_API_INSTANCE_ID or not GREEN_API_TOKEN:
        logger.error("Green API Instance ID or Token missing.")
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

@app.get("/webhook")
def verify_webhook():
    return {"status": "Webhook endpoint is active"}

@app.post("/webhook")
async def whatsapp_webhook(request: Request):
    try:
        data = await request.json()
        
        type_webhook = data.get("typeWebhook")
        if type_webhook != "incomingMessageReceived":
            return {"status": "ignored"}

        message_data = data.get("messageData", {})
        sender_data = data.get("senderData", {})
        chat_id = sender_data.get("chatId")

        if not chat_id:
            return {"status": "no_chat_id"}

        if not client:
            send_green_api_message(chat_id, "שלום! ליצירת קשר עם הנדי פלוס חייג: 055-9821845")
            return {"status": "error", "message": "Gemini API key missing"}

        contents = []
        type_message = message_data.get("typeMessage")

        # 1. קבלת תמונות
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

        # 2. קבלת טקסט רגיל או מורחב
        elif type_message in ["textMessage", "extendedTextMessage"]:
            text_data = message_data.get("textMessageData") or message_data.get("extendedTextMessageData", {})
            text_body = text_data.get("textMessage") or text_data.get("text", "")
            if text_body:
                contents.append(text_body)

        else:
            send_green_api_message(
                chat_id, 
                "שלום! כרגע אני יודע לקבל הודעות טקסט ותמונות בלבד. במה נוכל לעזור?"
            )
            return {"status": "unsupported_media"}

        if not contents:
            send_green_api_message(chat_id, "שלום! הגעת להנדי פלוס. במה נוכל לעזור?")
            return {"status": "empty_payload"}

        # הכנת ה-payload לשליחה בשיחה
        payload = contents if len(contents) > 1 else contents[0]

        # 3. ניהול שיחה עם זיכרון (Chat Session)
        bot_reply = None
        try:
            chat = get_or_create_chat(chat_id)
            response = chat.send_message(payload)
            if response and response.text:
                bot_reply = response.text.strip()
        except Exception as e:
            logger.error(f"Chat Session error for {chat_id}, resetting session: {e}")
            try:
                chat_sessions[chat_id] = client.chats.create(
                    model='gemini-3.1-flash-lite',
                    config=types.GenerateContentConfig(
                        system_instruction=SYSTEM_PROMPT
                    )
                )
                response = chat_sessions[chat_id].send_message(payload)
                if response and response.text:
                    bot_reply = response.text.strip()
            except Exception as inner_e:
                logger.error(f"Critical Gemini API Error: {inner_e}")

        if not bot_reply:
            bot_reply = "במה נוכל לעזור בתחום התיקונים? לפרטים נוספים ניתן גם לחייג 055-9821845."

        # 4. שליחת התשובה בחזרה ללקוח
        send_green_api_message(chat_id, bot_reply)
        return {"status": "success"}

    except Exception as e:
        logger.error(f"Error processing webhook: {str(e)}", exc_info=True)
        return {"status": "error", "message": str(e)}

@app.get("/")
def home():
    return {"status": "Handy Plus Green API Bot is up and running!"}
