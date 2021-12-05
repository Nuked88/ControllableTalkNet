#smart splits that are not cutting words
import textwrap




def readFile(file_path):
    with open(file_path, 'r') as f:
        return f.read()

text = readFile("conversations/read/read.txt")
print ('\n'.join(textwrap.wrap(text, 800)))

