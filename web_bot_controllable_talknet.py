import os
from typing import Text
import numpy as np
import tensorflow as tf
from scipy.io import wavfile

import json
from tqdm import tqdm
import traceback
import ffmpeg
from flask import Flask, request, render_template, send_from_directory, Response
from argparse import ArgumentParser
import transformers
from transformers import AutoModelForSequenceClassification
from transformers import AutoTokenizer
import numpy as np
from scipy.special import softmax
import csv
import time
import rtmidi
import requests

from twitchio.ext import commands
from dotenv import load_dotenv


load_dotenv()


midiout = rtmidi.MidiOut()
available_ports = midiout.get_ports()

#detect position element in list
def detect(list, element):
    for i in range(len(list)):
        if list[i] == element:
            return i

port= detect(available_ports, 'loopMIDI 1')
midiout.open_port(port) # Select midi port

RUN_PATH = os.path.dirname(os.path.realpath(__file__))


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


def list2file(l,f):
    with open(f, 'w') as f:
        json.dump(l, f, indent = 6)

def file2list(file):
    with open(file, 'r') as f:
        return json.load(f)


def load_history(f,conversation):
    jj = file2list(f)

    for j in jj:
        if j["is_user"]==False:
            conversation.append_response(j["text"])
            conversation.mark_processed()
        else:
            conversation.add_user_input(j["text"])
        
    return conversation




#smart splits that are not cutting words

def smart_split(str,max_lenght):
    list = []
    lenght_tot=0
    full_line=""
    #print(str.split())
    for s in str.split():
            lgn_w=len(s)
            lenght_tot=lenght_tot+lgn_w
            #print(f"current lenght sum: {lenght_tot}")
            if lenght_tot < max_lenght:
                full_line=full_line+" "+s

            else:        
                list.append(full_line)
                lenght_tot=len(s)
                full_line=s
    #append the last words
    list.append(full_line)   

    if len(list)==0:
            list=[str]
        
    return list


def smart_split_list(full_text,max_lenght):
    line = full_text.split(". ")
    sub_line=[]
    for l in line:
        sub_line= sub_line + smart_split(l,max_lenght)    

    return sub_line



def blande_sentiment(url_server,UTTERANCE,name="test"):
    #fetch  json from url
    url = url_server+"/?text="+UTTERANCE+"&author="+name
    print(url)

    response = requests.get(url)
    print(response.text)
    resp = json.loads(response.text)
    answer=resp[0]
    label= resp[1]
    waveurl=resp[2]
    print(label)
    print(answer)
    #print(data)
    #print(data["_text"])
    
    return label,answer,waveurl


def sanitize_input(input_str):
 
    stopwords = readListFromFile("Assets/emoticon.lst")

    for i in stopwords:
        n=input_str.replace(i.strip(),'')
        input_str=n
    result = input_str.strip()

    return result.replace("\n", " ").replace("\r", " ").replace("\t", " ").replace("’", "'").replace("“", "\"").replace("”", "\"").replace("‘","").replace("(",",").replace(")",",")

def sanitize_output(text):
    return text.replace("\n", " ").replace("\r", " ").replace("\t", " ").replace("’", "'").replace("“", "\"").replace("”", "\"").replace("?", "?,")



def play_audio_buffer(buffer,rate):
    import simpleaudio as sa
    play_obj = sa.play_buffer(buffer, 2, 2, rate)
    play_obj.wait_done()
    # script exit

def play_audio(audio_path):
    """
    Play audio
    """
    try:
        import subprocess
        subprocess.call(["ffplay", "-nodisp","-af","atempo=0.9", "-autoexit","-hide_banner","-loglevel","error", audio_path])
        #if sys.platform == "win32":
        #    os.startfile(audio_path)
        #else:
        #    opener = "open" if sys.platform == "darwin" else "xdg-open"
        #    subprocess.call([opener, audio_path])
    except Exception:
        return str(traceback.format_exc())

def readListFromFile(file_path):
    with open(file_path, 'r') as f:
        lines = f.readlines()
    return lines

def readFile(file_path):
    with open(file_path, 'r') as f:
        return f.read()

def writeFile(fileName, text):
    f = open(fileName, "w")
    f.write(text)
    f.close()

