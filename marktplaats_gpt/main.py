import sys
import os
import openai
from dotenv import load_dotenv
import logging
import argparse
from marktplaats_messages.client import Client
from marktplaats_gpt.scraping import load_item_data

# Load environment variables from .env file
load_dotenv()

openai.organization = os.environ.get("OPENAI_ORG_ID")
openai.api_key = os.environ.get("OPENAI_API_KEY")


def load_context(filename):
    """
    Loads context for system role for OpenAI chat completion task.
    """
    print(f"Loading context from {filename}...")
    lines = []

    with open(filename, 'r') as file:
        lines = [line.strip() for line in file]
    
    return ' '.join(lines)


def get_yes_no_answer(prompt):
    while True:
        answer = input(prompt).strip().lower()
        
        if answer in ['yes', 'y']:
            return True
        elif answer in ['no', 'n']:
            return False
        else:
            print("Please answer with 'yes' or 'no' (or 'y' or 'n').")


def main():
    parser = argparse.ArgumentParser(description='API Client to manage conversations.')

    parser.add_argument('--list-conversations', 
                        action='store_true', 
                        help='List all conversations')
    
    parser.add_argument('--conversations-offset', 
                        type=int,
                        default=0,
                        help='Conversations list offset (default is 0)')
    
    parser.add_argument('--conversations-limit', 
                        type=int,
                        default=5,
                        help='Conversations list limit (default is 5)')

    parser.add_argument('--conversation', 
                        type=str, 
                        help='Get details of a specific conversation by its ID')

    parser.add_argument('--load-item-data', 
                        type=str, 
                        help='Marktplaats item id')

    parser.add_argument('--dry-run', 
                        action='store_true', 
                        help='Run the command without making actual changes')
    
    parser.add_argument('--good-luck', 
                        action='store_true', 
                        help='Run the command without asking user for approval')
    
    parser.add_argument('--conversation-continue', 
                        action='store_true',
                        default=False, 
                        help='Continue conversation even if last message was not from peer')
    
    parser.add_argument('--openai-model', 
                        type=str,
                        default="gpt-3.5-turbo",
                        help='Model to be used in OpenAI chat completion (default is gpt-3.5-turbo)')
    
    parser.add_argument('--openai-context-file', 
                        type=str,
                        default="context.txt",
                        help='File with context to be used for OpenAI chat completion (system role)')
    
    args = parser.parse_args()

    logging.basicConfig(level=logging.DEBUG,
                    format='%(asctime)s [%(levelname)s] %(message)s',
                    filename='marktplaats-gpt.log',
                    filemode='a')
    
    c = Client()

    if args.load_item_data:
        print(load_item_data(args.load_item_data))

    elif args.list_conversations:
        convs = c.get_conversations(params = {
            'offset': str(args.conversations_offset),
            'limit': str(args.conversations_limit),
        })
        print(f"Listing {args.conversations_limit} newly-updated conversations (from {args.conversations_offset}):")
        print("{id} [{unreadMessagesCount}] :: {title} :: {otherParticipant_name} :: {itemId}")
        for conv in convs['_embedded']['mc:conversations']:
            print("{id} [{unreadMessagesCount}] :: {title} :: {otherParticipant_name} :: {itemId}".format(**conv, **{'otherParticipant_name': conv['otherParticipant']['name']}))

    elif args.conversation:
        messages = c.get_conversation(args.conversation)
        peer = messages['_embedded']['otherParticipant']
        if messages['totalCount'] > messages['limit'] + messages['offset']:
            print(f"Conversation {args.conversation} with {peer['name']} has {messages['totalCount']} messages, displaying {messages['limit']} from {messages['offset']}:")
        else:
            print(f"Conversation {args.conversation} with {peer['name']} has {messages['totalCount']} messages:")

        context = load_context(args.openai_context_file)

        completion_messages=[
            {
                "role": "system",
                # "content": "You are selling your item on marktplaats.nl. " +
                #     "A potential buyer is asking questions. " +
                #     "Answer questions and do not lower the price. " +
                #     "Convince the buyer to buy it for defined price. " +
                #     "All messages from 'user' are proxied buyers messages."
                "content": context
            },
            #{"role": "user", "content": "Will you sell for 100?"},
        ]
        
        sorted_items = sorted(messages['_embedded']['mc:message'], key=lambda x: x['receivedDate'], reverse=False)
        last_message = sorted_items[-1]

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
            print(f"[{m['receivedDate']}] {read_status}{author}: {m['text']}")
            completion_messages.append({
                "role": role,
                "content": m['text']
            })

        if last_message['senderId'] == peer['id'] or args.conversation_continue:
            print("Waiting for ChatGPT...")
            logging.debug("About to ask ChatGPT %s model for completion to %s", args.openai_model, completion_messages)
            completion = openai.ChatCompletion.create(model=args.openai_model, messages=completion_messages)
            logging.debug("Usage: %s", completion.usage)
            logging.debug("Choice: %s", completion.choices[0].message.content)
            completion = completion.choices[0].message.content
            print(f"Suggested answer: {completion}")

            if args.dry_run:
                print(f"Not replying in conversation (dry-run mode)")
            else:
                approved = False
                if args.good_luck:
                    approved = True
                else:
                    approved = get_yes_no_answer('Reply in conversation? [y/n] ')
                
                if not approved:
                    print(f"Not replying in conversation {args.conversation}")
                    logging.info("Not replying in conversation %s", args.conversation)
                else:
                    print(f"Replying in conversation {args.conversation}")
                    message_data = c.add_message(args.conversation, text=completion)
                    logging.debug("New message: %s", message_data)

        else:
            print("Last message was not from peer, to continue conversation use --conversation-continue")

    else:
        print("No action specified. Use --help for available options")



if __name__ == "__main__":
    main()
