import logging
from telegram import ReplyKeyboardMarkup, ReplyKeyboardRemove, Update
from telegram.ext import (
    filters,
    MessageHandler,
    ApplicationBuilder,
    ContextTypes,
    CommandHandler,
    ConversationHandler
)
from dotenv import load_dotenv
import os
from marktplaats_messages.client import Client
import re
import openai
from marktplaats_gpt.main import load_context
from marktplaats_gpt.scraping import load_item_data
from marktplaats_gpt.user_session import UserSession
from marktplaats_gpt.users_db import UserDB

CONVERSATION_NUMBER_PATTERN = r' \((\d*)\)$'

CONVERSATION, SUGGESTION = range(2)


def conversation_url(conversation_id):
    return f"https://www.marktplaats.nl/messages/{conversation_id}"


def admin_id():
    return int(os.environ.get("TELEGRAM_BOT_ADMIN_ID", "-1"))


def is_admin(user):
    return user.id == admin_id()


async def activate(update: Update, context: ContextTypes.DEFAULT_TYPE) -> int:
    """Activates the user (username specified as first argument). Admin command."""
    user = update.message.from_user

    logging.warn("User %s called /activate %s", user, context.args)
    if not is_admin(user):
        logging.warn(f"Not an admin")
        await update.message.reply_text(
            f"Nice try, talk to <a href='tg://user?id={admin_id()}'>admin</a>",
            reply_markup=ReplyKeyboardRemove(),
            parse_mode='HTML'
        )
        return

    logging.warn(f"Is an admin")
    if len(context.args) == 1:
        subject_user = context.args[0]
        UserDB.set(subject_user, 'status', 'active')
        logging.warn("User %s activated by %s", subject_user, user)
        await update.message.reply_text(
            f"User {subject_user} was activated!",
            reply_markup=ReplyKeyboardRemove(),
            parse_mode='HTML'
        )
        return

    await update.message.reply_text(
        f"Unclear command",
        reply_markup=ReplyKeyboardRemove(),
        parse_mode='HTML'
    )


async def deactivate(update: Update, context: ContextTypes.DEFAULT_TYPE) -> int:
    """Deactivates the user (username specified as first argument). Admin command."""
    user = update.message.from_user

    logging.warn("User %s called /deactivate %s", user, context.args)
    if not is_admin(user):
        logging.warn(f"Not an admin")
        await update.message.reply_text(
            f"Nice try, talk to <a href='tg://user?id={admin_id()}'>admin</a>",
            reply_markup=ReplyKeyboardRemove(),
            parse_mode='HTML'
        )
        return

    logging.warn(f"Is an admin")
    if len(context.args) == 1:
        subject_user = context.args[0]
        old_user_status = UserDB.get(subject_user, 'status')
        if old_user_status:
            UserDB.set(subject_user, 'status', 'inactive')
            logging.warn("User %s deactivated by %s (old status was %s)", subject_user, user, old_user_status)
            await update.message.reply_text(
                f"User {subject_user} was deactivated (old status was {old_user_status})!",
                reply_markup=ReplyKeyboardRemove(),
                parse_mode='HTML'
            )
        else:
            logging.warn("Unknown status of user %s", subject_user)
            await update.message.reply_text(
                f"Unknown status for user {subject_user}!",
                reply_markup=ReplyKeyboardRemove(),
                parse_mode='HTML'
            )
        return

    await update.message.reply_text(
        f"Unclear command",
        reply_markup=ReplyKeyboardRemove(),
        parse_mode='HTML'
    )


