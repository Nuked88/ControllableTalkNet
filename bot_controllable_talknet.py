import sys
import os
import base64
from typing import Text
import torch
import numpy as np
import tensorflow as tf
import crepe
import scipy
from scipy.io import wavfile
import psola
import io
import nemo
from nemo.collections.asr.models import EncDecCTCModel
from nemo.collections.tts.models import TalkNetSpectModel
from nemo.collections.tts.models import TalkNetPitchModel
from nemo.collections.tts.models import TalkNetDursModel
from talknet_singer import TalkNetSingerModel
import json
from tqdm import tqdm
import gdown
import zipfile
import resampy
import traceback
import ffmpeg
from flask import Flask, request, render_template, send_from_directory, Response
import uuid
import re
from argparse import ArgumentParser
import textwrap
sys.path.append("hifi-gan")
from env import AttrDict
from meldataset import mel_spectrogram, MAX_WAV_VALUE
from models import Generator
from denoiser import Denoiser

import transformers
from transformers import BlenderbotTokenizer, BlenderbotForConditionalGeneration, AutoTokenizer, AutoModelForSequenceClassification, AutoConfig, Conversation, ConversationalPipeline
from transformers import AutoModelForSequenceClassification
from transformers import AutoTokenizer
import numpy as np
from scipy.special import softmax
import csv
import time
import rtmidi


from twitchio.ext import commands
from dotenv import load_dotenv
import logging
logging.getLogger('nemo_logger').setLevel(logging.ERROR)
transformers.logging.set_verbosity_error()

load_dotenv()

DEVICE = "cpu" 
DEVICE2 = "cuda:0" if torch.cuda.is_available() else "cpu"
midiout = rtmidi.MidiOut()
available_ports = midiout.get_ports()

#detect position element in list
def detect(list, element):
    for i in range(len(list)):
        if list[i] == element:
            return i

port= detect(available_ports, 'loopMIDI 1')
midiout.open_port(port) # Select midi port



CPU_PITCH = False
RUN_PATH = os.path.dirname(os.path.realpath(__file__))

UI_MODE = "offline"
torch.set_grad_enabled(False)

if CPU_PITCH:
    tf.config.set_visible_devices([], "GPU")
DICT_PATH = os.path.join(RUN_PATH, "horsewords.clean")

# Load models and tokenizer for Blenderbot and sentiment analysis
mname = "facebook/blenderbot-1B-distill"
model_bb = BlenderbotForConditionalGeneration.from_pretrained(mname).to(DEVICE2)
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

config_sent = AutoConfig.from_pretrained(MODELP)
tokenizer_sent = AutoTokenizer.from_pretrained(MODELP)
model_sent = AutoModelForSequenceClassification.from_pretrained(MODELPR).to(DEVICE2)



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


def load_hifigan(model_name, conf_name):
    # Load HiFi-GAN
    conf = os.path.join("hifi-gan", conf_name + ".json")
    #print(f"Load HiFi-GAN {model_name} conf {conf_name}")
    with open(conf) as f:
        json_config = json.loads(f.read())
    h = AttrDict(json_config)
    torch.manual_seed(h.seed)
    hifigan = Generator(h).to(torch.device(DEVICE))
    state_dict_g = torch.load(model_name, map_location=torch.device(DEVICE))
    hifigan.load_state_dict(state_dict_g["generator"])
    hifigan.eval()
    hifigan.remove_weight_norm()
    denoiser = Denoiser(hifigan, mode="normal")
    return hifigan, h, denoiser


def generate_json(input, outpath):
    output = ""
    sample_rate = 22050
    lpath = input.split("|")[0].strip()
    size = os.stat(lpath).st_size
    x = {
        "audio_filepath": lpath,
        "duration": size / (sample_rate * 2),
        "text": input.split("|")[1].strip(),
    }
    output += json.dumps(x) + "\n"
    with open(outpath, "w", encoding="utf8") as w:
        w.write(output)


