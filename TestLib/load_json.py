import json



fname_base="conversations/base_message_conv.json"
def file2list(file):
    
    with open(file, 'r') as f:

        return json.load(f)


print(file2list(fname_base))