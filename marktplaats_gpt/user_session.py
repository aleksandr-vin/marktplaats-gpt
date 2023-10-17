

class UserSession:
    def __init__(self, user_data):
        self.user_data = user_data

    def set_conversations(self, conversations):
        self.user_data['conversations'] = conversations['_embedded']['mc:conversations']

    def activate_conversation(self, i):
        self.user_data['active_conversation'] = i
        return self.user_data['conversations'][i]

    def get_active_conversation(self):
        i = self.user_data['active_conversation']
        return self.user_data['conversations'][i]

    def set_item_data(self, item_data):
        self.user_data['item_data'] = item_data

    def get_item_data(self):
        return self.user_data['item_data']

    def set_completion_messages(self, completion_messages):
        self.user_data['completion_messages'] = completion_messages

    def get_completion_messages(self):
        return self.user_data['completion_messages']