async def user_settings(update: Update, context: ContextTypes.DEFAULT_TYPE) -> int:
    """Shows settings of a user (username specified as first argument). Admin command."""
    user = update.message.from_user

    logging.warn("User %s called /user_settings %s", user, context.args)
    if not is_admin(user):
        logging.warn(f"Not an admin")
        await update.message.reply_text(
            f"Nice try, talk to <a href='tg://user?id={admin_id()}'>admin</a>",
            reply_markup=ReplyKeyboardRemove(),
            parse_mode='HTML'
        )
        return

    logging.warn(f"Is an admin")
    if len(context.args) == 1:
        subject_user = context.args[0]
        user_settings = UserDB.get_all(subject_user)
        if user_settings:
            settings_list = []
            for k,v in user_settings.items():
                settings_list.append(f"[{v['modified_time']}] {k}: {v['value']}")
            logging.warn("Showing settings of user %s for %s", subject_user, user)
            settings_section = "\n".join(settings_list)
            await update.message.reply_text(
                f"User {subject_user} settings:\n\n"
                f"<pre>{settings_section}</pre>",
                reply_markup=ReplyKeyboardRemove(),
                parse_mode='HTML'
            )
        else:
            logging.warn("No settings found for user %s", subject_user)
            await update.message.reply_text(
                f"No settings found for user {subject_user}!",
                reply_markup=ReplyKeyboardRemove(),
                parse_mode='HTML'
            )
        return

    await update.message.reply_text(
        f"Unclear command",
        reply_markup=ReplyKeyboardRemove(),
        parse_mode='HTML'
    )


async def admin_help(update: Update, context: ContextTypes.DEFAULT_TYPE):
    user = update.message.from_user

    logging.warn("User %s called /admin_help %s", user, context.args)
    
    if not is_admin(user):
        logging.warn(f"Not an admin")
        await update.message.reply_text(
            f"Nice try, talk to <a href='tg://user?id={admin_id()}'>admin</a>",
            reply_markup=ReplyKeyboardRemove(),
            parse_mode='HTML'
        )
        return

    logging.warn(f"Is an admin")
    await context.bot.send_message(chat_id=update.effective_chat.id, text=get_admin_help())


async def start(update: Update, context: ContextTypes.DEFAULT_TYPE) -> int:
    """Starts the session, lists Marktplaats conversations and asks user which to pick up."""
    user = update.message.from_user
    user_status = UserDB.get(user.username, 'status')
    if user_status != 'active':
        await update.message.reply_text(
            f"You are not known for me, please talk to <a href='tg://user?id={admin_id()}'>admin</a>",
            reply_markup=ReplyKeyboardRemove(),
            parse_mode='HTML'
        )
        return ConversationHandler.END

    logging.info(f"Starting user session for {user}")
    session = UserSession(user_data=context.user_data)

    limit = 5
    offset = 0
    if len(context.args) > 0:
        try:
            limit = int(context.args[0])
        except Exception as e:
            logging.error(e)
            await context.bot.send_message(chat_id=update.effective_chat.id, text=f"I didn't get first (LIMIT) argument for the command. {e}")
    if len(context.args) > 1:
        try:
            offset = int(context.args[1])
        except Exception as e:
            logging.error(e)
            await context.bot.send_message(chat_id=update.effective_chat.id, text=f"I didn't get second (OFFSET) argument for the command. {e}")

    c = Client()

    convs = c.get_conversations(params = {
        'offset': str(offset),
        'limit': str(limit),
    })

    session.set_conversations(convs)

    logging.info(f"Listing {limit} newly-updated conversations (from {offset}):")

    ids = []
    convs_list = [] # "{id} [{unreadMessagesCount}] :: {title} :: {otherParticipant_name} :: {itemId}\n"
    for i, conv in enumerate(convs['_embedded']['mc:conversations']):
        conversation_number = i + 1
        details = ""
        if conv['unreadMessagesCount'] > 0:
            details = f" with {conv['unreadMessagesCount']} unread messages"
        convs_list.append("{conversation_number}. With <b>{otherParticipant_name}</b> on <b>'{title}'{details}</b>\n".format(
            **conv,
            **{
                'otherParticipant_name': conv['otherParticipant']['name'],
                'conversation_number': conversation_number,
                'details': details
            }
        ))
        ids.append(f"{conv['otherParticipant']['name']} ({conversation_number})")

    convs_section = "\n\n".join(convs_list)

    reply_keyboard = [[i] for i in ids]

    await update.message.reply_text(
        "Hi! My name is SalesRep Bot.\n"
        "I will advise you on conversations in Marktplaats, suggesting answers to potential buyers to make them buy on listed price. "
        "Send /cancel to stop.\n\n"
        f"Listing {limit} newly-updated conversations (starting from {offset}).\n\n"
        f"{convs_section}",
        reply_markup=ReplyKeyboardMarkup(
            reply_keyboard, one_time_keyboard=True, input_field_placeholder="Choose conversation"
        ),
        parse_mode='HTML'
    )

    return CONVERSATION


