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
from header_hunter.sniff import sniff_cookie_from_text
from header_hunter.store import store_value
import re
import openai
from marktplaats_gpt.main import load_context
from marktplaats_gpt.scraping import load_item_data
from marktplaats_gpt.user_session import UserSession
from marktplaats_gpt.users_db import UserDB
from marktplaats_gpt.sessions_db import SessionDB
from marktplaats_gpt.version_info import version as the_version
from datetime import datetime


CONVERSATION_NUMBER_PATTERN = r' \((\d*)\)$'

CONVERSATION, SUGGESTION = range(2)


def conversation_url(conversation_id):
    return f"https://www.marktplaats.nl/link/messages/{conversation_id}" # using '/link' makes it a Universal Link, see https://www.marktplaats.nl/.well-known/apple-app-site-association


def admin_id():
    return int(os.environ.get("TELEGRAM_BOT_ADMIN_ID", "-1"))


def is_admin(user):
    return user.id == admin_id()


def time_end_and_delta(str1, str2):
    """Return hh:mm:ss of the session end (str2) + duration in (d+)hh:mm:ss, like Unix `last` command."""
    time_format = "%Y-%m-%d %H:%M:%S"
    dt1 = datetime.strptime(str1, time_format)
    dt2 = datetime.strptime(str2, time_format)
    
    delta = abs(dt2 - dt1)
    
    # Extract days, hours, minutes, and seconds
    days = delta.days
    hours, remainder = divmod(delta.seconds, 3600)
    minutes, seconds = divmod(remainder, 60)

    hours_str2 = dt2.hour
    minutes_str2 = dt2.minute
    seconds_str2 = dt2.second
    
    # Format the result
    if days != 0:
        return f"{hours_str2:02}:{minutes_str2:02}:{seconds_str2:02} ({days}d+{hours:02}:{minutes:02}:{seconds:02})"
    else:
        return f"{hours_str2:02}:{minutes_str2:02}:{seconds_str2:02} ({hours:02}:{minutes:02}:{seconds:02})"


def openai_cost(model: str, prompt_tokens: int, completion_tokens: int):
    """
    Return estimated cost of OpenAI completion, based on prices at https://openai.com/pricing as of 2023-10-23.

    See https://platform.openai.com/docs/models/continuous-model-upgrades for models status.
    """
    if model == "gpt-4-0613": # 8K context	$0.03 / 1K tokens	$0.06 / 1K tokens
        return (0.03 * prompt_tokens ) / 1000.0 + (0.06 * completion_tokens) / 1000.0
    else:
        raise NotImplementedError(f"Model's costs are unknown: {model}!!!")


def users_openai_usage(username: str):
    """Return user's OpenAI total usage in $$."""
    sessions = SessionDB.get_all_for_user(username=username)
    return sum(openai_cost(session['model'], session['prompt_tokens'], session['completion_tokens']) for session in sessions.values() if session['model'])


async def set_quota(update: Update, context: ContextTypes.DEFAULT_TYPE) -> int:
    """Set user's quota for OpenAI use, args: {username} {amount_in_$$$}. Admin command."""
    user = update.message.from_user

    logging.warn("User %s called /set_quota %s", user, context.args)
    if not is_admin(user):
        logging.warn(f"Not an admin")
        await update.message.reply_text(
            f"Nice try, talk to <a href='tg://user?id={admin_id()}'>admin</a>",
            reply_markup=ReplyKeyboardRemove(),
            parse_mode='HTML'
        )
        return

    logging.warn(f"Is an admin")
    
    if len(context.args) == 2:
        subject_user = context.args[0]
        quota_amount_in_us_dollars = context.args[1]
        UserDB.set(subject_user, 'openai-quota', f"{quota_amount_in_us_dollars}")
        logging.warn("User %s quota is set to $%s by %s", subject_user, quota_amount_in_us_dollars, user)
        await update.message.reply_text(
            f"User {subject_user} quota set to ${quota_amount_in_us_dollars}!",
            reply_markup=ReplyKeyboardRemove(),
            parse_mode='HTML'
        )
        return

    await update.message.reply_text(
        f"Unclear command",
        reply_markup=ReplyKeyboardRemove(),
        parse_mode='HTML'
    )


