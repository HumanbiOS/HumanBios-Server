from settings import ROOT_PATH, Config, N_CORES, DEBUG, BOTSOCIETY_API_KEY, SERVER_HOST, SERVER_PORT, OWNER_HASH
from server_logic.utils.parser import parse_api, save_file
from sanic.response import json, html, redirect, empty, stream
from server_logic.definitions import Context
from fsm.handler import Worker
from settings import tokens
from sanic import Sanic
from db import Database
from db.enums import PermissionLevel
import urllib.parse
from jinja2 import Environment, FileSystemLoader, select_autoescape
import datetime
import aiohttp
import logging
import secrets
import ujson
import sanic
import uuid
import os
import re


env = Environment(
    loader=FileSystemLoader('web/templates'),
    autoescape=select_autoescape(['html', 'xml']),
    auto_reload=DEBUG,
    enable_async=True
)
app = Sanic(name="HumanBios-Server", strict_slashes=True)
handler = Worker()
handler.start()
database = Database()


@app.route('/api/webhooks/botsociety')
async def botsociety_webhook(request):
    args = request.args
    # Get user id and conv id for get request to the Botsociety API
    user_id = args["user_id"][0]
    conv_id = args["conversation_id"][0]
    # Data needed to use API
    v = "2.0"
    api_url = f"https://app.botsociety.io/apisociety/{v}/npm"
    url = f"{api_url}/conversations/{conv_id}"
    h = {
        "Content-Type": "application/json",
        "api_key_public": BOTSOCIETY_API_KEY,
        "user_id": user_id
    }
    # Get data from api
    async with aiohttp.ClientSession() as session:
        async with session.get(url, headers=h) as resp:
            data = await resp.json()
    # [DEBUG]
    # logging.info(data)
    # Parse/Save data
    save_file(parse_api(data['messages']))
    # Make sure to reload in-memory data / cache
    handler.reload_file()
    return empty()

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


# admin pages


app.static("/static", "web/static")


@app.get("/admin")
async def admin_root(request):
    if request.ctx.identity:
        _, permission_level = await request.ctx.ensure_user()
        return jinja2("admin/index.html", owner=(permission_level >= PermissionLevel.ADMIN))
    else:
        return jinja2("admin/login.html")

@app.get("/admin/auth/<token>")
async def admin_auth_token(request, token):
    if request.ctx.identity:
        return redirect("/admin")
    identity = await database.check_webtoken(token)
    session = await database.create_websession(identity)
    response = redirect("/admin")
    response.cookies["session"] = session
    response.cookies["session"]["max-age"] = 24 * 60 * 60
    response.cookies["session"]["secure"] = not DEBUG
    response.cookies["session"]["httponly"] = True
    response.cookies["session"]["path"] = "/admin"
    return response

# middlewares & utils

def jinja2(template_name, **ctx):
    async def render_stream(response):
        stream_data = env.get_template(template_name).generate_async(**ctx)
        async for chunk in stream_data:
            await response.write(chunk)
    return stream(render_stream, content_type="text/html")

@app.middleware('response')
async def prevent_xss(request, response):
    response.headers["x-xss-protection"] = "1; mode=block"


@app.middleware('request')
async def admin_auth_middleware(request):
    handler, args, kwargs, uri, name = app.router.get(request)
    if name.startswith("admin_"):
        print(request.cookies.get("session", None))
        request.ctx.identity = await database.check_websession(request.cookies.get("session", None))
        print(request.ctx.identity)

        async def get_user():
            request.ctx.user = await database.get_user(request.ctx.identity)
            if request.ctx.identity == OWNER_HASH:
                request.ctx.permission_level = float('inf')
            else:
                request.ctx.permission_level = request.ctx.user["permission_level"]
                if request.ctx.permission_level > PermissionLevel.MAX:
                    request.ctx.permission_level = PermissionLevel.DEFAULT
            return request.ctx.user, request.ctx.permission_level

        request.ctx.ensure_user = get_user


if __name__ == '__main__':
    app.run(host=SERVER_HOST, port=SERVER_PORT, debug=DEBUG, access_log=DEBUG, workers=N_CORES)