async def conversation(update: Update, context: ContextTypes.DEFAULT_TYPE) -> int:
    """Prints conversation and suggests a reply."""
    user = update.message.from_user
    user_status = UserDB.get(user.username, 'status')
    if user_status != 'active':
        await update.message.reply_text(
            f"You are not known for me, please talk to <a href='tg://user?id={admin_id()}'>admin</a>",
            reply_markup=ReplyKeyboardRemove(),
            parse_mode='HTML'
        )
        return ConversationHandler.END

    conversation_key_str = update.message.text
    logging.info("Conversation key string for %s is %s", user.id, conversation_key_str)

    matches = re.findall(CONVERSATION_NUMBER_PATTERN, conversation_key_str)
    if matches:
        match = matches[-1]
        conversation_number = int(match) - 1
    else:
        await context.bot.send_message(chat_id=update.effective_chat.id, text="Sorry, I didn't understand that.")
        return ConversationHandler.END

    session = UserSession(user_data=context.user_data)
    conv = session.activate_conversation(conversation_number)
    logging.info('Conv %d: %s', conversation_number, conv)
    conversation_id = conv['id']
    item_id = conv["itemId"]

    item_data, url = load_item_data(item_id)
    if not item_data:
        await update.message.reply_text(
            f"<i>Didn't find product description at <a href=\"{url}\">{url}</a></i>.",
            reply_markup=ReplyKeyboardRemove(),
            parse_mode='HTML'
        )
        return ConversationHandler.END
    else:
        await update.message.reply_text(
            f"<i>Reading <a href=\"{url}\">{url}</a></i>\n",
            reply_markup=ReplyKeyboardRemove(),
            parse_mode='HTML'
        )
        session.set_item_data(item_data)

    c = Client()

    messages = c.get_conversation(conversation_id)
    peer = messages['_embedded']['otherParticipant']
    if messages['totalCount'] > messages['limit'] + messages['offset']:
        messages_notice = f". Displaying {messages['limit']}, beginning from {messages['offset']}"
    else:
        messages_notice = ""

    conv_url = conversation_url(conversation_id)
    await update.message.reply_text(
        f"Loading conversation with <b>{peer['name']}</b>\n"
        f"<a href=\"{conv_url}\">{conv_url}</a>\n",
        reply_markup=ReplyKeyboardRemove(),
        parse_mode='HTML'
    )

    completion_messages=[]

    sorted_items = sorted(messages['_embedded']['mc:message'], key=lambda x: x['receivedDate'], reverse=False)
    last_message = sorted_items[-1]

    messages_list = []
    
    for m in sorted_items:
        if m['senderId'] == peer['id']:
            author = peer['name']
            role = "user"
        else:
            author = m['senderId']
            role = "assistant"
        if m['isRead']:
            read_status = '- '
        else:
            read_status = '* '
        messages_list.append(
            f"<i>[{m['receivedDate']}]</i> {read_status}<b>{author}:</b>\n"
            f"<pre>{m['text']}</pre>"
        )
        completion_messages.append({
            "role": role,
            "content": m['text']
        })

    session.set_completion_messages(completion_messages)

    messages_section = "\n\n".join(messages_list)
    await update.message.reply_text(
        f"It has {messages['totalCount']} messages{messages_notice}:\n\n"
        f"{messages_section}",
        reply_markup=ReplyKeyboardRemove(),
        parse_mode='HTML'
    )

    reply_keyboard = [["Yes", "No"]]

    if last_message['senderId'] == peer['id'] or args.conversation_continue:
        await update.message.reply_text(
            "<i>Asking ChatGPT?</i>",
            reply_markup=ReplyKeyboardMarkup(
                reply_keyboard, one_time_keyboard=True, input_field_placeholder="Ask ChatGPT for a suggestion?"
            ),
            parse_mode='HTML'
        )
        return SUGGESTION
    else:
        await update.message.reply_text(
            "Last message was not from peer. No suggestions will be given for this conversation.",
            reply_markup=ReplyKeyboardRemove(),
            parse_mode='HTML'
        )
        return ConversationHandler.END


