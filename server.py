from settings import ROOT_PATH, Config, N_CORES, DEBUG
from server_logic.definitions import Context
from sanic.response import json
from fsm.handler import Worker
from settings import tokens
from sanic import Sanic
from db import Database
#import googlemaps
import secrets
import sanic
import os
import urllib.parse


app = Sanic(name="HumanBios-Server")
handler = Worker()
handler.start()
database = Database()
#gclient = googlemaps.Client(key=LOAD_KEY)


@app.route('/api/process_message', methods=['POST'])
async def data_handler(request):
    # get data from request
    data = request.json
    if data is None:
        return json({"status": 403, "message": "expected json"})

    instance = data.get("via_instance")
    if not instance or instance not in tokens:
        return json({"status": 403, "message": "instance is not registered"})

    token = tokens.get(instance, '')
    # the session might be saved in the database
    if not token:
        potential_session = await database.get_session(data.get('via_instance'))
        if potential_session:
            # it is, we save it in the cache and set the token to the retrieved values
            tokens[potential_session["name"]] = Config(potential_session["token"], potential_session["url"])
            token = tokens.get(data.get('via_instance'))
    # `not token` to avoid `'' == ''`
    if not token or not (data.get("security_token", '') == token.token):
        # add custom 403 error code
        return json({"status": 403, "message": "token unauthorized (bad token)"})

    # build into context
    result = Context.from_json(data)
    # verify context `required` attributes
    if not result.validated:
        # add custom 403 error code
        return json({"status": 403, "message": result.error})
    # Validated object
    ctx = result.object
    # Replace security token to the server's after validation
    ctx.replace_security_token()
    # process message
    handler.process(ctx)
    # return context
    return json(ctx.ok)


@app.route('/api/webhooks/rasa/webhook/get_facility', methods=['POST'])
async def rasa_get_facility(request):
    # @Important: rasa sends location and facility type
    # @Important: we search in database -> Found: return relevant facility address.
    # @Important:                       -> Not Found: request facility from google places -> \
    # @Important:                                respond with address <- save to database <- /
    # TODO: Introduce database.
    # TODO: Introduce google places api
    data = request.json
    location: str = data.get('location')
    facility_type: str = data.get('facility_type')
    facility_id: str = data.get('facility_id')
    amount: int = data.get('amount')
    # Facility type is one of the values
    if facility_id:
        address = "<this is a dummy server response of the cached facility>"
        resp = {"facility_address_0": address}
    elif amount:
        resp = {}
        for i in range(amount):
            resp[f"facility_address_{i}"] = "<this is a dummy server response address>"
    else:
        resp = {"facility_address_0": "<this is a dummy server response address>"}
    return json(resp)


@app.route('/api/setup', methods=['POST'])
async def worker_setup(request):
    # get data from request
    data = request.json
    # If not data -> return "expected json"
    if not data:
        return json({"status": 403, "message": "expected json"})
    # get security token from the data
    token = data.get("security_token", "")
    # Verify security token (of the server)
    if token != tokens['server']:
        return json({"status": 403, "message": "token unauthorized"})
    # Pull url from request
    url = data.get("url", "")
    # Generate new token and pull url
    try:
        if not urllib.parse.urlparse(url).scheme != "https" and not DEBUG:
            return json({"status": 403, "message": "url must use https in production"})
    except ValueError:
        return json({"status": 403, "message": "url invalid"})
    # check if session is already saved, then this means the frontend was restarted and we can ignore this
    # TODO: Support a changed key where the instance can say that it didnt restart,
    # TODO: rather changed the other variables. Potentially its own endpoint
    check = False
    # if its in the cache we take it from there
    for session_name in tokens:
        # for reasons we save the server token in this cache as well so we have to ignore it in here
        if session_name == "server":
            continue
        if tokens[session_name].url == url:
            check = session_name
            break
    # it was not in the cache, maybe its in the database
    if not check:
        all_sessions = await database.all_frontend_sessions()
        for session in all_sessions:
            # url is the unique identifier here
            if session["url"] == url:
                tokens[session["name"]] = Config(session["token"], session["url"])
                check = session["name"]
    # check is set to the new name which is way better then giving it its own variable
    if check:
        return json({"status": 200, "name": check, "token": tokens[check].token})
    # continue setting up the new session
    # Pull broadcast channel from the request
    broadcast_entity = data.get("broadcast")
    # For "No entity" value must be None
    if broadcast_entity == "":
        return json({"status": 403, "message": "broadcast entity is invalid (for \'no entity\' value must be None)"})
    # Pull psychological room from the request
    psychological_room = data.get("psychological_room")
    # For "No entity" value must be None
    if psychological_room == "":
        return json({"status": 403, "message": "psychological room is invalid (for \'no entity\' value must be None)"})
    # Pull doctor room from the request
    doctor_room = data.get("doctor_room")
    # For "No entity" value must be None
    if doctor_room == "":
        return json({"status": 403, "message": "doctor room is invalid (for \'no entity\' value must be None)"})

    # Generate new token and name for the instance
    # @Important: 40 bytes token is > 50 characters long
    new_token = secrets.token_urlsafe(40)
    # @Important: Conveniently cut to length of 40
    new_token = new_token[:40]
    # @Important: Token hex returns n * 2 amount of symbols
    name = secrets.token_hex(10)
    # [DEBUG]: assert len(name) == 20

    config_obj = Config(new_token, url)
    tokens[name] = config_obj
    # Return useful data back to the caller
    await database.create_session({
        "name": name,
        "token": new_token,
        "url": url,
        "broadcast": broadcast_entity,
        "psychological_room": psychological_room,
        "doctor_room": doctor_room
    })
    return json({"status": 200, "name": name, "token": new_token})


if __name__ == '__main__':
    app.run(host='0.0.0.0', port=8282, debug=DEBUG, access_log=DEBUG, workers=N_CORES)
