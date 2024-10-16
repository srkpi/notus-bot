import json
import asyncio
import re
import requests
import sqlite3
from datetime import datetime, timezone
from google.oauth2 import service_account
from googleapiclient.discovery import build
from telegram import Update, Bot, BotCommand, InlineKeyboardButton, InlineKeyboardMarkup, LinkPreviewOptions
from telegram.ext import ApplicationBuilder, CommandHandler, ContextTypes, filters, MessageHandler, CallbackQueryHandler


# Налаштування Google Forms API
SCOPES = ['https://www.googleapis.com/auth/forms.responses.readonly', 'https://www.googleapis.com/auth/forms.body.readonly', 'https://www.googleapis.com/auth/drive.readonly']
SERVICE_ACCOUNT_FILE = 'client_secrets.json'
credentials = service_account.Credentials.from_service_account_file(SERVICE_ACCOUNT_FILE, scopes=SCOPES)
service = build('forms', 'v1', credentials=credentials)
drive_service = build('drive', 'v3', credentials=credentials)

# Налаштування Telegram бота
TELEGRAM_TOKEN = ''
bot = Bot(token=TELEGRAM_TOKEN)

#БД
conn = sqlite3.connect('forms_data.db')
cursor = conn.cursor()


cursor.execute('''
    CREATE TABLE IF NOT EXISTS forms_data (
        chat_id INTEGER,
        group_id TEXT,
        form_id TEXT,
        sent_response_ids TEXT
    )
''')
conn.commit()


forms_data = {}
start_time = datetime.now(timezone.utc)


def get_id_from_url(url):
    pattern = r"forms/d/([a-zA-Z0-9_-]+)"
    match = re.search(pattern, url)
    print(f'URL: {url}, match: {match.group(1)}')
    if match:
        return match.group(1)
    else:
        return None


def load_sent_response_ids():
    try:
        with open('response_ids.json', 'r') as file:
            return set(json.load(file))
    except FileNotFoundError:
        return set()


def save_sent_response_ids(response_ids):
    with open('response_ids.json', 'w') as file:
        json.dump(list(response_ids), file)


def get_group_name(group_id):
    response = requests.get(f'https://api.telegram.org/bot{TELEGRAM_TOKEN}/getChat?chat_id={group_id}')
    response.raise_for_status()
    chat_info = response.json()
    return chat_info['result']['title']


async def set_commands(bot: Bot):
    commands = [
        BotCommand("start", "Привітання"),
        BotCommand("help", "Допомога"),
        BotCommand("list", "Показати привʼязані форми"),
        BotCommand("connect", "Привʼязати форму"),
        BotCommand("delete", "Видалити привʼязану форму"),
    ]
    await bot.set_my_commands(commands)


def save_form_data(chat_id, group_id, form_id, sent_response_ids):
    cursor.execute('''
        INSERT INTO forms_data (chat_id, group_id, form_id, sent_response_ids)
        VALUES (?, ?, ?, ?)
    ''', (chat_id, group_id, form_id, json.dumps(list(sent_response_ids))))
    conn.commit()


def load_form_data(chat_id):
    cursor.execute('SELECT group_id, form_id, sent_response_ids FROM forms_data WHERE chat_id = ?', (chat_id,))
    rows = cursor.fetchall()
    data = {}
    for row in rows:
        group_id, form_id, sent_response_ids = row
        data[form_id] = {
            'group_id': group_id,
            'form_id': form_id,
            'sent_response_ids': set(json.loads(sent_response_ids))
        }
    return data


def delete_form_data(chat_id, form_id=None):
    if form_id:
        cursor.execute('DELETE FROM forms_data WHERE chat_id = ? AND form_id = ?', (chat_id, form_id))
    else:
        cursor.execute('DELETE FROM forms_data WHERE chat_id = ?', (chat_id,))
    conn.commit()


async def start(update: Update, context: ContextTypes.DEFAULT_TYPE):
    if update.message.chat.type == 'private':
        await update.message.reply_text('Привіт, я бот для роботи з Google Forms. Додай мене в групу за допомогою команди /connect.')
    if update.message.chat.type == 'supergroup':
        await update.message.reply_text('Привіт, надішліть посилання на форму у форматі /connect <url> (посилання має закінчуватись на /edit).')