async def suggestion(update: Update, context: ContextTypes.DEFAULT_TYPE) -> int:
    """Asks ChatGPT for reply suggestion for active conversation and sends to the user."""
    user = update.message.from_user
    user_status = UserDB.get(user.username, 'status')
    if user_status != 'active':
        await update.message.reply_text(
            f"You are not known for me, please talk to <a href='tg://user?id={admin_id()}'>admin</a>",
            reply_markup=ReplyKeyboardRemove(),
            parse_mode='HTML'
        )
        return ConversationHandler.END

    if update.message.text != "Yes":
        logging.info("Not asking ChatGPT, as user %s replied %s", user.id, update.message.text)
        return ConversationHandler.END

    session = UserSession(user_data=context.user_data)
    conv = session.get_active_conversation()
    logging.info('Active conv %s', conv)
    conversation_id = conv['id']

    item_data = session.get_item_data()
    chatgpt_context = session.get_chatgpt_context()
    if not chatgpt_context:
        chatgpt_context = load_context("chat-context")
    context = chatgpt_context + "\n" + item_data
    await update.message.reply_text(
        "<i>This will be the context for ChatGPT request:</i>\n"
        f"<pre>{context}</pre>\n\n"
        "<i>Waiting for ChatGPT answer</i>",
        reply_markup=ReplyKeyboardRemove(),
        parse_mode='HTML'
    )
    
    completion_messages = [{ "role": "system","content": context }] + session.get_completion_messages()

    openai.organization = os.environ.get("OPENAI_ORG_ID")
    openai.api_key = os.environ.get("OPENAI_API_KEY")
    openai_model = os.environ.get("OPENAI_MODEL", "gpt-4")
    logging.debug("About to ask ChatGPT %s model for completion to %s", openai_model, completion_messages)
    completion = openai.ChatCompletion.create(model=openai_model, messages=completion_messages)
    logging.debug("Usage: %s", completion.usage)
    logging.debug("Choice: %s", completion.choices[0].message.content)
    completion = completion.choices[0].message.content
    await update.message.reply_text(
        f"<i>Suggested answer:</i>\n",
        reply_markup=ReplyKeyboardRemove(),
        parse_mode='HTML'
    )
    await update.message.reply_text(
        f"<pre>{completion}</pre>",
        reply_markup=ReplyKeyboardRemove(),
        parse_mode='HTML'
    )

    reply_keyboard = [["Yes"],["No"]]
    await update.message.reply_text(
        "<i>Asking ChatGPT to regenerate?</i>",
        reply_markup=ReplyKeyboardMarkup(
            reply_keyboard, one_time_keyboard=True, input_field_placeholder="Ask ChatGPT for a new suggestion?"
        ),
        parse_mode='HTML'
    )
    return SUGGESTION

    return ConversationHandler.END


async def cancel(update: Update, context: ContextTypes.DEFAULT_TYPE) -> int:
    """Cancels and ends the conversation."""
    user = update.message.from_user
    user_status = UserDB.get(user.username, 'status')
    if user_status != 'active':
        await update.message.reply_text(
            f"You are not known for me, please talk to <a href='tg://user?id={admin_id()}'>admin</a>",
            reply_markup=ReplyKeyboardRemove(),
            parse_mode='HTML'
        )
        return ConversationHandler.END

    logging.info("User %s canceled the conversation.", user.first_name)
    await update.message.reply_text(
        "Bye! I hope we can talk again some day.", reply_markup=ReplyKeyboardRemove()
    )

    return ConversationHandler.END


