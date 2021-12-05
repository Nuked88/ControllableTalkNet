from transformers import BlenderbotTokenizer, BlenderbotForConditionalGeneration, AutoTokenizer, AutoModelForSequenceClassification, AutoConfig, Conversation, ConversationalPipeline
from transformers import AutoModelForSequenceClassification
from transformers import AutoTokenizer
import numpy as np
from scipy.special import softmax
import csv
import torch
import time
import rtmidi
import json

DEVICE = "cuda:0" if torch.cuda.is_available() else "cpu"
midiout = rtmidi.MidiOut()
available_ports = midiout.get_ports()
midiout.open_port(2) # Select midi port

def preprocess(text):
    new_text = []
 
 
    for t in text.split(" "):
        t = '@user' if t.startswith('@') and len(t) > 1 else t
        t = 'http' if t.startswith('http') else t
        new_text.append(t)
    return " ".join(new_text)


def play(note, duration):
    midiout.send_message([0x90, note, 0x7f])
    time.sleep(duration)
    midiout.send_message([0x80, note, 0x7f])


def signals(i):
        switcher={
                "negative":40,
                "neutral":36,
                "positive":38

             }
        return switcher.get(i,"Invalid day of week")

#zoo:blender/blender_1Bdistill/model
mname = "facebook/blenderbot-1B-distill"
model_bb = BlenderbotForConditionalGeneration.from_pretrained(mname).to(DEVICE)
tokenizer_bb = BlenderbotTokenizer.from_pretrained(mname)
nlp = ConversationalPipeline(model=model_bb, tokenizer=tokenizer_bb, device=0)



task='sentiment'
MODEL_S = f"cardiffnlp/twitter-roberta-base-{task}"
MODELP = f"C:\\Users\\nuked\\OneDrive\\Documents\\Script\\TalkNet\\ControllableTalkNet\\sentiment"
MODELPR = f"C:\\Users\\nuked\\OneDrive\\Documents\\Script\\TalkNet\\ControllableTalkNet\\twitter-roberta-base-sentiment"

#DO ONLY THE FIRST TIME
#tokenizer = AutoTokenizer.from_pretrained(MODEL_S)
#tokenizer.save_pretrained(MODELP)
#config.save_pretrained(MODELP)


#config = AutoConfig.from_pretrained(MODELP)
#
#
#tokenizer = AutoTokenizer.from_pretrained(MODELP)
#model = AutoModelForSequenceClassification.from_pretrained(MODELPR).to(DEVICE)


def list2file(l,f):
    with open(f, 'w') as f:
        json.dump(l, f, indent = 6)

def file2list(f):
    with open(f, 'r') as f:
        return json.load(f)


def load_history(f,conversation):

    jj = file2list(f)

    for j in jj:
        if j["is_user"]==False:
            #print(j["text"])
            conversation.append_response(j["text"])
            conversation.mark_processed()
        else:
            conversation.add_user_input(j["text"])
        
    return conversation





while True:
    conversation = Conversation()
    UTTERANCE= input(f"sss{DEVICE}: ")
    name="test"
    fname=f"conversations/{name}_messages.json"
    conversation= load_history(fname,conversation)
    
    # Put the user's messages as "old message".

    conversation.add_user_input(UTTERANCE)

    result = nlp([conversation], do_sample=False, max_length=1000)
   
    messages = []
    for is_user, text in result.iter_texts():
          messages.append({
               'is_user': is_user,
               'text': text
               
          })
    print(messages[len(messages)-1]["text"] )
    
    list2file(messages,fname)
    #print(a)
    ''' 
    inputs = tokenizer_bb([UTTERANCE], return_tensors='pt').to(DEVICE)
    reply_ids = model_bb.generate(**inputs)
    output_bb= tokenizer_bb.batch_decode(reply_ids)[0].replace("<s> ", "").replace("</s>", "")
    print(output_bb)
    '''
    # Transform input tokens 

    # Tasks:
    # emoji, emotion, hate, irony, offensive, sentiment
    # stance/abortion, stance/atheism, stance/climate, stance/feminist, stance/hillary

    # download label mapping
    labels=[]
    mapping_link = f"0	negative\n1	neutral\n2	positive\n"


    '''

    html = mapping_link.split("\n")
    csvreader = csv.reader(html, delimiter='\t')
    labels = [row[1] for row in csvreader if len(row) > 1]


    text = preprocess(output_bb)
    encoded_input = tokenizer(text, return_tensors='pt').to(DEVICE)
    outputs = model(**encoded_input)
    scores = outputs[0][0].cpu().detach().numpy()
    scores = softmax(scores)

    ranking = np.argsort(scores)
    ranking = ranking[::-1]

    print(str(output_bb)+"Sentiment:")
    label=None

    for i in range(scores.shape[0]):
        l = labels[ranking[i]]
        s = scores[ranking[i]]

        if(s>0.8):
            label=l


    if label==None:
        label="neutral"


    print(label)
    play(signals(label),0.5)

    '''






#print(f"{output_bb} Sentiment: {outputs}")
  
#tokenizer = AutoTokenizer.from_pretrained("facebook/blenderbot-1B-distill")
#
#model = AutoModel.from_pretrained("facebook/blenderbot-1B-distill")
#
##
#
##
#
#input_text = tokenizer("Hello, my name is Blenderbot.",  return_tensors="pt") 
#output_text = model(**input_text)
#print(output_text)