async def connect(update: Update, context: ContextTypes.DEFAULT_TYPE):
    if update.message.chat.type == 'private':
        keyboard = [[InlineKeyboardButton(text='Обрати групу', url='t.me/AnswerTestFormsABot?startgroup=botstart')]]
        reply_markup = InlineKeyboardMarkup(keyboard)
        await update.message.reply_text('Додай бота в групу та надішли там команду /start:', reply_markup=reply_markup)

    if update.message.chat.type == 'supergroup':
        chat_id = update.message.chat_id
        if len(context.args) != 1:
            await update.message.reply_text('Для привʼязки форми до групи надішли посилання на форму у форматі /connect <url> (посилання має закінчуватись на /edit).')
            return
        form_url = context.args[0]
        if not form_url.endswith('/edit'):
            await update.message.reply_text('Посилання має закінчуватись на /edit.')
            return
        form_id = get_id_from_url(form_url)
        if chat_id not in forms_data:
            forms_data[chat_id] = {}
        forms_data[chat_id][form_id] = {'group_id': chat_id, 'form_id': form_id, 'sent_response_ids': load_sent_response_ids()}
        save_form_data(chat_id, chat_id, form_id, forms_data[chat_id][form_id]['sent_response_ids'])
        await update.message.reply_text(f'Форма {form_id} привʼязана до групи {chat_id}.')


async def help(update: Update, context: ContextTypes.DEFAULT_TYPE):
    await update.message.reply_text(
        '1. Для початку роботи додайте бота в групу.\n\n'
        '2. В групі надішліть посилання на форму у форматі /connect <url> (посилання має закінчуватись на /edit).\n\n'
        '3. 🎉 Після цього бот надсилатиме відповіді на форму в групу.')


async def delete(update: Update, context: ContextTypes.DEFAULT_TYPE):
    chat_id = update.message.chat_id
    if len(context.args) != 1:
        await update.message.reply_text('Для видалення форми надішли посилання на форму у форматі /delete <url>.')
        return
    form_url = context.args[0]
    if not form_url.endswith('/edit'):
        await update.message.reply_text('Посилання має закінчуватись на /edit.')
        return
    form_id = get_id_from_url(form_url)

    data = load_form_data(chat_id)
    if not data:
        await update.message.reply_text('До цієї групи ще не привʼязано жодної форми.')
        return

    if form_id in data:
        delete_form_data(chat_id, form_id)
        del forms_data[chat_id][form_id]
        await update.message.reply_text(f'Форма {form_id} видалена.')
    else:
        await update.message.reply_text('Ця форма не привʼязана до групи.')


async def list_forms(update: Update, context: ContextTypes.DEFAULT_TYPE):
    chat_id = update.message.chat_id
    forms_data[chat_id] = load_form_data(chat_id)
    if forms_data[chat_id]:
        message = "Привʼязані форми:\n"
        for (index, data) in enumerate(forms_data[chat_id].values()):
            message += f"{index + 1}. https://docs.google.com/forms/d/{data['form_id']}/edit\n"
        await update.message.reply_text(message, link_preview_options=LinkPreviewOptions(is_disabled=True))
    else:
        await update.message.reply_text('До цієї групи ще не привʼязано жодної форми.')


def get_form_responses(form_id):
    try:
        result = service.forms().responses().list(formId=form_id).execute()
        responses = result.get('responses', [])
        return responses
    except Exception as e:
        print(f"Error getting form responses: {e}")
        return []


def get_detailed_response(form_id, response_id):
    try:
        result = service.forms().responses().get(formId=form_id, responseId=response_id).execute()
        return result
    except Exception as e:
        print(f"Error getting detailed response: {e}")
        return {}


def get_form_questions(form_id):
    try:
        form = service.forms().get(formId=form_id).execute()
        questions = {}
        for item in form['items']:
            if 'questionItem' in item and 'question' in item['questionItem'] and 'questionId' in item['questionItem']['question']:
                question_id = item['questionItem']['question']['questionId']
                question_text = item.get('title', 'Без назви')
                questions[question_id] = question_text
            elif 'textItem' in item:
                question_id = item['textItem']['text']
                question_text = item.get('title', 'Без назви')
                questions[question_id] = question_text
            elif 'imageItem' in item:
                question_id = item['imageItem']['image']
                question_text = item.get('title', 'Без назви')
                questions[question_id] = question_text
            elif 'videoItem' in item:
                question_id = item['videoItem']['video']
                question_text = item.get('title', 'Без назви')
                questions[question_id] = question_text
            elif 'timeItem' in item:
                question_id = item['timeItem']['time']
                question_text = item.get('title', 'Без назви')
                questions[question_id] = question_text
            elif 'tableItem' in item:
                table_id = item['tableItem']['table']['questionId']
                table_title = item.get('title', 'Без назви')
                questions[table_id] = table_title
                for row in item['tableItem']['table']['rows']:
                    row_id = row['rowId']
                    row_text = row.get('title', 'Без назви')
                    questions[f"{table_id}_{row_id}"] = row_text
        return questions
    except Exception as e:
        print(f"Error getting form questions: {e}")
        return {}