async def context(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Reset context to new text or to default one, if none provided."""
    user = update.message.from_user
    user_status = UserDB.get(user.username, 'status')
    if user_status != 'active':
        await update.message.reply_text(
            f"You are not known for me, please talk to <a href='tg://user?id={admin_id()}'>admin</a>",
            reply_markup=ReplyKeyboardRemove(),
            parse_mode='HTML'
        )
        return ConversationHandler.END

    session = UserSession(user_data=context.user_data)

    if len(context.args) == 0:
        text = load_context("chat-context")
    else:
        text = " ".join(context.args)
    logging.info("New context for ChatGPT: %s", text)
    session.set_chatgpt_context(text)

    await update.message.reply_text(
        "New context:\n\n"
        f"<pre>{text}</pre>",
        reply_markup=ReplyKeyboardRemove(),
        parse_mode='HTML'
    )


async def help(update: Update, context: ContextTypes.DEFAULT_TYPE):
    user = update.message.from_user

    help_text = get_help()
    if is_admin(user):
        help_text += "/admin_help -- show admin help"

    await context.bot.send_message(chat_id=update.effective_chat.id, text=help_text)


async def echo(update: Update, context: ContextTypes.DEFAULT_TYPE):
    await context.bot.send_message(chat_id=update.effective_chat.id, text="You've just said " + update.message.text)


async def unknown(update: Update, context: ContextTypes.DEFAULT_TYPE):
    user = update.message.from_user

    help_text = get_help()
    if is_admin(user):
        help_text += "/admin_help -- show admin help"

    await context.bot.send_message(chat_id=update.effective_chat.id, text="Sorry, I didn't understand that command.\n\n" + help_text)


def get_help():
    return """Available commands:
/start -- start the session, by listing all conversations first, optional parameters are LIMIT and OFFSET
/context -- reset the ChatGPT context, provide a new text or leave blank to load default
/help -- show this help
"""

def get_admin_help():
    return """Admin commands:
/activate {username} -- activate user by {username}
/deactivate {username} -- deactivate user by {username}
/user_settings {username} -- show settings for {username}
/admin_help -- show this help
"""


def main():
    print("Starting")

    logging.basicConfig(
        format='%(asctime)s - %(name)s - %(levelname)s - %(message)s',
        level=logging.INFO,
        filename='marktplaats-gpt-bot.log',
        filemode='a'
    )

    # Load environment variables from .env file
    load_dotenv()

    UserDB.init_db()

    application = ApplicationBuilder().token(os.environ.get("TELEGRAM_TOKEN")).build()

    conv_handler = ConversationHandler(
        entry_points=[CommandHandler("start", start)],
        states={
            CONVERSATION: [MessageHandler(filters.Regex(".*"), conversation)],
            SUGGESTION: [MessageHandler(filters.Regex("^(Yes|No)$"), suggestion)],
        },
        fallbacks=[CommandHandler("cancel", cancel)],
    )

    application.add_handler(CommandHandler('activate', activate))
    application.add_handler(CommandHandler('deactivate', deactivate))
    application.add_handler(CommandHandler('user_settings', user_settings))
    application.add_handler(conv_handler)
    application.add_handler(CommandHandler('context', context))
    application.add_handler(CommandHandler('help', help))
    application.add_handler(CommandHandler('admin_help', admin_help))
    application.add_handler(MessageHandler(filters.TEXT & (~filters.COMMAND), echo))
    application.add_handler(MessageHandler(filters.COMMAND, unknown))

    # Run the bot until the user presses Ctrl-C
    application.run_polling(allowed_updates=Update.ALL_TYPES)

if __name__ == '__main__':
    main()