async def last(update: Update, context: ContextTypes.DEFAULT_TYPE) -> int:
    """Lists known users. Extended for Admin."""
    user = update.message.from_user

    logging.warn("User %s called /last %s", user, context.args)

    replay_details = ""
    
    if len(context.args) == 1:
        if not is_admin(user):
            logging.warn(f"Not an admin")
            await update.message.reply_text(
                f"Nice try, talk to <a href='tg://user?id={admin_id()}'>admin</a>",
                reply_markup=ReplyKeyboardRemove(),
                parse_mode='HTML'
            )
            return
        im_an_admin = True
        logging.warn(f"Is an admin")
        subject_user = context.args[0]
        logging.warn("Getting sessions for %s", subject_user)
        sessions = SessionDB.get_all_for_user(username=subject_user)
    else:
        if not is_admin(user):
            im_an_admin = False
            logging.warn(f"Not an admin")
            logging.warn("Getting sessions for self", user.username)
            sessions = SessionDB.get_all_for_user(username=user.username)
        else:
            im_an_admin = True
            logging.warn(f"Is an admin")
            from_seconds = 3600*24*7 # last week
            replay_details = f" for last {from_seconds} seconds"
            logging.warn("Getting sessions for all users for last %d seconds", from_seconds)
            sessions = SessionDB.get_all(from_seconds)

    sessions_list = []
    sessions_stack = {}
    for k,v in sorted(sessions.items(), key=lambda x: x[1]['created_time'], reverse=True):
        username = v['username']
        if v['model']:
            if username not in sessions_stack:
                sessions_stack[username] = []
            sessions_stack[username].append((v['created_time'], v['prompt_tokens'], v['completion_tokens'], v['model']))
        else:
            session_attempts = [(openai_cost(m, pt, ct), pt,ct,) for t,pt,ct,m in sessions_stack[username]]
            session_costs = sum(c[0] for c in session_attempts)
            session_tokens = [(c[1],c[2]) for c in session_attempts]
            session_start = v['created_time']
            if sessions_stack[username]:
                session_end = sessions_stack[username][-1][0]
                session_end_and_delta = time_end_and_delta(session_start, session_end)
            else:
                session_end_and_delta = "                   "
            if im_an_admin:
                sessions_list.append(f"{username} - {session_start} - {session_end_and_delta} : ${session_costs} => {session_tokens}")
            else:
                sessions_list.append(f"{username} - {session_start} - {session_end_and_delta}")
            sessions_stack[username] = []
    sessions_section = "\n".join(sessions_list)
    await update.message.reply_text(
        f"Sessions{replay_details}:\n"
        f"<pre>{sessions_section}</pre>",
        reply_markup=ReplyKeyboardRemove(),
        parse_mode='HTML'
    )
    return


async def users(update: Update, context: ContextTypes.DEFAULT_TYPE) -> int:
    """Lists known users. Admin command."""
    user = update.message.from_user

    logging.warn("User %s called /users %s", user, context.args)
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
        from_seconds = int(context.args[0])
    else:
        from_seconds = 3600*24 # last 24 hours

    logging.warn("Getting sessions for last %d seconds", from_seconds)
    sessions = SessionDB.get_all(from_seconds)
    users_dict = {}
    user_sessions = {}
    for k,v in sorted(sessions.items(), key=lambda x: x[1]['created_time'], reverse=False):
        username = v['username']
        users_dict[username] = v['created_time']
        if v['model']:
            if username not in user_sessions:
                user_sessions[username] = []
            user_sessions[username].append(v)
    users_list = []
    for username, last_session_time in sorted(users_dict.items(), key=lambda x: x[1], reverse=True):
        user_costs_for_period = sum(openai_cost(session['model'], session['prompt_tokens'], session['completion_tokens']) for session in user_sessions[username])
        users_list.append(f"{last_session_time} - {username} - ${user_costs_for_period}")
    users_section = "\n".join(users_list)
    await update.message.reply_text(
        f"Sessions for last {from_seconds} seconds:\n"
        f"<pre>{users_section}</pre>",
        reply_markup=ReplyKeyboardRemove(),
        parse_mode='HTML'
    )
    return


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


