# ChatGPT for conversations in Marktplaats

To keep the conversation with peers and convince them in:

1. buying at the listed price

2. selling with discount


## Setup

```
python3 -m venv .venv
. .venv/bin/activate
pip install poetry
```

### Install dependencies

Due to tricky authentication process with Marktplaats (using unofficial [*marktplaats-messages*](https://github.com/aleksandr-vin/marktplaats-messages) python client),
python Tk library is needed:

```
sudo apt-get install python3-tk
```

### Development install

```
poetry install
```


## Configure

Provide following env vars (or place a *.env* file of the structure):

```
OPENAI_API_KEY=...
OPENAI_ORG_ID=...
```

### Marktplaats authentication

For now the only supported way is to steal cookies from the browser session. Find assistance from [header-hunter](https://github.com/aleksandr-vin/header-hunter).

Open https://marktplaats.nl and log in, open Developer Tools > Network tab and right-click on any request to marktplaats.nl (after you log-in), choose Save as Curl.
That will copy full request command (with cookies) to clip buffer.

Run next command to extract cookies and place them in *.env*:

```
header-hunter > .env
```


## Run as a cli tool

### Listing conversations

First you'll need to list recent conversations:

```
marktplaats-gpt --list-conversations
```

That will bring something like:

```
Listing 2 newly-updated conversations (from 0):
{id} [{unreadMessagesCount}] :: {title} :: {otherParticipant_name} :: {itemId}
14s06:4xxxxk3:2klxxxxb0 [0] :: Cannondale Scalpel Lefty 26" L Carbon :: Julia :: m20xxxxxx83
142dw:2xxxxdv:2klxxxxzt [2] :: Cannondale Scalpel Lefty 26" L Carbon :: Mike :: m20xxxxxx83
```

### Loading item data

Next step is to load product data for item-id (mind the last element in every conversations row):

```
marktplaats-gpt --load-item-data m20xxxxxx83 > item.data
```

### Prepare context for ChatGPT

```
cat chat-context item.data > context.txt
```

Here you combine the *chat-context* file and recently created *item.data* files to make a system context for ChatGPT.

### Dry-run the ChatGPT suggestion

Next you can dry-run the conversation, to see what ChatGPT will suggest:

```
marktplaats-gpt --dry-run --conversation 142dw:2xxxxdv:2klxxxxzt --openai-model gpt-4
```

That should give something like:

```
Conversation 142dw:2xxxxdv:2klxxxxzt with Mike has 5 messages:
Loading context from context.txt...
[2023-10-12T20:52:32Z] - Mike: Hallo Aleks, what is broken on the bike? I might be interested. Regards, Mike
[2023-10-12T20:56:46Z] - 2111116: Hi Mike! Front wheel is after crash and was straightened up but some minor bending still persists. Also tubeless has a small hole, that is opening sometimes but is kept by sealant. And since recently the fork needs maintenance as it started leaking
[2023-10-13T08:33:54Z] - Mike: Will you sell for € 200?
[2023-10-13T12:26:15Z] - Mike: Please let me know 🙏
[2023-10-13T16:19:27Z] - Mike: I will buy it for 250. Its worth it. Let me know if we have a deal
Waiting for ChatGPT...
Suggested answer: Hi Mike! Sounds great. I'm glad you see the value in the bike. Yes, we have a deal. I will look forward to meeting you for the handover!
Not replying in conversation (dry-run mode)
```

### Actually make a reply

To make a reply, remove `--dry-run` option.

## Run as a Telegram Bot

You'll need to create a Telegram Bot for yourself first and get a token. Place it to *.env* file with such line:

```
TELEGRAM_TOKEN=.....
```

Then, assuming you run `poetry install`, you can run `marktplaats-gpt-bot` and watch the logs in *marktplaats-gpt-bot.log*.

You'll first need to make yourself an admin and activate yourself.

### Becoming an admin

Issue a `/activate` command to the bot and check logs, you should see something like:

```
2023-10-17 18:04:40,543 - root - WARNING - User User(first_name='Aleksandr', id=11223344, is_bot=False, language_code='en', last_name='Vinokurov', username='yourfriend') called /activate []
```

Copy the number from `id=........` key-value pair and place it to *.env* file with such line:

```
TELEGRAM_BOT_ADMIN_ID=........
```

Now restart the bot.

### Activating yourself

As an admin you can activate users by their telegram usernames. Repeat same last command but provide your username, like `/activate yourfriend`.

For more admin commands see `/admin_help`.

### Interactive authenticating with Marktplaats

When cookie will stale or if you or any of your users do not have cookies, they will need to perform an log-in in their browser and copy a request with *Copy as cURL*,
then issue a command `/reset_cookie  ....` and paste the content of the paste buffer.
