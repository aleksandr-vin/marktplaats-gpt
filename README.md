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

Is tricky, you'll need to open https://marktplaats.nl and log in, open Developer Tools > Network tab and right-click on any request to marktplaats.nl (after you log-in),
choose Save as Curl. That will copy full request command (with cookies) to clip buffer.

Run next command to extract cookies and place them in *.env*:

```
python -m marktplaats_messages.cookie_awareness >> .env
```
