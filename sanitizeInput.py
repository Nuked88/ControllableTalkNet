
def readListFromFile(file_path):
    with open(file_path, 'r') as f:
        lines = f.readlines()
    return lines

    
def sanitize_input(input_str):
 
    stopwords = readListFromFile("Assets/emoticon.lst")

    for i in stopwords:
        print(f"Test: {i}!")
        n=input_str.replace(i.strip(),'')
        input_str=n
    result = input_str.strip()

    return result.replace("\n", " ").replace("\r", " ").replace("\t", " ").replace("’", "'").replace("“", "\"").replace("”", "\"")


req_text = sanitize_input(" BibleThump BibleThump")
print(req_text)