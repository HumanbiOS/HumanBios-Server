from settings import ROOT_PATH
import datetime
import ujson
import uuid
import re
import os


w = lambda data: ujson.dumps(data, indent=4, ensure_ascii=False)
# [DEBUG]
# p = lambda data: print(w(data))

# Find message by id
def get_msg(data, id_):
    for message in data:
       if message["id"] == id_:
            return message
# Command pattern
command = re.compile(r"#([^\s]+)")

# Parse text for special `#commands`
def get_text(text: str) -> (str, bool, str):
    cmd = command.search(text)
    if cmd is not None:
        cmd = cmd.group(1).lower()
        # Remove the #command after finding and strip any amount of trailing "\n" or " "
        return text.replace(f"#{cmd}", "").strip("\n "), True, cmd
    else:
        return text, False, cmd


# Parse Botsociety api data
def parse_api(raw_data):
    # Result list
    _tmp = list()
    # Merging all actions in one loop
    for msg in raw_data:
        # Add our own values
        msg['free_answer'] = False
        # Allow to use both normal buttons and quickreplies
        msg['buttons'] = [] if msg.get("buttons") is None else msg['buttons']
        msg['multichoice'] = False
        # Generate text key for the translation
        msg['text_key'] = str(uuid.uuid4())[:8]
        msg['command'] = None
        # Message that is not quickreply
        if msg['type'] != "quickreplies":
            # Parse text
            text, _case, cmd = get_text(msg['text'])
            msg['text'] = text
            if _case:
                msg['command'] = cmd
            _next = get_msg(raw_data, msg['next_message'])

            if _next:
                # Handle quickreplies as buttons
                if _next['type'] == "quickreplies":
                    msg['next_message'] = None
                    msg['buttons'] = _next['quickreplies']
                # Handle user message as free answer
                elif _next['type'] == "text" and _next['is_left_side'] is False:
                    msg['next_message'] = _next['next_message']
                    msg['free_answer'] = True
        
        # Make sure to keep these statements separate
        # We handled quickreplies
        if msg['type'] == "quickreplies":
            # Skip
            continue
        elif msg['type'] == "text" and msg['is_left_side'] is False:
            # Skip
            continue
        # Make sure to add keys for all buttons
        for index, btn in enumerate(msg['buttons']):
            btn['text_key'] = f"{msg['text_key']}-btn{index}"

        # Add messages if didn't skip
        _tmp.append(msg)
    return _tmp


# Save data to the file / reduce history
def save_file(data, path=None):
    # Default path
    if path is None:
        path = os.path.abspath(os.path.join(ROOT_PATH, "archive"))

    # Prepare path directory if needed
    if not os.path.exists(path):
        os.mkdir(path)
    # Rename old "latest"
    latest_fp = os.path.join(path, "latest.json")
    if os.path.exists(latest_fp):
        # Read creation time from file system in Unix timestamp format and isoformat it
        ct = datetime.datetime.fromtimestamp(os.path.getmtime(latest_fp)).isoformat()
        # Cut off partial units (we don't care about that precision) for better look
        ct = ct.split(".")[0]
        # Move the actual file by renaming
        os.rename(latest_fp, os.path.join(path, f"{ct}.json"))

    # Write new data "latest"
    with open(os.path.join(path, "latest.json"), "w") as file_:
        file_.write(w(data))

    # If more than 5 files -> remove oldest
    history = os.listdir(path)
    # Sort by newest first
    history.sort(reverse=True)
    # Make sure not to remove latest file
    history.remove("latest.json")
    for fp in history[4:]:
        fp = os.path.join(path, fp)
        os.remove(fp)