asr_model = (
    EncDecCTCModel.from_pretrained(model_name="asr_talknet_aligner").cpu().eval()
)


def forward_extractor(tokens, log_probs, blank):
    """Computes states f and p."""
    n, m = len(tokens), log_probs.shape[0]
    # `f[s, t]` -- max sum of log probs for `s` first codes
    # with `t` first timesteps with ending in `tokens[s]`.
    f = np.empty((n + 1, m + 1), dtype=float)
    f.fill(-(10 ** 9))
    p = np.empty((n + 1, m + 1), dtype=int)
    f[0, 0] = 0.0  # Start
    for s in range(1, n + 1):
        c = tokens[s - 1]
        for t in range((s + 1) // 2, m + 1):
            f[s, t] = log_probs[t - 1, c]
            # Option #1: prev char is equal to current one.
            if s == 1 or c == blank or c == tokens[s - 3]:
                options = f[s : (s - 2 if s > 1 else None) : -1, t - 1]
            else:  # Is not equal to current one.
                options = f[s : (s - 3 if s > 2 else None) : -1, t - 1]
            f[s, t] += np.max(options)
            p[s, t] = np.argmax(options)
    return f, p


def backward_extractor(f, p):
    """Computes durs from f and p."""
    n, m = f.shape
    n -= 1
    m -= 1
    durs = np.zeros(n, dtype=int)
    if f[-1, -1] >= f[-2, -1]:
        s, t = n, m
    else:
        s, t = n - 1, m
    while s > 0:
        durs[s - 1] += 1
        s -= p[s, t]
        t -= 1
    assert durs.shape[0] == n
    assert np.sum(durs) == m
    assert np.all(durs[1::2] > 0)
    return durs


def preprocess_tokens(tokens, blank):
    new_tokens = [blank]
    for c in tokens:
        new_tokens.extend([c, blank])
    tokens = new_tokens
    return tokens


parser = (
    nemo.collections.asr.data.audio_to_text.AudioToCharWithDursF0Dataset.make_vocab(
        notation="phonemes",
        punct=True,
        spaces=True,
        stresses=False,
        add_blank_at="last",
    )
)

arpadict = None


def load_dictionary(dict_path):
    arpadict = dict()
    with open(dict_path, "r", encoding="utf8") as f:
        for l in f.readlines():
            word = l.split("  ")
            assert len(word) == 2
            arpadict[word[0].strip().upper()] = word[1].strip()
    return arpadict


def replace_words(input, dictionary):
    regex = re.findall(r"[\w'-]+|[^\w'-]", input)
    assert input == "".join(regex)
    for i in range(len(regex)):
        word = regex[i].upper()
        if word in dictionary.keys():
            regex[i] = "{" + dictionary[word] + "}"
    return "".join(regex)


def arpa_parse(input, model):
    global arpadict
    if arpadict is None:
        arpadict = load_dictionary(DICT_PATH)
    z = []
    space = parser.labels.index(" ")
    input = replace_words(input, arpadict)
    while "{" in input:
        if "}" not in input:
            input.replace("{", "")
        else:
            pre = input[: input.find("{")]
            if pre.strip() != "":
                x = model.parse(text=pre.strip())
                seq_ids = x.squeeze(0).cpu().detach().numpy()
                z.extend(seq_ids)
            z.append(space)

            arpaword = input[input.find("{") + 1 : input.find("}")]
            arpaword = (
                arpaword.replace("0", "")
                .replace("1", "")
                .replace("2", "")
                .strip()
                .split(" ")
            )

            seq_ids = []
            for x in arpaword:
                if x == "":
                    continue
                if x.replace("_", " ") not in parser.labels:
                    continue
                seq_ids.append(parser.labels.index(x.replace("_", " ")))
            seq_ids.append(space)
            z.extend(seq_ids)
            input = input[input.find("}") + 1 :]
    if input != "":
        x = model.parse(text=input.strip())
        seq_ids = x.squeeze(0).cpu().detach().numpy()
        z.extend(seq_ids)
    if z[-1] == space:
        z = z[:-1]
    if z[0] == space:
        z = z[1:]
    return [
        z[i] for i in range(len(z)) if (i == 0) or (z[i] != z[i - 1]) or (z[i] != space)
    ]


def to_arpa(input):
    arpa = ""
    z = []
    space = parser.labels.index(" ")
    while space in input:
        z.append(input[: input.index(space)])
        input = input[input.index(space) + 1 :]
    z.append(input)
    for y in z:
        if len(y) == 0:
            continue

        arpaword = " {"
        for s in y:
            if parser.labels[s] == " ":
                arpaword += "_ "
            else:
                arpaword += parser.labels[s] + " "
        arpaword += "} "
        if not arpaword.replace("{", "").replace("}", "").replace(" ", "").isalnum():
            arpaword = arpaword.replace("{", "").replace(" }", "")
        arpa += arpaword
    return arpa.replace("  ", " ").replace(" }", "}").strip()


def get_duration(wav_name, transcript, tokens):
    if not os.path.exists(os.path.join(RUN_PATH, "temp")):
        os.mkdir(os.path.join(RUN_PATH, "temp"))
    if "_" not in transcript:
        generate_json(
            os.path.join(RUN_PATH, "temp", wav_name + "_conv.wav")
            + "|"
            + transcript.strip(),
            os.path.join(RUN_PATH, "temp", wav_name + ".json"),
        )
    else:
        generate_json(
            os.path.join(RUN_PATH, "temp", wav_name + "_conv.wav") + "|" + "dummy",
            os.path.join(RUN_PATH, "temp", wav_name + ".json"),
        )

    data_config = {
        "manifest_filepath": os.path.join(RUN_PATH, "temp", wav_name + ".json"),
        "sample_rate": 22050,
        "batch_size": 1,
    }

    dataset = nemo.collections.asr.data.audio_to_text._AudioTextDataset(
        manifest_filepath=data_config["manifest_filepath"],
        sample_rate=data_config["sample_rate"],
        parser=parser,
    )

    dl = torch.utils.data.DataLoader(
        dataset=dataset,
        batch_size=data_config["batch_size"],
        collate_fn=dataset.collate_fn,
        shuffle=False,
    )

    blank_id = asr_model.decoder.num_classes_with_blank - 1

    for sample_idx, test_sample in tqdm(enumerate(dl), total=len(dl)):
        log_probs, _, greedy_predictions = asr_model(
            input_signal=test_sample[0], input_signal_length=test_sample[1]
        )

        log_probs = log_probs[0].cpu().detach().numpy()
        target_tokens = preprocess_tokens(tokens, blank_id)

        f, p = forward_extractor(target_tokens, log_probs, blank_id)
        durs = backward_extractor(f, p)

        del test_sample
        return durs
    return None


def crepe_f0(wav_path, hop_length=256):
    # sr, audio = wavfile.read(io.BytesIO(wav_data))
    sr, audio = wavfile.read(wav_path)
    audio_x = np.arange(0, len(audio)) / 22050.0
    f0time, frequency, confidence, activation = crepe.predict(audio, sr, viterbi=True)

    x = np.arange(0, len(audio), hop_length) / 22050.0
    freq_interp = np.interp(x, f0time, frequency)
    conf_interp = np.interp(x, f0time, confidence)
    audio_interp = np.interp(x, audio_x, np.absolute(audio)) / 32768.0
    weights = [0.5, 0.25, 0.25]
    audio_smooth = np.convolve(audio_interp, np.array(weights)[::-1], "same")

    conf_threshold = 0.25
    audio_threshold = 0.0005
    for i in range(len(freq_interp)):
        if conf_interp[i] < conf_threshold:
            freq_interp[i] = 0.0
        if audio_smooth[i] < audio_threshold:
            freq_interp[i] = 0.0

    # Hack to make f0 and mel lengths equal
    if len(audio) % hop_length == 0:
        freq_interp = np.pad(freq_interp, pad_width=[0, 1])
    return (
        torch.from_numpy(freq_interp.astype(np.float32)),
        torch.from_numpy(frequency.astype(np.float32)),
    )


def f0_to_audio(f0s):
    volume = 0.2
    sr = 22050
    freq = 440.0
    base_audio = (
        np.sin(2 * np.pi * np.arange(256.0 * len(f0s)) * freq / sr) * volume
    ).astype(np.float32)
    shifted_audio = psola.vocode(base_audio, sr, target_pitch=f0s)
    for i in range(len(f0s)):
        if f0s[i] == 0.0:
            shifted_audio[i * 256 : (i + 1) * 256] = 0.0
    print(type(shifted_audio[0]))
    buffer = io.BytesIO()
    wavfile.write(buffer, sr, shifted_audio.astype(np.float32))
    b64 = base64.b64encode(buffer.getvalue())
    sound = "data:audio/x-wav;base64," + b64.decode("ascii")
    return sound



def update_model(model):
    if model is not None and model.split("|")[0] == "Custom":
        style = {"margin-bottom": "0.7em", "display": "block"}
    else:
        style = {"display": "none"}
    return style



def update_pitch_options(value):
    return ["pf" not in value, "dra" in value, "dra" in value]




def debug_pitch(n_clicks, pitch_clicks, current_f0s):
    if not n_clicks or current_f0s is None or n_clicks <= pitch_clicks:
        if n_clicks is not None:
            pitch_clicks = n_clicks
        else:
            pitch_clicks = 0
        return [
            None,
            None,
            pitch_clicks,
        ]
    pitch_clicks = n_clicks
    return [f0_to_audio(current_f0s), playback_style, pitch_clicks]


hifigan_sr = None


def download_model(model, custom_model):

    global hifigan_sr, h2, denoiser_sr
    d = "https://drive.google.com/uc?id="
    if model == "Custom":
        drive_id = custom_model
    else:
        drive_id = model
    if drive_id == "" or drive_id is None:
        return ("Missing Drive ID", None, None)
    if not os.path.exists(os.path.join(RUN_PATH, "models")):
        os.mkdir(os.path.join(RUN_PATH, "models"))
    if not os.path.exists(os.path.join(RUN_PATH, "models", drive_id)):
        os.mkdir(os.path.join(RUN_PATH, "models", drive_id))
        zip_path = os.path.join(RUN_PATH, "models", drive_id, "model.zip")
        gdown.download(
            d + drive_id,
            zip_path,
            quiet=False,
        )
        if not os.path.exists(zip_path):
            os.rmdir(os.path.join(RUN_PATH, "models", drive_id))
            return ("Model download failed", None, None)
        if os.stat(zip_path).st_size < 16:
            os.remove(zip_path)
            os.rmdir(os.path.join(RUN_PATH, "models", drive_id))
            return ("Model zip is empty", None, None)
        with zipfile.ZipFile(zip_path, "r") as zip_ref:
            zip_ref.extractall(os.path.join(RUN_PATH, "models", drive_id))
        os.remove(zip_path)
    #print("Download super-resolution HiFi-GAN")
    # Download super-resolution HiFi-GAN
    sr_path = "hifi-gan/hifisr"
    if not os.path.exists(sr_path):
        gdown.download(
            d + "14fOprFAIlCQkVRxsfInhEPG0n-xN4QOa", sr_path, quiet=False
        )
    if not os.path.exists(sr_path):
        raise Exception("HiFI-GAN model failed to download!")
    if hifigan_sr is None:
        hifigan_sr, h2, denoiser_sr = load_hifigan(sr_path, "config_32k")
    #print("END DOWNLOAD")
    return (
        None,
        os.path.join(RUN_PATH, "models", drive_id, "TalkNetSpect.nemo"),
        os.path.join(RUN_PATH, "models", drive_id, "hifiganmodel"),
    )



tnmodel, tnpath, tndurs, tnpitch = None, None, None, None
hifigan, h, denoiser, hifipath = None, None, None, None

def getSentiment(text,DEVICE2,model_sent,tokenizer_sent):
    # Transform input tokens 

    # Tasks:
    # emoji, emotion, hate, irony, offensive, sentiment
    # stance/abortion, stance/atheism, stance/climate, stance/feminist, stance/hillary

    # download label mapping
    labels=[]
    mapping_link = f"0	negative\n1	neutral\n2	positive\n"

    html = mapping_link.split("\n")
    csvreader = csv.reader(html, delimiter='\t')
    labels = [row[1] for row in csvreader if len(row) > 1]


    #text = preprocess(output_bb)
    #react to the question not at the answer
    text = preprocess(text)
    encoded_input = tokenizer_sent(text, return_tensors='pt').to(DEVICE2)
    outputs = model_sent(**encoded_input)
    scores = outputs[0][0].cpu().detach().numpy()
    scores = softmax(scores)

    ranking = np.argsort(scores)
    ranking = ranking[::-1]

    
    label=None

    for i in range(scores.shape[0]):
        l = labels[ranking[i]]
        s = scores[ranking[i]]

        if(s>0.8):
            label=l


    if label==None:
        label="neutral"
    
    return label


def blande_sentiment(UTTERANCE,DEVICE2,model_sent,tokenizer_sent,name="test"):
    #UTTERANCE= input(f"sss{DEVICE}: ")
    try:
        conversation = Conversation()
        fname_base="conversations/base_message_conv.json"
        fname=f"conversations/{name}_messages.json"

        if os.path.exists(fname):
                conversation= load_history(fname,conversation)
        else:
            print("loading base conversation")
            conversation= load_history(fname_base,conversation)

            


        conversation.add_user_input(UTTERANCE)
        result = nlp([conversation], do_sample=False, max_length=1000)
        
        messages = []
        for is_user, text in result.iter_texts():
            messages.append({
                'is_user': is_user,
                'text': text
                
            })
        output_bb =messages[len(messages)-1]["text"].strip()
 
        list2file(messages,fname)

        label = getSentiment(UTTERANCE,DEVICE2,model_sent,tokenizer_sent)

        print(f"Sentiment detected: {label}")
        return label,str(output_bb)
    except Exception as e:
        exc_type, exc_obj, exc_tb = sys.exc_info()
        fname = os.path.split(exc_tb.tb_frame.f_code.co_filename)[1]
        print(exc_type, fname, exc_tb.tb_lineno)

def pad_audio(data, fs, T):
    # Calculate target number of samples
    N_tar = int(fs * T)
    # Calculate number of zero samples to append
    shape = data.shape
    # Create the target shape    
    N_pad = N_tar - shape[0]
    print("Padding with %s seconds of silence" % str(N_pad/fs) )
    shape = (N_pad,) + shape[1:]
    # Stack only if there is something to append    
    if shape[0] > 0:                
        if len(shape) > 1:
            return np.vstack((np.zeros(shape),
                              data))
        else:
            return np.hstack((np.zeros(shape),
                              data))
    else:
        return data


def generate_audio(n_clicks,model,custom_model,transcript,pitch_options,pitch_factor,wav_name="wavname",f0s=None,f0s_wo_silence=None,silence=0):

    print(f"Generateing audio...")
    global tnmodel, tnpath, tndurs, tnpitch, hifigan, h, denoiser, hifipath

    if n_clicks is None:
        raise PreventUpdate
    if model is None:
        return [None, "No character selected", None, None]
    if transcript is None or transcript.strip() == "":
        return [
            None,
            "No transcript entered",
            None,
            None,
        ]
    if wav_name is None and "dra" not in pitch_options:
        return [
            None,
            "No reference audio selected",
            None,
            None,
        ]
    load_error, talknet_path, hifigan_path = download_model(
        model.split("|")[0], custom_model
    )
    
    if load_error is not None:
        print(load_error)
        return [
            None,
            load_error,
            None,
            None,
        ]
    


    with torch.no_grad():
        if tnpath != talknet_path:
            singer_path = os.path.join(
                os.path.dirname(talknet_path), "TalkNetSinger.nemo"
            )
            if os.path.exists(singer_path):
                tnmodel = TalkNetSingerModel.restore_from(singer_path).to(DEVICE)
            else:
                tnmodel = TalkNetSpectModel.restore_from(talknet_path).to(DEVICE)
            durs_path = os.path.join(
                os.path.dirname(talknet_path), "TalkNetDurs.nemo"
            )
            pitch_path = os.path.join(
                os.path.dirname(talknet_path), "TalkNetPitch.nemo"
            )
            if os.path.exists(durs_path):
                tndurs = TalkNetDursModel.restore_from(durs_path)
                tnmodel.add_module("_durs_model", tndurs)
                tnpitch = TalkNetPitchModel.restore_from(pitch_path)
                tnmodel.add_module("_pitch_model", tnpitch)
            else:
                tndurs = None
                tnpitch = None
            tnmodel.to(DEVICE)
            tnmodel.eval()
            tnpath = talknet_path

        token_list = arpa_parse(transcript, tnmodel)
        tokens = torch.IntTensor(token_list).view(1, -1).to(DEVICE)
        arpa = to_arpa(token_list)
        print(arpa)
        if "dra" in pitch_options:
            if tndurs is None or tnpitch is None:
                return [
                    None,
                    "Model doesn't support pitch prediction",
                    None,
                    None,
                ]
            spect = tnmodel.generate_spectrogram(tokens=tokens)
        else:
            durs = get_duration(wav_name, transcript, token_list)

            # Change pitch
            if "pf" in pitch_options:
                f0_factor = np.power(np.e, (0.0577623 * float(pitch_factor)))
                f0s = [x * f0_factor for x in f0s]
                f0s_wo_silence = [x * f0_factor for x in f0s_wo_silence]

            spect = tnmodel.force_spectrogram(
                tokens=tokens,
                durs=torch.from_numpy(durs)
                .view(1, -1)
                .type(torch.LongTensor)
                .to(DEVICE),
                f0=torch.FloatTensor(f0s).view(1, -1).to(DEVICE),
            )

        if hifipath != hifigan_path:
            hifigan, h, denoiser = load_hifigan(hifigan_path, "config_v1")
            hifipath = hifigan_path

        y_g_hat = hifigan(spect.float())
        audio = y_g_hat.squeeze()
        audio = audio * MAX_WAV_VALUE
        audio_denoised = denoiser(audio.view(1, -1), strength=35)[:, 0]
        audio_np = (
            audio_denoised.detach().cpu().numpy().reshape(-1).astype(np.int16)
        )

        # Auto-tuning
        if "pc" in pitch_options and "dra" not in pitch_options:
                _, output_freq, _, _ = crepe.predict(audio_np, 22050, viterbi=True)
                output_pitch = torch.from_numpy(output_freq.astype(np.float32))
                target_pitch = torch.FloatTensor(f0s_wo_silence).to(DEVICE)
                factor = torch.mean(output_pitch) / torch.mean(target_pitch)

                octaves = [0.125, 0.25, 0.5, 1.0, 2.0, 4.0, 8.0]
                nearest_octave = min(octaves, key=lambda x: abs(x - factor))
                target_pitch *= nearest_octave
                if len(target_pitch) < len(output_pitch):
                    target_pitch = torch.nn.functional.pad(
                        target_pitch,
                        (0, list(output_pitch.shape)[0] - list(target_pitch.shape)[0]),
                        "constant",
                        0,
                    )
                if len(target_pitch) > len(output_pitch):
                    target_pitch = target_pitch[0 : list(output_pitch.shape)[0]]

                audio_np = psola.vocode(
                    audio_np, 22050, target_pitch=target_pitch
                ).astype(np.float32)
                normalize = (1.0 / np.max(np.abs(audio_np))) ** 0.9
                audio_np = audio_np * normalize * MAX_WAV_VALUE
                audio_np = audio_np.astype(np.int16)

        # Resample to 32k
        wave = resampy.resample(
            audio_np,
            h.sampling_rate,
            h2.sampling_rate,
            filter="sinc_window",
            window=scipy.signal.windows.hann,
            num_zeros=8,
        )
        wave_out = wave.astype(np.int16)

        # HiFi-GAN super-resolution
        wave = wave / MAX_WAV_VALUE
        wave = torch.FloatTensor(wave).to(DEVICE)
        new_mel = mel_spectrogram(
            wave.unsqueeze(0),
            h2.n_fft,
            h2.num_mels,
            h2.sampling_rate,
            h2.hop_size,
            h2.win_size,
            h2.fmin,
            h2.fmax,
        )
        y_g_hat2 = hifigan_sr(new_mel)
        audio2 = y_g_hat2.squeeze()
        audio2 = audio2 * MAX_WAV_VALUE
        audio2_denoised = denoiser(audio2.view(1, -1), strength=35)[:, 0]

        # High-pass filter, mixing and denormalizing
        audio2_denoised = audio2_denoised.detach().cpu().numpy().reshape(-1)
        b = scipy.signal.firwin(
            101, cutoff=10500, fs=h2.sampling_rate, pass_zero=False
        )
        y = scipy.signal.lfilter(b, [1.0], audio2_denoised)
        y *= 4.0  # superres strength
        y_out = y.astype(np.int16)
        y_padded = np.zeros(wave_out.shape)
        y_padded[: y_out.shape[0]] = y_out
        sr_mix = wave_out + y_padded
        out_data = pad_audio(sr_mix, 30000, silence)

        audio_array = out_data.astype(np.int16)

        
        return audio_array


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

        
        subprocess.call(["ffplay", "-nodisp","-af","atempo=0.8", "-autoexit","-hide_banner","-loglevel","error", audio_path])
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
            l,answer = blande_sentiment(req_text,DEVICE2,model_sent,tokenizer_sent,author)
            answer = sanitize_output(f"{answer}")
    

        else:
            print("Skip because it's emoticon only")
        delay=15
    
    wav_name="ok"
    
    list_chunks=textwrap.wrap(answer, 700)
  
    for chunk in list_chunks:
        #get audio voice
        #1KgVnjrnxZTXgjnI56ilkq5G4UJCbbwZZ|default fluttershy
        #1QnOliOAmerMUNuo2wXoH-YoainoSjZen|default default
        #1_ztAbe5YArCMwyyQ_G9lUiz74ym5xJKC|default luna
        #1YkV1VtP1w5XOx3jYYarrCKSzXCB_FLCy|default scootaloo
        #1rcPDqgDeCIHGDdvfOo-fxfA1XeM4g3CB|default trixie
        #1BBdTHis91MwnHTt7tD_xtZ-nQ9SgvqD6|singing fluttershy
        #10CENYWV5ugTXZbnsldN6OKR7wkDEe7V7|singing default singing

        audio_buffer = generate_audio(8, "1QnOliOAmerMUNuo2wXoH-YoainoSjZen|default",None,chunk,"dra",0,wav_name,delay)

        try:
            audio_numpy= np.concatenate((audio_numpy, audio_buffer), axis=0)
        except:
            print("Error?")
            audio_numpy=audio_buffer

    #save last audio
    wavfile.write(wav_name+".wav", 30000, audio_numpy)



    #send midi for control the character
    play(signals(l),1.5)
    print(f"Playing audio of: {answer}")
    play_audio("ok.wav")     


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
