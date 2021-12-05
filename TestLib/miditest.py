import time
import rtmidi

midiout = rtmidi.MidiOut()
available_ports = midiout.get_ports()
print(available_ports)
#detect position element in list
def detect(list, element):
    for i in range(len(list)):
        if list[i] == element:
            return i

port= detect(available_ports, 'loopMIDI 1')
midiout.open_port(port)
def play(note, duration):
    midiout.send_message([0x90, note, 0x7f])
    time.sleep(duration)
    midiout.send_message([0x80, note, 0x7f])

play(38, 2.5)