def format_response(response, questions):
    answers = response.get('answers', {})
    formatted_response = "*Нова відповідь:*\n"
    for question_id, answer in answers.items():
        question = questions.get(question_id, 'Запитання')
        if 'textAnswers' in answer and 'answers' in answer['textAnswers']:
            response_text = ', '.join([ans.get('value', 'Немає відповіді') for ans in answer['textAnswers']['answers']])
            formatted_response += f"{question}: {response_text}\n"
        elif 'fileUploadAnswers' in answer and 'answers' in answer['fileUploadAnswers']:
            file_id = answer['fileUploadAnswers']['answers'][0]['fileId']
            file_url = f"https://drive.google.com/file/d/{file_id}/view?usp=sharing"
            response_file = drive_service.files().get(fileId=file_id, fields='name').execute()
            file_name = response_file.get('name', 'downloaded_file')
            formatted_response += f"{question}:\nНазва файлу: {file_name}\nURL файлу: {file_url}\n"
        elif 'checkboxAnswers' in answer and 'answers' in answer['checkboxAnswers']:
            checkbox_answers = [ans.get('value', 'Немає відповіді') for ans in answer['checkboxAnswers']['answers']]
            formatted_response += f"{question}: {', '.join(checkbox_answers)}\n"
        elif 'tableAnswers' in answer and 'answers' in answer['tableAnswers']:
            table_answers = answer['tableAnswers']['answers']
            formatted_response += f"{question}:\n"
            for row_id, row_answers in table_answers.items():
                for col_id, ans in row_answers['answers'].items():
                    row_text = f"Рядок {questions.get(f'{question_id}_{row_id}', row_id)}: Стовпець {questions.get(col_id, col_id)}: {ans.get('value', 'Немає відповіді')}"
                    formatted_response += f"  {row_text}\n"
        elif 'radioAnswers' in answer and 'answers' in answer['radioAnswers']:
            radio_answer = answer['radioAnswers']['answers'][0].get('value', 'Немає відповіді')
            formatted_response += f"{question}: {radio_answer}\n"
        elif 'scaleAnswers' in answer and 'answers' in answer['scaleAnswers']:
            scale_answer = answer['scaleAnswers']['answers'][0].get('value', 'Немає відповіді')
            formatted_response += f"{question}: {scale_answer}\n"
        elif 'dateAnswers' in answer and 'answers' in answer['dateAnswers']:
            date_answer = answer['dateAnswers']['answers'][0].get('value', 'Немає відповіді')
            formatted_response += f"{question}: {date_answer}\n"
        elif 'timeAnswers' in answer and 'answers' in answer['timeAnswers']:
            time_answer = answer['timeAnswers']['answers'][0].get('value', 'Немає відповіді')
            formatted_response += f"{question}: {time_answer}\n"
        elif 'dropdownAnswers' in answer and 'answers' in answer['dropdownAnswers']:
            dropdown_answer = answer['dropdownAnswers']['answers'][0].get('value', 'Немає відповіді')
            formatted_response += f"{question}: {dropdown_answer}\n"
        else:
            formatted_response += f"{question}: Немає відповіді\n"
    return formatted_response


async def check_for_new_responses():
    while True:
        for chat_id, forms in forms_data.items():
            for form_id, data in forms.items():
                responses = get_form_responses(form_id)
                new_responses = [r for r in responses if r['responseId'] not in data['sent_response_ids'] and datetime.fromisoformat(r['createTime'][:-1]).replace(tzinfo=timezone.utc) > start_time]
                questions = get_form_questions(form_id)
                for response in new_responses:
                    detailed_response = get_detailed_response(form_id, response['responseId'])
                    formatted_response = format_response(detailed_response, questions)
                    await bot.send_message(chat_id=data['group_id'], text=formatted_response, parse_mode='Markdown')
                    data['sent_response_ids'].add(response['responseId'])
                save_form_data(chat_id, data['group_id'], form_id, data['sent_response_ids'])
        await asyncio.sleep(60)

if __name__ == '__main__':
    application = ApplicationBuilder().token(TELEGRAM_TOKEN).build()

    application.add_handler(CommandHandler("start", start))
    application.add_handler(CommandHandler("connect", connect))
    application.add_handler(CommandHandler("delete", delete))
    application.add_handler(CommandHandler("list", list_forms))
    application.add_handler(CommandHandler("help", help))

    loop = asyncio.get_event_loop()
    loop.create_task(check_for_new_responses())
    loop.run_until_complete(set_commands(bot))
    application.run_polling()