async def load_cookie(update: Update, context: ContextTypes.DEFAULT_TYPE):
    user = update.message.from_user

    logging.warn("User %s called /load_cookie %s", user, context.args)
    
    if not is_admin(user):
        logging.warn(f"Not an admin")
        await update.message.reply_text(
            f"Nice try, talk to <a href='tg://user?id={admin_id()}'>admin</a>",
            reply_markup=ReplyKeyboardRemove(),
            parse_mode='HTML'
        )
        return

    logging.warn(f"Is an admin")
    cookie = os.environ.get("COOKIE")
    if cookie:
        UserDB.set(user.username, 'cookie', cookie)
        logging.info("User %s set new cookie", user)
        await update.message.reply_text(
            "New cookie:\n\n"
            f"<pre>{cookie}</pre>",
            reply_markup=ReplyKeyboardRemove(),
            parse_mode='HTML'
        )
    else:
        logging.info("No COOKIE env var found", user)
        await update.message.reply_text(
            "No COOKIE env var found",
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

    SessionDB.create(user.username)

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

    cookie = UserDB.get(user.username, 'cookie')
    if not cookie:
        await update.message.reply_text(
            f"No cookie found, set cookie with /reset_cookie.",
            reply_markup=ReplyKeyboardRemove(),
            parse_mode='HTML'
        )
        return ConversationHandler.END
    c = Client(load_env=False, use_jar=False, cookie=cookie)

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

    cookie = UserDB.get(user.username, 'cookie')
    if not cookie:
        await update.message.reply_text(
            f"No cookie found, set cookie with /reset_cookie.",
            reply_markup=ReplyKeyboardRemove(),
            parse_mode='HTML'
        )
        return ConversationHandler.END
    c = Client(load_env=False, use_jar=False, cookie=cookie)

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
        parse_mode='HTML',
        disable_web_page_preview=True
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
            author = 'You' # m['senderId']
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

    if last_message['senderId'] == peer['id']:
        await update.message.reply_text(
            "<i>Asking ChatGPT?</i>",
            reply_markup=ReplyKeyboardMarkup(
                reply_keyboard, one_time_keyboard=True, input_field_placeholder="Ask ChatGPT for a suggestion?"
            ),
            parse_mode='HTML'
        )
        return SUGGESTION
    else:
        conv_url = conversation_url(conversation_id)
        await update.message.reply_text(
            "Last message was not from peer. No suggestions will be given for this conversation.\n"
            f"<a href=\"{conv_url}\">{conv_url}</a>\n",
            reply_markup=ReplyKeyboardRemove(),
            parse_mode='HTML',
            disable_web_page_preview=True
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

    quota = UserDB.get(user.username, 'openai-quota')
    if not quota:
        await update.message.reply_text(
            f"No OpenAI quota defined for you, please talk to <a href='tg://user?id={admin_id()}'>admin</a>",
            reply_markup=ReplyKeyboardRemove(),
            parse_mode='HTML'
        )
        return ConversationHandler.END
    else:
        quota_amount_in_us_dollars = float(quota)
    
    current_usage = users_openai_usage(user.username)
    logging.info("User OpenAI quota is $%s, and $%s is already used", current_usage, quota_amount_in_us_dollars)
    
    if users_openai_usage(user.username) >= quota_amount_in_us_dollars:
        await update.message.reply_text(
            f"You exceeded your OpenAI quota, please talk to <a href='tg://user?id={admin_id()}'>admin</a>",
            reply_markup=ReplyKeyboardRemove(),
            parse_mode='HTML'
        )
        return ConversationHandler.END

    session = UserSession(user_data=context.user_data)
    conv = session.get_active_conversation()
    logging.info('Active conv %s', conv)
    conversation_id = conv['id']

    if update.message.text != "Yes":
        logging.info("Not asking ChatGPT, as user %s replied %s", user.id, update.message.text)
        conv_url = conversation_url(conversation_id)
        await update.message.reply_text(
            f"You can open conversation here:\n"
            f"<a href=\"{conv_url}\">{conv_url}</a>\n",
            reply_markup=ReplyKeyboardRemove(),
            parse_mode='HTML',
            disable_web_page_preview=True
        )
        return ConversationHandler.END

    item_data = session.get_item_data()
    chatgpt_context = UserDB.get(user.username, 'chat-context')
    if not chatgpt_context:
        chatgpt_context = load_context("chat-context")
    context = chatgpt_context + "\n" + item_data
    await update.message.reply_text(
        "<i>This will be the context for ChatGPT request:</i>",
        reply_markup=ReplyKeyboardRemove(),
        parse_mode='HTML'
    )
    await update.message.reply_text(
        f"<pre>{context}</pre>",
        reply_markup=ReplyKeyboardRemove(),
        parse_mode='HTML'
    )
    await update.message.reply_text(
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
    SessionDB.use(
        username=user.username,
        model=completion.model,
        prompt_tokens=completion.usage.prompt_tokens,
        completion_tokens=completion.usage.completion_tokens
    )
    logging.info(f">>>>>>>>> {completion.id}")
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


async def quota(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Returns current user's quota."""
    user = update.message.from_user
    user_status = UserDB.get(user.username, 'status')
    if user_status != 'active':
        await update.message.reply_text(
            f"You are not known for me, please talk to <a href='tg://user?id={admin_id()}'>admin</a>",
            reply_markup=ReplyKeyboardRemove(),
            parse_mode='HTML'
        )
        return ConversationHandler.END

    quota = UserDB.get(user.username, 'openai-quota')
    if not quota:
        await update.message.reply_text(
            f"No OpenAI quota defined for you, please talk to <a href='tg://user?id={admin_id()}'>admin</a>",
            reply_markup=ReplyKeyboardRemove(),
            parse_mode='HTML'
        )
        return ConversationHandler.END
    else:
        quota_amount_in_us_dollars = float(quota)
    
    current_usage = users_openai_usage(user.username)
    logging.info("User OpenAI quota is $%s, and $%s is already used", current_usage, quota_amount_in_us_dollars)

    await update.message.reply_text(
        f"Your OpenAI quota is ${quota_amount_in_us_dollars}",
        reply_markup=ReplyKeyboardRemove(),
        parse_mode='HTML'
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
        UserDB.delete(user.username, 'chat-context')
    else:
        text = " ".join(context.args)
        UserDB.set(user.username, 'chat-context', text)
    logging.info("New context for ChatGPT: %s", text)

    await update.message.reply_text(
        "New context:\n\n"
        f"<pre>{text}</pre>",
        reply_markup=ReplyKeyboardRemove(),
        parse_mode='HTML'
    )


async def reset_cookie(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Reset cookie to new value."""
    user = update.message.from_user
    user_status = UserDB.get(user.username, 'status')
    if user_status != 'active':
        await update.message.reply_text(
            f"You are not known for me, please talk to <a href='tg://user?id={admin_id()}'>admin</a>",
            reply_markup=ReplyKeyboardRemove(),
            parse_mode='HTML'
        )
        return ConversationHandler.END

    if len(context.args) == 0:
        UserDB.delete(user.username, 'cookie')
        logging.info("User %s deleted cookie", user)
        await update.message.reply_text(
                "Cookie deleted",
                reply_markup=ReplyKeyboardRemove(),
                parse_mode='HTML'
            )
    else:
        text = " ".join(context.args)
        cookie = store_value(sniff_cookie_from_text(text))
        if cookie:
            UserDB.set(user.username, 'cookie', cookie)
            logging.info("User %s set new cookie", user)
            await update.message.reply_text(
                "New cookie:\n\n"
                f"<pre>{cookie}</pre>",
                reply_markup=ReplyKeyboardRemove(),
                parse_mode='HTML'
            )
        else:
            logging.info("User %s did not provide new cookie", user)
            logging.debug("User %s provided: %s", text)
            await update.message.reply_text(
                "No new cookie found in:\n\n"
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


async def version(update: Update, context: ContextTypes.DEFAULT_TYPE):
    await context.bot.send_message(chat_id=update.effective_chat.id, text=f"Version {the_version}")


async def unknown(update: Update, context: ContextTypes.DEFAULT_TYPE):
    user = update.message.from_user

    help_text = get_help()
    if is_admin(user):
        help_text += "/admin_help -- show admin help"

    await context.bot.send_message(chat_id=update.effective_chat.id, text="Sorry, I didn't understand that command.\n\n" + help_text)


def get_help():
    return """Available commands:
/start -- start the session, by listing all conversations first, optional parameters are LIMIT and OFFSET
/reset_cookie -- set your marktplaats.nl cookie (can parse the result of "Copy as cURL" browser command) or delete current one if nothing is provided
/context -- reset the ChatGPT context, provide a new text or leave blank to load default
/last -- list user's sessions
/help -- show this help
"""

def get_admin_help():
    return """Admin commands:
/activate {username} -- activate user by {username}
/deactivate {username} -- deactivate user by {username}
/user_settings {username} -- show settings for {username}
/load_cookie -- load cookie for bot's COOKIE env var into admin's settings
/users ({seconds}) -- list users, active for last {seconds} (24 hours by default)
/last {username} -- list sessions of {username}, showing OpenAI costs and tokens per request
/last -- list all sessions for the last week, showing OpenAI costs and tokens per request
/set_quota {username} {amount} -- set $$$ quota for OpenAI use for {username}
/admin_help -- show this help
"""


def main():
    print("Starting")

    logging.basicConfig(
        format='%(asctime)s - %(name)s - %(levelname)s - %(message)s',
        level=logging.DEBUG,
        filename='marktplaats-gpt-bot.log',
        filemode='a'
    )

    # set higher logging level for httpx to avoid all GET and POST requests being logged
    logging.getLogger("httpx").setLevel(logging.WARNING)
    logging.getLogger("telegram").setLevel(logging.INFO)
    logging.getLogger("httpcore").setLevel(logging.INFO)

    # Load environment variables from .env file
    load_dotenv()

    UserDB.init_db()
    SessionDB.init_db()

    application = ApplicationBuilder().token(os.environ.get("TELEGRAM_TOKEN")).build()

    conv_handler = ConversationHandler(
        entry_points=[CommandHandler("start", start)],
        states={
            CONVERSATION: [MessageHandler(filters.Regex(".*"), conversation)],
            SUGGESTION: [MessageHandler(filters.Regex("^(Yes|No)$"), suggestion)],
        },
        fallbacks=[CommandHandler("cancel", cancel)],
    )

    application.add_handler(CommandHandler('set_quota', set_quota))
    application.add_handler(CommandHandler('last', last))
    application.add_handler(CommandHandler('users', users))
    application.add_handler(CommandHandler('activate', activate))
    application.add_handler(CommandHandler('deactivate', deactivate))
    application.add_handler(CommandHandler('user_settings', user_settings))
    application.add_handler(CommandHandler('load_cookie', load_cookie))
    application.add_handler(conv_handler)
    application.add_handler(CommandHandler('quota', quota))
    application.add_handler(CommandHandler('context', context))
    application.add_handler(CommandHandler('reset_cookie', reset_cookie))
    application.add_handler(CommandHandler('help', help))
    application.add_handler(CommandHandler('admin_help', admin_help))
    application.add_handler(CommandHandler('version', version))
    application.add_handler(MessageHandler(filters.TEXT & (~filters.COMMAND), echo))
    application.add_handler(MessageHandler(filters.COMMAND, unknown))

    # Run the bot until the user presses Ctrl-C
    application.run_polling(allowed_updates=Update.ALL_TYPES)

if __name__ == '__main__':
    main()
