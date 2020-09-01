from settings import ROOT_PATH
import datetime
import logging
import ujson
import uuid
import re
import os


w = lambda data: ujson.dumps(data, indent=4, ensure_ascii=False)
# [DEBUG]
# p = lambda data: print(w(data))

# Find message by id
def get_msg(data, msg_id):
    for message in data:
       if message["id"] == msg_id:
            return message
# Command pattern
command = re.compile(r"(?:^|[^\\])#([^\s]+)")

# Parse text for special `#commands`
def get_text(text: str) -> (str, bool, str):
    cmds = command.findall(text)
    result_cmds = list()
    args = dict()
    # After doing search, fix all actual hashtags:
    #     change all '\#' to '#'
    text = text.replace(r"\#", "#")
    for cmd in cmds:
        # Remove the #command after finding and strip any amount of trailing "\n" or " "
        text = text.replace(f"#{cmd}", "").strip("\n ")
        # The actual command
        if "=" in cmd:
            result_cmds.append(cmd.split("=")[0].lower())
        else:
            result_cmds.append(cmd.lower())
        # Add args
        tmp = cmd.split(";")
        for single_tmp in tmp:
            try:
                key, value = single_tmp.split("=")
            except ValueError:
                continue
            args[key] = value
    return text, bool(result_cmds), result_cmds, args


# Parse Botsociety api data
def parse_api(raw_data):
    # Result list
    result = list()
    # Merging all actions in one loop
    for msg in raw_data:
        # [DEBUG]
        # p(msg)
        
        # Add our own values
        msg['free_answer'] = False
        # Allow to use both normal buttons and quickreplies
        msg['buttons'] = msg.get("buttons") or []
        msg['multichoice'] = False
        # Generate text key for the translation
        msg['text_key'] = str(uuid.uuid4())[:8]
        msg['commands'] = []
        msg['expected_type'] = "text"
        msg['text'] = msg.get("text") or ""
        # Message that is not quickreply
        if msg['type'] != "quickreplies":
            # Parse text
            text, _, cmds, args = get_text(msg['text'])
            msg['text'] = text
            msg['commands'] = cmds
            msg['command_args'] = args

            next_msg = get_msg(raw_data, msg['next_message'])

            if next_msg:
                # Handle quickreplies as buttons
                if next_msg['type'] == "quickreplies":
                    msg['next_message'] = None
                    msg['buttons'] = next_msg['quickreplies']
                # Handle user message as free answer
                elif next_msg['is_left_side'] is False:
                    msg['next_message'] = next_msg['next_message']
                    msg['free_answer'] = True
                    
                    if next_msg['type'] == "image":
                        msg['expected_type'] = "image"
                    elif next_msg['type'] == "location":
                        msg['expected_type'] = "location"
        
        # Make sure to keep these statements separate
        # We handled quickreplies
        if msg['type'] == "quickreplies":
            # Skip
            continue
        elif msg['is_left_side'] is False:
            # Skip
            continue

        # Make sure to add keys for all buttons and do the parsing
        for index, btn in enumerate(msg['buttons']):
            btn['text_key'] = f"{msg['text_key']}-btn{index}"
            text, _, cmds, args = get_text(btn['text'])
            btn['text'] = text
            btn['commands'] = cmds
            btn['command_args'] = args

        # Add messages if didn't skip
        result.append(msg)
    # [DEBUG]
    # logging.info(w(_tmp))
    logging.info("Parsed new flow from Botsociety.")
    return result


# Save data to the file / reduce history
def save_file(data, path=None):
    # Default path
    if path is None:
        path = os.path.abspath(os.path.join("archive"))
    # [DEBUG]
    logging.info(f"Saving to path: {path}")
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
    with open(os.path.join(path, "latest.json"), "w") as file_latest:
        file_latest.write(w(data))

    # If more than 5 files -> remove oldest
    history = os.listdir(path)
    # Sort by newest first
    history.sort(reverse=True)
    # Make sure not to remove latest file
    history.remove("latest.json")
    for fp in history[4:]:
        fp = os.path.join(path, fp)
        os.remove(fp)

    logging.info("Updated latest file / archived files.")


# Get first message; next message; next message by the answer
def get_next(items, curr_id=None, answer=None):
    if curr_id is None:
        for msg in items:
            if msg['is_first_message']:
                return msg
        else:
            raise ValueError("Somehow we dont have first message?")
    else:
        curr = get_msg(items, curr_id)

    if curr['buttons']:
        # find button
        for btn in curr['buttons']:
            if answer == btn['text_key']:
                next_id = btn.get("next_message")
                if next_id is not None:
                    return get_msg(items, next_id)
    elif curr:
        return get_msg(items, curr["next_message"])