def launch_voice(question,author):
    #create file .lock
    writeFile("./.lock", "")
    if author == "":
        print("NO auth, enter in manual mode")
        answer=sanitize_input(question)
        l= "neutral" #getSentiment(answer,DEVICE2,model_sent,tokenizer_sent)
        delay=0
    else:
        #get text
        req_text = sanitize_input(question)
        if req_text!="":
            print("Sanitized input: "+req_text)
            writeFile("current.txt", f"{author}'s turn!")
            #get answer and sentiment
            #read content of https://gist.githubusercontent.com/Nuked88/55e78cb995bce277b4482d836c811fb0/raw/gistfile1.txt
            url= requests.get("https://gist.githubusercontent.com/Nuked88/55e78cb995bce277b4482d836c811fb0/raw/gistfile1.txt")
            l,answer,waveurl = blande_sentiment(url.text,req_text,author)
            answer = sanitize_output(f"{answer}")

        else:
            print("Skip because it's emoticon only")
        delay=15
    
    wav_name="ok"
    

    #send midi for control the character
    play(signals(l),1.5)
    print(f"Playing audio of: {answer}")
    play_audio(waveurl)     

    writeFile("current.txt", f" ")
    #remove file .lock
    os.remove("./.lock")

from threading import Thread
b = 1



class Bot(commands.Bot):

    def __init__(self):
        # Initialise our Bot with our access token, prefix and a list of channels to join on boot...
        super().__init__(token=os.environ['TMI_TOKEN'],
                            client_id=os.environ['CLIENT_ID'],
                            nick=os.environ['BOT_NICK'],
                            prefix="!",
                            initial_channels=[os.environ['CHANNEL']])

    async def event_ready(self):
        # We are logged in and ready to chat and use commands...
        print(f'Logged in as | {self.nick}')




    async def event_message(self, message):
        print(f"Message received: {message.content} from {message.author.name}")
        #check if  file .lock exists
        if os.path.isfile("./.lock"):
            #print("Skip because .lock file exists")
            return
        else:
            # This is where we handle all of our commands...
            if message.content.startswith('@aki '):
                #await message.channel.send('Hello!')
                mess=message.content.replace('@aki ','')
                print(f"Message received: {mess} from {message.author.name}")
                #launch_voice(mess,message.author.name)
                th = Thread(target=launch_voice, args=(message.content,message.author.name ))
                th.start()

            else:
                print(f"Message received: {message.content} from {message.author.name}")
                #launch_voice(message.content,message.author.name)
                th = Thread(target=launch_voice, args=(message.content,message.author.name ))
                th.start()

           
           
            #await self.handle_commands(message)


#create menu
def create_menu(options, width=30):
    menu = []
    for option in options:
        menu.append(option.ljust(width))
    return menu

#show menu
def show_menu(menu):
    i=0
    for item in menu:
        i=i+1
        print(f"{i} - {item}")


#get choice
def get_choice(menu):
    show_menu(menu)
    choice = input(">>> ")
    return choice

#handle choice
def handle_choice(choice, menu, options):
    # handle invalid choice
    if choice.isdigit() and (int(choice) in range(1, len(options) + 1)):
        return options[int(choice) - 1]
    else:
        print("Invalid choice!")
        return handle_choice(get_choice(menu), menu, options)

#main
def main():
    # Remove the lock file if it exists
    if os.path.isfile("./.lock"):
        os.remove("./.lock")
    # Create a list of options
    options = ["QA Mode","Input Text","Get From Txt","Test Emotion" ,"Exit"]
    # Create a menu from the options list
    menu = create_menu(options)
    choice = handle_choice(get_choice(menu), menu, options)
    # Play the selected audio
    if choice == "QA Mode":
        bot = Bot()
        bot.run()
    elif choice == "Input Text":
        
        while True:
            text = input("Enter text: ")
            
            #break the loop when press crtl+x
            if text == "":
                break
            else:
                launch_voice(text,"")
            

         
    elif choice == "Get From Txt":
        text = readFile("conversations/read/read.txt")
        launch_voice(text,"")
    elif choice == "Test Emotion":
        play(signals("positive"),1.5)
    # Exit the program
    elif choice == "Exit":
        exit()

#call main
if __name__ == "__main__":
    while True:
        try:
            main()
        except Exception:
            main()
