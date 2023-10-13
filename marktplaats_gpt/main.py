
import os
import openai
from dotenv import load_dotenv
import logging
import argparse
from marktplaats_messages.client import Client

# Load environment variables from .env file
load_dotenv()

openai.organization = os.environ.get("OPENAI_ORG_ID")
openai.api_key = os.environ.get("OPENAI_API_KEY")


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

    parser.add_argument('--dry-run', 
                        action='store_true', 
                        help='Run the command without making actual changes')
    
    parser.add_argument('--conversation-continue', 
                        action='store_true',
                        default=False, 
                        help='Continue conversation even if last message was not from peer')
    
    parser.add_argument('--openai-model', 
                        type=str,
                        default="gpt-3.5-turbo",
                        help='Model to be used in OpenAI chat completion (default is gpt-3.5-turbo)')
    
    args = parser.parse_args()

    logging.basicConfig(level=logging.DEBUG,
                    format='%(asctime)s [%(levelname)s] %(message)s',
                    filename='marktplaats-gpt.log',
                    filemode='a')
    
    c = Client()

    if args.list_conversations:
        convs = c.get_conversations(params = {
            'offset': str(args.conversations_offset),
            'limit': str(args.conversations_limit),
        })
        print(f"Listing {args.conversations_limit} newly-updated conversations (from {args.conversations_offset}):")
        for conv in convs['_embedded']['mc:conversations']:
            print("{id} [{unreadMessagesCount}] :: {title} :: {otherParticipant_name}".format(**conv, **{'otherParticipant_name': conv['otherParticipant']['name']}))

    elif args.conversation:
        messages = c.get_conversation(args.conversation)
        peer = messages['_embedded']['otherParticipant']
        if messages['totalCount'] > messages['limit'] + messages['offset']:
            print(f"Conversation {args.conversation} with {peer['name']} has {messages['totalCount']} messages, displaying {messages['limit']} from {messages['offset']}:")
        else:
            print(f"Conversation {args.conversation} with {peer['name']} has {messages['totalCount']} messages:")

        completion_messages=[
            {"role": "system",
                "content": "You are selling your item on marktplaats.nl. " +
                    "A potential buyer is asking questions. " +
                    "Answer questions and do not lower the price. " +
                    "Convince the buyer to buy it for defined price. " +
                    "All messages from 'user' are proxied buyers messages."
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
            logging.debug("About to ask ChatGPT %s model for completion to %s", args.openai_model, completion_messages)
            completion = openai.ChatCompletion.create(model=args.openai_model, messages=completion_messages)
            logging.debug("Usage: %s", completion.usage)
            logging.debug("Choice: %s", completion.choices[0].message.content)
            print(completion.choices[0].message.content)

            if args.dry_run:
                print(f"Not replying in conversation (dry-run mode)")
            else:
                print(f"[TBD] Replying in conversation {args.conversation}")
        else:
            print("Last message was not from peer, to continue conversation use --conversation-continue")

    else:
        print("No action specified. Use --help for available options")




if __name__ == "__main__":
    main()
    #print("org id: %s" % (os.environ.get("OPENAI_ORG_ID")))
    #print("api key: %s" % (os.environ.get("OPENAI_API_KEY")))





